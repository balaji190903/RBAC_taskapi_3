"""One-off script to bootstrap the very first Admin user.

Since self-signup always forces the 'member' role (to prevent privilege escalation),
you need at least one Admin account to manage roles afterwards. Run this once:

    python scripts/create_admin.py

You can pass them as CLI args:

    python scripts/create_admin.py admin@example.com "Str0ngPass!" "Super Admin"
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import RoleEnum, User  # noqa: E402
from app.security import hash_password  # noqa: E402


def main():
    email = sys.argv[1] if len(sys.argv) > 1 else os.getenv("FIRST_ADMIN_EMAIL", "admin@example.com")
    password = sys.argv[2] if len(sys.argv) > 2 else os.getenv("FIRST_ADMIN_PASSWORD", "Admin@12345")
    full_name = sys.argv[3] if len(sys.argv) > 3 else os.getenv("FIRST_ADMIN_NAME", "Super Admin")

    if not email or not password:
        print("Provide email/password via environment variables or CLI args.")
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"User {email} already exists (role={existing.role.value}). No changes made.")
            return
        admin = User(
            full_name=full_name,
            email=email,
            password=hash_password(password),
            role=RoleEnum.ADMIN,
        )
        db.add(admin)
        db.commit()
        print(f"Admin user created: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
