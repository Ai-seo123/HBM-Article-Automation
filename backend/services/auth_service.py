import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from core.config import settings
from core.security import (
    hash_password,
    verify_password,
    generate_session_id,
    generate_csrf_token,
)
from models.employee import Employee, EmployeeSession

log = logging.getLogger(__name__)


def ensure_initial_admin(db: Session) -> Optional[Employee]:
    """
    Ensure an initial administrator exists in the database.
    Mandatory ADMIN_INITIAL_PASSWORD: Never prints or exposes passwords in logs.
    If no admin exists and ADMIN_INITIAL_PASSWORD is missing, fails safely with an error log.
    """
    existing_admin = db.query(Employee).filter(Employee.role == "admin").first()
    if existing_admin:
        return existing_admin

    admin_password = (settings.ADMIN_INITIAL_PASSWORD or "").strip()
    admin_email = (settings.ADMIN_EMAIL or "admin@espialsolutions.com").strip().lower()

    if not admin_password:
        log.error(
            "CRITICAL: No admin user exists and ADMIN_INITIAL_PASSWORD is not configured in environment. "
            "Admin bootstrapping skipped. Please set ADMIN_INITIAL_PASSWORD in backend/.env to initialize."
        )
        return None

    try:
        pw_hash = hash_password(admin_password)
        admin = Employee(
            email=admin_email,
            full_name="Espial Administrator",
            password_hash=pw_hash,
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        log.info(
            "Initial admin account successfully bootstrapped for %s. Zero passwords exposed in logs.",
            admin_email,
        )
        return admin
    except Exception as exc:
        db.rollback()
        log.error("Failed to bootstrap initial admin account: %s", exc)
        return None


def authenticate_employee(db: Session, email: str, password: str) -> Optional[Employee]:
    """Authenticate an employee by email and password using salted PBKDF2 verification."""
    clean_email = (email or "").strip().lower()
    if not clean_email or not password:
        return None

    employee = db.query(Employee).filter(
        Employee.email == clean_email,
        Employee.is_active == True,
    ).first()

    if not employee:
        return None

    if verify_password(password, employee.password_hash):
        return employee

    return None


def create_employee_session(
    db: Session,
    employee_id: int,
    duration_days: int = 7,
) -> Tuple[EmployeeSession, str]:
    """
    Create a secure session for the authenticated employee.
    Returns (EmployeeSession, csrf_token).
    """
    session_id = generate_session_id()
    csrf_token = generate_csrf_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)

    session = EmployeeSession(
        id=session_id,
        employee_id=employee_id,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, csrf_token


def get_session_and_employee(
    db: Session,
    session_id: str,
) -> Tuple[Optional[EmployeeSession], Optional[Employee]]:
    """Retrieve active session and employee. Cleans up expired sessions."""
    if not session_id:
        return None, None

    session = db.query(EmployeeSession).filter(EmployeeSession.id == session_id).first()
    if not session:
        return None, None

    if session.is_expired():
        try:
            db.delete(session)
            db.commit()
        except Exception:
            db.rollback()
        return None, None

    employee = db.query(Employee).filter(
        Employee.id == session.employee_id,
        Employee.is_active == True,
    ).first()

    if not employee:
        return None, None

    return session, employee


def delete_session(db: Session, session_id: str) -> None:
    """Invalidate a session upon logout."""
    if not session_id:
        return
    try:
        session = db.query(EmployeeSession).filter(EmployeeSession.id == session_id).first()
        if session:
            db.delete(session)
            db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Failed to delete session %s: %s", session_id, exc)


def create_employee_by_admin(
    db: Session,
    email: str,
    full_name: str,
    password: str,
    role: str = "employee",
) -> Employee:
    """Create a new employee account by an administrator (No public signup)."""
    clean_email = (email or "").strip().lower()
    clean_name = (full_name or "").strip()
    clean_role = (role or "employee").strip().lower()

    if clean_role not in ("admin", "employee"):
        clean_role = "employee"

    if not clean_email or "@" not in clean_email:
        raise ValueError("A valid email address is required.")
    if not clean_name:
        raise ValueError("Full name is required.")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")

    existing = db.query(Employee).filter(Employee.email == clean_email).first()
    if existing:
        raise ValueError(f"An employee with email '{clean_email}' already exists.")

    pw_hash = hash_password(password)
    employee = Employee(
        email=clean_email,
        full_name=clean_name,
        password_hash=pw_hash,
        role=clean_role,
        is_active=True,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    log.info("Admin created new employee account: %s (role=%s)", clean_email, clean_role)
    return employee

