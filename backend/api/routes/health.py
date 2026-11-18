from fastapi import APIRouter
from sqlalchemy import text
from core.database import engine

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def health_check():
    """Basic liveness check — always returns ok if the process is running."""
    return {"status": "ok"}


@router.get("/db")
def database_health_check():
    """
    Checks whether the PostgreSQL database is reachable.
    Returns a safe error message on failure — no credentials exposed.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "database": "unavailable"},
        )
