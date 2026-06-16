from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.mysql import TINYINT, BIGINT
from datetime import datetime, timezone

Base = declarative_base()

# === USERS AND TEAMS ===

class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(127), nullable=False)

    users = relationship("User", back_populates="team")
    submissions = relationship("Submission", back_populates="team")
    participant_in_projects = relationship("ProjectTeam", back_populates="team")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(127), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    code = Column(String(255), nullable=False, unique=True)
    telegram_id = Column(BIGINT, unique=True)
        
    academic_role = Column(Enum('org', 'expert', 'student', name='academic_role_enum'), nullable=False, default='student')
    team_role = Column(Enum('team_lead', 'developer', 'analytic', 'game_designer', 'designer', name='team_role_enum'), nullable=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)

    team = relationship("Team", back_populates="users")
    
    authored_comments = relationship("SubmissionComment", back_populates="author")
    scores_given = relationship("SubmissionCriterionScore", back_populates="expert")
    assignments_received = relationship("SubmissionAssignment", back_populates="reviewer")


# === PROJECTS AND CRITERIA ===

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    mode = Column(TINYINT(unsigned=True), nullable=False)
    deadline = Column(DateTime, nullable=False)
    date_created = Column(DateTime, default=datetime.now(timezone.utc))
    status = Column(Enum('submitted', 'assigned', 'checked', name='project_status_enum'), default='submitted')

    participant_links = relationship("ProjectTeam", back_populates="project", cascade="all, delete-orphan")
    criteria = relationship("ProjectCriterion", back_populates="project", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="project", cascade="all, delete-orphan")


class ProjectTeam(Base):
    __tablename__ = "project_teams"
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)

    project = relationship("Project", back_populates="participant_links")
    team = relationship("Team", back_populates="participant_in_projects")


class ProjectCriterion(Base):
    __tablename__ = "project_criteria"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(127), nullable=False)
    max_score = Column(TINYINT(unsigned=True), nullable=False)
    sort_order = Column(TINYINT(unsigned=True), default=0)

    project = relationship("Project", back_populates="criteria")
    scores = relationship("SubmissionCriterionScore", back_populates="criterion")


# === SUBMISSIONS ===

class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    
    mark = Column(TINYINT(unsigned=True), nullable=True)
    checked_at = Column(DateTime, nullable=True)
    status = Column(Enum('unchecked', 'checking', 'checked', name='submission_status_enum'), default='unchecked')
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    project = relationship("Project", back_populates="submissions")
    team = relationship("Team", back_populates="submissions")
    
    artifacts = relationship("SubmissionArtifact", back_populates="submission", cascade="all, delete-orphan")
    comments = relationship("SubmissionComment", back_populates="submission", cascade="all, delete-orphan")
    scores = relationship("SubmissionCriterionScore", back_populates="submission", cascade="all, delete-orphan")
    assignments = relationship("SubmissionAssignment", back_populates="submission", cascade="all, delete-orphan")


class SubmissionArtifact(Base):
    __tablename__ = "submission_artifacts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(511), nullable=False)
    type = Column(Enum('link', 'file', 'text', name='artifact_type_enum'), default='link')

    submission = relationship("Submission", back_populates="artifacts")


class SubmissionComment(Base):
    __tablename__ = "submission_comments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    submission = relationship("Submission", back_populates="comments")
    author = relationship("User", back_populates="authored_comments")


# === SCORING AND ASSIGNMENTS ===

class SubmissionCriterionScore(Base):
    __tablename__ = "submission_criterion_scores"
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True)
    criterion_id = Column(Integer, ForeignKey("project_criteria.id", ondelete="CASCADE"), primary_key=True)
    expert_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    score = Column(TINYINT(unsigned=True), nullable=False)

    submission = relationship("Submission", back_populates="scores")
    criterion = relationship("ProjectCriterion", back_populates="scores")
    expert = relationship("User", back_populates="scores_given")


class SubmissionAssignment(Base):
    __tablename__ = "submission_assignments"
    __table_args__ = (
        UniqueConstraint('submission_id', 'reviewer_id'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum('pending', 'done', name='assignment_status_enum'), default='pending')
    assigned_at = Column(DateTime, default=datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)

    submission = relationship("Submission", back_populates="assignments")
    reviewer = relationship("User", back_populates="assignments_received")