from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import engine, Base, get_db

# Import all models so SQLAlchemy registers them before create_all
import models.article  # noqa: F401
import models.wordpress_site  # noqa: F401
import models.report  # noqa: F401
import models.employee  # noqa: F401
import models.activity_log  # noqa: F401

from api.routes.health import router as health_router
from api.routes.auth import router as auth_router
from api.routes.basecamp import router as basecamp_router
from api.routes.articles import router as articles_router
from api.routes.wordpress_sites import router as wordpress_sites_router
from api.routes.reports import router as reports_router
from api.routes.images import router as images_router
from api.routes.qa import router as qa_router
from api.routes.wizard import router as wizard_router
from api.routes.activity_logs import router as activity_logs_router
import services.site_service as site_service


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_TITLE,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow Vite dev servers
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(basecamp_router)
    app.include_router(articles_router)
    app.include_router(wordpress_sites_router)
    app.include_router(reports_router)
    app.include_router(images_router)
    app.include_router(qa_router)
    app.include_router(wizard_router)
    app.include_router(activity_logs_router)

    from api.routes.auth import get_current_admin
    from api.routes.activity_logs import get_activity_employees

    @app.get("/api/admin/employees", tags=["Admin Activity Monitoring"])
    def admin_employees_alias(
        admin=Depends(get_current_admin),
        db=Depends(get_db),
    ):
        return get_activity_employees(admin=admin, db=db)

    @app.on_event("startup")
    def _create_tables():
        import logging
        from core.database import SessionLocal
        from services.auth_service import ensure_initial_admin
        try:
            Base.metadata.create_all(bind=engine)
            site_service.ensure_default_site()
            db = SessionLocal()
            try:
                ensure_initial_admin(db)
            finally:
                db.close()
            logging.getLogger(__name__).info("Database tables, default sites, and initial admin verified.")
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Could not initialize database on startup: %s.", exc
            )

    return app


app = create_app()

