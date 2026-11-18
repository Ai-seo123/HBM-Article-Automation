from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Application
    APP_TITLE: str = "HBM Article Automation API"
    APP_VERSION: str = "0.1.0"

    # CORS — preserves local development and supports staging/production origins via env
    @property
    def ALLOWED_ORIGINS(self) -> list[str]:
        origins = [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
        ]
        extra = os.getenv("ALLOWED_ORIGINS", "")
        if extra:
            for item in extra.split(","):
                clean = item.strip().rstrip("/")
                if clean and clean not in origins:
                    origins.append(clean)
        frontend_url = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
        if frontend_url and frontend_url not in origins:
            origins.append(frontend_url)
        return origins

    # Basecamp OAuth 2.0
    BASECAMP_CLIENT_ID: str = os.getenv("BASECAMP_CLIENT_ID", "")
    BASECAMP_CLIENT_SECRET: str = os.getenv("BASECAMP_CLIENT_SECRET", "")
    BASECAMP_REDIRECT_URI: str = os.getenv(
        "BASECAMP_REDIRECT_URI",
        "http://localhost:8000/api/basecamp/callback",
    )
    BASECAMP_ACCOUNT_ID: str = os.getenv("BASECAMP_ACCOUNT_ID", "")

    # Security & Authentication
    TOKEN_ENCRYPTION_KEY: str = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "")
    ADMIN_INITIAL_PASSWORD: str = os.getenv("ADMIN_INITIAL_PASSWORD", "")
    RENDER_DISK_PATH: str = os.getenv("RENDER_DISK_PATH", "/var/data")

    # Gemini AI
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # WordPress REST API (Multi-Site and Legacy fallback)
    WORDPRESS_BASE_URL: str = os.getenv("WORDPRESS_BASE_URL", "")
    WORDPRESS_USERNAME: str = os.getenv("WORDPRESS_USERNAME", "")
    WORDPRESS_APP_PASSWORD: str = os.getenv("WORDPRESS_APP_PASSWORD", "")
    WORDPRESS_DEFAULT_AUTHOR: str = os.getenv("WORDPRESS_DEFAULT_AUTHOR", "pratiksha_dev")

    @property
    def WORDPRESS_SITES(self) -> list[dict]:
        """Return list of WordPress site configs from environment variables."""
        sites = []
        # Check indexed sites: WORDPRESS_SITE_1, WORDPRESS_SITE_2, etc.
        idx = 1
        while idx <= 20:
            name = os.getenv(f"WORDPRESS_SITE_{idx}_NAME")
            url = os.getenv(f"WORDPRESS_SITE_{idx}_URL")
            username = os.getenv(f"WORDPRESS_SITE_{idx}_USERNAME")
            app_password = os.getenv(f"WORDPRESS_SITE_{idx}_APP_PASSWORD")

            if url and username:
                sites.append({
                    "name": name or f"Site {idx}",
                    "url": url.strip().rstrip("/"),
                    "username": username.strip(),
                    "app_password": (app_password or "").strip(),
                    "is_default": (idx == 1),
                })
            idx += 1

        # Fallback to legacy single site if no multi-site env vars matched
        if not sites and self.WORDPRESS_BASE_URL and self.WORDPRESS_USERNAME:
            sites.append({
                "name": "EspialSolutions",
                "url": self.WORDPRESS_BASE_URL.strip().rstrip("/"),
                "username": self.WORDPRESS_USERNAME.strip(),
                "app_password": self.WORDPRESS_APP_PASSWORD.strip(),
                "is_default": True,
            })
        return sites

    # Image Providers Configuration
    # 1. Envato
    ENVATO_API_TOKEN: str = os.getenv("ENVATO_API_TOKEN", "")
    ENVATO_API_URL: str = os.getenv(
        "ENVATO_API_URL",
        "https://api.envato.com/v1/discovery/search/search/item",
    )
    ENVATO_SITE: str = os.getenv("ENVATO_SITE", "photodune.net")

    # 2. Magnific (AI Generation)
    MAGNIFIC_API_KEY: str = os.getenv("MAGNIFIC_API_KEY", "")
    MAGNIFIC_API_URL: str = os.getenv("MAGNIFIC_API_URL", "https://api.magnific.ai/v1")

    # 3. Dreamstime
    DREAMSTIME_API_KEY: str = os.getenv("DREAMSTIME_API_KEY", "")
    DREAMSTIME_API_SECRET: str = os.getenv("DREAMSTIME_API_SECRET", "")
    DREAMSTIME_API_URL: str = os.getenv("DREAMSTIME_API_URL", "https://www.dreamstime.com/api/")

    # 4. Unsplash
    UNSPLASH_ACCESS_KEY: str = os.getenv("UNSPLASH_ACCESS_KEY", "")
    UNSPLASH_API_URL: str = os.getenv("UNSPLASH_API_URL", "https://api.unsplash.com")

    # 5. Deposit Photos
    DEPOSITPHOTOS_API_KEY: str = os.getenv("DEPOSITPHOTOS_API_KEY", "")
    DEPOSITPHOTOS_API_SECRET: str = os.getenv("DEPOSITPHOTOS_API_SECRET", "")
    DEPOSITPHOTOS_API_URL: str = os.getenv("DEPOSITPHOTOS_API_URL", "https://api.depositphotos.com")

    # 6. Pexels
    PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")
    PEXELS_API_URL: str = os.getenv("PEXELS_API_URL", "https://api.pexels.com/v1")

    # 7. Calamari
    CALAMARI_API_KEY: str = os.getenv("CALAMARI_API_KEY", "")
    CALAMARI_API_URL: str = os.getenv("CALAMARI_API_URL", "")

    # Yoast Sidecar
    BCWP_SECRET: str = os.getenv("BCWP_SECRET", "")
    YOAST_SIDECAR_URL: str = os.getenv("YOAST_SIDECAR_URL", "")

    # Policy
    ALLOW_ARTICLES_WITHOUT_IMAGE: bool = os.getenv("ALLOW_ARTICLES_WITHOUT_IMAGE", "False").lower() == "true"

    def __post_init__(self):
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is not set.")


settings = Settings()
