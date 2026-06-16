from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from database import get_db
from api.models import (
    Submission, Project, SubmissionAssignment,
    SubmissionCriterionScore, SubmissionComment, ProjectCriterion
)
from api.schemas import (
    ScoreCreate, ScoreRead,
    CommentCreate, CommentRead, CommentUpdate,
    CriterionCreate, CriterionRead, CriterionUpdate
)

scoring_router = APIRouter(prefix="/scoring", tags=["scoring"])

def is_deadline_passed(deadline: datetime) -> bool:
    """Приводит deadline к naive-формату и сравнивает с текущим UTC"""
    dl = deadline.replace(tzinfo=None) if deadline.tzinfo else deadline
    return dl <= datetime.utcnow()

def _check_deadline(project: Project):
    if is_deadline_passed(project.deadline):
        raise HTTPException(status_code=403, detail="Project deadline has passed. Edits are locked.")

# === ОЦЕНКИ ===

@scoring_router.post("/scores", response_model=ScoreRead, status_code=status.HTTP_201_CREATED)
async def create_score(data: ScoreCreate, db: AsyncSession = Depends(get_db)):
    submission = await db.get(Submission, data.submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
        
    project = await db.get(Project, submission.project_id)
    if project.mode != 1:
        raise HTTPException(400, "Scores are only allowed in Mode 1 (Expert)")
    _check_deadline(project)

    criterion = await db.get(ProjectCriterion, data.criterion_id)
    if not criterion or criterion.project_id != project.id:
        raise HTTPException(400, "Invalid criterion for this project")
    if data.score > criterion.max_score:
        raise HTTPException(400, f"Score exceeds max_score ({criterion.max_score})")

    assign = (await db.execute(select(SubmissionAssignment).where(
        SubmissionAssignment.submission_id == data.submission_id,
        SubmissionAssignment.reviewer_id == data.expert_id,
        SubmissionAssignment.status == "pending"
    ))).scalar_one_or_none()
    if not assign:
        raise HTTPException(400, "No pending assignment for this expert")

    # Защита от дублей
    exists = (await db.execute(select(SubmissionCriterionScore).where(
        SubmissionCriterionScore.submission_id == data.submission_id,
        SubmissionCriterionScore.criterion_id == data.criterion_id,
        SubmissionCriterionScore.expert_id == data.expert_id
    ))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "Score for this criterion already exists. Use PATCH to update.")

    new_score = SubmissionCriterionScore(**data.model_dump())
    db.add(new_score)
    await db.commit()
    await db.refresh(new_score)
    return new_score

@scoring_router.patch("/scores/{submission_id}/{criterion_id}", response_model=ScoreRead)
async def update_score(
    submission_id: int,
    criterion_id: int,
    data: ScoreCreate,
    db: AsyncSession = Depends(get_db)
):
    submission = await db.get(Submission, submission_id)
    if not submission: raise HTTPException(404, "Submission not found")

    project = await db.get(Project, submission.project_id)
    if project.mode != 1: raise HTTPException(400, "Scores only allowed in Mode 1")
    _check_deadline(project)

    score_obj = (await db.execute(select(SubmissionCriterionScore).where(
        SubmissionCriterionScore.submission_id == submission_id,
        SubmissionCriterionScore.criterion_id == criterion_id,
        SubmissionCriterionScore.expert_id == data.expert_id
    ))).scalar_one_or_none()
    if not score_obj:
        raise HTTPException(404, "Score not found or not created by you")

    criterion = await db.get(ProjectCriterion, criterion_id)
    if not criterion or criterion.project_id != project.id:
        raise HTTPException(400, "Invalid criterion")
    if data.score > criterion.max_score:
        raise HTTPException(400, f"Score exceeds max_score ({criterion.max_score})")

    score_obj.score = data.score
    
    submission.mark = (await db.execute(select(func.sum(SubmissionCriterionScore.score)).where(
        SubmissionCriterionScore.submission_id == submission_id
    ))).scalar() or 0

    await db.commit()
    await db.refresh(score_obj)
    return score_obj


@scoring_router.get("/scores/{submission_id}", response_model=list[ScoreRead])
async def get_submission_scores(submission_id: int, db: AsyncSession = Depends(get_db)):
    if not await db.get(Submission, submission_id):
        raise HTTPException(404, "Submission not found")
    res = await db.execute(
        select(SubmissionCriterionScore).where(SubmissionCriterionScore.submission_id == submission_id)
    )
    return res.scalars().all()

# === КОММЕНТАРИИ ===

@scoring_router.post("/comments", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
async def create_comment(data: CommentCreate, db: AsyncSession = Depends(get_db)):
    submission = await db.get(Submission, data.submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")

    project = await db.get(Project, submission.project_id)
    _check_deadline(project)

    assign = (await db.execute(select(SubmissionAssignment).where(
        SubmissionAssignment.submission_id == data.submission_id,
        SubmissionAssignment.reviewer_id == data.author_id,
        SubmissionAssignment.status == "pending"
    ))).scalar_one_or_none()
    if not assign:
        raise HTTPException(400, "No pending assignment for this reviewer")

    comment = SubmissionComment(**data.model_dump())
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment

@scoring_router.patch("/comments/{comment_id}", response_model=CommentRead)
async def update_comment(comment_id: int, update: CommentUpdate, db: AsyncSession = Depends(get_db)):
    comment = await db.get(SubmissionComment, comment_id)
    if not comment: raise HTTPException(404, "Comment not found")

    submission = await db.get(Submission, comment.submission_id)
    project = await db.get(Project, submission.project_id)
    _check_deadline(project)

    comment.comment = update.comment
    await db.commit()
    await db.refresh(comment)
    return comment

@scoring_router.get("/comments/{submission_id}", response_model=list[CommentRead])
async def get_submission_comments(
    submission_id: int,
    viewer_id: int,
    viewer_team_id: int | None = None,
    db: AsyncSession = Depends(get_db)
):
    submission = await db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")

    stmt = select(SubmissionComment).where(SubmissionComment.submission_id == submission_id)
    if not (viewer_team_id and viewer_team_id == submission.team_id):
        stmt = stmt.where(SubmissionComment.author_id == viewer_id)
    
    res = await db.execute(stmt.order_by(SubmissionComment.created_at.asc()))
    return res.scalars().all()

# === CRITERIA ===
@scoring_router.delete("/criteria/{criterion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_criterion(criterion_id: int, db: AsyncSession = Depends(get_db)):
    criterion = await db.get(ProjectCriterion, criterion_id)
    if not criterion:
        raise HTTPException(404, "Criterion not found")
    
    scores = await db.execute(select(SubmissionCriterionScore).where(
        SubmissionCriterionScore.criterion_id == criterion_id
    ))
    if scores.scalars().first():
        raise HTTPException(400, "Cannot delete: scores have already been submitted for this criterion")
        
    await db.delete(criterion)
    await db.commit()
    return None

@scoring_router.post("/criteria", response_model=CriterionRead, status_code=status.HTTP_201_CREATED)
async def create_criterion(data: CriterionCreate, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, data.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    
    if project.deadline <= datetime.utcnow():
        raise HTTPException(403, "Project deadline passed. Criteria are locked.")

    new_criterion = ProjectCriterion(**data.model_dump())
    db.add(new_criterion)
    await db.commit()
    await db.refresh(new_criterion)
    return new_criterion

@scoring_router.get("/criteria/project/{project_id}", response_model=list[CriterionRead])
async def get_project_criteria(project_id: int, db: AsyncSession = Depends(get_db)):
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    
    res = await db.execute(
        select(ProjectCriterion)
        .where(ProjectCriterion.project_id == project_id)
        .order_by(ProjectCriterion.sort_order.asc(), ProjectCriterion.id.asc())
    )
    return res.scalars().all()

@scoring_router.patch("/criteria/{criterion_id}", response_model=CriterionRead)
async def update_criterion(criterion_id: int, data: CriterionUpdate, db: AsyncSession = Depends(get_db)):
    criterion = await db.get(ProjectCriterion, criterion_id)
    if not criterion:
        raise HTTPException(404, "Criterion not found")

    project = await db.get(Project, criterion.project_id)
    if project.deadline <= datetime.utcnow():
        raise HTTPException(403, "Project deadline passed. Criteria are locked.")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return criterion

    if "max_score" in update_data:
        scores = await db.execute(select(func.count(SubmissionCriterionScore.id)).where(
            SubmissionCriterionScore.criterion_id == criterion_id
        ))
        if scores.scalar() > 0:
            raise HTTPException(400, "Cannot change max_score: scores have already been submitted")

    for field, value in update_data.items():
        setattr(criterion, field, value)

    await db.commit()
    await db.refresh(criterion)
    return criterion