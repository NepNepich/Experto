from pydantic import BaseModel, Field, ConfigDict, model_validator
from datetime import datetime
from enum import Enum

#Enums

class UserRoleSystem(str, Enum):
    ORG = "org"
    EXPERT = "expert"
    STUDENT = "student"

class ProjectStatus(str, Enum):
    SUBMITTED = "submitted"
    ASSIGNED = "assigned"
    CHECKED = "checked"

class ArtifactType(str, Enum):
    LINK = "link"
    FILE = "file"
    TEXT = "text"

class ReviewerRole(str, Enum):
    EXPERT = "expert"
    STUDENT = "student"

class ReviewStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"

#Teams stuff

class TeamCreate(BaseModel):
    name: str = Field(..., max_length=127)

class TeamRead(TeamCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)

#Users stuff

class UserCreate(BaseModel):
    name: str = Field(..., max_length=127)
    email: str = Field(..., max_length=255)
    code: str = Field(..., max_length=255)  # В заглушке хранится как есть, позже захешируем
    telegram_id: int | None = None
    role: UserRoleSystem = UserRoleSystem.STUDENT
    team_id: int | None = None

class UserUpdate(BaseModel):
    name: str | None = Field(None, max_length=127)
    telegram_id: int | None = None
    team_id: int | None = None

class UserRead(UserCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)

#Artifacts stuff

class ArtifactCreate(BaseModel):
    url: str = Field(..., max_length=511)
    type: ArtifactType = ArtifactType.LINK

class ArtifactRead(ArtifactCreate):
    id: int
    project_id: int
    model_config = ConfigDict(from_attributes=True)

#Project stuff

class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=255)
    mode: int = Field(..., ge=1, le=2, description="1=все команды, 2=выбранные команды")
    creator_team_id: int = Field(..., description="Команда, создающая проект")
    participant_team_ids: list[int] | None = Field(None, description="Только для режима 2")

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == 2 and not self.participant_team_ids:
            raise ValueError("Для режима 2 обязателен список participant_team_ids")
        if self.mode == 1:
            self.participant_team_ids = []  # Для режима 1 список не нужен
        return self

class ProjectUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    mode: int | None = Field(None, ge=0, le=255)
    status: ProjectStatus | None = None

class ProjectRead(ProjectCreate):
    id: int
    status: ProjectStatus = ProjectStatus.SUBMITTED
    date_created: datetime
    date_checked: datetime | None = None
    mark: int | None = None
    # Связи будут подтягиваться отдельно или через nested models позже
    model_config = ConfigDict(from_attributes=True)

#Criterias

class CriterionCreate(BaseModel):
    project_id: int
    name: str = Field(..., max_length=127)
    max_score: int = Field(..., ge=1, le=100)
    sort_order: int = 0

class CriterionRead(CriterionCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)

#Score

class ScoreCreate(BaseModel):
    project_id: int
    criterion_id: int
    reviewer_id: int
    score: int = Field(..., ge=0)  # max_score проверим в бизнес-логике

class ScoreRead(ScoreCreate):
    model_config = ConfigDict(from_attributes=True)

#Comments

class CommentCreate(BaseModel):
    project_id: int
    commentator_id: int
    comment: str = Field(..., min_length=1)

class CommentRead(CommentCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

#Reviewrs

class ReviewerAssignCreate(BaseModel):
    project_id: int
    reviewer_id: int
    role: ReviewerRole = ReviewerRole.EXPERT

class ReviewerAssignRead(ReviewerAssignCreate):
    id: int
    status: ReviewStatus = ReviewStatus.PENDING
    assigned_at: datetime
    model_config = ConfigDict(from_attributes=True)