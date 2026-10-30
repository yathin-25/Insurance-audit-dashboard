"""Audit logging. Only allow-listed, non-sensitive detail keys are stored:
never claim contents, credentials or whole files."""
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog

ALLOWED_DETAIL_KEYS = {
    "dataset_id", "run_id", "rows", "size_bytes", "filename", "reason",
    "role", "target_user", "new_role", "origin", "format", "is_active",
}


def client_ip(request: Request) -> str:
    # Behind a reverse proxy, configure uvicorn --proxy-headers / trusted hosts so this is the real client.
    return request.client.host if request.client else "unknown"


def audit(db: Session, request: Request, actor: str, action: str, resource: Optional[str],
          outcome: str, detail: Optional[dict] = None) -> None:
    clean = {}
    for k, v in (detail or {}).items():
        if k not in ALLOWED_DETAIL_KEYS:
            continue
        if isinstance(v, (bool, int)):
            clean[k] = v
        elif isinstance(v, str):
            clean[k] = v[:120]
    db.add(AuditLog(actor=actor[:100], action=action, resource=(resource or None) and resource[:120],
                    outcome=outcome, ip=client_ip(request), detail=clean))
    db.commit()  # if this fails the request fails: no un-audited actions (fail closed)
