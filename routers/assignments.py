from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from database import get_db
from api.models import SubmissionAssignment, Submission, Project, SubmissionCriterionScore
from api.schemas import AssignmentRead, SubmissionRead

assignments_router = APIRouter(prefix="/assignments", tags=["assignments"])

# ✅ Следующая работа по КОНКРЕТНОМУ проекту (для эксперта)
@assignments_router.get("/project/{project_id}/next", response_model=SubmissionRead)
async def get_next_project_task(
    project_id: int,
    reviewer_id: int = Query(...),
    db: AsyncSession = Depends(get_db)
):
    # Проверяем, что проект существует и активен
    project = await db.get(Project, project_id)
    if not project or project.deadline <= datetime.utcnow():
        raise HTTPException(400, "Project not found or deadline passed")

    assign = (await db.execute(select(SubmissionAssignment).where(
        SubmissionAssignment.submission_id.in_(
            select(Submission.id).where(Submission.project_id == project_id)
        ),
        SubmissionAssignment.reviewer_id == reviewer_id,
        SubmissionAssignment.status == "pending"
    ).order_by(SubmissionAssignment.assigned_at.asc()).limit(1))).scalar_one_or_none()

    if not assign:
        raise HTTPException(404, "All assigned works for this project are reviewed or pending finalization")
    
    return await db.get(Submission, assign.submission_id)

# ✅ ФИНАЛИЗАЦИЯ ПРОВЕРКИ (эксперт подтверждает отправку)
@assignments_router.post("/{assignment_id}/finalize")
async def finalize_review(assignment_id: int, db: AsyncSession = Depends(get_db)):
    assign = await db.get(SubmissionAssignment, assignment_id)
    if not assign:
        raise HTTPException(404, "Assignment not found")
    if assign.status == "done":
        raise HTTPException(400, "Review already finalized")

    sub = await db.get(Submission, assign.submission_id)
    project = await db.get(Project, sub.project_id)

    # 1. Помечаем назначение завершённым
    assign.status = "done"
    assign.completed_at = datetime.utcnow()

    # 2. Пересчитываем mark (только для Mode 1)
    if project.mode == 1:
        total_mark = (await db.execute(select(func.sum(SubmissionCriterionScore.score)).where(
            SubmissionCriterionScore.submission_id == sub.id
        ))).scalar() or 0
        sub.mark = total_mark
        sub.checked_at = datetime.now()
        sub.status = "checked"

    await db.commit()

    # 3. Авто-выдача следующей работы из ЭТОГО ЖЕ проекта
    next_sub_id = None
    next_query = (
        select(Submission)
        .where(
            Submission.project_id == project.id,
            Submission.status.in_(['unchecked', 'checking']),
            ~Submission.id.in_(
                select(SubmissionAssignment.submission_id).where(
                    SubmissionAssignment.reviewer_id == assign.reviewer_id
                )
            )
        )
        .order_by(Submission.id.asc()).limit(1)
    )
    next_sub = (await db.execute(next_query)).scalar_one_or_none()

    if next_sub:
        count = (await db.execute(select(func.count(SubmissionAssignment.id)).where(
            SubmissionAssignment.submission_id == next_sub.id
        ))).scalar()
        max_reviewers = 1 if project.mode == 1 else 5
        if count < max_reviewers:
            db.add(SubmissionAssignment(
                submission_id=next_sub.id, reviewer_id=assign.reviewer_id, status="pending"
            ))
            if next_sub.status == "unchecked":
                next_sub.status = "checking"
            await db.commit()
            next_sub_id = next_sub.id

    return {"message": "Review finalized", "next_submission_id": next_sub_id}

@assignments_router.get("/history", response_model=list[AssignmentRead])
async def get_review_history(
    project_id: int = Query(..., description="ID активного проекта"),
    reviewer_id: int = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Возвращает работы, которые эксперт уже проверил в этом проекте"""
    # Проверяем, что проект существует
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")

    res = await db.execute(
        select(SubmissionAssignment)
        .join(Submission, SubmissionAssignment.submission_id == Submission.id)
        .where(
            SubmissionAssignment.reviewer_id == reviewer_id,
            SubmissionAssignment.status == "done",
            Submission.project_id == project_id
        )
        .order_by(SubmissionAssignment.completed_at.desc())
    )
    return res.scalars().all()