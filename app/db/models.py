from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class PRReview(Base):
    __tablename__ = "pr_reviews"

    id = Column(Integer, primary_key=True, index=True)
    repo_full_name = Column(String(255), nullable=False)
    pr_number = Column(Integer, nullable=False)
    base_sha = Column(String(40), nullable=False)
    last_completed_sha = Column(String(40), nullable=True)
    status = Column(String(50), default="IDLE")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("repo_full_name", "pr_number", name="uq_repo_pr"),
    )