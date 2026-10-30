import csv
import hashlib
import io
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, insert, select
from sqlalchemy.orm import Session

from .audit import audit
from .config import get_settings
from .db import Base, SessionLocal, engine, get_db
from .metrics import DEFAULT_METRICS, SEVERITY_RANK, evaluate
from .models import AuditLog, ClaimResult, Dataset, EvaluationRun, Observation, User, as_aware, utcnow
from .ratelimit import limiter
from .recommendations import build_recommendations
from .security import (DUMMY_HASH, create_token, hash_password, password_policy_errors,
                       require_permission, verify_password)
from .validation import UploadValidationError, parse_upload, sanitize_filename

settings = get_settings()

app = FastAPI(
    title="Insurance Evaluation & Observation Dashboard API",
    docs_url=None if settings.is_prod else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_prod else "/openapi.json",
)

if not settings.is_prod:
    Base.metadata.create_all(engine)  # production must use migrations (Alembic is still TODO)

app.add_middleware(
    CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"],
)

SEC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    ip = request.client.host if request.client else "unknown"
    bucket, limit = ("login", 10) if request.url.path == "/auth/login" else ("api", 120)
    if not limiter.allow(f"{ip}:{bucket}", limit):
        return JSONResponse({"detail": "Too many requests"}, status_code=429, headers=SEC_HEADERS)
    response = await call_next(request)
    for k, v in SEC_HEADERS.items():
        response.headers[k] = v
    if not request.url.path.startswith(("/docs", "/openapi")):
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.is_prod:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled(_: Request, __: Exception):
    return JSONResponse({"detail": "Internal server error"}, status_code=500, headers=SEC_HEADERS)


# ---------------------------------------------------------------- helpers
def storage_path(key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise HTTPException(500, "Invalid storage key")
    return Path(settings.storage_dir) / key


def write_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(content)


def get_run_or_404(db: Session, run_id: int) -> EvaluationRun:
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


def csv_safe(v) -> str:
    """Neutralise spreadsheet formula injection in exported cells."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


# ---------------------------------------------------------------- auth
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    now = utcnow()
    user = db.query(User).filter(User.username == body.username).one_or_none()
    generic = HTTPException(401, "Invalid credentials")
    if user is None:
        verify_password(body.password, DUMMY_HASH)
        audit(db, request, body.username[:100], "login", None, "failure", {"reason": "unknown_user"})
        raise generic
    if user.locked_until and as_aware(user.locked_until) > now:
        audit(db, request, user.username, "login", None, "failure", {"reason": "locked"})
        raise generic
    if not user.is_active or not verify_password(body.password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= settings.login_max_attempts:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_attempts = 0
        db.commit()
        audit(db, request, user.username, "login", None, "failure", {"reason": "bad_credentials"})
        raise generic
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    audit(db, request, user.username, "login", None, "success")
    return {"access_token": create_token(user), "token_type": "bearer", "role": user.role}


@app.get("/me")
def me(user: User = Depends(require_permission("runs:read"))):
    return {"username": user.username, "role": user.role}


# ---------------------------------------------------------------- upload & evaluate
@app.post("/datasets", status_code=201)
async def upload_dataset(request: Request, file: UploadFile = File(...), data_origin: str = Form(...),
                         user: User = Depends(require_permission("dataset:upload")),
                         db: Session = Depends(get_db)):
    if data_origin not in ("synthetic", "real"):
        raise HTTPException(422, "data_origin must be 'synthetic' or 'real'")
    if data_origin == "real" and not settings.allow_real_data:
        audit(db, request, user.username, "upload", None, "denied", {"reason": "real_data_disabled"})
        raise HTTPException(403, "Real-data uploads are disabled in this environment. Use synthetic data "
                                 "until the security team approves this environment.")
    declared = request.headers.get("content-length")
    try:
        if declared and int(declared) > settings.max_upload_bytes + 1_000_000:
            raise HTTPException(413, "File too large")
    except ValueError:
        raise HTTPException(400, "Bad Content-Length")
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        audit(db, request, user.username, "upload", None, "rejected", {"reason": "too_large"})
        raise HTTPException(413, f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit")

    filename = sanitize_filename(file.filename or "")
    try:
        parsed = parse_upload(filename, content, settings)
    except UploadValidationError as e:
        audit(db, request, user.username, "upload", None, "rejected", {"reason": "validation_failed", "filename": filename})
        raise HTTPException(400, {"message": "Upload rejected", "errors": e.errors})

    key = uuid.uuid4().hex
    write_private(storage_path(key), content)
    ds = Dataset(original_filename=filename, storage_key=key, sha256=hashlib.sha256(content).hexdigest(),
                 size_bytes=len(content), row_count=parsed.row_count, data_origin=data_origin,
                 warnings=parsed.warnings, uploaded_by=user.username)
    db.add(ds)
    db.commit()
    audit(db, request, user.username, "upload", f"dataset:{ds.id}", "success",
          {"dataset_id": ds.id, "rows": ds.row_count, "size_bytes": ds.size_bytes, "origin": data_origin})
    return {"dataset_id": ds.id, "rows": ds.row_count, "data_origin": data_origin, "warnings": parsed.warnings}


@app.post("/datasets/{dataset_id}/evaluate", status_code=201)
def evaluate_dataset(dataset_id: int, request: Request,
                     user: User = Depends(require_permission("run:create")), db: Session = Depends(get_db)):
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    path = storage_path(ds.storage_key)
    if not path.exists():
        raise HTTPException(404, "Dataset file is no longer available")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != ds.sha256:  # integrity check
        audit(db, request, user.username, "evaluate", f"dataset:{ds.id}", "failure", {"reason": "integrity_mismatch"})
        raise HTTPException(409, "Stored file failed its integrity check")

    parsed = parse_upload(ds.original_filename, content, settings)
    as_of = pd.Timestamp(datetime.now(timezone.utc).date())
    result = evaluate(parsed, as_of)
    recs = build_recommendations(result)
    label = "SYNTHETIC / sample data" if ds.data_origin == "synthetic" else "Calculated from uploaded real data"
    summary = {
        "dataset": {"id": ds.id, "filename": ds.original_filename, "data_origin": ds.data_origin, "label": label},
        "as_of": as_of.date().isoformat(), "kpis": result.kpis, "overall": result.overall,
        "metrics": result.metrics, "recommendations": recs,
        "review_notice": "Findings are indicators for human review. This system never approves, denies or settles claims.",
    }
    run = EvaluationRun(dataset_id=ds.id, started_by=user.username, as_of=as_of.date(),
                        overall_score=result.overall["score"], summary=summary)
    db.add(run)
    db.flush()
    for rows, model in ((result.claims, ClaimResult), (result.observations, Observation)):
        payload = [{**r, "run_id": run.id} for r in rows]
        for i in range(0, len(payload), 5000):
            db.execute(insert(model), payload[i:i + 5000])
    db.commit()
    audit(db, request, user.username, "evaluate", f"run:{run.id}", "success", {"run_id": run.id, "dataset_id": ds.id})
    return {"run_id": run.id, "overall_score": run.overall_score}


# ---------------------------------------------------------------- read APIs
@app.get("/metrics/definitions")
def metric_definitions(user: User = Depends(require_permission("runs:read"))):
    return [{"key": d.key, "name": d.name, "definition": d.definition, "formula": d.formula,
             "required_fields": list(d.required_fields), "threshold": d.threshold, "severity": d.severity,
             "weight": d.weight, "limitations": d.limitations} for d in DEFAULT_METRICS]


@app.get("/runs")
def list_runs(user: User = Depends(require_permission("runs:read")), db: Session = Depends(get_db)):
    rows = db.query(EvaluationRun).order_by(EvaluationRun.id.desc()).limit(100).all()
    return [{"run_id": r.id, "dataset_id": r.dataset_id, "created_at": r.created_at, "started_by": r.started_by,
             "overall_score": r.overall_score, "data_origin": r.summary["dataset"]["data_origin"]} for r in rows]


@app.get("/runs/{run_id}")
def get_run(run_id: int, user: User = Depends(require_permission("runs:read")), db: Session = Depends(get_db)):
    run = get_run_or_404(db, run_id)
    return {"run_id": run.id, "created_at": run.created_at, "started_by": run.started_by, **run.summary}


@app.get("/runs/{run_id}/claims")
def list_claims(run_id: int,
                search: Optional[str] = Query(None, max_length=50),
                metric: Optional[str] = Query(None, max_length=40),
                critical_only: bool = False, failing_only: bool = False,
                sort_by: Literal["row_number", "claim_id", "score", "failure_count"] = "score",
                order: Literal["asc", "desc"] = "asc",
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                user: User = Depends(require_permission("claims:read")), db: Session = Depends(get_db)):
    get_run_or_404(db, run_id)
    q = select(ClaimResult).where(ClaimResult.run_id == run_id)
    if search:
        q = q.where(ClaimResult.claim_id.contains(search, autoescape=True))
    if metric:
        q = q.where(ClaimResult.row_number.in_(
            select(Observation.row_number).where(Observation.run_id == run_id, Observation.metric == metric)))
    if critical_only:
        q = q.where(ClaimResult.has_critical.is_(True))
    if failing_only:
        q = q.where(ClaimResult.failure_count > 0)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    col = getattr(ClaimResult, sort_by)
    q = q.order_by(col.desc() if order == "desc" else col.asc(), ClaimResult.row_number)
    rows = db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size,
            "items": [{"row_number": r.row_number, "claim_id": r.claim_id, "score": r.score,
                       "failure_count": r.failure_count, "has_critical": r.has_critical} for r in rows]}


@app.get("/runs/{run_id}/claims/{row_number}")
def claim_detail(run_id: int, row_number: int,
                 user: User = Depends(require_permission("claims:read")), db: Session = Depends(get_db)):
    get_run_or_404(db, run_id)
    claim = db.scalars(select(ClaimResult).where(ClaimResult.run_id == run_id,
                                                  ClaimResult.row_number == row_number)).first()
    if claim is None:
        raise HTTPException(404, "Claim not found")
    obs = db.scalars(select(Observation).where(Observation.run_id == run_id,
                                                Observation.row_number == row_number)).all()
    return {"row_number": claim.row_number, "claim_id": claim.claim_id, "score": claim.score,
            "has_critical": claim.has_critical,
            "observations": [{"metric": o.metric, "severity": o.severity, "reason": o.reason,
                              "evidence": o.evidence} for o in obs]}


@app.get("/runs/{run_id}/observations")
def list_observations(run_id: int,
                      severity: Optional[Literal["critical", "high", "medium", "low"]] = None,
                      metric: Optional[str] = Query(None, max_length=40),
                      page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                      user: User = Depends(require_permission("claims:read")), db: Session = Depends(get_db)):
    get_run_or_404(db, run_id)
    q = select(Observation).where(Observation.run_id == run_id)
    if severity:
        q = q.where(Observation.severity == severity)
    if metric:
        q = q.where(Observation.metric == metric)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rank = case(*[(Observation.severity == k, v) for k, v in SEVERITY_RANK.items()], else_=9)
    rows = db.scalars(q.order_by(rank, Observation.row_number).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size,
            "items": [{"row_number": o.row_number, "claim_id": o.claim_id, "metric": o.metric,
                       "severity": o.severity, "reason": o.reason, "evidence": o.evidence} for o in rows]}


@app.get("/runs/{run_id}/report.csv")
def export_report(run_id: int, request: Request,
                  user: User = Depends(require_permission("report:export")), db: Session = Depends(get_db)):
    """Minimal-exposure report: claim IDs, scores and failed metric names only
    (no amounts, no evidence values). Cells are protected against formula injection."""
    get_run_or_404(db, run_id)
    failed = {}
    for rn, metric in db.execute(select(Observation.row_number, Observation.metric).where(Observation.run_id == run_id)):
        failed.setdefault(rn, []).append(metric)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["row_number", "claim_id", "score", "failure_count", "has_critical", "failed_metrics"])
    for c in db.scalars(select(ClaimResult).where(ClaimResult.run_id == run_id).order_by(ClaimResult.row_number)):
        w.writerow([c.row_number, csv_safe(c.claim_id), c.score, c.failure_count, c.has_critical,
                    csv_safe("|".join(failed.get(c.row_number, [])))])
    audit(db, request, user.username, "export", f"run:{run_id}", "success", {"run_id": run_id, "format": "csv"})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="run_{run_id}_report.csv"'})


# ---------------------------------------------------------------- admin
@app.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, request: Request,
                   user: User = Depends(require_permission("dataset:delete")), db: Session = Depends(get_db)):
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    run_ids = [r for (r,) in db.execute(select(EvaluationRun.id).where(EvaluationRun.dataset_id == ds.id))]
    for model in (Observation, ClaimResult):
        db.query(model).filter(model.run_id.in_(run_ids)).delete(synchronize_session=False)
    db.query(EvaluationRun).filter(EvaluationRun.dataset_id == ds.id).delete(synchronize_session=False)
    path = storage_path(ds.storage_key)
    db.delete(ds)
    db.commit()
    path.unlink(missing_ok=True)
    audit(db, request, user.username, "delete_dataset", f"dataset:{dataset_id}", "success", {"dataset_id": dataset_id})
    return Response(status_code=204)


@app.get("/admin/audit")
def read_audit(limit: int = Query(100, ge=1, le=500), user: User = Depends(require_permission("audit:read")),
               db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"ts": r.ts, "actor": r.actor, "action": r.action, "resource": r.resource,
             "outcome": r.outcome, "ip": r.ip, "detail": r.detail} for r in rows]


class UserIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.@-]{3,100}$")
    password: str = Field(min_length=1, max_length=200)
    role: Literal["viewer", "analyst", "admin"]


class UserPatch(BaseModel):
    role: Optional[Literal["viewer", "analyst", "admin"]] = None
    is_active: Optional[bool] = None


@app.post("/admin/users", status_code=201)
def create_user(body: UserIn, request: Request,
                admin: User = Depends(require_permission("user:manage")), db: Session = Depends(get_db)):
    errs = password_policy_errors(body.password)
    if errs:
        raise HTTPException(422, {"message": "Weak password", "errors": errs})
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(409, "Username already exists")
    u = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.commit()
    audit(db, request, admin.username, "create_user", f"user:{u.id}", "success",
          {"target_user": u.username, "role": u.role})
    return {"id": u.id, "username": u.username, "role": u.role}


@app.patch("/admin/users/{user_id}")
def update_user(user_id: int, body: UserPatch, request: Request,
                admin: User = Depends(require_permission("user:manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id:
        raise HTTPException(400, "Admins cannot change their own role or active state")
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
    db.commit()
    audit(db, request, admin.username, "update_user", f"user:{u.id}", "success",
          {"target_user": u.username, "new_role": u.role, "is_active": u.is_active})
    return {"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active}
