from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_aware(dt):
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(300), nullable=False)
    role = Column(String(20), nullable=False, default="viewer")  # viewer | analyst | admin
    is_active = Column(Boolean, nullable=False, default=True)
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(Integer, primary_key=True)
    original_filename = Column(String(150), nullable=False)
    storage_key = Column(String(64), nullable=False, unique=True)  # random name in private storage
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    row_count = Column(Integer, nullable=False)
    data_origin = Column(String(20), nullable=False)  # synthetic | real  (declared by uploader)
    warnings = Column(JSON, nullable=False, default=list)
    uploaded_by = Column(String(100), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id = Column(Integer, primary_key=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    started_by = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    as_of = Column(Date, nullable=False)
    overall_score = Column(Float, nullable=True)
    summary = Column(JSON, nullable=False)


class ClaimResult(Base):
    __tablename__ = "claim_results"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("evaluation_runs.id"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)  # row in the uploaded file (header = row 1)
    claim_id = Column(String(120), nullable=True, index=True)
    score = Column(Float, nullable=True)
    failure_count = Column(Integer, nullable=False, default=0)
    has_critical = Column(Boolean, nullable=False, default=False)


class Observation(Base):
    __tablename__ = "observations"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("evaluation_runs.id"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    claim_id = Column(String(120), nullable=True)
    metric = Column(String(40), nullable=False, index=True)
    severity = Column(String(10), nullable=False)
    reason = Column(String(500), nullable=False)
    evidence = Column(JSON, nullable=False)  # only the metric's allow-listed fields


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    actor = Column(String(100), nullable=False)
    action = Column(String(60), nullable=False)
    resource = Column(String(120), nullable=True)
    outcome = Column(String(20), nullable=False)
    ip = Column(String(64), nullable=True)
    detail = Column(JSON, nullable=False, default=dict)
