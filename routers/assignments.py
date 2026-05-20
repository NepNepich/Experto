from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from database import get_db
from api.models import SubmissionAssignment, Submission, Project, SubmissionCriterionScore
from api.schemas import AssignmentRead, SubmissionRead, NextTaskResponse

assignments_router = APIRouter(prefix="/assignments", tags=["assignments"])

# === ХЕЛПЕР: АВТО-ВЫДАЧА ===
async def _assign_next_work(db: AsyncSession, reviewer_id: int, project: Project) -> int | None:
    """Ищет следующую доступную работу и создаёт назначение (без коммита)."""
    max_reviewers = 1 if project.mode == 1 else 5
    
    next_sub_query = (
        select(Submission)
        .where(
            Submission.project_id == project.id,
            Submission.status.in_(['unchecked', 'checking']),
            ~Submission.id.in_(
                select(SubmissionAssignment.submission_id).where(
                    SubmissionAssignment.reviewer_id == reviewer_id
                )
            )
        )
        .order_by(Submission.id.asc())
        .limit(1)
    )
    next_sub = (await db.execute(next_sub_query)).scalar_one_or_none()

    if next_sub:
        assigned_count = (await db.execute(
            select(func.count(SubmissionAssignment.id)).where(
                SubmissionAssignment.submission_id == next_sub.id
            )
        )).scalar()

        if assigned_count < max_reviewers:
            db.add(SubmissionAssignment(
                submission_id=next_sub.id,
                reviewer_id=reviewer_id,
                status="pending"
            ))
            if next_sub.status == "unchecked":
                next_sub.status = "checking"
            return next_sub.id
    return None

# === ВЗЯТЬ ЗАДАЧУ (ПЕРВАЯ ИЛИ СЛЕДУЮЩАЯ) ===

@assignments_router.get("/project/{project_id}/next", response_model=NextTaskResponse)
async def get_next_project_task(
    project_id: int,
    reviewer_id: int = Query(...),
    db: AsyncSession = Depends(get_db)
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    max_reviewers = 1 if project.mode == 1 else 5

    existing = (await db.execute(select(SubmissionAssignment).where(
        SubmissionAssignment.reviewer_id == reviewer_id,
        SubmissionAssignment.status == "pending",
        SubmissionAssignment.submission_id.in_(
            select(Submission.id).where(Submission.project_id == project_id)
        )
    ))).scalar_one_or_none()

    if existing:
        sub = await db.get(Submission, existing.submission_id)
        return NextTaskResponse(submission=sub, assignment_id=existing.id)

    candidates_query = (
        select(Submission)
        .where(
            Submission.project_id == project_id,
            Submission.status.in_(['unchecked', 'checking']),
            ~Submission.id.in_(
                select(SubmissionAssignment.submission_id).where(SubmissionAssignment.reviewer_id == reviewer_id)
            )
        )
        .order_by(Submission.created_at.asc())
    )
    candidates = (await db.execute(candidates_query)).scalars().all()

    for sub in candidates:
        count_res = await db.execute(select(func.count(SubmissionAssignment.id)).where(
            SubmissionAssignment.submission_id == sub.id
        ))
        current_count = count_res.scalar()

        if current_count < max_reviewers:
            new_assign = SubmissionAssignment(
                submission_id=sub.id,
                reviewer_id=reviewer_id,
                status="pending"
            )
            db.add(new_assign)
            if sub.status == "unchecked":
                sub.status = "checking"
            
            await db.commit()
            await db.refresh(sub)
            await db.refresh(new_assign)
            return NextTaskResponse(submission=sub, assignment_id=new_assign.id)

    raise HTTPException(404, "No available submissions. All works are fully assigned or checked.")

# === ФИНАЛИЗАЦИЯ ПРОВЕРКИ ===

@assignments_router.post("/{assignment_id}/finalize")
async def finalize_review(assignment_id: int, db: AsyncSession = Depends(get_db)):
    assign = await db.get(SubmissionAssignment, assignment_id)
    if not assign:
        raise HTTPException(404, "Assignment not found")
    if assign.status == "done":
        raise HTTPException(400, "Review already finalized")

    sub = await db.get(Submission, assign.submission_id)
    project = await db.get(Project, sub.project_id)

    assign.status = "done"
    assign.completed_at = datetime.utcnow()

    if project.mode == 1:
        total_mark_res = await db.execute(select(func.sum(SubmissionCriterionScore.score)).where(
            SubmissionCriterionScore.submission_id == sub.id
        ))
        sub.mark = total_mark_res.scalar() or 0
        sub.status = "checked"
        sub.checked_at = datetime.utcnow()

    await db.commit()

    next_sub_id = await _assign_next_work(db, assign.reviewer_id, project)
    await db.commit()

    return {"message": "Review finalized successfully", "next_submission_id": next_sub_id}

# === МОИ АКТИВНЫЕ ЗАДАЧИ ===

@assignments_router.get("/my", response_model=list[AssignmentRead])
async def get_my_assignments(
    reviewer_id: int = Query(...),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(SubmissionAssignment)
        .where(
            SubmissionAssignment.reviewer_id == reviewer_id,
            SubmissionAssignment.status == "pending"
        )
        .order_by(SubmissionAssignment.assigned_at.asc())
    )
    return res.scalars().all()

# === ИСТОРИЯ ПРОВЕРЕННЫХ РАБОТ ===

@assignments_router.get("/history", response_model=list[AssignmentRead])
async def get_review_history(
    reviewer_id: int = Query(...),
    project_id: int | None = Query(None, description="Фильтр по проекту"),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(SubmissionAssignment).where(
        SubmissionAssignment.reviewer_id == reviewer_id,
        SubmissionAssignment.status == "done"
    )
    if project_id:
        stmt = stmt.join(Submission).where(Submission.project_id == project_id)
        
    res = await db.execute(stmt.order_by(SubmissionAssignment.completed_at.desc()))
    return res.scalars().all()