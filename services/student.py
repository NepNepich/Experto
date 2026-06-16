from datetime import datetime, timezone
from datetime import datetime, timezone

from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload

from api.models import Submission, SubmissionCriterionScore, SubmissionComment, User, Project
from api.models import (
    SubmissionAssignment,
    SubmissionArtifact, ProjectTeam
)
from api.schemas import AcademicRole, SubmissionStatus, AssignmentStatus, ArtifactType
from database import AsyncSessionLocal


# === Авторизация ===
async def get_student_by_telegram(telegram_id: int) -> User | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.team))
        )
        user = result.scalar_one_or_none()
        return user if user and user.academic_role == AcademicRole.STUDENT else None


# === Активные проекты для студента ===
async def get_student_projects(telegram_id: int, mode: int) -> list[Project]:
    """Режим 1: свои сабмишены | Режим 2: + доступные для P2P"""
    async with AsyncSessionLocal() as session:
        user = await get_student_by_telegram(telegram_id)
        if not user or not user.team_id:
            return []

        # Базовый фильтр
        query = select(Project).where(
            Project.mode == mode,
            Project.deadline > datetime.now(timezone.utc)
        )

        # Режим 2: только проекты, где команда студента участвует
        if mode == 2:
            query = query.join(ProjectTeam).where(
                ProjectTeam.team_id == user.team_id
            )

        result = await session.execute(query.order_by(Project.deadline))
        return list(result.scalars().all())


# === Отправка работы (с артефактами) ===
async def submit_work(
        telegram_id: int,
        project_id: int,
        content: str,
        artifacts: list[dict]
) -> Submission:
    async with AsyncSessionLocal() as session:
        # 1. Находим пользователя и проверяем команду
        res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = res.scalar_one_or_none()
        if not user or not user.team_id:
            raise ValueError("Вы не привязаны к команде. Обратитесь к организатору.")
        project = await session.get(Project, project_id)
        if not project:
            raise ValueError("Проект не найден")
        if project.mode == 1:
            raise ValueError("В этом режиме работы загружает только организатор.")
        # 2. Проверка на дубликат (одна команда = одна работа на проект)
        check = await session.execute(
            select(Submission.id).where(
                Submission.project_id == project_id,
                Submission.team_id == user.team_id
            )
        )
        if check.scalar_one_or_none():
            raise ValueError("Работа уже отправлена в этот проект")

        # 3. Создаём запись
        submission = Submission(
            project_id=project_id,
            team_id=user.team_id,
            content=content,
            status="unchecked",
            created_at=datetime.now(timezone.utc)
        )
        session.add(submission)
        await session.flush()  # Получаем submission.id до коммита

        # 4. Привязываем артефакты
        for art in artifacts:
            session.add(SubmissionArtifact(
                submission_id=submission.id,
                url=art["url"],
                type=ArtifactType(art.get("type", "link"))
            ))

        # 5. Коммитим всё одной транзакцией
        await session.commit()
        await session.refresh(submission)
        return submission


async def get_active_projects_for_team(team_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        has_teams_subquery = (
            select(func.count(ProjectTeam.team_id))
            .where(ProjectTeam.project_id == Project.id)
            .scalar_subquery()
        )
        team_in_project_subquery = (
            select(func.count(ProjectTeam.team_id))
            .where(
                (ProjectTeam.project_id == Project.id) &
                (ProjectTeam.team_id == team_id)
            )
            .scalar_subquery()
        )

        result = await session.execute(
            select(Project)
            .where(
                Project.deadline > datetime.now(timezone.utc),
                Project.status.in_(["submitted", "assigned"]),
                Project.mode.in_([1, 2]),
                (
                    (has_teams_subquery == 0) |  # Открытый проект
                    (team_in_project_subquery > 0)  # Команда добавлена
                )
            )
            .order_by(Project.deadline)
        )
        projects = result.scalars().all()

        return [
            {"id": p.id, "name": p.name, "mode": p.mode, "deadline": p.deadline}
            for p in projects
        ]


# === Взять работу на рецензию (P2P, режим 2) ===
async def get_peer_review_task(telegram_id: int, project_id: int) -> dict | None:
    """Найти работу другой команды для рецензии"""
    async with AsyncSessionLocal() as session:
        user = await get_student_by_telegram(telegram_id)
        if not user or not user.team_id:
            return None

        # Ищем незавершённое задание
        pending = await session.execute(
            select(SubmissionAssignment)
            .where(
                SubmissionAssignment.reviewer_id == user.id,
                SubmissionAssignment.status == AssignmentStatus.PENDING
            )
            .options(selectinload(SubmissionAssignment.submission))
            .limit(1)
        )
        assign = pending.scalar_one_or_none()
        if assign:
            return {"assignment_id": assign.id, "submission": assign.submission}

        # Ищем новую работу: не своя команда, не проверена, не назначена этому рецензенту
        available = await session.execute(
            select(Submission)
            .where(
                Submission.project_id == project_id,
                Submission.team_id != user.team_id,  # ❌ Не своя команда
                Submission.status == SubmissionStatus.UNCHECKED,
                Submission.id.notin_(
                    select(SubmissionAssignment.submission_id)
                    .where(SubmissionAssignment.reviewer_id == user.id)
                )
            )
            .limit(1)
        )
        submission = available.scalar_one_or_none()
        if not submission:
            return None

        # Создаём задание
        new_assign = SubmissionAssignment(
            submission_id=submission.id,
            reviewer_id=user.id,
            status=AssignmentStatus.PENDING,
            assigned_at=datetime.now(timezone.utc)
        )
        session.add(new_assign)
        await session.commit()
        await session.refresh(new_assign)

        return {"assignment_id": new_assign.id, "submission": submission}


# === Просмотр работы для рецензии ===
async def get_submission_for_review(submission_id: int, reviewer_id: int) -> dict | None:
    async with AsyncSessionLocal() as session:
        # Проверяем, имеет ли право рецензент видеть эту работу
        assign = await session.execute(
            select(SubmissionAssignment)
            .where(
                SubmissionAssignment.submission_id == submission_id,
                SubmissionAssignment.reviewer_id == reviewer_id
            )
        )
        if not assign.scalar_one_or_none():
            return None

        submission = await session.execute(
            select(Submission)
            .where(Submission.id == submission_id)
            .options(
                selectinload(Submission.artifacts),
                selectinload(Submission.project)
            )
        )
        sub = submission.scalar_one_or_none()
        if not sub:
            return None

        return {
            "submission": sub,
            "artifacts": sub.artifacts,
            "project_name": sub.project.name
        }


# === Добавление/обновление комментария ===
async def submit_peer_comment(
    assignment_id: int,
    comment_text: str,
    edit_comment_id: int | None = None
) -> dict:
    async with AsyncSessionLocal() as session:
        # 🔥 УБРАНО: async with session.begin():
        
        assign = await session.get(SubmissionAssignment, assignment_id)
        if not assign or assign.status != AssignmentStatus.PENDING:
            raise ValueError("Задание не найдено или уже завершено")
        
        if edit_comment_id:
            # Редактирование
            comment = await session.execute(
                select(SubmissionComment).where(
                    SubmissionComment.id == edit_comment_id,
                    SubmissionComment.author_id == assign.reviewer_id,
                    SubmissionComment.submission_id == assign.submission_id
                )
            )
            cmt = comment.scalar_one_or_none()
            if not cmt:
                raise ValueError("Комментарий не найден или недоступен для редактирования")
            cmt.comment = comment_text
        else:
            # Новый комментарий
            cmt = SubmissionComment(
                submission_id=assign.submission_id,
                author_id=assign.reviewer_id,
                comment=comment_text,
                created_at=datetime.now(timezone.utc)
            )
            session.add(cmt)
            await session.flush()  
        await session.commit()
        await session.refresh(cmt)
        
        return {
            "id": cmt.id, 
            "action": "updated" if edit_comment_id else "created"
        }


# === Финализация рецензии ===
async def finalize_student_peer_review(assignment_id: int) -> dict:
    """Финализация рецензии студентом: проверка комментария + пересчёт среднего балла"""
    async with AsyncSessionLocal() as session:
        assign = await session.get(SubmissionAssignment, assignment_id)
        if not assign or assign.status == "done": # или AssignmentStatus.DONE
            raise ValueError("Задание не найдено или уже завершено")

        submission_id = assign.submission_id
        reviewer_id = assign.reviewer_id

        # 1. Проверяем наличие комментария именно этого студента
        has_comment = await session.execute(
            select(SubmissionComment.id).where(
                SubmissionComment.submission_id == submission_id,
                SubmissionComment.author_id == reviewer_id
            ).limit(1)
        )
        if not has_comment.scalar_one_or_none():
            raise ValueError("Нельзя отправить рецензию без вашего комментария")

        # 2. Завершаем задание рецензента
        assign.status = "done" # или AssignmentStatus.DONE
        assign.completed_at = datetime.now(timezone.utc)

        # 3. Считаем среднюю оценку по ВСЕМ рецензиям на эту работу
        avg_result = await session.execute(
            select(func.avg(SubmissionCriterionScore.score))
            .where(SubmissionCriterionScore.submission_id == submission_id)
        )
        avg_score = avg_result.scalar_one_or_none()

        # 4. Обновляем саму работу (Submission)
        if avg_score is not None:
            await session.execute(
                update(Submission)
                .where(Submission.id == submission_id)
                .values(
                    mark=round(avg_score),
                    status="checked", # или SubmissionStatus.CHECKED
                    checked_at=datetime.now(timezone.utc)
                )
            )

        await session.commit()

        return {
            "submission_id": submission_id,
            "final_mark": round(avg_score) if avg_score else None
        }


# Вспомогательная функция
async def get_peer_review_task_by_user(user_id: int, project_id: int) -> dict | None:
    """Внутренняя: получить следующее задание без проверки telegram"""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.team_id:
            return None

        available = await session.execute(
            select(Submission)
            .where(
                Submission.project_id == project_id,
                Submission.team_id != user.team_id,
                Submission.status == SubmissionStatus.UNCHECKED,
                Submission.id.notin_(
                    select(SubmissionAssignment.submission_id)
                    .where(SubmissionAssignment.reviewer_id == user_id)
                )
            )
            .limit(1)
        )
        submission = available.scalar_one_or_none()
        if not submission:
            return None

        new_assign = SubmissionAssignment(
            submission_id=submission.id,
            reviewer_id=user_id,
            status=AssignmentStatus.PENDING,
            assigned_at=datetime.now(timezone.utc)
        )
        session.add(new_assign)
        await session.commit()
        await session.refresh(new_assign)

        return {"assignment_id": new_assign.id, "submission": submission}


# === Просмотр своих работ и фидбека ===
async def get_my_submissions(telegram_id: int, project_id: int | None = None) -> list[dict]:
    """Вернуть список работ студента с фидбеком"""
    async with AsyncSessionLocal() as session:
        user = await get_student_by_telegram(telegram_id)
        if not user or not user.team_id:
            return []

        query = select(Submission).where(
            Submission.team_id == user.team_id
        ).options(
            selectinload(Submission.project),
            selectinload(Submission.comments),
            selectinload(Submission.scores)  # для режима 1
        )

        if project_id:
            query = query.where(Submission.project_id == project_id)

        result = await session.execute(query.order_by(Submission.created_at.desc()))
        submissions = result.scalars().all()

        return [
            {
                "id": s.id,
                "project_name": s.project.name,
                "status": s.status,
                "created_at": s.created_at,
                "content": s.content[:200] + "..." if len(s.content) > 200 else s.content,
                "comments": [
                    {"author": c.author.name, "text": c.comment, "created_at": c.created_at}
                    for c in s.comments
                ],
                "scores": [
                    {"criterion": sc.criterion.name, "score": sc.score, "max": sc.criterion.max_score}
                    for sc in s.scores
                ] if s.scores else None,
                "mark": s.mark
            }
            for s in submissions
        ]


async def get_student_submissions_with_feedback(telegram_id: int, project_id: int | None = None) -> list[dict]:
    """
    Возвращает список работ студента с оценками и комментариями экспертов.
    Если project_id указан — фильтрует по проекту.
    """
    async with AsyncSessionLocal() as session:
        # Находим студента
        student = await session.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.team))
        )
        user = student.scalar_one_or_none()
        if not user or not user.team_id:
            return []

        # Запрос работ с подгрузкой связанных данных
        query = select(Submission).where(
            Submission.team_id == user.team_id
        ).options(
            selectinload(Submission.project),
            selectinload(Submission.scores)
            .selectinload(SubmissionCriterionScore.criterion),
            selectinload(Submission.scores)
            .selectinload(SubmissionCriterionScore.expert),
            selectinload(Submission.comments)
            .selectinload(SubmissionComment.author)
        )

        if project_id:
            query = query.where(Submission.project_id == project_id)

        query = query.order_by(Submission.created_at.desc())

        result = await session.execute(query)
        submissions = result.scalars().all()

        # Формируем удобный ответ
        output = []
        for sub in submissions:
            # Группируем оценки по критериям
            scores_by_criterion = {}
            for score in sub.scores:
                crit_name = score.criterion.name
                if crit_name not in scores_by_criterion:
                    scores_by_criterion[crit_name] = {
                        "scores": [],
                        "max_score": score.criterion.max_score
                    }
                scores_by_criterion[crit_name]["scores"].append({
                    "expert": score.expert.name,
                    "value": score.score
                })

            # Считаем среднее по каждому критерию
            criteria_summary = []
            for crit_name, data in scores_by_criterion.items():
                avg = sum(s["value"] for s in data["scores"]) / len(data["scores"])
                criteria_summary.append({
                    "name": crit_name,
                    "average": round(avg, 1),
                    "max": data["max_score"],
                    "details": data["scores"]
                })

            # Комментарии экспертов
            comments = [
                {
                    "author": c.author.name,
                    "text": c.comment,
                    "created_at": c.created_at.strftime("%d.%m.%Y %H:%M") if c.created_at else None
                }
                for c in sub.comments
                if c.author_id != user.id  
            ]   

            output.append({
                "id": sub.id,
                "project_name": sub.project.name,
                "project_id": sub.project.id,
                "status": sub.status,
                "content": sub.content,
                "created_at": sub.created_at.strftime("%d.%m.%Y %H:%M") if sub.created_at else None,
                "mark": sub.mark,
                "checked_at": sub.checked_at.strftime("%d.%m.%Y %H:%M") if sub.checked_at else None,
                "criteria": criteria_summary,
                "comments": comments
            })

        return output


async def get_active_projects_for_student(telegram_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        student = await session.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.team))
        )
        user = student.scalar_one_or_none()
        if not user or not user.team_id:
            return []

        has_teams_subquery = (
            select(func.count(ProjectTeam.team_id))
            .where(ProjectTeam.project_id == Project.id)
            .scalar_subquery()
        )
        team_in_project_subquery = (
            select(func.count(ProjectTeam.team_id))
            .where(
                (ProjectTeam.project_id == Project.id) &
                (ProjectTeam.team_id == user.team_id)
            )
            .scalar_subquery()
        )

        result = await session.execute(
            select(Project)
            .join(Submission, Submission.project_id == Project.id)
            .where(
                Submission.team_id == user.team_id,
                Project.mode.in_([1, 2]),
                (
                    (has_teams_subquery == 0) |
                    (team_in_project_subquery > 0)
                )
            )
            .distinct()
            .order_by(Project.deadline.desc())
        )
        projects = result.scalars().all()

        return [
            {"id": p.id, "name": p.name, "deadline": p.deadline, "mode": p.mode}
            for p in projects
        ]