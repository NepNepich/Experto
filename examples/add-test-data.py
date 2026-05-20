import asyncio
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from api.models import (
    Base, Team, User, Project, ProjectTeam, ProjectCriterion,
    Submission, SubmissionAssignment, SubmissionCriterionScore,
    SubmissionComment, SubmissionArtifact
)

load_dotenv()
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "12345")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "experto_database")

DATABASE_URL = f"mysql+aiomysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"auth_plugin": "mysql_native_password"})
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def seed_database(clear_first: bool = False):
    print("🌱 Запуск заполнения БД тестовыми данными...")
    
    async with AsyncSessionLocal() as db:
        # 🔹 Опциональная очистка (раскомментируй, если нужно начать с нуля)
        # ⚠️ УДАЛЯЕТ ВСЕ ДАННЫЕ!
        
        if clear_first:
            print("🧹 Очистка таблиц...")
            await db.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table in reversed(Base.metadata.sorted_tables):
                await db.execute(table.delete())
            await db.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            await db.commit()
            print("✅ Таблицы очищены")

        now = datetime.now(timezone.utc)

        # === 1. КОМАНДЫ ===
        t1 = Team(name="Alpha Devs")
        t2 = Team(name="Beta Squad")
        db.add_all([t1, t2])
        await db.flush()

        # === 2. ПОЛЬЗОВАТЕЛИ (уникальные коды!) ===
        # Студенты Команды 1
        s1 = User(name="Alice", email="alice@test.com", code="alice123", telegram_id=None, academic_role="student", team_role="team_lead", team_id=t1.id)
        s2 = User(name="Bob", email="bob@test.com", code="bob456", telegram_id=None, academic_role="student", team_role="developer", team_id=t1.id)
        s3 = User(name="Charlie", email="charlie@test.com", code="charlie789", telegram_id=None, academic_role="student", team_role="designer", team_id=t1.id)
        
        # Студенты Команды 2
        s4 = User(name="Dave", email="dave@test.com", code="dave111", telegram_id=None, academic_role="student", team_role="team_lead", team_id=t2.id)
        s5 = User(name="Eve", email="eve@test.com", code="eve222", telegram_id=None, academic_role="student", team_role="developer", team_id=t2.id)
        s6 = User(name="Frank", email="frank@test.com", code="frank333", telegram_id=None, academic_role="student", team_role="analytic", team_id=t2.id)

        experts = [
            User(name="Expert1", email="exp1@test.com", code="exp1code", telegram_id=None, academic_role="expert"),
            User(name="Expert2", email="exp2@test.com", code="exp2code", telegram_id=None, academic_role="expert"),
            User(name="Expert3", email="exp3@test.com", code="exp3code", telegram_id=None, academic_role="expert"),
        ]
        orgs = [
            User(name="Org1", email="org1@test.com", code="org1code", telegram_id=None, academic_role="org"),
            User(name="Org2", email="org2@test.com", code="org2code", telegram_id=None, academic_role="org"),
        ]
        db.add_all([s1,s2,s3,s4,s5,s6] + experts + orgs)
        await db.flush()

        all_students = [s1,s2,s3,s4,s5,s6]
        all_teams = [t1, t2]

        # === 3. ПРОЕКТЫ ===
        p1 = Project(name="Hackathon AI (Mode 1 - Done)", mode=1, deadline=now - timedelta(days=10), status="checked", date_created=now - timedelta(days=20))
        p2 = Project(name="WebDev Sprint (Mode 1 - Active)", mode=1, deadline=now + timedelta(days=30), status="assigned", date_created=now - timedelta(days=5))
        p3 = Project(name="GameJam P2P (Mode 2 - Done)", mode=2, deadline=now - timedelta(days=5), status="checked", date_created=now - timedelta(days=15))
        p4 = Project(name="Startup Pitch (Mode 2 - Active)", mode=2, deadline=now + timedelta(days=20), status="submitted", date_created=now - timedelta(days=2))
        db.add_all([p1, p2, p3, p4])
        await db.flush()

        # Привязка команд к режиму 2
        for proj in [p3, p4]:
            for team in all_teams:
                db.add(ProjectTeam(project_id=proj.id, team_id=team.id))

        # === 4. КРИТЕРИИ ===
        crits = [
            ProjectCriterion(project_id=p1.id, name="Innovation", max_score=10, sort_order=1),
            ProjectCriterion(project_id=p1.id, name="Code Quality", max_score=10, sort_order=2),
            ProjectCriterion(project_id=p2.id, name="Architecture", max_score=15, sort_order=1),
            ProjectCriterion(project_id=p2.id, name="Documentation", max_score=5, sort_order=2),
            ProjectCriterion(project_id=p3.id, name="Gameplay", max_score=10, sort_order=1),
            ProjectCriterion(project_id=p4.id, name="Presentation", max_score=10, sort_order=1),
        ]
        db.add_all(crits)
        await db.flush()

        # === 5. РАБОТЫ (SUBMISSIONS) ===
        subs = []
        for proj in [p1, p2, p3, p4]:
            for team in all_teams:
                sub = Submission(
                    project_id=proj.id, 
                    team_id=team.id, 
                    content=f"Submission content for {proj.name} by {team.name}", 
                    status="unchecked", 
                    created_at=now - timedelta(days=2)
                )
                db.add(sub)
                subs.append(sub)
        await db.flush()

        # === 6. ЗАПОЛНЕНИЕ СОСТОЯНИЙ ===
        
        # 🔹 P1 (Mode 1, Дедлайн прошёл, Проверено)
        p1_subs = [s for s in subs if s.project_id == p1.id]
        p1_crits = [c for c in crits if c.project_id == p1.id]
        for sub in p1_subs:
            for exp in experts:
                db.add(SubmissionAssignment(
                    submission_id=sub.id, 
                    reviewer_id=exp.id, 
                    status="done", 
                    assigned_at=now - timedelta(days=3), 
                    completed_at=now - timedelta(days=1)
                ))
                for crit in p1_crits:
                    db.add(SubmissionCriterionScore(
                        submission_id=sub.id, 
                        criterion_id=crit.id, 
                        expert_id=exp.id, 
                        score=7
                    ))
                db.add(SubmissionComment(
                    submission_id=sub.id, 
                    author_id=exp.id, 
                    comment="Excellent submission.", 
                    created_at=now - timedelta(days=1)
                ))
            sub.mark = 14  # 7 + 7
            sub.status = "checked"
            sub.checked_at = now - timedelta(days=1)

        # 🔹 P2 (Mode 1, Дедлайн в будущем, На проверке)
        p2_subs = [s for s in subs if s.project_id == p2.id]
        p2_crits = [c for c in crits if c.project_id == p2.id]
        for sub in p2_subs:
            sub.status = "unchecked"

        # 🔹 P3 (Mode 2, Дедлайн прошёл, P2P завершён)
        p3_subs = [s for s in subs if s.project_id == p3.id]
        for sub in p3_subs:
            for stu in all_students[:3]:  # 3 студента рецензируют
                db.add(SubmissionAssignment(
                    submission_id=sub.id, 
                    reviewer_id=stu.id, 
                    status="done", 
                    assigned_at=now - timedelta(days=4), 
                    completed_at=now - timedelta(days=2)
                ))
                db.add(SubmissionComment(
                    submission_id=sub.id, 
                    author_id=stu.id, 
                    comment="Great UI, needs optimization.", 
                    created_at=now - timedelta(days=2)
                ))
            sub.status = "checked"
            sub.checked_at = now - timedelta(days=2)

        # 🔹 P4 (Mode 2, Дедлайн в будущем, Не назначено) — оставляем как есть

        # === 7. АРТЕФАКТЫ ===
        for sub in subs:
            db.add_all([
                SubmissionArtifact(submission_id=sub.id, url="https://github.com/example/repo", type="link"),
                SubmissionArtifact(submission_id=sub.id, url="https://drive.google.com/docs/example", type="file"),
                SubmissionArtifact(submission_id=sub.id, url="Readme: Check main branch.", type="text")
            ])

        await db.commit()
        print("✅ Seed completed successfully!")
        print("📊 Summary:")
        print("   👥 Users: 11 (2 Org, 3 Expert, 6 Student)")
        print("   🛡️ Teams: 2 (3 students each with roles)")
        print("   📦 Projects: 4 (2x Mode1, 2x Mode2)")
        print("   📝 Submissions: 8 (Checked: 4, Active/Pending: 4)")
        print("   🔑 Telegram IDs: Set to None (MVP mode)")

if __name__ == "__main__":
    # Запуск с очисткой: seed_database(clear_first=True)
    # Запуск без очистки: seed_database(clear_first=False)
    asyncio.run(seed_database(clear_first=True))