from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from api.models import Team
from api.schemas import TeamCreate, TeamRead, TeamUpdate

teams_router = APIRouter(prefix="/teams", tags=["teams"])

# ✅ CREATE
@teams_router.post("/", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(team_data: TeamCreate, db: AsyncSession = Depends(get_db)):
    new_team = Team(**team_data.model_dump())
    db.add(new_team)
    await db.commit()
    await db.refresh(new_team)
    return new_team

# ✅ READ (один)
@teams_router.get("/{team_id}", response_model=TeamRead)
async def get_team(team_id: int, db: AsyncSession = Depends(get_db)):
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team

# ✅ READ (список с пагинацией)
@teams_router.get("/", response_model=list[TeamRead])
async def list_teams(
    skip: int = Query(0, ge=0, description="Смещение"),
    limit: int = Query(10, ge=1, le=100, description="Лимит записей"),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Team).order_by(Team.id.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()

# ✅ UPDATE (частичное)
@teams_router.patch("/{team_id}", response_model=TeamRead)
async def update_team(
    team_id: int,
    team_update: TeamUpdate,
    db: AsyncSession = Depends(get_db)
):
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    update_data = team_update.model_dump(exclude_unset=True)
    if not update_data:
        return team  # Нечего менять

    # Прямое обновление объекта в памяти (без лишнего SQL-запроса)
    for field, value in update_data.items():
        setattr(team, field, value)

    await db.commit()
    await db.refresh(team)
    return team

# ✅ DELETE
@teams_router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: int, db: AsyncSession = Depends(get_db)):
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    try:
        await db.delete(team)  # SQLAlchemy 2.0 паттерн
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Срабатывает, если у команды есть привязанные проекты (fk_projects_team)
        # или пользователи (fk_users_team)
        raise HTTPException(
            status_code=400,
            detail="Cannot delete team: it has associated projects or users. Please remove them first."
        )
    
    return None