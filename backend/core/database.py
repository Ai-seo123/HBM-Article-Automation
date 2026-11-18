import logging
import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from core.config import settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def _resolve_sqlite_path() -> str:
    """
    Resolve SQLite path with safe Render persistent disk migration support.
    If Render persistent disk is configured and mounted, safely migrates local database
    using SQLite online backup API, validates integrity, and atomically moves to persistent disk.
    Preserves all workflow reports, site configs, and employee records.
    """
    local_db_path = Path(__file__).resolve().parents[1] / "hbm_automation.db"
    render_disk_dir = Path(settings.RENDER_DISK_PATH) if settings.RENDER_DISK_PATH else None

    if render_disk_dir and render_disk_dir.is_dir():
        render_db_path = render_disk_dir / "hbm_automation.db"
        if not render_db_path.exists() and local_db_path.exists():
            log.info("Migrating SQLite database to Render persistent disk: %s -> %s", local_db_path, render_db_path)
            tmp_path = render_db_path.with_suffix(".db.tmp")
            try:
                import sqlite3
                src_conn = sqlite3.connect(str(local_db_path))
                dst_conn = sqlite3.connect(str(tmp_path))
                src_conn.backup(dst_conn)
                dst_conn.close()
                src_conn.close()

                # Integrity verification
                chk_conn = sqlite3.connect(str(tmp_path))
                status = chk_conn.execute("PRAGMA integrity_check;").fetchone()[0]
                chk_conn.close()

                if status != "ok":
                    if tmp_path.exists():
                        tmp_path.unlink()
                    raise RuntimeError(f"Render persistent disk SQLite migration integrity check failed: {status}")

                import os
                os.replace(str(tmp_path), str(render_db_path))
                log.info("Render persistent disk SQLite migration completed successfully. Integrity: %s", status)
            except Exception as exc:
                if tmp_path.exists():
                    tmp_path.unlink()
                log.error("Render persistent disk migration failed: %s", exc)
                raise RuntimeError(f"Render persistent disk migration failed: {exc}")

        return f"sqlite:///{render_db_path}"

    return f"sqlite:///{local_db_path}"


def _make_engine():
    """
    Create the SQLAlchemy engine.
    Supports PostgreSQL and SQLite. If PostgreSQL is configured but unreachable,
    falls back cleanly to local SQLite database so reports and site configs are persisted.
    """
    default_sqlite_url = _resolve_sqlite_path()
    db_url = settings.DATABASE_URL.strip() if settings.DATABASE_URL else ""

    if not db_url:
        db_url = default_sqlite_url

    # Normalize Render's postgres:// scheme to postgresql:// for SQLAlchemy
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    if db_url.startswith("sqlite"):
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False},
        )

    # Try PostgreSQL with short connect timeout
    try:
        eng = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            connect_args={"connect_timeout": 2},
        )
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return eng
    except Exception as exc:
        log.warning(
            "Configured PostgreSQL database unreachable (%s). Using local SQLite fallback: %s",
            exc, default_sqlite_url
        )
        return create_engine(
            default_sqlite_url,
            connect_args={"check_same_thread": False},
        )


engine = _make_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def get_db():
    """FastAPI dependency that provides a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

