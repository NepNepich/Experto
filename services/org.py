import re
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from api.models import (
    User, Project, ProjectCriterion, Team, ProjectTeam,
    Submission, SubmissionAssignment, SubmissionComment, SubmissionArtifact
)
from api.schemas import AcademicRole, ProjectStatus
from database import AsyncSessionLocal

# 📚 Библиотека стандартных критериев (потом легко вынесем в БД)
CRITERIA_TEMPLATES = [
    {"name": "Innovation", "default_max": 15},
    {"name": "Code Quality", "default_max": 20},
    {"name": "Architecture", "default_max": 15},
    {"name": "Presentation", "default_max": 10},
    {"name": "Documentation", "default_max": 10},
    {"name": "Teamwork", "default_max": 10},
]


async def get_criteria_templates() -> list[dict]:
    return CRITERIA_TEMPLATES


# === Авторизация организатора ===
async def get_organizer_by_telegram(telegram_id: int) -> User | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(
                User.telegram_id == telegram_id,
                User.academic_role == AcademicRole.ORG
            )
        )
        return result.scalar_one_or_none()


# === Создание проекта с критериями (атомарно) ===
async def create_project_with_criteria(
    organizer_id: int, name: str, mode: int, deadline: datetime,
    criteria: list[dict] | None = None, participant_team_ids: list[int] | None = None, is_public: bool = True
) -> Project:
    async with AsyncSessionLocal() as session:
        organizer = await session.get(User, organizer_id)
        if not organizer or organizer.academic_role != AcademicRole.ORG:
            raise PermissionError("Только организатор может создавать проекты")
        
        project = Project(
            name=name[:255], mode=mode, deadline=deadline,
            status=ProjectStatus.SUBMITTED, date_created=datetime.now(timezone.utc)
        )
        session.add(project)
        await session.flush()

        if criteria:
            for i, c in enumerate(criteria):
                session.add(ProjectCriterion(
                    project_id=project.id, name=c["name"],
                    max_score=c["max_score"], sort_order=c.get("sort_order", i + 1)
                ))

        if not is_public and participant_team_ids:
            for team_id in participant_team_ids:
                session.add(ProjectTeam(project_id=project.id, team_id=team_id))

        await session.commit()
        await session.refresh(project)
        return project

# 🔥 ИСПРАВЛЕНИЕ 1: Реальное назначение экспертов на существующие работы
async def assign_experts_to_project(project_id: int, expert_ids: list[int]) -> dict:
    async with AsyncSessionLocal() as session:
        # 1. Находим все непроверенные работы этого проекта
        subs_result = await session.execute(
            select(Submission.id).where(
                Submission.project_id == project_id,
                Submission.status == 'unchecked'
            )
        )
        submission_ids = [row[0] for row in subs_result.all()]
        
        if not submission_ids:
            return {"assigned_count": 0, "message": "В проекте пока нет работ для назначения."}

        assigned_count = 0
        for sub_id in submission_ids:
            for exp_id in expert_ids:
                # Проверяем UniqueConstraint('submission_id', 'reviewer_id')
                exists = await session.execute(
                    select(SubmissionAssignment.id).where(
                        SubmissionAssignment.submission_id == sub_id,
                        SubmissionAssignment.reviewer_id == exp_id
                    )
                )
                if not exists.scalar_one_or_none():
                    session.add(SubmissionAssignment(
                        submission_id=sub_id,
                        reviewer_id=exp_id,
                        status='pending',
                        assigned_at=datetime.now(timezone.utc)
                    ))
                    assigned_count += 1
        
        await session.commit()
        return {"assigned_count": assigned_count, "message": f"Успешно создано {assigned_count} заданий."}

# 🔥 ВСПОМОГАТЕЛЬНАЯ: Получить список ID экспертов, уже назначенных на проект
async def get_project_experts(project_id: int) -> list[int]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SubmissionAssignment.reviewer_id).distinct().join(Submission).where(
                Submission.project_id == project_id
            )
        )
        return [row[0] for row in result.all()]

async def get_organizer_projects(organizer_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Project).where(Project.deadline > datetime.now(timezone.utc)).order_by(Project.deadline)
        )
        projects = result.scalars().all()
        return [{"id": p.id, "name": p.name, "mode": p.mode, "deadline": p.deadline, "status": p.status} for p in projects]

# === Дашборд проекта ===
async def get_project_dashboard(project_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        from sqlalchemy import case

        stats = await session.execute(
            select(
                func.count(Submission.id).label("total"),
                func.sum(
                    case(
                        (Submission.status == "checked", 1),
                        else_=0
                    )
                ).label("checked"),
                func.sum(
                    case(
                        (Submission.status == "unchecked", 1),
                        else_=0
                    )
                ).label("pending")
            ).where(Submission.project_id == project_id)
        )
        s = stats.one()

        # Эксперты и их прогресс (тоже через CASE)
        experts = await session.execute(
            select(
                User.id,
                User.name,
                func.sum(
                    case(
                        (SubmissionAssignment.status == "done", 1),
                        else_=0
                    )
                ).label("checked_count")
            )
            .join(SubmissionAssignment, User.id == SubmissionAssignment.reviewer_id)
            .join(Submission, SubmissionAssignment.submission_id == Submission.id)
            .where(Submission.project_id == project_id)
            .group_by(User.id, User.name)
        )

        # Критерии
        criteria = await session.execute(
            select(ProjectCriterion.name, ProjectCriterion.max_score)
            .where(ProjectCriterion.project_id == project_id)
            .order_by(ProjectCriterion.sort_order)
        )

        return {
            "project_id": project_id,
            "total_submissions": s.total or 0,
            "checked_submissions": s.checked or 0,
            "pending_submissions": s.pending or 0,
            "experts": [
                {"expert_id": e.id, "expert_name": e.name, "checked_count": e.checked_count or 0}
                for e in experts.all()
            ],
            "criteria": [
                {"name": c.name, "max_score": c.max_score}
                for c in criteria.all()
            ]
        }


async def export_project_results(project_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        # Получаем все работы проекта
        submissions = await session.execute(
            select(Submission)
            .where(Submission.project_id == project_id)
            .options(
                selectinload(Submission.team),
                selectinload(Submission.comments)
                .selectinload(SubmissionComment.author)
            )
            .order_by(Submission.team_id)
        )
        subs = submissions.scalars().all()

        output = []
        for sub in subs:
            # Собираем комментарии
            comments = [
                {
                    "author": c.author.name if c.author else f"ID {c.author_id}",
                    "text": c.comment
                }
                for c in sub.comments
            ]

            output.append({
                "team_name": sub.team.name if sub.team else f"Команда #{sub.team_id}",
                "submission_id": sub.id,
                "mark": sub.mark,
                "status": sub.status,
                "checked_at": sub.checked_at.strftime("%Y-%m-%d %H:%M") if sub.checked_at else None,
                "comments": comments
            })

        return output


# === Список всех экспертов ===
async def get_all_experts() -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.academic_role == AcademicRole.EXPERT).order_by(User.name)
        )
        return [{"id": e.id, "name": e.name, "email": e.email, "telegram_id": e.telegram_id} for e in result.scalars().all()]

async def get_all_teams() -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Team).order_by(Team.name))
        return [{"id": t.id, "name": t.name} for t in result.scalars().all()]

async def org_bulk_submit_works(organizer_id: int, project_id: int, works_raw: list[str]) -> dict:
    async with AsyncSessionLocal() as session:
        organizer = await session.get(User, organizer_id)
        if not organizer or organizer.academic_role != AcademicRole.ORG:
            raise PermissionError("Только организатор может загружать работы")
            
        project = await session.get(Project, project_id)
        if not project or project.mode != 1:
            raise ValueError("Проект не найден или не относится к Режиму 1")

        results = {"success": [], "errors": []}
        
        # Получаем экспертов, которые уже работают над этим проектом
        project_expert_ids = await get_project_experts(project_id)

        for line in works_raw:
            line = line.strip()
            if not line or ": " not in line:
                continue

            team_part, rest = line.split(": ", 1)
            rest = rest.strip()
            match = re.search(r'\d+', team_part.strip())
            
            if not match:
                results["errors"].append(f"❌ Не найден ID в строке: `{line}`")
                continue

            team_id = int(match.group())
            title, link_or_text = ("", rest) if "| " not in rest else rest.split("| ", 1)
            title, link_or_text = title.strip(), link_or_text.strip()

            team = await session.get(Team, team_id)
            if not team:
                results["errors"].append(f"❌ Команда ID {team_id} не найдена")
                continue

            existing = await session.execute(
                select(Submission.id).where(Submission.project_id == project_id, Submission.team_id == team_id)
            )
            if existing.scalar_one_or_none():
                results["errors"].append(f"⚠️ Команда `{team.name}` уже загрузила работу")
                continue

            content = title if title else ("Ссылка на работу" if link_or_text.startswith("http") else link_or_text)
            submission = Submission(
                project_id=project_id, team_id=team_id, content=content,
                status='unchecked', created_at=datetime.now(timezone.utc)
            )
            session.add(submission)  # <-- ИСПРАВЛЕНО: добавлена закрывающая скобка
            await session.flush()    # <-- flush вынесен на отдельную строку

            if link_or_text.startswith("http"):
                session.add(SubmissionArtifact(submission_id=submission.id, url=link_or_text, type='link'))

            # 🔥 АВТО-НАЗНАЧЕНИЕ: Создаем задания для экспертов проекта на эту новую работу
            for exp_id in project_expert_ids:
                session.add(SubmissionAssignment(
                    submission_id=submission.id,
                    reviewer_id=exp_id,
                    status='pending',
                    assigned_at=datetime.now(timezone.utc)
                ))

            team_info = f"{team.name} (ID: {team_id})" + (f" — \"{title}\"" if title else "")
            results["success"].append(f"✅ {team_info}")

        await session.commit()
        return results