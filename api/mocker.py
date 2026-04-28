import asyncio
from typing import List, Optional, Dict
from datetime import datetime, timezone
from api.schemas import *

class MockDatabase:
    def __init__(self):
        # псевдотаблицы
        self.users: Dict[int, dict] = {}
        self.teams: Dict[int, dict] = {}
        self.projects: Dict[int, dict] = {}
        self.artifacts: List[dict] = []
        self.reviewers: List[dict] = []
        self.criteria: List[dict] = []
        self.scores: List[dict] = []
        self.comments: List[dict] = []
        self.project_roles: List[dict] = []
        self.participant_teams: List[dict] = []

        # Счётчики объектов
        self._counters = {
            "user": 0, "team": 0, "project": 0, "artifact": 0,
            "reviewer": 0, "criterion": 0, "score": 0, "comment": 0
        }
        
        self._lock = asyncio.Lock()  # Защита от гонок в асинхронном окружении

    async def _next_id(self, table: str) -> int:
        async with self._lock:
            self._counters[table] += 1
            
            return self._counters[table]

    def _assert_exists(self, table: Dict, obj_id: int, error_msg: str):
        if obj_id not in table:
            raise ValueError(error_msg)

    # Users
    async def create_user(self, data: UserCreate) -> UserRead:
        if any(u["email"] == data.email for u in self.users.values()):
            raise ValueError("Email already registered")
        
        uid = await self._next_id("user")
        record = {
            "id": uid,
            **data.model_dump(),
            "created_at": datetime.now(timezone.utc)
        }
        self.users[uid] = record
        
        return UserRead(**record)

    async def get_user_by_email(self, email: str) -> Optional[UserRead]:
        for u in self.users.values():
            if u["email"] == email:
                return UserRead(**u)
            
        return None

    async def get_user(self, user_id: int) -> Optional[UserRead]:
        if user_id not in self.users:
            return None
        
        return UserRead(**self.users[user_id])

    # Projects
    async def create_project(self, data: ProjectCreate) -> ProjectRead:
        if data.creator_team_id not in self.teams:
            raise ValueError("Creator team not found")

        pid = await self._next_id("project")
        record = {
            "id": pid,
            "name": data.name,
            "mode": data.mode,
            "creator_team_id": data.creator_team_id,  # ← Сохраняем владельца
            "status": ProjectStatus.SUBMITTED.value,
            "date_created": datetime.now(timezone.utc),
            "date_checked": None,
            "mark": None
        }
        self.projects[pid] = record
        if data.mode == 2 and data.participant_team_ids:
            for tid in data.participant_team_ids:
                if tid not in self.teams:
                    raise ValueError(f"Participant team {tid} not found")
                
                self.participant_teams.append({"project_id": pid, "team_id": tid})

        return ProjectRead(**record)

    async def get_project(self, project_id: int) -> ProjectRead:
        self._assert_exists(self.projects, project_id, "Project not found")
        
        return ProjectRead(**self.projects[project_id])

    async def get_projects_by_team(self, team_id: int) -> List[ProjectRead]:
        return [ProjectRead(**p) for p in self.projects.values() if p["team_id"] == team_id]
    
    async def get_projects_for_team(self, team_id: int) -> list[ProjectRead]:
        global_projects = [p for p in self.projects.values() if p["mode"] == 1]
        assigned_project_ids = {
            pt["project_id"] for pt in self.participant_teams 
            if pt["team_id"] == team_id
        }
        assigned_projects = [self.projects[pid] for pid in assigned_project_ids if pid in self.projects]
        merged = {p["id"]: p for p in global_projects + assigned_projects}
        
        return [ProjectRead(**p) for p in merged.values()]

    # Artifacts
    async def add_artifact(self, project_id: int, data: ArtifactCreate) -> ArtifactRead:
        self._assert_exists(self.projects, project_id, "Project not found")
        
        aid = await self._next_id("artifact")
        record = {"id": aid, "project_id": project_id, **data.model_dump()}
        self.artifacts.append(record)
        
        return ArtifactRead(**record)

    async def get_artifacts(self, project_id: int) -> List[ArtifactRead]:
        return [ArtifactRead(**a) for a in self.artifacts if a["project_id"] == project_id]

    # Reviewers and reviews
    async def assign_reviewer(self, project_id: int, data: ReviewerAssignCreate) -> ReviewerAssignRead:
        self._assert_exists(self.projects, project_id, "Project not found")
        self._assert_exists(self.users, data.reviewer_id, "Reviewer not found")

        if any(r["project_id"] == project_id and r["reviewer_id"] == data.reviewer_id for r in self.reviewers):
            raise ValueError("Reviewer already assigned to this project")

        if any(r["project_id"] == project_id and r["status"] == ReviewStatus.ACTIVE.value for r in self.reviewers):
            raise ValueError("Project is currently being reviewed by another person")

        rid = await self._next_id("reviewer")
        record = {
            "id": rid,
            "project_id": project_id,
            "status": ReviewStatus.PENDING.value,
            "assigned_at": datetime.now(timezone.utc),
            **data.model_dump()
        }
        self.reviewers.append(record)
        self.projects[project_id]["status"] = ProjectStatus.ASSIGNED.value
        
        return ReviewerAssignRead(**record)

    async def get_pending_reviews(self, reviewer_id: int) -> List[ProjectRead]:
        assigned_ids = [
            r["project_id"] for r in self.reviewers
            if r["reviewer_id"] == reviewer_id and r["status"] == ReviewStatus.PENDING.value
        ]
        return [ProjectRead(**self.projects[pid]) for pid in assigned_ids]

    async def start_review(self, reviewer_id: int, project_id: int):
        for r in self.reviewers:
            if r["reviewer_id"] == reviewer_id and r["project_id"] == project_id and r["status"] == ReviewStatus.PENDING.value:
                r["status"] = ReviewStatus.ACTIVE.value
                self.projects[project_id]["status"] = ProjectStatus.ASSIGNED.value # или REVIEWING
                
                return
            
        raise ValueError("Review assignment not found or already done")

    # Scores
    async def add_score(self, data: ScoreCreate) -> ScoreRead:
        sid = await self._next_id("score")
        record = {"id": sid, **data.model_dump()}
        self.scores.append(record)
        total = sum(s["score"] for s in self.scores if s["project_id"] == data.project_id)
        self.projects[data.project_id]["mark"] = total
        self.projects[data.project_id]["status"] = ProjectStatus.CHECKED.value
        self.projects[data.project_id]["date_checked"] = datetime.now(timezone.utc)
        
        return ScoreRead(**data.model_dump())
    
    # Comments
    async def add_comment(self, data: CommentCreate) -> CommentRead:
        cid = await self._next_id("comment")
        record = {
            "id": cid,
            "created_at": datetime.now(timezone.utc),
            **data.model_dump()
        }
        self.comments.append(record)
        
        return CommentRead(**record)

    async def get_comments(self, project_id: int) -> List[CommentRead]:
        return [CommentRead(**c) for c in self.comments if c["project_id"] == project_id]

    # Test data and examples
    async def test_data(self):
        """Заполняет БД тестовыми данными при старте"""
        await self.create_user(UserCreate(name="Организатор", email="org@test.ru", code="ORG123", role=UserRoleSystem.ORG, telegram_id=111))
        await self.create_user(UserCreate(name="Эксперт", email="expert@test.ru", code="EXP456", role=UserRoleSystem.EXPERT, telegram_id=222))
        await self.create_user(UserCreate(name="Студент", email="student@test.ru", code="STU789", role=UserRoleSystem.STUDENT, telegram_id=333))