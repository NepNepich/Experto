from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from api.models import Submission, SubmissionArtifact
from api.schemas import ArtifactCreate, ArtifactRead

artifacts_router = APIRouter(prefix="/artifacts", tags=["artifacts"])

# ✅ CREATE
@artifacts_router.post("/", response_model=ArtifactRead, status_code=201)
async def create_artifact(data: ArtifactCreate, db: AsyncSession = Depends(get_db)):
    if not await db.get(Submission, data.submission_id):
        raise HTTPException(404, "Submission not found")
    
    artifact = SubmissionArtifact(**data.model_dump())
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    return artifact

# ✅ READ (список по работе)
@artifacts_router.get("/submission/{submission_id}", response_model=list[ArtifactRead])
async def get_submission_artifacts(submission_id: int, db: AsyncSession = Depends(get_db)):
    if not await db.get(Submission, submission_id):
        raise HTTPException(404, "Submission not found")
    
    res = await db.execute(
        select(SubmissionArtifact)
        .where(SubmissionArtifact.submission_id == submission_id)
        .order_by(SubmissionArtifact.id.desc())
    )
    return res.scalars().all()

# ✅ DELETE
@artifacts_router.delete("/{artifact_id}", status_code=204)
async def delete_artifact(artifact_id: int, db: AsyncSession = Depends(get_db)):
    artifact = await db.get(SubmissionArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    
    await db.delete(artifact)
    await db.commit()
    return None