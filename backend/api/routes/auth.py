import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import verify_csrf_token
from models.employee import Employee
from services.auth_service import (
    authenticate_employee,
    create_employee_session,
    get_session_and_employee,
    delete_session,
    create_employee_by_admin,
)
from services.activity_logger import log_activity

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication & Employees"])

SESSION_COOKIE_NAME = "espial_session"
CSRF_COOKIE_NAME = "espial_csrf"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds


# Request / Response Schemas
class LoginRequest(BaseModel):
    email: str
    password: str


class CreateEmployeeRequest(BaseModel):
    email: str
    full_name: str
    password: str
    role: str = "employee"


def get_current_employee(
    request: Request,
    db: Session = Depends(get_db),
) -> Employee:
    """Dependency to retrieve currently authenticated employee from session cookie or header."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_id = auth_header[7:].strip()

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
        )

    session, employee = get_session_and_employee(db, session_id)
    if not session or not employee:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or is invalid. Please log in again.",
        )

    # Attach session to request state for CSRF checks
    request.state.session = session
    verify_csrf(request)
    return employee


def get_current_admin(
    current_employee: Employee = Depends(get_current_employee),
) -> Employee:
    """Dependency that restricts route access to administrators only."""
    if current_employee.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required for this action.",
        )
    return current_employee


def verify_csrf(request: Request) -> None:
    """Verify CSRF token for state-changing requests when session cookie is used."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if session_cookie:
            header_token = request.headers.get("X-CSRF-Token")
            session = getattr(request.state, "session", None)
            if not session or not header_token or not verify_csrf_token(session.csrf_token, header_token):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="CSRF validation failed. Missing or invalid X-CSRF-Token header.",
                )


@router.post("/login")
def login(
    req: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    """Employee login. Public registration is disabled; accounts are admin-provisioned."""
    employee = authenticate_employee(db, req.email, req.password)
    if not employee:
        log_activity(
            db=db,
            action="login",
            status="failure",
            employee_email=req.email,
            details={"reason": "Invalid credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    session, csrf_token = create_employee_session(db, employee.id)
    log_activity(
        db=db,
        action="login",
        status="success",
        employee=employee,
    )

    # Production-ready secure cookies supporting both local dev and cross-origin staging
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    samesite_val = "none" if is_https else "lax"

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session.id,
        httponly=True,
        secure=is_https,
        samesite=samesite_val,
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,  # Accessible to frontend JS to mirror in X-CSRF-Token header
        secure=is_https,
        samesite=samesite_val,
        max_age=COOKIE_MAX_AGE,
        path="/",
    )

    return {
        "status": "success",
        "employee": employee.to_safe_dict(),
        "csrf_token": csrf_token,
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Invalidate employee session and clear authentication cookies."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        _, employee = get_session_and_employee(db, session_id)
        if employee:
            log_activity(
                db=db,
                action="logout",
                status="success",
                employee=employee,
            )
        delete_session(db, session_id)

    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    samesite_val = "none" if is_https else "lax"
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=is_https, samesite=samesite_val)
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=is_https, samesite=samesite_val)
    return {"status": "success", "message": "Logged out successfully."}


@router.get("/me")
def get_me(
    current_employee: Employee = Depends(get_current_employee),
    request: Request = None,
):
    """Retrieve currently authenticated employee identity."""
    session = getattr(request.state, "session", None)
    return {
        "status": "success",
        "employee": current_employee.to_safe_dict(),
        "csrf_token": session.csrf_token if session else None,
    }


# Admin Employee Management Endpoints (Strictly RBAC Guarded)
@router.get("/employees")
def list_employees(
    admin: Employee = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """List all registered employee accounts. Strictly admin-only."""
    employees = db.query(Employee).order_by(Employee.id.asc()).all()
    return {
        "status": "success",
        "employees": [e.to_safe_dict() for e in employees],
    }


@router.post("/employees")
def create_employee(
    req: CreateEmployeeRequest,
    admin: Employee = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Create a new employee account. Strictly admin-only (No public signup)."""
    try:
        new_emp = create_employee_by_admin(
            db=db,
            email=req.email,
            full_name=req.full_name,
            password=req.password,
            role=req.role,
        )
        log_activity(
            db=db,
            action="employee_create",
            status="success",
            employee=admin,
            details={
                "created_employee_id": new_emp.id,
                "created_employee_email": new_emp.email,
                "role": new_emp.role,
            },
        )
        return {
            "status": "success",
            "message": f"Employee {new_emp.email} created successfully.",
            "employee": new_emp.to_safe_dict(),
        }
    except ValueError as exc:
        log_activity(
            db=db,
            action="employee_create",
            status="failure",
            employee=admin,
            details={"target_email": req.email, "error": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        log.error("Failed to create employee: %s", exc)
        log_activity(
            db=db,
            action="employee_create",
            status="failure",
            employee=admin,
            details={"target_email": req.email, "error": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create employee.")


@router.delete("/employees/{employee_id}")
def deactivate_employee(
    employee_id: int,
    admin: Employee = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Deactivate or remove an employee account. Strictly admin-only."""
    if admin.id == employee_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete or deactivate your own admin account.",
        )

    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    emp.is_active = False
    db.commit()
    log_activity(
        db=db,
        action="employee_deactivate",
        status="success",
        employee=admin,
        details={"deactivated_employee_id": emp.id, "deactivated_employee_email": emp.email},
    )
    return {"status": "success", "message": f"Employee {emp.email} deactivated."}
