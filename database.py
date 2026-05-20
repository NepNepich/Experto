# database.py
import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

# 🔹 Конфигурация подключения
DATABASE_URL = (
    f"mysql+aiomysql://{os.getenv('DB_USER', 'root')}:"
    f"{os.getenv('DB_PASSWORD', '')}@"
    f"{os.getenv('DB_HOST', 'localhost')}:"
    f"{os.getenv('DB_PORT', 3306)}/"
    f"{os.getenv('DB_NAME', 'experto_database')}"
    f"?charset=utf8mb4"  # 👈 Явно указываем кодировку для emoji и кириллицы
)

# 🔹 Настройки пула соединений (оптимизировано для продакшена)
engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",  # Логи запросов через env
    pool_pre_ping=True,           # Проверка "живости" соединения перед использованием
    pool_recycle=3600,            # Пересоздавать соединения раз в час (защита от MySQL wait_timeout)
    pool_size=int(os.getenv("DB_POOL_SIZE", 10)),      # Количество постоянных соединений
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", 20)), # Дополнительные соединения при пике
    connect_args={
        "connect_timeout": 10,   # Таймаут подключения (сек)
    }
)

# 🔹 Фабрика сессий
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Важно: объекты не "протухают" после коммита, доступны в кэше
    autoflush=False          # Отключаем авто-flush для явного контроля (опционально)
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Зависимость FastAPI для инъекции сессии БД.
    Гарантирует закрытие сессии и откат при ошибке.
    """
    session = AsyncSessionLocal()
    try:
        yield session
        # Если всё прошло успешно — коммит уже сделан в роутере.
        # Если нет — выбросится исключение и сработает except ниже.
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

async def check_database_connection() -> bool:
    """
    Утилита для проверки подключения к БД (используется в lifespan).
    Возвращает True, если соединение успешно, иначе пробрасывает исключение.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        raise

# 🔹 Экспорт для удобства импорта в других файлах
__all__ = ["engine", "AsyncSessionLocal", "get_db", "check_database_connection"]