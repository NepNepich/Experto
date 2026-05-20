from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from api.models import User
from api.schemas import UserCreate, UserRead, UserUpdate

users_router = APIRouter(prefix="/users", tags=["users"])

# CREATE
@users_router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    email_exists = await db.execute(select(User).where(User.email == user_data.email))
    if email_exists.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    code_exists = await db.execute(select(User).where(User.code == user_data.code))
    if code_exists.scalar_one_or_none():
        raise HTTPException(400, "Code already registered")

    new_user = User(**user_data.model_dump())
    db.add(new_user)

    try:
        await db.commit()
        await db.refresh(new_user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, "Invalid team_id: team does not exist or constraint violation")

    return new_user

# READ (один)
@users_router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user

# READ (список с пагинацией)
@users_router.get("/", response_model=list[UserRead])
async def list_users(
    skip: int = Query(0, ge=0, description="Смещение"),
    limit: int = Query(10, ge=1, le=100, description="Лимит записей"),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).order_by(User.id.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()

# UPDATE (частичное)
@users_router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_db)
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    update_data = user_update.model_dump(exclude_unset=True)
    if not update_data:
        return user

    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user

# DELETE
@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    await db.delete(user)
    await db.commit()
    return None