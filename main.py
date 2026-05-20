from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database import engine, check_database_connection

from routers.users import users_router
from routers.teams import teams_router
from routers.projects import projects_router
from routers.submissions import submissions_router
from routers.scoring import scoring_router
from routers.assignments import assignments_router
from routers.artifacts import artifacts_router
from routers.auth import auth_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await check_database_connection()  # 👈 Проверка перед стартом
    print("🚀 Experto Backend запущен")
    yield
    await engine.dispose()  # 👈 Корректное закрытие пула при остановке
    print("✅ Experto Backend остановлен")
    
app = FastAPI(
    title="Experto Backend",
    description="API для управления проектами и экспертной оценки",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# 🔒 CORS Configuration
# ⚠️ Важно: allow_origins=["*"] + allow_credentials=True блокируется современными браузерами.
# Для разработки используйте конкретные домены или allow_origin_regex.
CORS_ORIGINS = [
    "http://localhost:3000",   # Next.js / React dev
    "http://localhost:5173",   # Vite / Vue dev
    "http://127.0.0.1:8080",   # Local dev
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # Для локальной отладки можно временно вернуть ["*"], убрав credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔌 Роутеры
app.include_router(users_router)
app.include_router(teams_router)
app.include_router(projects_router)
app.include_router(submissions_router)
app.include_router(scoring_router)
app.include_router(assignments_router)
app.include_router(artifacts_router)
app.include_router(auth_router)

# 🩹 Health Check
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "Experto Backend",
        "version": app.version
    }