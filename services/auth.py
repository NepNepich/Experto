from sqlalchemy import select
from utils import generate_user_code
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from database import AsyncSessionLocal
from api.models import User
from api.schemas import AcademicRole


async def find_user_by_email(email: str) -> User | None:
    """Поиск пользователя по email (case-insensitive)"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email.ilike(email.strip()))
        )
        return result.scalar_one_or_none()


async def register_new_user(
        email: str,
        name: str | None = None,
        telegram_id: int | None = None,
        telegram_username: str | None = None
) -> tuple[bool, User | str]:
    """
    Регистрирует нового пользователя в БД.

    Возвращает:
        (True, User) — при успехе
        (False, "error message") — при ошибке
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 1. Проверяем, нет ли уже такого email
            existing = await session.execute(
                select(User).where(User.email.ilike(email.strip()))
            )
            if existing.scalar_one_or_none():
                return False, "Пользователь с таким email уже зарегистрирован"

            # 2. Генерируем уникальный code (с защитой от коллизий)
            max_attempts = 5
            for _ in range(max_attempts):
                code = generate_user_code()
                # Проверяем уникальность
                conflict = await session.execute(
                    select(User.id).where(User.code == code)
                )
                if not conflict.scalar_one_or_none():
                    break
            else:
                return False, "Не удалось сгенерировать уникальный код. Попробуйте позже."

            # 3. Создаём пользователя
            display_name = name or telegram_username or email.split('@')[0]

            new_user = User(
                name=display_name[:127],  # Обрезаем под лимит БД
                email=email.strip().lower(),
                code=code,
                telegram_id=telegram_id,
                academic_role=AcademicRole.STUDENT,  # По умолчанию — студент
                team_id=None  # Команду можно назначить позже
            )

            try:
                session.add(new_user)
                await session.commit()
                await session.refresh(new_user)
                return True, new_user
            except IntegrityError as e:
                await session.rollback()
                # Дубликат email или code (маловероятно, но бывает)
                if "email" in str(e).lower():
                    return False, "Этот email уже занят"
                elif "code" in str(e).lower():
                    return False, "Ошибка генерации кода. Попробуйте ещё раз"
                return False, "Ошибка регистрации. Попробуйте позже."

async def bind_telegram_account(user_id: int, telegram_id: int, telegram_username: str | None = None) -> bool:
    """
    Привязывает Telegram-аккаунт к пользователю в БД.
    Возвращает True при успехе, False если:
    - пользователь не найден
    - telegram_id уже занят другим пользователем
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():  # 🔥 Транзакция
            user = await session.get(User, user_id)
            if not user:
                return False

            # Проверка: не занят ли этот telegram_id другим
            conflict = await session.execute(
                select(User.id).where(
                    User.telegram_id == telegram_id,
                    User.id != user_id
                )
            )
            if conflict.scalar_one_or_none():
                return False  # Конфликт: такой аккаунт уже привязан

            # Обновляем пользователя
            user.telegram_id = telegram_id
            # Опционально: обновляем username, если он изменился
            if telegram_username and user.name == user.email.split('@')[0]:
                user.name = telegram_username

            await session.commit()
            return True


async def get_user_by_telegram(telegram_id: int) -> User | None:
    """Получение пользователя по telegram_id (для авторизованных)"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def get_user_role(telegram_id: int) -> AcademicRole | None:
    """Возвращает роль пользователя для роутинга меню"""
    user = await get_user_by_telegram(telegram_id)
    return user.academic_role if user else None