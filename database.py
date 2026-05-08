# database.py
import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from dotenv import load_dotenv

load_dotenv()

# Строка подключения: mysql+aiomysql://user:pass@host:port/db
DATABASE_URL = (
    f"mysql+aiomysql://{os.getenv('DB_USER', 'root')}:"
    f"{os.getenv('DB_PASSWORD', '')}@"
    f"{os.getenv('DB_HOST', 'localhost')}:"
    f"{os.getenv('DB_PORT', 3306)}/"
    f"{os.getenv('DB_NAME', 'experto_database')}"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Поставь True, чтобы видеть SQL-запросы в консоли
    pool_pre_ping=True,  # Проверка соединения перед использованием
    pool_recycle=3600    # Переподключение раз в час (защита от MySQL timeout)
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость для инъекции сессии БД в роутеры"""
    async with AsyncSessionLocal() as session:
        yield session