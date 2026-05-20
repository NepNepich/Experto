from pydantic import BaseModel, Field, ConfigDict, model_validator
from datetime import datetime
from enum import Enum

# === ENUMS ===

class AcademicRole(str, Enum):
    ORG = "org"
    EXPERT = "expert"
    STUDENT = "student"

class TeamRole(str, Enum):
    TEAM_LEAD = "team_lead"
    DEVELOPER = "developer"
    ANALYTIC = "analytic"
    GAME_DESIGNER = "game_designer"
    DESIGNER = "designer"

class ProjectStatus(str, Enum):
    SUBMITTED = "submitted"
    ASSIGNED = "assigned"
    CHECKED = "checked"

class SubmissionStatus(str, Enum):
    UNCHECKED = "unchecked"
    CHECKING = "checking"
    CHECKED = "checked"

class ArtifactType(str, Enum):
    LINK = "link"
    FILE = "file"
    TEXT = "text"

class AssignmentStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"

# === TEAMS ===

class TeamCreate(BaseModel):
    name: str = Field(..., max_length=127)

class TeamUpdate(BaseModel):
    name: str | None = Field(None, max_length=127)

class TeamRead(TeamCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)

# === USERS === 

class UserCreate(BaseModel):
    name: str = Field(..., max_length=127)
    email: str = Field(..., max_length=255)
    code: str = Field(..., max_length=255)
    telegram_id: int | None = None
    academic_role: AcademicRole = AcademicRole.STUDENT
    team_role: TeamRole | None = None
    team_id: int | None = None

class UserUpdate(BaseModel):
    name: str | None = Field(None, max_length=127)
    telegram_id: int | None = None
    academic_role: AcademicRole | None = None
    team_role: TeamRole | None = None
    team_id: int | None = None

class UserRead(UserCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)

# === PROJECTS ===
class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=255)
    mode: int = Field(..., ge=1, le=2)
    deadline: datetime  # 👈 Обязательно при создании
    participant_team_ids: list[int] | None = Field(None, description="Required for mode 2")

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == 2 and (not self.participant_team_ids):
            raise ValueError("Mode 2 requires participant_team_ids")
        if self.mode == 1:
            self.participant_team_ids = []
        if self.deadline <= datetime.now():
            raise ValueError("Deadline must be in the future")
        return self

class ProjectUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    deadline: datetime | None = None
    # Статус меняет только система или организатор вручную при необходимости
    status: ProjectStatus | None = None

class ProjectRead(BaseModel):
    id: int
    name: str
    mode: int
    status: ProjectStatus
    deadline: datetime
    date_created: datetime
    model_config = ConfigDict(from_attributes=True)

# === CRITERIA ===

class CriterionCreate(BaseModel):
    project_id: int
    name: str = Field(..., max_length=127)
    max_score: int = Field(..., ge=1, le=100)
    sort_order: int = 0

class CriterionRead(CriterionCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)
    
# === SUBMISSIONS ===

class SubmissionCreate(BaseModel):
    project_id: int
    team_id: int
    content: str

class SubmissionUpdate(BaseModel):
    content: str | None = None
    status: SubmissionStatus | None = None

class SubmissionRead(BaseModel):
    id: int
    project_id: int
    team_id: int
    content: str
    mark: int | None = None
    status: SubmissionStatus
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
    
# === ARTIFACTS ===

class ArtifactCreate(BaseModel):
    submission_id: int
    url: str = Field(..., max_length=511)
    type: ArtifactType = ArtifactType.LINK

class ArtifactRead(ArtifactCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)
    
# === COMMENTS ===

class CommentCreate(BaseModel):
    submission_id: int
    author_id: int
    comment: str = Field(..., min_length=1)

class CommentRead(CommentCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
    
class CommentUpdate(BaseModel):
    comment: str = Field(..., min_length=1)

# === SCORES ===

class ScoreCreate(BaseModel):
    submission_id: int
    criterion_id: int
    expert_id: int
    score: int = Field(..., ge=0)

class ScoreRead(ScoreCreate):
    model_config = ConfigDict(from_attributes=True)

class ScoreSubmitResponse(BaseModel):
    submission_id: int
    criterion_id: int
    reviewer_id: int
    score: int
    next_submission_id: int | None = None  # ID следующей работы для авто-выдачи
    model_config = ConfigDict(from_attributes=True)

# === ASSIGNMENTS ===

class AssignmentCreate(BaseModel):
    submission_id: int
    reviewer_id: int

class AssignmentRead(BaseModel):
    id: int
    submission_id: int
    reviewer_id: int
    status: AssignmentStatus
    assigned_at: datetime
    completed_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)

# === ACTUALLY USEFUL ENDPOINT STUFF IDK ===

class WebLoginRequest(BaseModel):
    email: str = Field(..., max_length=255)

class BotLoginRequest(BaseModel):
    email: str = Field(..., max_length=255)
    telegram_id: int  # Бот подставит его автоматически

class LoginResponse(BaseModel):
    user_id: int
    academic_role: str
    message: str

class SubmissionReviewView(BaseModel):
    submission: SubmissionRead
    artifacts: list[ArtifactRead]

class ProjectMiniRead(BaseModel):
    id: int
    name: str
    date_created: datetime
    deadline: datetime
    status: ProjectStatus
    model_config = ConfigDict(from_attributes=True)

class ExpertProgress(BaseModel):
    expert_id: int
    expert_name: str
    checked_count: int

class ProjectDashboard(BaseModel):
    project_id: int
    project_name: str
    total_submissions: int
    checked_submissions: int
    pending_submissions: int
    last_check_date: datetime | None
    experts: list[ExpertProgress]
    model_config = ConfigDict(from_attributes=True)

class ProjectExportItem(BaseModel):
    team_id: int
    team_name: str
    total_score: int
    comment: str | None
    expert_name: str | None
    check_date: datetime | None
    
class StudentSubmissionMini(BaseModel):
    id: int
    project_name: str
    status: SubmissionStatus
    created_at: datetime
    comment_count: int = 0
    model_config = ConfigDict(from_attributes=True)

class CriterionScoreItem(BaseModel):
    criterion_name: str
    max_score: int
    score: int

class SubmissionDetailMode1(BaseModel):
    project_name: str
    content: str
    artifacts: list[ArtifactRead]
    scores: list[CriterionScoreItem]
    total_mark: int | None
    expert_comment: str | None
    model_config = ConfigDict(from_attributes=True)

class PeerCommentView(BaseModel):
    author_name: str
    comment: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class SubmissionDetailMode2(BaseModel):
    project_name: str
    content: str
    comments: list[PeerCommentView]
    model_config = ConfigDict(from_attributes=True)