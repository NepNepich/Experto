from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from database import get_db
from api.models import (
    Submission, Project, Team, ProjectTeam,
    SubmissionArtifact, SubmissionAssignment,
    User, SubmissionComment, SubmissionCriterionScore,
    ProjectCriterion
)
from api.schemas import (
    SubmissionCreate, SubmissionRead, SubmissionUpdate, 
    SubmissionReviewView, StudentSubmissionMini, CriterionScoreItem, 
    SubmissionDetailMode1, PeerCommentView, SubmissionDetailMode2
    )

submissions_router = APIRouter(prefix="/submissions", tags=["submissions"])

# ✅ CREATE (Организатор загружает работу команды)
@submissions_router.post("/", response_model=SubmissionRead, status_code=status.HTTP_201_CREATED)
async def create_submission(data: SubmissionCreate, db: AsyncSession = Depends(get_db)):
    # 1. Базовые проверки существования
    project = await db.get(Project, data.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    team = await db.get(Team, data.team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    # 2. Валидация для Режима 2: команда должна быть явно допущена
    if project.mode == 2:
        allowed = await db.execute(select(ProjectTeam).where(
            ProjectTeam.project_id == data.project_id,
            ProjectTeam.team_id == data.team_id
        ))
        if not allowed.scalar_one_or_none():
            raise HTTPException(400, "Team is not authorized to submit to this restricted project")

    # 3. Создание записи
    new_sub = Submission(**data.model_dump())
    db.add(new_sub)

    try:
        await db.commit()
        await db.refresh(new_sub)
    except IntegrityError:
        await db.rollback()
        # Срабатывает благодаря UNIQUE(project_id, team_id) в БД
        raise HTTPException(400, "Submission for this team & project already exists")

    return new_sub

# ✅ READ ONE
@submissions_router.get("/{submission_id}", response_model=SubmissionRead)
async def get_submission(submission_id: int, db: AsyncSession = Depends(get_db)):
    sub = await db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    return sub

# ✅ READ ALL FOR PROJECT (Для организатора) + Пагинация
@submissions_router.get("/project/{project_id}", response_model=list[SubmissionRead])
async def list_project_submissions(
    project_id: int,
    skip: int = Query(0, ge=0, description="Смещение"),
    limit: int = Query(50, ge=1, le=100, description="Лимит"),
    db: AsyncSession = Depends(get_db)
):
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    
    res = await db.execute(
        select(Submission)
        .where(Submission.project_id == project_id)
        .order_by(Submission.created_at.desc())  # 🔹 Исправлено: было updated_at
        .offset(skip)
        .limit(limit)
    )
    return res.scalars().all()

# ✅ UPDATE (Изменение текста или смена статуса)
@submissions_router.patch("/{submission_id}", response_model=SubmissionRead)
async def update_submission(
    submission_id: int,
    data: SubmissionUpdate,
    db: AsyncSession = Depends(get_db)
):
    sub = await db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return sub

    # Безопасное обновление атрибутов
    for field, value in update_data.items():
        setattr(sub, field, value)
        
    await db.commit()
    await db.refresh(sub)
    return sub

# ✅ DELETE
@submissions_router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_submission(submission_id: int, db: AsyncSession = Depends(get_db)):
    sub = await db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")

    await db.delete(sub)  # SQLAlchemy 2.0 паттерн
    await db.commit()
    return None

@submissions_router.get("/{submission_id}/review", response_model=SubmissionReviewView)
async def get_submission_for_review(
    submission_id: int,
    reviewer_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Получить работу + артефакты для проверки. Проверяет наличие назначения."""
    # 1. Проверяем, назначен ли пользователь на эту работу
    assign = (await db.execute(select(SubmissionAssignment).where(
        SubmissionAssignment.submission_id == submission_id,
        SubmissionAssignment.reviewer_id == reviewer_id
    ))).scalar_one_or_none()

    if not assign:
        raise HTTPException(403, "You are not assigned to review this submission.")

    # 2. Загружаем работу
    sub = await db.get(Submission, submission_id)
    
    # 3. Загружаем артефакты
    arts_res = await db.execute(select(SubmissionArtifact).where(
        SubmissionArtifact.submission_id == submission_id
    ))
    artifacts = arts_res.scalars().all()

    # 4. Возвращаем строго по твоей схеме SubmissionReviewView
    return SubmissionReviewView(submission=sub, artifacts=artifacts)

@submissions_router.get("/student/{user_id}/list", response_model=list[StudentSubmissionMini])
async def get_student_submissions(
    user_id: int,
    mode: int = Query(..., ge=1, le=2, description="1 = Экспертный, 2 = P2P"),
    search: str | None = Query(None, description="Поиск по названию проекта"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    user = await db.get(User, user_id)
    if not user or not user.team_id:
        raise HTTPException(400, "User not found or not assigned to a team")

    # Базовый запрос: работы команды + название проекта
    stmt = (
        select(Submission, Project.name)
        .join(Project, Submission.project_id == Project.id)
        .where(Submission.team_id == user.team_id, Project.mode == mode)
    )

    # Применяем фильтры
    if search:
        stmt = stmt.where(Project.name.ilike(f"%{search}%"))
    if date_from:
        stmt = stmt.where(Submission.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Submission.created_at <= date_to)

    # Для режима 2 считаем количество комментариев
    if mode == 2:
        stmt = stmt.add_columns(func.count(SubmissionComment.id).label("comment_count"))
        stmt = stmt.outerjoin(SubmissionComment, Submission.id == SubmissionComment.submission_id)
        stmt = stmt.group_by(Submission.id, Project.name)

    stmt = stmt.order_by(Submission.created_at.desc())
    res = await db.execute(stmt)
    rows = res.all()

    # Формируем ответ
    if mode == 1:
        return [StudentSubmissionMini(id=r[0].id, project_name=r[1], status=r[0].status, created_at=r[0].created_at) for r in rows]
    else:
        return [StudentSubmissionMini(id=r[0].id, project_name=r[1], status=r[0].status, created_at=r[0].created_at, comment_count=r[2]) for r in rows]


@submissions_router.get("/{submission_id}/detail/mode1", response_model=SubmissionDetailMode1)
async def get_detail_mode1(submission_id: int, user_id: int, db: AsyncSession = Depends(get_db)):
    sub = await db.get(Submission, submission_id)
    if not sub: raise HTTPException(404, "Submission not found")

    user = await db.get(User, user_id)
    if not user or user.team_id != sub.team_id:
        raise HTTPException(403, "Access denied: submission belongs to another team")

    project = await db.get(Project, sub.project_id)
    if project.mode != 1: raise HTTPException(400, "This endpoint is for Mode 1 only")

    # 1. Артефакты
    arts = (await db.execute(select(SubmissionArtifact).where(SubmissionArtifact.submission_id == sub.id))).scalars().all()

    # 2. Оценки по критериям
    scores_res = await db.execute(
        select(SubmissionCriterionScore.score, ProjectCriterion.name, ProjectCriterion.max_score)
        .join(ProjectCriterion, SubmissionCriterionScore.criterion_id == ProjectCriterion.id)
        .where(SubmissionCriterionScore.submission_id == sub.id)
    )
    scores = [CriterionScoreItem(name=r[1], max_score=r[2], score=r[0]) for r in scores_res.all()]

    # 3. Комментарий эксперта (ищем автора через назначение)
    assign = (await db.execute(select(SubmissionAssignment.reviewer_id).where(
        SubmissionAssignment.submission_id == sub.id, SubmissionAssignment.status == "done"
    ))).scalar_one_or_none()
    
    expert_comment = None
    if assign:
        comments = (await db.execute(select(SubmissionComment.comment).where(
            SubmissionComment.submission_id == sub.id, SubmissionComment.author_id == assign
        ))).scalars().all()
        expert_comment = "\n".join(comments) if comments else None

    return SubmissionDetailMode1(
        project_name=project.name,
        content=sub.content,
        artifacts=arts,
        scores=scores,
        total_mark=sub.mark,
        expert_comment=expert_comment
    )


@submissions_router.get("/{submission_id}/detail/mode2", response_model=SubmissionDetailMode2)
async def get_detail_mode2(submission_id: int, user_id: int, db: AsyncSession = Depends(get_db)):
    sub = await db.get(Submission, submission_id)
    if not sub: raise HTTPException(404, "Submission not found")

    user = await db.get(User, user_id)
    if not user or user.team_id != sub.team_id:
        raise HTTPException(403, "Access denied: submission belongs to another team")

    project = await db.get(Project, sub.project_id)
    if project.mode != 2: raise HTTPException(400, "This endpoint is for Mode 2 only")

    # Комментарии всех студентов-ревьюеров
    comments_res = await db.execute(
        select(SubmissionComment.comment, SubmissionComment.created_at, User.name.label("author_name"))
        .join(User, SubmissionComment.author_id == User.id)
        .where(SubmissionComment.submission_id == sub.id)
        .order_by(SubmissionComment.created_at.asc())
    )
    peer_comments = [PeerCommentView(author_name=r[2], comment=r[0], created_at=r[1]) for r in comments_res.all()]

    return SubmissionDetailMode2(
        project_name=project.name,
        content=sub.content,
        comments=peer_comments
    )