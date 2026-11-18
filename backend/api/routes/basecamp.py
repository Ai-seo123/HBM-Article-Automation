"""
Basecamp OAuth 2.0 API routes for Espial Article Publishing.

Endpoints:
  GET  /api/basecamp/connect                 → redirect to Basecamp authorization page with employee state
  GET  /api/basecamp/callback                → receive code, exchange for employee tokens, handle single or multi-account
  GET  /api/basecamp/status                  → connection status for authenticated employee
  POST /api/basecamp/disconnect              → disconnect employee's Basecamp connection
  POST /api/basecamp/refresh                 → strictly manual-only token refresh
  GET  /api/basecamp/pending-accounts        → list accounts pending employee selection (multi-account OAuth)
  POST /api/basecamp/select-account          → select chosen account to finalize connection

  GET  /api/basecamp/identity                → authenticated employee's Basecamp identity & accounts
  GET  /api/basecamp/projects                → list projects using employee's own account_id
  GET  /api/basecamp/projects/{id}           → single project details
  GET  /api/basecamp/projects/{id}/messages  → messages in project
  GET  /api/basecamp/projects/{id}/messages/{id} → single message details
"""

import logging
import os
from typing import Optional
from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from core.date_utils import normalize_timestamp_to_date
from models.employee import Employee
from api.routes.auth import get_current_employee
import services.basecamp as bc_service
from services.activity_logger import log_activity

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/basecamp", tags=["Basecamp Integration"])


def _get_frontend_settings_page() -> str:
    """Return the frontend settings page URL dynamically."""
    frontend_url = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    if frontend_url:
        return f"{frontend_url}/settings"
    for origin in settings.ALLOWED_ORIGINS:
        if "localhost" not in origin and "127.0.0.1" not in origin:
            return f"{origin.rstrip('/')}/settings"
    base = settings.ALLOWED_ORIGINS[0].rstrip("/") if settings.ALLOWED_ORIGINS else "http://localhost:5173"
    return f"{base}/settings"


_FRONTEND_BASE = settings.ALLOWED_ORIGINS[0]
_FRONTEND_SETTINGS_PAGE = f"{_FRONTEND_BASE}/settings"


class SelectAccountRequest(BaseModel):
    account_id: str


def _get_optional_employee(
    request: Request,
    db: Session,
) -> Optional[Employee]:
    """Helper to retrieve employee if logged in, without raising 401 immediately (for callback/connect)."""
    from services.auth_service import get_session_and_employee
    session_id = request.cookies.get("espial_session")
    if not session_id:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_id = auth_header[7:].strip()
    if session_id:
        _, employee = get_session_and_employee(db, session_id)
        return employee
    return None


def _format_error_response(exc: Exception) -> JSONResponse:
    err_str = str(exc)
    if "basecamp_token_expired" in err_str:
        return JSONResponse(
            status_code=401,
            content={
                "error": "basecamp_token_expired",
                "message": "Basecamp session has expired. Please go to Settings → Integrations → Basecamp and click 'Refresh Connection'.",
            },
        )
    if "not_connected" in err_str:
        return JSONResponse(
            status_code=403,
            content={
                "error": "not_connected",
                "message": "You have not connected your Basecamp account. Please go to Settings → Integrations → Basecamp to connect.",
            },
        )
    log.error("Basecamp API error: %s", err_str)
    return JSONResponse(
        status_code=503,
        content={
            "error": "basecamp_api_error",
            "message": "Could not fetch data from Basecamp. Please try again.",
        },
    )


# ---------------------------------------------------------------------------
# OAuth Flow Endpoints
# ---------------------------------------------------------------------------

@router.get("/connect", summary="Start Basecamp OAuth flow for current employee")
def basecamp_connect(
    request: Request,
    db: Session = Depends(get_db),
):
    """Initiate Basecamp OAuth flow. Associates employee ID in state parameter."""
    employee = _get_optional_employee(request, db)
    state = str(employee.id) if employee else ""
    try:
        url = bc_service.build_authorization_url(state=state)
        return RedirectResponse(url=url, status_code=302)
    except RuntimeError as exc:
        log.warning("Basecamp connect failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": "basecamp_not_configured", "message": str(exc)},
        )


@router.get("/callback", summary="Handle Basecamp OAuth callback")
async def basecamp_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    db: Session = Depends(get_db),
):
    """
    Handle OAuth callback from Basecamp.
    Exchanges code for tokens, resolves account(s), and isolates to the employee.
    If multiple accounts, redirects to settings with select_basecamp_account=1.
    """
    settings_page = _get_frontend_settings_page()
    if error:
        log.warning("Basecamp OAuth denied: %s — %s", error, error_description)
        return RedirectResponse(
            url=f"{settings_page}?tab=integrations&basecamp_error=access_denied",
            status_code=302,
        )

    if not code:
        return RedirectResponse(
            url=f"{settings_page}?tab=integrations&basecamp_error=missing_code",
            status_code=302,
        )

    # Resolve employee from state or session cookie
    employee_id: Optional[int] = None
    if state and state.isdigit():
        employee_id = int(state)
    else:
        emp = _get_optional_employee(request, db)
        if emp:
            employee_id = emp.id

    if not employee_id:
        return RedirectResponse(
            url=f"{settings_page}?tab=integrations&basecamp_error=unauthenticated",
            status_code=302,
        )

    try:
        res = await bc_service.exchange_code_for_employee(code, employee_id, db)
        if res.get("status") == "pending_selection":
            log_activity(
                db=db,
                action="basecamp_connect",
                status="success",
                employee_id=employee_id,
                details={"step": "pending_account_selection"},
            )
            # Multiple accounts returned — employee must select account
            return RedirectResponse(
                url=f"{settings_page}?tab=integrations&select_basecamp_account=1",
                status_code=302,
            )
        log_activity(
            db=db,
            action="basecamp_connect",
            status="success",
            employee_id=employee_id,
            details={"account_id": res.get("account_id"), "account_name": res.get("account_name")},
        )
        return RedirectResponse(
            url=f"{settings_page}?tab=integrations&basecamp_status=connected",
            status_code=302,
        )
    except Exception as exc:
        log.error("Basecamp token exchange error for employee %s: %s", employee_id, exc)
        log_activity(
            db=db,
            action="basecamp_connect",
            status="failure",
            employee_id=employee_id,
            details={"error": str(exc)},
        )
        return RedirectResponse(
            url=f"{settings_page}?tab=integrations&basecamp_error=exchange_failed",
            status_code=302,
        )


@router.get("/status", summary="Connection status for authenticated employee")
def basecamp_status(
    request: Request,
    current_employee: Employee = Depends(get_current_employee),
):
    """Return connection status for the authenticated employee. Never exposes raw tokens."""
    return bc_service.get_connection_status(employee_id=current_employee.id)


@router.post("/disconnect", summary="Disconnect employee Basecamp connection")
def basecamp_disconnect(
    current_employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Disconnect Basecamp connection for authenticated employee."""
    res = bc_service.disconnect_employee(db, current_employee.id)
    log_activity(
        db=db,
        action="basecamp_disconnect",
        status="success",
        employee=current_employee,
    )
    return res


@router.post("/refresh", summary="Strictly manual-only token refresh")
async def basecamp_refresh_manual(
    current_employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """
    Manually refresh the authenticated employee's Basecamp tokens.
    Strictly manual: only runs when employee explicitly clicks Refresh Connection.
    """
    result = await bc_service.refresh_employee_token_manual(db, current_employee.id)
    if not result.get("success"):
        log_activity(
            db=db,
            action="basecamp_refresh",
            status="failure",
            employee=current_employee,
            details={"error": result.get("message", "Token refresh failed.")},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("message", "Token refresh failed."),
        )
    log_activity(
        db=db,
        action="basecamp_refresh",
        status="success",
        employee=current_employee,
    )
    return result


@router.get("/pending-accounts", summary="List accounts pending employee selection")
def get_pending_accounts(
    current_employee: Employee = Depends(get_current_employee),
):
    """Retrieve list of accounts when OAuth returned multiple accounts."""
    accounts = bc_service.get_pending_accounts_for_employee(current_employee.id)
    return {"accounts": accounts}


@router.post("/select-account", summary="Select account to finalize connection")
def select_account(
    req: SelectAccountRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Finalize Basecamp OAuth with the employee's chosen account ID."""
    try:
        res = bc_service.select_account_for_employee(db, current_employee.id, req.account_id)
        log_activity(
            db=db,
            action="basecamp_connect",
            status="success",
            employee=current_employee,
            details={"account_id": req.account_id, "step": "account_selected"},
        )
        return res
    except ValueError as exc:
        log_activity(
            db=db,
            action="basecamp_connect",
            status="failure",
            employee=current_employee,
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        log_activity(
            db=db,
            action="basecamp_connect",
            status="failure",
            employee=current_employee,
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ---------------------------------------------------------------------------
# Basecamp Data Endpoints (Employee-Isolated Context)
# ---------------------------------------------------------------------------

@router.get("/identity", summary="Authenticated employee Basecamp identity")
async def basecamp_identity(
    current_employee: Employee = Depends(get_current_employee),
):
    """Fetch employee's Basecamp identity and accessible accounts."""
    try:
        return await bc_service.get_identity(employee_id=current_employee.id)
    except Exception as exc:
        return _format_error_response(exc)


@router.get("/projects", summary="List Basecamp projects")
async def basecamp_list_projects(
    current_employee: Employee = Depends(get_current_employee),
):
    """Return projects accessible to the employee using their own account_id."""
    try:
        projects = await bc_service.get_projects(employee_id=current_employee.id)
        return {"projects": projects, "count": len(projects)}
    except Exception as exc:
        return _format_error_response(exc)


@router.get("/projects/{project_id}", summary="Single Basecamp project details")
async def basecamp_get_project(
    project_id: int,
    current_employee: Employee = Depends(get_current_employee),
):
    try:
        return await bc_service.get_project(project_id, employee_id=current_employee.id)
    except Exception as exc:
        return _format_error_response(exc)


@router.get("/projects/{project_id}/messages", summary="Messages for a Basecamp project")
async def basecamp_list_messages(
    project_id: int,
    date: str | None = None,
    current_employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Return messages for a project using the employee's own account_id."""
    try:
        messages = await bc_service.get_messages(project_id, employee_id=current_employee.id, date=date)
        log_activity(
            db=db,
            action="project_select",
            status="success",
            employee=current_employee,
            project_id=project_id,
            details={"date_filter": date} if date else None,
        )
        if date and date.strip():
            target_date = date.strip()
            filtered = []
            for m in messages:
                raw_ts = (
                    m.get("created_at")
                    or (m.get("recording") or {}).get("created_at")
                    or (m.get("message") or {}).get("created_at")
                    or m.get("date")
                )
                _, article_date = normalize_timestamp_to_date(raw_ts)
                if article_date == target_date:
                    filtered.append(m)
            return {"messages": filtered, "count": len(filtered)}
        return {"messages": messages, "count": len(messages)}
    except Exception as exc:
        return _format_error_response(exc)


@router.get("/projects/{project_id}/messages/{message_id}", summary="Single Basecamp message details")
async def basecamp_get_message(
    project_id: int,
    message_id: int,
    current_employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Return full message body and attachments using employee's own account_id."""
    try:
        msg = await bc_service.get_message(project_id, message_id, employee_id=current_employee.id)
        log_activity(
            db=db,
            action="article_select",
            status="success",
            employee=current_employee,
            project_id=project_id,
            message_id=message_id,
            article_title=msg.get("subject") if isinstance(msg, dict) else None,
        )
        return msg
    except Exception as exc:
        return _format_error_response(exc)
