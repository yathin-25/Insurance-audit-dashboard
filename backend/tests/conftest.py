import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update({
    "ENVIRONMENT": "test",
    "JWT_SECRET": "t" * 48,
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "STORAGE_DIR": f"{_tmp}/store",
    "MAX_UPLOAD_BYTES": "2000000",
    "MAX_ROWS": "1000",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.ratelimit import limiter  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "CorrectHorse-Battery9"


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    limiter.reset()
    with SessionLocal() as db:
        for name, role in (("vera", "viewer"), ("anna", "analyst"), ("adam", "admin")):
            db.add(User(username=name, password_hash=hash_password(PASSWORD), role=role))
        db.commit()
    with TestClient(app) as c:
        yield c


def auth(client, username):
    r = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
