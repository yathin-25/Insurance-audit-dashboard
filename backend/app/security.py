"""Authentication (JWT bearer), password hashing and permission checks.

PRODUCTION NOTE: local username/password login is a development / fallback mechanism.
In production, replace `decode_token` with validation of tokens issued by the company's
identity provider (OIDC/SAML SSO with MFA). The permission checks below stay the same.
"""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .audit import audit
from .config import get_settings
from .db import get_db
from .models import User

ISSUER = "insurance-dashboard"
ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 12

PERMISSIONS = {
    "viewer": {"runs:read"},
    "analyst": {"runs:read", "claims:read", "dataset:upload", "run:create", "report:export"},
    "admin": {"runs:read", "claims:read", "dataset:upload", "run:create", "report:export",
              "dataset:delete", "audit:read", "user:manage"},
}

bearer = HTTPBearer(auto_error=False)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


DUMMY_HASH = hash_password("dummy-password-for-timing")  # equalises timing for unknown usernames


def password_policy_errors(password: str) -> list:
    errs = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errs.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        errs.append("Password must mix upper/lower case letters and include a digit.")
    return errs


def create_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "iss": ISSUER, "iat": now,
               "exp": now + timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], issuer=ISSUER,
                      options={"require": ["exp", "sub", "iss"]})


def _unauthorized():
    return HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise _unauthorized()
    try:
        user_id = int(decode_token(creds.credentials)["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _unauthorized()
    user = db.get(User, user_id)  # role is read from the DB every request: changes/deactivation apply immediately
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


def require_permission(permission: str):
    def dependency(request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> User:
        if permission not in PERMISSIONS.get(user.role, set()):  # unknown role => no permissions (fail closed)
            audit(db, request, user.username, "access_denied", permission, "denied")
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return dependency
