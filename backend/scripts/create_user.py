"""Create a user from the command line (password is prompted, never passed as an argument).

    python -m scripts.create_user --username alice --role analyst
"""
import argparse
import getpass

from app.db import Base, SessionLocal, engine
from app.models import User
from app.security import hash_password, password_policy_errors


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--role", choices=["viewer", "analyst", "admin"], required=True)
    a = p.parse_args()
    pw = getpass.getpass("Password: ")
    errs = password_policy_errors(pw)
    if errs:
        raise SystemExit("\n".join(errs))
    if pw != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(User).filter(User.username == a.username).first():
            raise SystemExit("User already exists")
        db.add(User(username=a.username, password_hash=hash_password(pw), role=a.role))
        db.commit()
    print(f"Created {a.role} '{a.username}'")


if __name__ == "__main__":
    main()
