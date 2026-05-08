from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from routers.router import router

# Современный способ запуска/остановки (FastAPI 0.110+)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Сюда можно добавить проверку подключения к БД, кэширование конфигов и т.д.
    print("🚀 Experto Backend запущен")
    yield
    print(" Experto Backend остановлен")

app = FastAPI(
    title="Experto Backend",
    description="API для управления проектами и экспертной оценки",
    version="0.1.0",
    lifespan=lifespan
)

# 🔹 CORS: разрешаем запросы с фронтенда и бота
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене укажи конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔹 Подключаем роутеры
app.include_router(router)

# 🔹 Эндпоинт здоровья
@app.get("/health")
async def health():
    return {"status": "ok", "service": "Experto Backend"}