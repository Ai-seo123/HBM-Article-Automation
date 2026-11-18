"""
Articles API routes.

POST /api/articles/process
  Orchestrates: Basecamp message fetch → DOCX extraction →
  duplicate check → Gemini AI processing.

Route handlers are kept thin — all logic is in services/article_processor.py.
"""

import logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from core.database import get_db
from schemas.article_processor import ProcessRequest, ProcessResponse
import services.article_processor as processor
import services.basecamp as bc_service
from services.auth_service import get_session_and_employee
from services.activity_logger import log_activity

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/articles", tags=["articles"])


@router.post(
    "/process",
    response_model=ProcessResponse,
    summary="Process a Basecamp Word attachment through the AI pipeline",
)
async def process_article(
    body: ProcessRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Run the full article processing pipeline for a selected Basecamp attachment.
    """
    session_id = request.cookies.get("espial_session")
    employee = None
    if session_id:
        _, employee = get_session_and_employee(db, session_id)
        if employee:
            bc_service.set_current_employee_id(employee.id)

    eff_session_id = body.session_id or processor._get_workflow_session_id(
        body.project_id, body.message_id, body.attachment_id
    )

    if body.resume_action == "approve_image":
        log_activity(
            db=db,
            action="image_approve",
            status="success",
            session_id=eff_session_id,
            employee=employee,
            project_id=body.project_id,
            message_id=body.message_id,
            author_id=body.author_id,
            site_id=body.site_id,
            details={
                "resume_action": body.resume_action,
                "candidate": body.selected_image_data.get("label") if body.selected_image_data else None,
            },
        )
    else:
        log_activity(
            db=db,
            action="workflow_start",
            status="success",
            session_id=eff_session_id,
            employee=employee,
            project_id=body.project_id,
            message_id=body.message_id,
            author_id=body.author_id,
            site_id=body.site_id,
            details={
                "author_id": body.author_id,
                "site_id": body.site_id,
                "image_provider": body.image_provider,
                "pause_at_image": body.pause_at_image,
            },
        )

    try:
        result = await processor.process(
            project_id=body.project_id,
            message_id=body.message_id,
            attachment_id=body.attachment_id,
            site_id=body.site_id,
            author_id=body.author_id,
            image_provider=body.image_provider,
            selected_image_data=body.selected_image_data,
            pause_at_image=body.pause_at_image,
            session_id=body.session_id,
            resume_action=body.resume_action,
            custom_content=body.custom_content,
            custom_seo=body.custom_seo,
            employee_id=employee.id if employee else None,
            employee_name=employee.full_name if employee else None,
            employee_email=employee.email if employee else None,
        )
        # Map plain dict to response model for validation
        return ProcessResponse(**result)
    except Exception as exc:
        # Catch-all — must not expose internal details or secrets
        log.error("Unhandled error in process_article: %s", type(exc).__name__)
        log_activity(
            db=db,
            action="workflow_failure",
            status="failure",
            session_id=eff_session_id,
            employee=employee,
            project_id=body.project_id,
            message_id=body.message_id,
            details={"error": f"Unhandled server error: {type(exc).__name__}"},
        )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": "An unexpected server error occurred. Please try again.",
                "duplicate": False,
                "unchecked_wp": False,
                "stages": [],
            },
        )
