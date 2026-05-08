# routers/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from database import get_db
from api.models import *

from api.schemas import *

router = APIRouter(prefix="/api/v1", tags=["main"])

# ==================== USERS ====================

@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user( data: UserCreate, db: AsyncSession = Depends(get_db)):
    # Проверка на дубликат
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    
    new_user = User(**data.model_dump())
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

# ==================== PROJECTS ====================

@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project( data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    # Валидация команды-создателя
    result = await db.execute(select(Team).where(Team.id == data.creator_team_id))
    if not result.scalar_one_or_none():
        raise HTTPException(400, "Creator team not found")

    # Создаем проект
    new_project = Project(
        name=data.name,
        mode=data.mode,
        team_id=data.creator_team_id, # creator_team_id -> team_id (владелец)
        status="submitted"
    )
    db.add(new_project)
    await db.commit()
    await db.refresh(new_project)
    
    # Если режим 2: сохраняем связи с командами-участниками
    if data.mode == 2 and data.participant_team_ids:
        for tid in data.participant_team_ids:
            # Тут можно добавить проверку существования team_id
            db.add(ProjectTeam(project_id=new_project.id, team_id=tid))
        await db.commit()
        
    return new_project

@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    return project

@router.get("/projects/my", response_model=list[ProjectRead])
async def get_my_projects(team_id: int, db: AsyncSession = Depends(get_db)):
    """Логика: (Режим 1) ИЛИ (Режим 2 + есть в project_teams)"""
    
    # 1. Запрос на глобальные проекты (mode=1)
    query_global = select(Project).where(Project.mode == 1)
    
    # 2. Запрос на проекты для конкретной команды (mode=2)
    # Нужно сделать JOIN с таблицей project_teams
    query_team = (
        select(Project)
        .join(ProjectTeam) # Убедись, что модель ProjectTeam создана
        .where(Project.mode == 2, ProjectTeam.team_id == team_id)
    )
    
    # Объединяем запросы (UNION)
    # В чистом SQLAlchemy 2.0 это делается через .union()
    from sqlalchemy import union
    combined_query = union(query_global, query_team).order_by(Project.date_created.desc())
    
    result = await db.execute(combined_query)
    projects = result.scalars().all()
    return projects

# ==================== SCORES & COMMENTS (ИСПРАВЛЕНО) ====================

@router.post("/projects/{project_id}/scores", response_model=ScoreRead)
async def add_score(
    project_id: int,
    data: ScoreCreate,  # 👈 ФИКС: добавили имя переменной 'data'
    db: AsyncSession = Depends(get_db)
):
    if data.project_id != project_id:
        raise HTTPException(400, "project_id mismatch in URL and body")
    
    # Проверка: существует ли критерий и проект
    criterion_res = await db.execute(
        select(ProjectCriterion).where(
            ProjectCriterion.id == data.criterion_id,
            ProjectCriterion.project_id == project_id
        )
    )
    if not criterion_res.scalar_one_or_none():
        raise HTTPException(404, "Criterion not found for this project")

    # Используем INSERT ... ON DUPLICATE KEY UPDATE для обновления оценки
    from sqlalchemy.dialects.mysql import insert
    stmt = insert(ProjectCriterionScore).values(
        project_id=project_id,
        criterion_id=data.criterion_id,
        expert_id=data.reviewer_id,
        score=data.score
    ).on_duplicate_key_update(score=data.score)
    
    await db.execute(stmt)
    
    # Пересчет общего балла (mark)
    score_res = await db.execute(
        select(func.sum(ProjectCriterionScore.score)).where(
            ProjectCriterionScore.project_id == project_id
        )
    )
    total_mark = score_res.scalar() or 0
    
    await db.execute(
        update(Project).where(Project.id == project_id).values(
            mark=total_mark,
            status="checked",
            date_checked=datetime.utcnow()
        )
    )
    
    await db.commit()
    return data # Возвращаем то, что приняли

@router.post("/projects/{project_id}/comments", response_model=CommentRead)
async def add_comment(
    project_id: int,
    data: CommentCreate,
    db: AsyncSession = Depends(get_db)
):
    if data.project_id != project_id:
        raise HTTPException(400, "project_id mismatch")
    
    new_comment = ProjectComment(**data.model_dump())
    db.add(new_comment)
    await db.commit()
    await db.refresh(new_comment)
    return new_comment

@router.get("/projects/{project_id}/comments", response_model=list[CommentRead])
async def get_comments(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProjectComment)
        .where(ProjectComment.project_id == project_id)
        .order_by(ProjectComment.created_at.desc())
    )
    return result.scalars().all()

# TEAMS

@router.post("/teams", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team( data: TeamCreate, db: AsyncSession = Depends(get_db)):
    new_team = Team(name=data.name)
    db.add(new_team)
    await db.commit()
    await db.refresh(new_team)
    return new_team