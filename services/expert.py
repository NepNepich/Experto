from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload, joinedload
from datetime import datetime, timezone
from database import AsyncSessionLocal
from api.models import (
    User, Project, Submission, SubmissionAssignment,
    ProjectCriterion, SubmissionCriterionScore, SubmissionComment, SubmissionArtifact
)
from api.schemas import AcademicRole, SubmissionStatus, AssignmentStatus

# === Авторизация эксперта ===
async def get_expert_by_telegram(telegram_id: int) -> User | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.team))
        )
        user = result.scalar_one_or_none()
        return user if user and user.academic_role == AcademicRole.EXPERT else None

# === Активные проекты для эксперта (только Режим 1) ===
async def get_expert_active_projects(telegram_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        expert = await get_expert_by_telegram(telegram_id)
        if not expert:
            return []
        result = await session.execute(
            select(Project)
            .where(
                Project.mode == 1,
                Project.deadline > datetime.now(timezone.utc),
                Project.status.in_(['submitted', 'assigned'])
            )
            .order_by(Project.deadline)
        )
        projects = result.scalars().all()
        return [{"id": p.id, "name": p.name, "deadline": p.deadline, "mode": p.mode} for p in projects]

# === Взять следующую работу (или продолжить текущую) ===
async def get_next_task_for_expert(telegram_id: int, project_id: int) -> dict | None:
    async with AsyncSessionLocal() as session:
        expert = await get_expert_by_telegram(telegram_id)
        if not expert:
            return None

        # 1. Сначала ищем незавершённое задание эксперта
        pending = await session.execute(
            select(SubmissionAssignment)
            .where(
                SubmissionAssignment.reviewer_id == expert.id,
                SubmissionAssignment.status == AssignmentStatus.PENDING
            )
            .options(
                selectinload(SubmissionAssignment.submission).selectinload(Submission.artifacts),
                selectinload(SubmissionAssignment.submission).selectinload(Submission.project)
            )
            .limit(1)
        )
        assign = pending.scalar_one_or_none()
        if assign:
            return {"assignment_id": assign.id, "submission": assign.submission, "is_continuation": True}

        # 2. Ищем новую работу в очереди
        available = await session.execute(
            select(Submission)
            .where(
                Submission.project_id == project_id,
                Submission.status == SubmissionStatus.UNCHECKED,
                Submission.id.notin_(
                    select(SubmissionAssignment.submission_id)
                    .where(SubmissionAssignment.reviewer_id == expert.id)
                )
            )
            .options(
                selectinload(Submission.artifacts),
                selectinload(Submission.project)
            )
            .limit(1)
        )
        submission = available.scalar_one_or_none()
        if not submission:
            return None

        # 3. Создаём новое задание
        new_assign = SubmissionAssignment(
            submission_id=submission.id,
            reviewer_id=expert.id,
            status=AssignmentStatus.PENDING,
            assigned_at=datetime.now(timezone.utc)
        )
        session.add(new_assign)
        await session.commit()
        await session.refresh(new_assign)

        return {"assignment_id": new_assign.id, "submission": submission, "is_continuation": False}

# === Получить критерии проекта ===
async def get_project_criteria(project_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ProjectCriterion)
            .where(ProjectCriterion.project_id == project_id)
            .order_by(ProjectCriterion.sort_order)
        )
        criteria = result.scalars().all()
        return [{"id": c.id, "name": c.name, "max_score": c.max_score, "sort_order": c.sort_order} for c in criteria]

# === Проверить, есть ли уже оценка по критерию ===
async def get_existing_score(submission_id: int, criterion_id: int, expert_id: int) -> int | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SubmissionCriterionScore.score)
            .where(
                SubmissionCriterionScore.submission_id == submission_id,
                SubmissionCriterionScore.criterion_id == criterion_id,
                SubmissionCriterionScore.expert_id == expert_id
            )
        )
        score_obj = result.scalar_one_or_none()
        return score_obj if score_obj is not None else None

# === Отправить оценку по критерию (атомарно!) ===
async def submit_criterion_score(assignment_id: int, criterion_id: int, score: int) -> dict:
    async with AsyncSessionLocal() as session:
        assign = await session.get(SubmissionAssignment, assignment_id)
        if not assign or assign.status != AssignmentStatus.PENDING:
            raise ValueError("Задание не найдено или уже завершено")

        criterion = await session.get(ProjectCriterion, criterion_id)
        if not criterion or not (0 <= score <= criterion.max_score):
            raise ValueError("Некорректная оценка")

        existing = await session.execute(
            select(SubmissionCriterionScore)
            .where(
                SubmissionCriterionScore.submission_id == assign.submission_id,
                SubmissionCriterionScore.criterion_id == criterion_id,
                SubmissionCriterionScore.expert_id == assign.reviewer_id
            )
        )
        score_obj = existing.scalar_one_or_none()

        if score_obj:
            score_obj.score = score
        else:
            session.add(SubmissionCriterionScore(
                submission_id=assign.submission_id,
                criterion_id=criterion_id,
                expert_id=assign.reviewer_id, 
                score=score
            ))

        await session.commit()
        return {"submission_id": assign.submission_id, "criterion_id": criterion_id, "score": score, "max_score": criterion.max_score}

# 🔥 ИСПРАВЛЕНИЕ: Явный commit для гарантированного сохранения комментариев (в т.ч. от Whisper)
async def submit_expert_comment(assignment_id: int, comment_text: str, edit_comment_id: int | None = None) -> dict:
    async with AsyncSessionLocal() as session:
        assign = await session.get(SubmissionAssignment, assignment_id)
        if not assign or assign.status != AssignmentStatus.PENDING:
            raise ValueError("Задание не найдено или уже завершено")
        
        if edit_comment_id:
            result = await session.execute(
                select(SubmissionComment).where(
                    SubmissionComment.id == edit_comment_id,
                    SubmissionComment.author_id == assign.reviewer_id,
                    SubmissionComment.submission_id == assign.submission_id
                )
            )
            cmt = result.scalar_one_or_none()
            if not cmt:
                raise ValueError("Комментарий не найден или нет прав на его изменение")
            cmt.comment = comment_text
            await session.commit()
            return {"id": cmt.id, "action": "updated"}
        else:
            new_comment = SubmissionComment(
                submission_id=assign.submission_id,
                author_id=assign.reviewer_id,
                comment=comment_text,
                created_at=datetime.now(timezone.utc)
            )
            session.add(new_comment)
            await session.commit() # 🔥 Явный коммит вместо flush
            await session.refresh(new_comment)
            return {"id": new_comment.id, "action": "created"}


# === Вспомогательная функция (без проверки telegram) ===
async def get_next_task_for_expert_by_id(user_id: int, project_id: int) -> dict | None:
    async with AsyncSessionLocal() as session:
        available = await session.execute(
            select(Submission)
            .where(
                Submission.project_id == project_id,
                Submission.status == SubmissionStatus.UNCHECKED,
                Submission.id.notin_(
                    select(SubmissionAssignment.submission_id)
                    .where(SubmissionAssignment.reviewer_id == user_id)
                )
            )
            .options(selectinload(Submission.artifacts))
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
    
# === Финализация проверки ===
async def finalize_expert_review(assignment_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        assign = await session.execute(
            select(SubmissionAssignment)
            .where(SubmissionAssignment.id == assignment_id)
            .options(
                selectinload(SubmissionAssignment.submission).selectinload(Submission.project)
            )
        )
        assign = assign.scalar_one_or_none()
        if not assign or assign.status == AssignmentStatus.DONE:
            raise ValueError("Задание не найдено или уже завершено")

        submission_id = assign.submission.id
        project_id = assign.submission.project_id
        reviewer_id = assign.reviewer_id

        total_criteria = await session.scalar(select(func.count()).where(ProjectCriterion.project_id == project_id))
        scored = await session.scalar(
            select(func.count())
            .where(
                SubmissionCriterionScore.submission_id == submission_id,
                SubmissionCriterionScore.expert_id == reviewer_id
            )
        )
 
        if scored < total_criteria:
            raise ValueError(f"Оцените все критерии ({scored}/{total_criteria})")

        assign.status = AssignmentStatus.DONE
        assign.completed_at = datetime.now(timezone.utc)

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
                    status=SubmissionStatus.CHECKED,
                    checked_at=datetime.now(timezone.utc)
                )
            )

        await session.commit()
        await session.refresh(assign)

        # Поиск следующего задания
        next_task = await get_next_task_for_expert_by_id(reviewer_id, project_id)

        return {
            "submission_id": submission_id,
            "final_mark": round(avg_score) if avg_score else None,
            "next_submission_id": next_task["submission"].id if next_task else None
        }

# === Статистика эксперта ===
async def get_expert_stats(telegram_id: int, project_id: int | None = None) -> dict:
    async with AsyncSessionLocal() as session:
        expert = await get_expert_by_telegram(telegram_id)
        if not expert:
            return {}
        
        from sqlalchemy import case
        query = select(
            func.count(SubmissionAssignment.id).label("total"),
            func.sum(case((SubmissionAssignment.status == "done", 1), else_=0)).label("completed")
        ).where(SubmissionAssignment.reviewer_id == expert.id)

        if project_id:
            query = query.join(Submission).where(Submission.project_id == project_id)

        result = await session.execute(query)
        stats = result.one()

        return {
            "total_assigned": stats.total or 0,
            "completed": stats.completed or 0,
            "pending": (stats.total or 0) - (stats.completed or 0)
        }