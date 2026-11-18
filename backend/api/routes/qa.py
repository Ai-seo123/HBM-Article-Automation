"""
API routes for Authoritative 10-Category QA Engine.
Strictly read-only with zero WordPress mutations.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
import services.qa_engine as qa_engine
import services.site_service as site_service
from services.auth_service import get_session_and_employee
from services.activity_logger import log_activity

router = APIRouter(prefix="/api/qa", tags=["qa-engine"])


class QARunRequest(BaseModel):
    site_id: int = Field(..., description="ID of destination WordPress site in database")
    post_id: int = Field(..., description="WordPress Post ID of draft to audit")
    docx_source: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional source DOCX configuration (none, basecamp, external)",
    )
    client_instructions: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional parsed client instructions (author, tags, overrides)",
    )


@router.post("/run", summary="Run Authoritative 10-Category Read-Only QA Engine")
async def run_qa_audit(
    request: QARunRequest,
    http_request: Request,
    db: Session = Depends(get_db),
):
    """
    Execute authoritative 10-category read-only QA audit against WordPress draft.
    Zero WordPress writes guaranteed.
    """
    employee = None
    session_id = http_request.cookies.get("espial_session")
    if session_id:
        _, employee = get_session_and_employee(db, session_id)

    site = site_service.get_site(request.site_id)
    if not site:
        raise HTTPException(status_code=404, detail="WordPress destination site not found")

    try:
        results = await qa_engine.run_comprehensive_qa(
            site_id=request.site_id,
            post_id=request.post_id,
            docx_source=request.docx_source,
            client_instructions=request.client_instructions,
        )
        is_passed = results.get("status") == "passed"
        log_activity(
            db=db,
            action="qa_audit",
            status="success" if is_passed else "failure",
            employee=employee,
            site_id=request.site_id,
            post_id=request.post_id,
            details={
                "passed": is_passed,
                "score": results.get("score"),
                "total_checks": results.get("total_checks"),
                "passed_checks": results.get("passed_checks"),
                "failed_checks": results.get("failed_checks"),
            },
        )
        return results
    except ValueError as exc:
        log_activity(
            db=db,
            action="qa_audit",
            status="failure",
            employee=employee,
            site_id=request.site_id,
            post_id=request.post_id,
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log_activity(
            db=db,
            action="qa_audit",
            status="failure",
            employee=employee,
            site_id=request.site_id,
            post_id=request.post_id,
            details={"error": f"QA audit execution failed: {str(exc)}"},
        )
        raise HTTPException(status_code=500, detail=f"QA audit execution failed: {str(exc)}")
