"""
Service for saving and retrieving workflow execution reports.
Reports are persistently stored in the database.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from core.database import SessionLocal
from core.date_utils import normalize_timestamp_to_date
from models.report import WorkflowReport

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def save_report(
    article_title: str,
    status: str,
    date_str: Optional[str] = None,
    filename: Optional[str] = None,
    project_id: Optional[int] = None,
    project_name: Optional[str] = None,
    message_id: Optional[int] = None,
    attachment_id: Optional[str] = None,
    wordpress_site_id: Optional[int] = None,
    wordpress_site_name: Optional[str] = None,
    wordpress_site_url: Optional[str] = None,
    wordpress_post_id: Optional[int] = None,
    draft_url: Optional[str] = None,
    edit_url: Optional[str] = None,
    author: Optional[str] = None,
    primary_category: Optional[str] = None,
    all_categories: Optional[list] = None,
    focus_keyphrase: Optional[str] = None,
    image_source: Optional[str] = None,
    image_source_url: Optional[str] = None,
    qa_status: Optional[str] = None,
    qa_checklist: Optional[dict] = None,
    details: Optional[dict] = None,
) -> dict:
    """Save a workflow run to the reports table."""
    db = SessionLocal()
    try:
        if not date_str:
            date_str = _utcnow().strftime("%Y-%m-%d")

        # Sanitize details to guarantee no sensitive credentials or tokens
        safe_details = dict(details or {})
        for token_key in ("access_token", "refresh_token", "app_password", "api_key", "secret"):
            safe_details.pop(token_key, None)

        report = WorkflowReport(
            date=date_str,
            article_title=article_title or "Untitled",
            filename=filename,
            project_id=project_id,
            project_name=project_name,
            message_id=message_id,
            attachment_id=attachment_id,
            status=status,
            wordpress_site_id=wordpress_site_id,
            wordpress_site_name=wordpress_site_name,
            wordpress_site_url=wordpress_site_url,
            wordpress_post_id=wordpress_post_id,
            draft_url=draft_url,
            edit_url=edit_url,
            author=author,
            primary_category=primary_category,
            all_categories=json.dumps(all_categories or []),
            focus_keyphrase=focus_keyphrase,
            image_source=image_source,
            image_source_url=image_source_url,
            qa_status=qa_status,
            qa_checklist=json.dumps(qa_checklist or {}),
            details=json.dumps(safe_details),
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        log.info("Saved workflow report #%s (status=%s, article=%r)", report.id, status, article_title)
        return report.to_dict()
    except Exception as exc:
        log.error("Failed to save workflow report: %s", exc)
        db.rollback()
        return {}
    finally:
        db.close()


def list_reports(
    date: Optional[str] = None,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieve filtered workflow reports, newest first."""
    db = SessionLocal()
    try:
        query = db.query(WorkflowReport)

        if project_id:
            query = query.filter(WorkflowReport.project_id == project_id)

        if status and status.lower() != "all":
            query = query.filter(WorkflowReport.status == status.lower().strip())

        if search and search.strip():
            search_pattern = f"%{search.strip()}%"
            query = query.filter(
                (WorkflowReport.article_title.ilike(search_pattern))
                | (WorkflowReport.filename.ilike(search_pattern))
                | (WorkflowReport.project_name.ilike(search_pattern))
            )

        if date and date.strip():
            target_date = date.strip()
            reports = query.order_by(WorkflowReport.created_at.desc(), WorkflowReport.id.desc()).all()
            filtered_reports = []
            for r in reports:
                raw_ts = r.created_at
                normalized_ts, report_execution_date = normalize_timestamp_to_date(raw_ts)
                match = (report_execution_date == target_date)
                log.info(
                    "REPORT_FILTER: SELECTED_REPORT_DATE=%s | RAW_TIMESTAMP=%s | NORMALIZED_TIMESTAMP=%s | REPORT_EXECUTION_DATE=%s | MATCH=%s | TITLE=%s",
                    target_date, raw_ts, normalized_ts, report_execution_date, match, r.article_title
                )
                safe_title = (r.article_title or "").encode("ascii", errors="replace").decode("ascii")
                print(
                    f"REPORT_FILTER: SELECTED_REPORT_DATE={target_date} | RAW_TIMESTAMP={raw_ts} | NORMALIZED_TIMESTAMP={normalized_ts} | REPORT_EXECUTION_DATE={report_execution_date} | MATCH={match} | TITLE={safe_title}",
                    flush=True
                )
                if match:
                    filtered_reports.append(r)
            return [r.to_dict() for r in filtered_reports[:limit]]

        reports = query.order_by(WorkflowReport.created_at.desc(), WorkflowReport.id.desc()).limit(limit).all()
        return [r.to_dict() for r in reports]
    finally:
        db.close()


def get_report(report_id: int) -> Optional[dict]:
    """Retrieve full details of a specific workflow report."""
    db = SessionLocal()
    try:
        report = db.query(WorkflowReport).filter(WorkflowReport.id == report_id).first()
        return report.to_dict() if report else None
    finally:
        db.close()
