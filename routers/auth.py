import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from api.models import User
from api.schemas import WebLoginRequest, BotLoginRequest, LoginResponse

auth_router = APIRouter(prefix="/auth", tags=["auth"])

# ==================== ВЕБ-ВХОД (только существующие пользователи) ====================

@auth_router.post("/web", response_model=LoginResponse)
async def web_login(data: WebLoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found. Please contact support to register.")
    
    return LoginResponse(user_id=user.id, academic_role=user.academic_role, message="Login successful")

# ==================== БОТ-ВХОД (сверка TG ID или авторегистрация) ====================

@auth_router.post("/bot", response_model=LoginResponse)
async def bot_login(data: BotLoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()

    if user:
        # Пользователь есть → сверяем Telegram ID
        if user.telegram_id != data.telegram_id:
            raise HTTPException(403, "Telegram ID does not match the registered account.")
        return LoginResponse(user_id=user.id, academic_role=user.academic_role, message="Login successful")
    
    # Пользователя нет → создаём нового с привязкой к боту
    try:
        new_user = User(
            name=data.email.split("@")[0] or "bot_user",
            email=data.email,
            code=secrets.token_urlsafe(8),
            telegram_id=data.telegram_id,
            academic_role="student"
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, "Failed to register user. Email conflict.")

    return LoginResponse(user_id=new_user.id, academic_role=new_user.academic_role, message="New user registered and logged in")