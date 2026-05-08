from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.mysql import TINYINT, BIGINT
from datetime import datetime

Base = declarative_base()

class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(127), nullable=False)
    
    projects = relationship("Project", foreign_keys="Project.team_id", back_populates="team")
    users = relationship("User", back_populates="team")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(127), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    code = Column(String(255), nullable=False, unique=True)
    telegram_id = Column(BIGINT, unique=True)
    role = Column(Enum('org', 'expert', 'student', name='user_role_enum'), nullable=False, default='student')
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    
    team = relationship("Team", back_populates="users")

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    mode = Column(TINYINT(unsigned=True), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    date_created = Column(DateTime, default=datetime.utcnow)
    date_checked = Column(DateTime, nullable=True)
    mark = Column(TINYINT(unsigned=True), nullable=True)
    status = Column(Enum('submitted', 'assigned', 'checked', name='project_status_enum'), default='submitted')
    
    team = relationship("Team", foreign_keys=[team_id], back_populates="projects")
    artifacts = relationship("ProjectArtifact", back_populates="project", cascade="all, delete-orphan")
    criteria = relationship("ProjectCriterion", back_populates="project", cascade="all, delete-orphan")
    comments = relationship("ProjectComment", back_populates="project", cascade="all, delete-orphan")
    scores = relationship("ProjectCriterionScore", back_populates="project", cascade="all, delete-orphan")
    reviewers = relationship("ProjectReviewer", back_populates="project", cascade="all, delete-orphan")

class ProjectArtifact(Base):
    __tablename__ = "project_artifacts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(511), nullable=False)
    type = Column(Enum('link', 'file', 'text', name='artifact_type_enum'), default='link')
    
    project = relationship("Project", back_populates="artifacts")

class ProjectCriterion(Base):
    __tablename__ = "project_criteria"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(127), nullable=False)
    max_score = Column(TINYINT(unsigned=True), nullable=False)
    sort_order = Column(TINYINT(unsigned=True), default=0)
    
    project = relationship("Project", back_populates="criteria")
    scores = relationship("ProjectCriterionScore", back_populates="criterion")

class ProjectCriterionScore(Base):
    __tablename__ = "project_criterion_scores"
    
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    criterion_id = Column(Integer, ForeignKey("project_criteria.id", ondelete="CASCADE"), primary_key=True)
    expert_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    score = Column(TINYINT(unsigned=True), nullable=False)
    
    project = relationship("Project", back_populates="scores")
    criterion = relationship("ProjectCriterion", back_populates="scores")
    expert = relationship("User")

class ProjectComment(Base):
    __tablename__ = "project_comments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    commentator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    comment = Column(Text, nullable=False)
    
    project = relationship("Project", back_populates="comments")
    commentator = relationship("User")

class ProjectReviewer(Base):
    __tablename__ = "project_reviewers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum('expert', 'student', name='reviewer_role_enum'), default='expert')
    status = Column(Enum('pending', 'active', 'done', name='review_status_enum'), default='pending')
    assigned_at = Column(DateTime, default=datetime.utcnow)
    
    project = relationship("Project", back_populates="reviewers")
    reviewer = relationship("User")

class ProjectTeam(Base):
    __tablename__ = "project_teams"
    
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    
    project = relationship("Project", backref="participant_teams")
    team = relationship("Team")