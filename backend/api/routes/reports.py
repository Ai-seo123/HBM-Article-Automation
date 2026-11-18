"""
API routes for Workflow Reports history.
"""

from typing import Optional
from fastapi import APIRouter, Query, HTTPException

import services.report_service as report_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", summary="Get workflow reports history")
def get_reports(
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    project_id: Optional[int] = Query(None, description="Filter by Basecamp project ID"),
    status: Optional[str] = Query(None, description="Filter by status (all, completed, duplicate, error, warning)"),
    search: Optional[str] = Query(None, description="Search by article title, filename or project"),
    limit: int = Query(100, ge=1, le=500),
):
    """Retrieve filtered list of processing reports, newest first."""
    reports = report_service.list_reports(
        date=date,
        project_id=project_id,
        status=status,
        search=search,
        limit=limit,
    )
    return {"reports": reports}


@router.get("/{report_id}", summary="Get a single workflow report detail")
def get_report(report_id: int):
    """Retrieve full details of a specific report."""
    report = report_service.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report": report}
