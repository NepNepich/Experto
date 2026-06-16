from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from database import get_db
from api.models import (
    Project, Team, ProjectTeam,
    Submission, SubmissionAssignment,
    SubmissionCriterionScore, SubmissionComment,
    User, ProjectCriterion
)
from api.schemas import (
    ProjectCreate, ProjectRead, ProjectUpdate,
    ProjectMiniRead, ProjectDashboard, ExpertProgress, ProjectExportItem,
    ProjectWithCriteriaCreate, CriterionCreateNested
)

projects_router = APIRouter(prefix="/projects", tags=["projects"])


# CREATE
@projects_router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    if data.mode == 2 and data.participant_team_ids:
        teams_res = await db.execute(select(Team).where(Team.id.in_(data.participant_team_ids)))
        existing = {t.id for t in teams_res.scalars().all()}
        missing = set(data.participant_team_ids) - existing
        if missing:
            raise HTTPException(400, f"Teams not found: {missing}")

    new_project = Project(
        name=data.name,
        mode=data.mode,
        deadline=data.deadline,
        status="submitted"
    )
    db.add(new_project)
    await db.flush()

    if data.mode == 2 and data.participant_team_ids:
        for tid in data.participant_team_ids:
            db.add(ProjectTeam(project_id=new_project.id, team_id=tid))

    await db.commit()
    await db.refresh(new_project)
    return new_project


# READ ALL (Пагинация по 16 штук для веба)
@projects_router.get("/", response_model=list[ProjectMiniRead])
async def list_projects(
        skip: int = Query(0, ge=0),
        limit: int = Query(16, ge=1, le=50),
        db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(Project)
        .order_by(Project.date_created.desc())
        .offset(skip)
        .limit(limit)
    )
    return res.scalars().all()


@projects_router.get("/active", response_model=list[ProjectRead])
async def get_active_projects(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)

    stmt = select(Project).where(Project.deadline > now).order_by(Project.deadline.asc())

    res = await db.execute(stmt)
    projects = res.scalars().all()

    return [ProjectRead.model_validate(p) for p in projects]


@projects_router.post("/with-criteria", response_model=ProjectRead, status_code=201)
async def create_project_with_criteria(data: ProjectWithCriteriaCreate, db: AsyncSession = Depends(get_db)):
    if data.mode == 2 and data.participant_team_ids:
        teams_res = await db.execute(select(Team).where(Team.id.in_(data.participant_team_ids)))
        existing = {t.id for t in teams_res.scalars().all()}
        missing = set(data.participant_team_ids) - existing
        if missing:
            raise HTTPException(400, f"Teams not found: {missing}")

    new_project = Project(
        name=data.name,
        mode=data.mode,
        deadline=data.deadline,
        status="submitted"
    )
    db.add(new_project)
    await db.flush()

    if data.mode == 2 and data.participant_team_ids:
        for tid in data.participant_team_ids:
            db.add(ProjectTeam(project_id=new_project.id, team_id=tid))

    if data.criteria:
        for crit_data in data.criteria:
            criterion = ProjectCriterion(
                project_id=new_project.id,
                name=crit_data.name,
                max_score=crit_data.max_score,
                sort_order=crit_data.sort_order
            )
            db.add(criterion)

    await db.commit()
    await db.refresh(new_project)
    return new_project


# READ ONE
@projects_router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


# UPDATE
@projects_router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
        project_id: int,
        data: ProjectUpdate,
        db: AsyncSession = Depends(get_db)
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return project

    if "deadline" in update_data and update_data["deadline"] <= datetime.now(timezone.utc):
        raise HTTPException(400, "Deadline must be in the future")

    for field, value in update_data.items():
        setattr(project, field, value)

    await db.commit()
    await db.refresh(project)
    return project


# DELETE
@projects_router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    try:
        await db.delete(project)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, "Cannot delete: active foreign key constraints exist.")
    return None


# DASHBOARD (Статистика для организатора)
@projects_router.get("/{project_id}/dashboard", response_model=ProjectDashboard)
async def get_project_dashboard(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project: raise HTTPException(404, "Project not found")

    total_res = await db.execute(select(func.count(Submission.id)).where(Submission.project_id == project_id))
    total = total_res.scalar()

    checked_res = await db.execute(select(func.count(Submission.id)).where(
        Submission.project_id == project_id, Submission.status == "checked"
    ))
    checked = checked_res.scalar()

    experts_res = await db.execute(
        select(SubmissionAssignment.reviewer_id, User.name, func.count(SubmissionAssignment.id))
        .join(User, SubmissionAssignment.reviewer_id == User.id)
        .join(Submission, SubmissionAssignment.submission_id == Submission.id)
        .where(Submission.project_id == project_id, SubmissionAssignment.status == "done")
        .group_by(SubmissionAssignment.reviewer_id, User.name)
    )
    experts = [ExpertProgress(expert_id=row[0], expert_name=row[1], checked_count=row[2]) for row in experts_res.all()]

    last_res = await db.execute(select(func.max(Submission.checked_at)).where(Submission.project_id == project_id))
    last_date = last_res.scalar()

    return ProjectDashboard(
        project_id=project.id,
        project_name=project.name,
        total_submissions=total,
        checked_submissions=checked,
        pending_submissions=total - checked,
        last_check_date=last_date,
        experts=experts
    )


# EXPORT (Таблица для выгрузки)
@projects_router.get("/{project_id}/export", response_model=list[ProjectExportItem])
async def export_project_data(project_id: int, db: AsyncSession = Depends(get_db)):
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")

    stmt = (
        select(
            Submission.team_id,
            Team.name.label("team_name"),
            func.coalesce(func.sum(SubmissionCriterionScore.score), 0).label("total_score"),
            func.max(SubmissionComment.comment).label("comment"),
            User.name.label("expert_name"),
            Submission.checked_at.label("check_date")
        )
        .join(Team, Submission.team_id == Team.id)
        .outerjoin(SubmissionCriterionScore, Submission.id == SubmissionCriterionScore.submission_id)
        .outerjoin(SubmissionAssignment, Submission.id == SubmissionAssignment.submission_id)
        .outerjoin(User, SubmissionAssignment.reviewer_id == User.id)
        .outerjoin(SubmissionComment, (Submission.id == SubmissionComment.submission_id) & (
                    SubmissionComment.author_id == SubmissionAssignment.reviewer_id))
        .where(Submission.project_id == project_id)
        .group_by(Submission.id, Team.name, User.name, Submission.checked_at)
        .order_by(Team.name.asc())
    )

    res = await db.execute(stmt)
    return [ProjectExportItem(**row._asdict()) for row in res.all()]
