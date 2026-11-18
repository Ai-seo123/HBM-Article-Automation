"""
API routes for the Step-by-Step Create Draft Wizard.

Endpoints:
  GET  /api/wizard/session   - Load or initialize persistent session
  POST /api/wizard/advance   - Advance or execute a specific stage
  POST /api/wizard/reset     - Reset session and clear stored state
"""

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query, Request, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
import services.wizard_service as wizard_service
import services.basecamp as bc_service
from services.auth_service import get_session_and_employee

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wizard", tags=["wizard"])


class WizardAdvanceRequest(BaseModel):
    project_id: int = Field(..., description="Basecamp project ID")
    message_id: int = Field(..., description="Basecamp message ID")
    attachment_id: str = Field(..., description="Attachment ID")
    site_id: Optional[int] = Field(default=None, description="WordPress site ID")
    target_stage: Optional[int] = Field(default=None, description="Target stage number (1-9)")
    action: Optional[str] = Field(default=None, description="Action such as 'approve_image' or 'create_draft'")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Payload containing user edits or choices")


class WizardResetRequest(BaseModel):
    project_id: int = Field(..., description="Basecamp project ID")
    message_id: int = Field(..., description="Basecamp message ID")
    attachment_id: str = Field(..., description="Attachment ID")


import copy

def _sanitize_session(session: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not session or not isinstance(session, dict):
        return session
    safe = copy.deepcopy(session)
    if "shared" in safe and isinstance(safe["shared"], dict):
        safe["shared"].pop("site_app_password", None)
        safe["shared"].pop("token", None)
    return safe


@router.get("/session", summary="Get or initialize wizard session")
async def get_session(
    request: Request,
    project_id: int = Query(...),
    message_id: int = Query(...),
    attachment_id: str = Query(...),
    site_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Retrieve current wizard state or initialize a new session.
    Persisted server-side to guarantee seamless resumption after browser refresh.
    """
    session_id = request.cookies.get("espial_session")
    if session_id:
        _, employee = get_session_and_employee(db, session_id)
        if employee:
            bc_service.set_current_employee_id(employee.id)

    try:
        session = wizard_service.get_or_create_session(
            project_id=project_id,
            message_id=message_id,
            attachment_id=str(attachment_id),
            site_id=site_id,
        )
        return _sanitize_session(session)
    except Exception as exc:
        log.error("Failed to load wizard session: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/advance", summary="Advance wizard or run a stage")
async def advance_stage(
    req: WizardAdvanceRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Advance through the 9-stage wizard with genuine review and approval gates.
    Stage 6 requires explicit user action='approve_image'.
    Stage 7 requires explicit user action='create_draft' (zero draft creation before Step 7 approval).
    """
    session_id = request.cookies.get("espial_session")
    if session_id:
        _, employee = get_session_and_employee(db, session_id)
        if employee:
            bc_service.set_current_employee_id(employee.id)

    try:
        session = await wizard_service.advance_wizard(
            project_id=req.project_id,
            message_id=req.message_id,
            attachment_id=str(req.attachment_id),
            site_id=req.site_id,
            target_stage=req.target_stage,
            action=req.action,
            payload=req.payload,
        )
        return _sanitize_session(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("Wizard advance error at stage %s: %s", req.target_stage, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/reset", summary="Reset wizard session")
async def reset_session(req: WizardResetRequest):
    """
    Clear stored wizard session to start from stage 1.
    """
    success = wizard_service.reset_session(
        project_id=req.project_id,
        message_id=req.message_id,
        attachment_id=str(req.attachment_id),
    )
    return {"status": "ok", "reset": success}
