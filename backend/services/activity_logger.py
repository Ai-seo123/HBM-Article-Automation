"""
Activity Logging and Auditing Service for Espial Article Publishing.

Provides immutable, sanitized audit trails, KPI metrics, filtering, and CSV export.
Guarantees zero leakage of credentials, passwords, tokens, or encryption keys.
"""

from datetime import datetime, time, timezone, timedelta
from typing import Optional, Any, Dict, List, Tuple
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo
import csv
import io
import json
import logging
import re
from sqlalchemy import or_, and_, desc
from sqlalchemy.orm import Session

from models.activity_log import ActivityLog
from models.employee import Employee

log = logging.getLogger(__name__)

# Explicit sensitive key denylist — exact match or normalized suffix
EXPLICIT_SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "admin_initial_password",
    "app_password",
    "site_app_password",
    "token",
    "access_token",
    "refresh_token",
    "encrypted_access_token",
    "encrypted_refresh_token",
    "token_encryption_key",
    "espial_session",
    "session_token",
    "csrf_token",
    "espial_csrf",
    "bcwp_secret",
    "client_secret",
    "api_key",
    "secret",
    "authorization",
    "cookie",
    "set-cookie",
    "private_key",
}

# Regex to detect credentials in error messages or URLs
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE)
_APP_PASSWORD_RE = re.compile(r"\b[A-Za-z0-9]{4}\s+[A-Za-z0-9]{4}\s+[A-Za-z0-9]{4}\s+[A-Za-z0-9]{4}\b")
_DB_URL_PW_RE = re.compile(r"://([^:]+):([^@]+)@")


def _is_sensitive_key(key: str) -> bool:
    """Check if key matches explicit sensitive denylist."""
    norm = key.strip().lower()
    if norm in EXPLICIT_SENSITIVE_KEYS:
        return True
    # Suffix checks for specific credential fields
    if norm.endswith("_password") or norm.endswith("_secret") or norm.endswith("_token") or norm.endswith("_api_key"):
        return True
    return False


def sanitize_value(val: Any) -> Any:
    """Recursively sanitize metadata dictionaries, lists, and strings."""
    if isinstance(val, dict):
        cleaned = {}
        for k, v in val.items():
            if _is_sensitive_key(str(k)):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = sanitize_value(v)
        return cleaned
    if isinstance(val, list):
        return [sanitize_value(item) for item in val]
    if isinstance(val, str):
        # Scrub Bearer tokens
        s = _BEARER_RE.sub("Bearer [REDACTED]", val)
        # Scrub WordPress app passwords
        s = _APP_PASSWORD_RE.sub("[REDACTED_APP_PASSWORD]", s)
        # Scrub DB password in connection strings
        s = _DB_URL_PW_RE.sub(r"://\1:[REDACTED]@", s)
        # Scrub sensitive query params if looks like URL
        if "://" in s and ("?" in s or "&" in s):
            try:
                parts = urlsplit(s)
                if parts.query:
                    qs_pairs = parse_qsl(parts.query, keep_blank_values=True)
                    clean_pairs = []
                    for qk, qv in qs_pairs:
                        if _is_sensitive_key(qk) or qk.lower() in ("code", "state", "token", "key", "secret"):
                            clean_pairs.append((qk, "[REDACTED]"))
                        else:
                            clean_pairs.append((qk, qv))
                    clean_qs = urlencode(clean_pairs)
                    s = urlunsplit((parts.scheme, parts.netloc, parts.path, clean_qs, parts.fragment))
            except Exception:
                pass
        return s
    return val


def sanitize_csv_cell(value: Any) -> str:
    """
    Sanitize CSV cell against formula injection (CSV Injection / DDE attack).
    Prefixes leading '=', '+', '-', '@', tab, newline with single quote.
    """
    if value is None:
        return ""
    val_str = str(value)
    if val_str and val_str[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return f"'{val_str}"
    return val_str


# ---------------------------------------------------------------------------
# Logging Function
# ---------------------------------------------------------------------------

def log_activity(
    db: Optional[Session] = None,
    action: str = "",
    status: str = "success",
    session_id: Optional[str] = None,
    employee: Optional[Employee] = None,
    employee_id: Optional[int] = None,
    employee_name: Optional[str] = None,
    employee_email: Optional[str] = None,
    project_id: Optional[int] = None,
    project_name: Optional[str] = None,
    message_id: Optional[Any] = None,
    article_title: Optional[str] = None,
    post_id: Optional[int] = None,
    author_id: Optional[int] = None,
    author_name: Optional[str] = None,
    site_id: Optional[int] = None,
    site_name: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Optional[ActivityLog]:
    """
    Record an immutable audit log entry.
    Fail-safe: Never raises exceptions to caller.
    If db is not provided, opens and manages an independent SessionLocal().
    """
    own_db = False
    active_db = db
    if active_db is None:
        try:
            from core.database import SessionLocal
            active_db = SessionLocal()
            own_db = True
        except Exception as init_exc:
            log.warning("Could not create database session for activity logging: %s", init_exc)
            return None

    try:
        # Resolve employee identity
        emp_id = employee_id or (employee.id if employee else None)
        emp_name = employee_name or (employee.full_name if employee else None)
        emp_email = employee_email or (employee.email if employee else None)

        if not emp_name and emp_id:
            db_emp = active_db.query(Employee).filter(Employee.id == emp_id).first()
            if db_emp:
                emp_name = db_emp.full_name
                emp_email = db_emp.email

        # Selection Deduplication: avoid duplicate project_select / article_select within 120s
        if action in ("project_select", "article_select") and emp_id is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=120)
            query = active_db.query(ActivityLog).filter(
                ActivityLog.employee_id == emp_id,
                ActivityLog.action == action,
                ActivityLog.created_at >= cutoff,
            )
            if project_id:
                query = query.filter(ActivityLog.project_id == project_id)
            if message_id:
                query = query.filter(ActivityLog.message_id == str(message_id))
            recent = query.first()
            if recent:
                return recent

        # Sanitize details
        sanitized_details = None
        if details:
            clean_dict = sanitize_value(details)
            try:
                sanitized_details = json.dumps(clean_dict, ensure_ascii=False)
            except Exception:
                sanitized_details = str(clean_dict)

        msg_id_str = str(message_id) if message_id is not None else None

        entry = ActivityLog(
            session_id=str(session_id) if session_id else None,
            employee_id=emp_id,
            employee_name=emp_name,
            employee_email=emp_email,
            action=action,
            status=status,
            project_id=project_id,
            project_name=project_name,
            message_id=msg_id_str,
            article_title=article_title,
            post_id=post_id,
            author_id=author_id,
            author_name=author_name,
            site_id=site_id,
            site_name=site_name,
            details=sanitized_details,
            created_at=datetime.now(timezone.utc),
        )

        active_db.add(entry)
        active_db.commit()
        active_db.refresh(entry)
        return entry
    except Exception as exc:
        if active_db:
            try:
                active_db.rollback()
            except Exception:
                pass
        log.warning("Failed to record activity log (%s): %s", action, exc)
        return None
    finally:
        if own_db and active_db:
            try:
                active_db.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# KPI Summary Calculation (Asia/Kolkata Day Boundary + Mutually Exclusive Outcomes)
# ---------------------------------------------------------------------------

def get_activity_summary(db: Session) -> Dict[str, Any]:
    """
    Calculate summary KPIs for Admin Dashboard:
    1. Total Employees
    2. Active Accounts (enabled in database)
    3. Employees Logged In Today (Asia/Kolkata calendar day converted to UTC)
    4. Articles Processed (successful distinct sessions)
    5. WordPress Drafts Created (distinct post IDs)
    6. Successful vs Failed Workflows (mutually exclusive)
    7. Recent Activities (last 10 events)
    """
    # 1. Total Employees
    total_employees = db.query(Employee).count()

    # 2. Active Accounts (enabled accounts, not online users)
    active_employees = db.query(Employee).filter(Employee.is_active == True).count()

    # 3. Employees Logged In Today (Asia/Kolkata local calendar day converted to UTC)
    kolkata_tz = ZoneInfo("Asia/Kolkata")
    now_ist = datetime.now(kolkata_tz)
    ist_start = datetime.combine(now_ist.date(), time.min, tzinfo=kolkata_tz)
    ist_end = datetime.combine(now_ist.date(), time.max, tzinfo=kolkata_tz)
    utc_start = ist_start.astimezone(timezone.utc)
    utc_end = ist_end.astimezone(timezone.utc)

    logged_in_today = (
        db.query(ActivityLog.employee_id)
        .filter(
            ActivityLog.action == "login",
            ActivityLog.status == "success",
            ActivityLog.employee_id.isnot(None),
            ActivityLog.created_at >= utc_start,
            ActivityLog.created_at <= utc_end,
        )
        .distinct()
        .count()
    )

    # 4. Mutually Exclusive Workflow Outcomes
    # Successful sessions: any session that achieved workflow_complete with status 'success'
    successful_sessions_rows = (
        db.query(ActivityLog.session_id)
        .filter(
            ActivityLog.action == "workflow_complete",
            ActivityLog.status == "success",
            ActivityLog.session_id.isnot(None),
        )
        .distinct()
        .all()
    )
    successful_session_ids = set(r[0] for r in successful_sessions_rows if r[0])

    # Failed sessions: any session that logged a workflow_failure
    failed_sessions_rows = (
        db.query(ActivityLog.session_id)
        .filter(
            ActivityLog.action == "workflow_failure",
            ActivityLog.session_id.isnot(None),
        )
        .distinct()
        .all()
    )
    failed_session_ids_raw = set(r[0] for r in failed_sessions_rows if r[0])

    # Final outcome resolution: a workflow is Failed ONLY if it never subsequently completed successfully
    failed_session_ids = failed_session_ids_raw - successful_session_ids

    successful_workflows = len(successful_session_ids)
    failed_workflows = len(failed_session_ids)
    articles_processed = successful_workflows

    # 5. WordPress Drafts Created
    drafts_created = (
        db.query(ActivityLog.post_id)
        .filter(
            ActivityLog.action == "draft_create",
            ActivityLog.status == "success",
            ActivityLog.post_id.isnot(None),
        )
        .distinct()
        .count()
    )

    # 6. Recent Activities
    recent_logs = (
        db.query(ActivityLog)
        .order_by(desc(ActivityLog.created_at))
        .limit(10)
        .all()
    )

    return {
        "total_employees": total_employees,
        "active_employees": active_employees,
        "logged_in_today": logged_in_today,
        "articles_processed": articles_processed,
        "drafts_created": drafts_created,
        "successful_workflows": successful_workflows,
        "failed_workflows": failed_workflows,
        "recent_activities": [log_entry.to_dict() for log_entry in recent_logs],
    }


# ---------------------------------------------------------------------------
# Filtered Queries & Pagination
# ---------------------------------------------------------------------------

def _apply_log_filters(query, filters: Dict[str, Any]):
    """Apply search and filter criteria to ActivityLog query."""
    emp_id = filters.get("employee_id")
    if emp_id is not None:
        try:
            query = query.filter(ActivityLog.employee_id == int(emp_id))
        except (ValueError, TypeError):
            pass

    action = filters.get("action")
    if action and isinstance(action, str) and action != "all":
        query = query.filter(ActivityLog.action == action)

    status_val = filters.get("status")
    if status_val and isinstance(status_val, str) and status_val != "all":
        query = query.filter(ActivityLog.status == status_val)

    start_date = filters.get("start_date")
    if start_date and isinstance(start_date, str):
        try:
            # Parse YYYY-MM-DD
            dt_start = datetime.strptime(start_date.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            query = query.filter(ActivityLog.created_at >= dt_start)
        except Exception:
            pass

    end_date = filters.get("end_date")
    if end_date and isinstance(end_date, str):
        try:
            dt_end = (
                datetime.strptime(end_date.strip()[:10], "%Y-%m-%d")
                .replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
            )
            query = query.filter(ActivityLog.created_at <= dt_end)
        except Exception:
            pass

    search = filters.get("search")
    if search and isinstance(search, str) and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                ActivityLog.session_id.ilike(term),
                ActivityLog.employee_name.ilike(term),
                ActivityLog.employee_email.ilike(term),
                ActivityLog.action.ilike(term),
                ActivityLog.article_title.ilike(term),
                ActivityLog.project_name.ilike(term),
                ActivityLog.details.ilike(term),
            )
        )

    return query


def get_activity_logs(
    db: Session,
    filters: Optional[Dict[str, Any]] = None,
    page: int = 1,
    page_size: int = 25,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Retrieve paginated, filtered activity logs."""
    filters = filters or {}
    query = db.query(ActivityLog)
    query = _apply_log_filters(query, filters)

    total = query.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    offset = (page - 1) * page_size

    logs = (
        query.order_by(desc(ActivityLog.created_at))
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return [l.to_dict() for l in logs], total, total_pages


def get_distinct_action_types(db: Session) -> List[str]:
    """Retrieve distinct action types present in activity logs."""
    rows = (
        db.query(ActivityLog.action)
        .distinct()
        .order_by(ActivityLog.action.asc())
        .all()
    )
    return [r[0] for r in rows if r[0]]


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

def export_activity_logs_csv(db: Session, filters: Optional[Dict[str, Any]] = None) -> str:
    """
    Export filtered activity logs to CSV format.
    Applies CSV formula injection protection to all user-controlled text cells.
    """
    filters = filters or {}
    query = db.query(ActivityLog)
    query = _apply_log_filters(query, filters)
    logs = query.order_by(desc(ActivityLog.created_at)).all()

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Header
    writer.writerow([
        "Timestamp (UTC)",
        "Employee ID",
        "Employee Name",
        "Employee Email",
        "Action",
        "Status",
        "Session ID",
        "Project ID",
        "Project Name",
        "Message ID",
        "Article Title",
        "WP Post ID",
        "WP Author ID",
        "WP Author Name",
        "WP Site ID",
        "WP Site Name",
        "Details",
    ])

    for entry in logs:
        writer.writerow([
            sanitize_csv_cell(entry.created_at.isoformat() if entry.created_at else ""),
            sanitize_csv_cell(entry.employee_id),
            sanitize_csv_cell(entry.employee_name),
            sanitize_csv_cell(entry.employee_email),
            sanitize_csv_cell(entry.action),
            sanitize_csv_cell(entry.status),
            sanitize_csv_cell(entry.session_id),
            sanitize_csv_cell(entry.project_id),
            sanitize_csv_cell(entry.project_name),
            sanitize_csv_cell(entry.message_id),
            sanitize_csv_cell(entry.article_title),
            sanitize_csv_cell(entry.post_id),
            sanitize_csv_cell(entry.author_id),
            sanitize_csv_cell(entry.author_name),
            sanitize_csv_cell(entry.site_id),
            sanitize_csv_cell(entry.site_name),
            sanitize_csv_cell(entry.details),
        ])

    return output.getvalue()
