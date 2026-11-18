"""
Admin-only Activity Monitoring and Auditing API routes.
Strictly guarded by RBAC: only users with role=admin may access these endpoints.
"""

from datetime import datetime, timezone
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from core.database import get_db
from models.employee import Employee
from api.routes.auth import get_current_admin
import services.activity_logger as act_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/activity", tags=["Admin Activity Monitoring"])


@router.get("/summary", summary="KPI Metrics and Recent Activities (Admin Only)")
def get_activity_summary(
    admin: Employee = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Retrieve activity metrics:
    - Total Employees
    - Active Accounts (is_active=True in DB)
    - Employees Logged In Today (Asia/Kolkata calendar day converted to UTC)
    - Articles Processed (successful distinct sessions)
    - WordPress Drafts Created (distinct post IDs)
    - Successful and Failed Workflows (mutually exclusive)
    - Recent Activities
    """
    return act_service.get_activity_summary(db)


@router.get("/logs", summary="Paginated Activity Logs with Filters (Admin Only)")
def get_activity_logs(
    employee_id: Optional[int] = Query(None, description="Filter by employee ID"),
    action: Optional[str] = Query(None, description="Filter by activity action"),
    status: Optional[str] = Query(None, description="Filter by status (success/failure)"),
    start_date: Optional[str] = Query(None, description="Filter by start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Keyword search across text fields"),
    q: Optional[str] = Query(None, description="Keyword search alias"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=5, le=100, description="Items per page"),
    limit: Optional[int] = Query(None, description="Alias for page_size"),
    admin: Employee = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Retrieve filtered, paginated audit logs."""
    effective_search = search or q
    effective_limit = limit or page_size or 25
    filters = {
        "employee_id": employee_id,
        "action": action,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "search": effective_search,
    }

    logs, total, total_pages = act_service.get_activity_logs(
        db,
        filters=filters,
        page=page,
        page_size=effective_limit,
    )

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": effective_limit,
        "limit": effective_limit,
        "total_pages": total_pages,
    }


@router.get("/export", summary="Export Activity Logs as CSV (Admin Only)")
def export_activity_logs(
    employee_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin: Employee = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Download filtered activity logs as a CSV file.
    All user-controlled text cells are protected against formula injection.
    """
    filters = {
        "employee_id": employee_id,
        "action": action,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "search": search,
    }

    csv_content = act_service.export_activity_logs_csv(db, filters)
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"activity_logs_{now_str}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.get("/types", summary="Distinct Activity Types (Admin Only)")
def get_activity_types(
    admin: Employee = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Retrieve list of distinct action names for dropdown filters."""
    types = act_service.get_distinct_action_types(db)
    return {"types": types, "action_types": types}


@router.get("/employees", summary="Filterable Employees List (Admin Only)")
def get_activity_employees(
    admin: Employee = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Retrieve list of all employees for activity log filtering:
    - Registered employees (active and inactive) from Employee model.
    - Historical employees present in ActivityLog records.
    """
    employees = db.query(Employee).order_by(Employee.id.asc()).all()
    emp_map = {e.id: e.to_safe_dict() for e in employees}

    historical = (
        db.query(
            act_service.ActivityLog.employee_id,
            act_service.ActivityLog.employee_name,
            act_service.ActivityLog.employee_email,
        )
        .filter(act_service.ActivityLog.employee_id.isnot(None))
        .distinct()
        .all()
    )
    for h_id, h_name, h_email in historical:
        if h_id not in emp_map:
            emp_map[h_id] = {
                "id": h_id,
                "email": h_email or f"user_{h_id}@unknown",
                "full_name": h_name or f"User #{h_id}",
                "role": "employee",
                "is_active": False,
                "has_activity": True,
            }

    result = list(emp_map.values())
    result.sort(key=lambda x: (not x.get("is_active", False), (x.get("full_name") or "").lower(), x.get("id")))

    return {
        "status": "success",
        "employees": result,
    }
