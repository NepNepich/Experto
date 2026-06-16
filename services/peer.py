import random
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from database import AsyncSessionLocal
from api.models import (
    User, Project, Submission, SubmissionAssignment,
    ProjectCriterion, SubmissionCriterionScore, SubmissionArtifact, Team
)
from api.schemas import AcademicRole, SubmissionStatus, AssignmentStatus


# === ЗАГРУЗКА РАБОТЫ ===
async def submit_peer_work(telegram_id: int, project_id: int, content: str, artifacts: list[dict]) -> int:
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user.scalar_one_or_none()
        if not user or not user.team_id:
            raise ValueError("Вы не привязаны к команде.")

        project = await session.get(Project, project_id)
        if not project or project.mode != 2:
            raise ValueError("Проект не относится к Режиму 2 (P2P).")

        dup = await session.execute(select(Submission.id).where(
            Submission.project_id == project_id,
            Submission.team_id == user.team_id
        ))
        if dup.scalar_one_or_none():
            raise ValueError("Работа уже отправлена в этот проект.")

        sub = Submission(
            project_id=project_id, team_id=user.team_id, content=content,
            status="unchecked", created_at=datetime.now(timezone.utc)
        )
        session.add(sub)
        await session.flush()

        for art in artifacts:
            session.add(SubmissionArtifact(
                submission_id=sub.id, url=art["url"], type=art.get("type", "link")
            ))

        await session.commit()
        return sub.id


# === ОЧЕРЕДЬ РАБОТ НА ПРОВЕРКУ ===
async def get_peer_review_queue(telegram_id: int, project_id: int, limit: int = 3) -> list[dict]:
    """Возвращает работы, которые этот студент ещё не проверял и которые не его команды"""
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user.scalar_one_or_none()
        
        # 🔥 Если студент не привязан к команде, он не может проверять других
        if not user or not user.team_id: 
            return []

        result = await session.execute(
            select(Submission)
            .where(
                Submission.project_id == project_id,
                Submission.status == "unchecked", # 🔥 Фильтруем только непроверенные работы
                Submission.team_id != user.team_id,
                Submission.id.notin_(
                    select(SubmissionAssignment.submission_id)
                    .where(SubmissionAssignment.reviewer_id == user.id)
                )
            )
            .options(selectinload(Submission.artifacts), selectinload(Submission.team))
            .limit(limit)
        )
        subs = result.scalars().all()
        return [
            {"id": s.id, "team_name": s.team.name, "content": s.content, "artifacts": s.artifacts}
            for s in subs
        ]


# === ВЗЯТЬ ЗАДАНИЕ НА ПРОВЕРКУ ===
async def take_peer_task(telegram_id: int, submission_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user.scalar_one_or_none()
        if not user: raise ValueError("Пользователь не найден")

        result = await session.execute(
            select(Submission)
            .where(Submission.id == submission_id)
            .options(selectinload(Submission.artifacts))
        )
        sub = result.scalar_one_or_none()
        
        if not sub or sub.team_id == user.team_id:
            raise ValueError("Нельзя проверить работу своей команды или работа не найдена.")

        assign = SubmissionAssignment(
            submission_id=submission_id, reviewer_id=user.id,
            status="pending", assigned_at=datetime.now(timezone.utc)
        )
        session.add(assign)
        await session.commit()
        await session.refresh(assign)
        return {"assignment_id": assign.id, "submission": sub}


# === МОИ ЗАДАНИЯ НА ПРОВЕРКУ ===
async def get_my_peer_tasks(telegram_id: int, project_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user.scalar_one_or_none()
        if not user: return []

        result = await session.execute(
            select(SubmissionAssignment)
            .where(
                SubmissionAssignment.reviewer_id == user.id,
                SubmissionAssignment.status == "pending"
            )
            .options(
                selectinload(SubmissionAssignment.submission).selectinload(Submission.team),
                selectinload(SubmissionAssignment.submission).selectinload(Submission.project)
            )
        )
        tasks = []
        for t in result.scalars().all():
            if t.submission.project_id == project_id:
                tasks.append({"assignment_id": t.id, "submission": t.submission})
        return tasks


# === ОЦЕНКА И ФИНАЛИЗАЦИЯ (аналогично эксперту, но для студентов) ===
async def submit_peer_score(assignment_id: int, criterion_id: int, score: int) -> dict:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            assign = await session.get(SubmissionAssignment, assignment_id)
            if not assign or assign.status != "pending":
                raise ValueError("Задание не найдено или уже завершено.")

            crit = await session.get(ProjectCriterion, criterion_id)
            if not crit or not (0 <= score <= crit.max_score):
                raise ValueError("Некорректная оценка.")

            existing = await session.execute(select(SubmissionCriterionScore).where(
                SubmissionCriterionScore.submission_id == assign.submission_id,
                SubmissionCriterionScore.criterion_id == criterion_id,
                SubmissionCriterionScore.expert_id == assign.reviewer_id
            ))
            score_obj = existing.scalar_one_or_none()

            if score_obj:
                score_obj.score = score
            else:
                session.add(SubmissionCriterionScore(
                    submission_id=assign.submission_id, criterion_id=criterion_id,
                    expert_id=assign.reviewer_id, score=score
                ))
            await session.commit()
            return {"submission_id": assign.submission_id, "criterion_id": criterion_id, "score": score,
                    "max_score": crit.max_score}


async def finalize_peer_review(assignment_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SubmissionAssignment)
            .where(SubmissionAssignment.id == assignment_id)
            .options(selectinload(SubmissionAssignment.submission))
        )
        assign = result.scalar_one_or_none()

        if not assign or assign.status == "done":
            raise ValueError("Задание не найдено или уже завершено.")

        submission_id = assign.submission_id
        project_id = assign.submission.project_id
        reviewer_id = assign.reviewer_id

        # Считаем критерии
        total_criteria = await session.scalar(
            select(func.count()).where(ProjectCriterion.project_id == project_id)
        )
        scored = await session.scalar(
            select(func.count())
            .where(
                SubmissionCriterionScore.submission_id == submission_id,
                SubmissionCriterionScore.expert_id == reviewer_id
            )
        )

        if scored < total_criteria:
            raise ValueError(f"Оцените все критерии ({scored}/{total_criteria})")

        # Обновляем задание
        assign.status = "done"
        assign.completed_at = datetime.now(timezone.utc)

        # Считаем среднюю оценку по ВСЕМ рецензиям на эту работу
        avg_result = await session.execute(
            select(func.avg(SubmissionCriterionScore.score))
            .where(SubmissionCriterionScore.submission_id == submission_id)
        )
        avg_score = avg_result.scalar_one_or_none()

        if avg_score is not None:
            await session.execute(
                update(Submission)
                .where(Submission.id == submission_id)
                .values(
                    mark=round(avg_score),
                    status="checked",
                    checked_at=datetime.now(timezone.utc)
                )
            )

        await session.commit()

        return {
            "submission_id": submission_id,
            "final_mark": round(avg_score) if avg_score else None
        }