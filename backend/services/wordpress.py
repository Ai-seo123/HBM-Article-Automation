"""
WordPress REST API service.

Security:
  - Uses WordPress Application Password (never a user account password).
  - Credentials are read from server-side configuration or database.
  - Never exposed or returned to the frontend.
  - Posts are ALWAYS created as DRAFT ONLY. Never published.
"""

import asyncio
import html
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

from core.config import settings

log = logging.getLogger(__name__)

# Global cache of anti-bot challenge cookies (e.g. host-level challenge cookies)
_WP_COOKIES: dict[str, str] = {
    "humans_21909": "1",
}

DEFAULT_WP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def is_configured(
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> bool:
    """Return True if WordPress connection details are present."""
    url = site_url or settings.WORDPRESS_BASE_URL
    user = username or settings.WORDPRESS_USERNAME
    pwd = app_password or settings.WORDPRESS_APP_PASSWORD
    return bool(url and user and pwd)


def _base_url(site_url: Optional[str] = None) -> str:
    """Normalised base URL — no trailing slash."""
    url = site_url or settings.WORDPRESS_BASE_URL or "https://espialsolutions.com"
    return url.strip().rstrip("/")


def _get_auth(
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> tuple[str, str]:
    """Get basic auth tuple."""
    return (
        username or settings.WORDPRESS_USERNAME,
        app_password or settings.WORDPRESS_APP_PASSWORD,
    )


# ---------------------------------------------------------------------------
# HTTP request helper with anti-bot challenge solving
# ---------------------------------------------------------------------------

def _extract_challenge_cookie(html_or_text: str) -> Optional[tuple[str, str]]:
    """Extract cookie name and value from anti-bot JS challenges like document.cookie='name=val'."""
    if not html_or_text:
        return None
    m = re.search(r'document\.cookie\s*=\s*["\']([^"\'=]+)=([^;"\']+)["\']', html_or_text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None


def _get_wp_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient configured for WordPress REST API with anti-bot cookies."""
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=DEFAULT_WP_HEADERS,
        cookies=_WP_COOKIES,
    )


async def _wp_request(
    method: str,
    url: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    auth: Optional[tuple] = None,
    headers: Optional[dict] = None,
    timeout: float = 30.0,
    max_retries: int = 3,
    **kwargs,
) -> httpx.Response:
    """
    Execute an HTTP request against WordPress with automatic anti-bot challenge handling and retry logic.
    If an HTTP 409 or JS challenge is encountered, it learns the cookie and retries once.
    Transient connection or timeout errors are retried up to max_retries times with backoff.
    """
    merged_headers = dict(DEFAULT_WP_HEADERS)
    if headers:
        merged_headers.update(headers)

    owns_client = client is None
    c = client or _get_wp_client(timeout=timeout)

    last_exc = None
    try:
        for attempt in range(1, max_retries + 1):
            try:
                resp = await c.request(method, url, auth=auth, headers=merged_headers, **kwargs)

                # Check for 409 or anti-bot challenge page
                if resp.status_code == 409 or "document.cookie" in resp.text:
                    challenge = _extract_challenge_cookie(resp.text)
                    if challenge:
                        c_name, c_val = challenge
                        log.info("WordPress anti-bot challenge detected — setting cookie %s=%s", c_name, c_val)
                        _WP_COOKIES[c_name] = c_val
                        c.cookies.set(c_name, c_val)

                        # Retry the request with the new cookie
                        resp = await c.request(method, url, auth=auth, headers=merged_headers, **kwargs)

                return resp
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = exc
                log.warning("WordPress request %s %s attempt %d/%d failed: %s", method, url, attempt, max_retries, exc)
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * attempt)
        if last_exc:
            raise last_exc
        raise RuntimeError(f"WordPress request {method} {url} failed after {max_retries} attempts.")
    finally:
        if owns_client:
            await c.aclose()


# ---------------------------------------------------------------------------
# Title normalisation
# ---------------------------------------------------------------------------

def _normalize_title(title: str) -> str:
    """
    Comprehensive normalisation for title comparison across WordPress and local DOCX:
    - Decodes HTML entities (e.g. &#8217;, &amp;, &quot;, &#038;)
    - Normalizes typographic/curly quotes and apostrophes to standard ASCII
    - Normalizes typographic dashes/hyphens to standard ASCII hyphen
    - Collapses multiple whitespace
    """
    if not title:
        return ""
    t = html.unescape(title)
    t = (
        t.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u00a0", " ")
    )
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


# ---------------------------------------------------------------------------
# WordPress REST API verification
# ---------------------------------------------------------------------------

async def verify_auth(
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> bool:
    """
    Verify WordPress REST API authentication by checking /users/me.
    Returns True if valid, False if 401/403 or unavailable.
    """
    if not is_configured(site_url, username, app_password):
        return False

    url = f"{_base_url(site_url)}/wp-json/wp/v2/users/me"
    auth = _get_auth(username, app_password)

    try:
        resp = await _wp_request("GET", url, auth=auth)
        if resp.status_code in (401, 403):
            log.error("WordPress authentication failed: HTTP %s", resp.status_code)
            return False
        resp.raise_for_status()
        return True
    except Exception as exc:
        log.error("WordPress auth check failed: %s", exc)
        return False


async def _wp_search_posts(
    search_term: str,
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> list[dict]:
    """
    Call the WordPress REST API to search posts by title/content.
    """
    url = f"{_base_url(site_url)}/wp-json/wp/v2/posts"
    params = {
        "search": search_term,
        "per_page": 5,       # small page — we only need to know if 1 exists
        "status": "any",     # check drafts and published
        "_fields": "id,title,link,status",
    }
    auth = _get_auth(username, app_password)

    try:
        resp = await _wp_request("GET", url, params=params, auth=auth)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        log.error(
            "WordPress API error %s: %s",
            exc.response.status_code, exc.response.text[:200],
        )
        raise RuntimeError(
            f"WordPress returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.RequestError as exc:
        log.error("WordPress request error: %s", exc)
        raise RuntimeError(
            "Could not reach the WordPress REST API."
        ) from exc


async def list_drafts(
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
    per_page: int = 20,
) -> list[dict]:
    """
    Fetch existing draft posts from WordPress via read-only GET request.
    Returns sanitized post records with id, title, slug, date, link, and status.
    """
    url = f"{_base_url(site_url)}/wp-json/wp/v2/posts"
    params = {
        "status": "draft",
        "per_page": min(per_page, 50),
        "context": "edit",
        "_fields": "id,title,slug,date,modified,link,status,author,featured_media",
    }
    auth = _get_auth(username, app_password)
    try:
        resp = await _wp_request("GET", url, params=params, auth=auth)
        resp.raise_for_status()
        raw_posts = resp.json()
        drafts = []
        for p in raw_posts:
            raw_t = p.get("title", {})
            title_str = raw_t.get("raw") or raw_t.get("rendered") if isinstance(raw_t, dict) else str(raw_t)
            drafts.append({
                "id": p.get("id"),
                "title": html.unescape(title_str or "Untitled"),
                "slug": p.get("slug"),
                "date": p.get("date"),
                "modified": p.get("modified"),
                "link": p.get("link"),
                "status": p.get("status"),
                "author": p.get("author"),
                "featured_media": p.get("featured_media"),
            })
        return drafts
    except httpx.HTTPStatusError as exc:
        log.error("Failed to list drafts: HTTP %s", exc.response.status_code)
        raise RuntimeError(f"WordPress returned HTTP {exc.response.status_code}.") from exc
    except httpx.RequestError as exc:
        log.error("Network error while listing drafts: %s", exc)
        raise RuntimeError("Could not reach WordPress to list drafts.") from exc


async def get_post(
    post_id: int,
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> dict:
    """Fetch a single post from WordPress via read-only GET request."""
    url = f"{_base_url(site_url)}/wp-json/wp/v2/posts/{post_id}"
    params = {"context": "edit"}
    auth = _get_auth(username, app_password)
    resp = await _wp_request("GET", url, params=params, auth=auth)
    resp.raise_for_status()
    return resp.json()


async def get_media(
    media_id: int,
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> dict:
    """Fetch media metadata from WordPress via read-only GET request."""
    url = f"{_base_url(site_url)}/wp-json/wp/v2/media/{media_id}"
    params = {"context": "edit"}
    auth = _get_auth(username, app_password)
    resp = await _wp_request("GET", url, params=params, auth=auth)
    resp.raise_for_status()
    return resp.json()


async def get_categories(
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> list[dict]:
    """Fetch categories from WordPress via read-only GET request."""
    url = f"{_base_url(site_url)}/wp-json/wp/v2/categories"
    params = {"per_page": 100, "context": "view"}
    auth = _get_auth(username, app_password)
    try:
        resp = await _wp_request("GET", url, params=params, auth=auth)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("Could not fetch categories: %s", exc)
        return []


async def get_user(
    user_id: int,
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> dict:
    """Fetch author/user details from WordPress via read-only GET request."""
    url = f"{_base_url(site_url)}/wp-json/wp/v2/users/{user_id}"
    params = {"context": "view"}
    auth = _get_auth(username, app_password)
    try:
        resp = await _wp_request("GET", url, params=params, auth=auth)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("Could not fetch user %s: %s", user_id, exc)
        return {}


# ---------------------------------------------------------------------------
# Public duplicate-check API
# ---------------------------------------------------------------------------

async def check_duplicate(
    title: str,
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> dict:
    """
    Check whether a post with the given title already exists on WordPress.
    """
    if not title or not title.strip():
        return {
            "duplicate": False,
            "unchecked": True,
            "reason": "Article title is empty — cannot check for duplicate.",
            "existing_post": None,
        }

    if not is_configured(site_url, username, app_password):
        log.info("WordPress not configured — skipping duplicate check.")
        return {
            "duplicate": False,
            "unchecked": True,
            "reason": "WordPress site is not configured with credentials.",
            "existing_post": None,
        }

    is_auth = await verify_auth(site_url, username, app_password)
    if not is_auth:
        log.warning("WordPress duplicate check: authentication failed.")
        return {
            "duplicate": False,
            "unchecked": True,
            "reason": "WordPress authentication failed. Please check your credentials.",
            "existing_post": None,
        }

    normalised = _normalize_title(title)
    log.info("Checking WordPress for duplicate title: %r on %s", title, _base_url(site_url))

    try:
        posts = await _wp_search_posts(title, site_url, username, app_password)
    except RuntimeError as exc:
        log.warning("Duplicate check failed: %s", exc)
        return {
            "duplicate": False,
            "unchecked": True,
            "reason": str(exc),
            "existing_post": None,
        }

    for post in posts:
        raw_post_title = post.get("title", {})
        if isinstance(raw_post_title, dict):
            post_title_str = raw_post_title.get("rendered", "")
        else:
            post_title_str = str(raw_post_title)

        if _normalize_title(post_title_str) == normalised:
            post_id = post.get("id")
            base = _base_url(site_url)
            edit_url = f"{base}/wp-admin/post.php?post={post_id}&action=edit" if post_id else post.get("link", "")
            log.info("Duplicate found: WP post id=%s title=%r", post_id, post_title_str)
            return {
                "duplicate": True,
                "unchecked": False,
                "reason": None,
                "existing_post": {
                    "id": post_id,
                    "title": post_title_str,
                    "url": edit_url or post.get("link", ""),
                    "status": post.get("status", ""),
                },
            }

    log.info("No duplicate found for title: %r", title)
    return {
        "duplicate": False,
        "unchecked": False,
        "reason": None,
        "existing_post": None,
    }


# ---------------------------------------------------------------------------
# Category helpers
# ---------------------------------------------------------------------------

async def _get_or_create_category(
    name: str,
    auth: tuple,
    site_url: Optional[str] = None,
) -> Optional[int]:
    """Look up a WordPress category by name or create it."""
    if not name or not name.strip():
        return None

    url = f"{_base_url(site_url)}/wp-json/wp/v2/categories"
    params = {"search": name, "per_page": 10, "_fields": "id,name,slug"}

    try:
        resp = await _wp_request("GET", url, params=params, auth=auth)
        resp.raise_for_status()
        cats = resp.json()
        for cat in cats:
            if cat.get("name", "").lower() == name.lower():
                log.info("Category found: %r → id=%s", name, cat["id"])
                return cat["id"]
    except Exception as exc:
        log.warning("Category lookup failed for %r: %s", name, exc)

    try:
        resp = await _wp_request(
            "POST",
            url,
            json={"name": name},
            auth=auth,
        )
        resp.raise_for_status()
        data = resp.json()
        cat_id = data.get("id")
        log.info("Category created: %r → id=%s", name, cat_id)
        return cat_id
    except Exception as exc:
        log.warning("Category creation failed for %r: %s", name, exc)
        return None


async def _get_featured_category_id(
    auth: tuple,
    site_url: Optional[str] = None,
) -> Optional[int]:
    """Look up the 'Featured' category ID."""
    url = f"{_base_url(site_url)}/wp-json/wp/v2/categories"
    params = {"search": "Featured", "per_page": 10, "_fields": "id,name"}
    try:
        resp = await _wp_request("GET", url, params=params, auth=auth)
        resp.raise_for_status()
        cats = resp.json()
        for cat in cats:
            if cat.get("name", "").lower() == "featured":
                return cat["id"]
    except Exception as exc:
        log.warning("Featured category lookup failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
async def get_site_authors(
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> list[dict]:
    """
    Fetch available authors dynamically from the configured WordPress site.
    Never hardcodes author names. Calls /wp-json/wp/v2/users.
    """
    auth = _get_auth(username, app_password)
    base = _base_url(site_url)
    url = f"{base}/wp-json/wp/v2/users"

    try:
        resp = await _wp_request("GET", url, params={"context": "edit", "per_page": 100}, auth=auth)
        if resp.status_code == 200:
            users = resp.json()
            return [
                {
                    "id": u["id"],
                    "name": u.get("name") or u.get("slug") or f"User {u['id']}",
                    "slug": u.get("slug", ""),
                }
                for u in users
            ]
        resp_view = await _wp_request("GET", url, params={"per_page": 100}, auth=auth)
        if resp_view.status_code == 200:
            users = resp_view.json()
            return [
                {
                    "id": u["id"],
                    "name": u.get("name") or u.get("slug") or f"User {u['id']}",
                    "slug": u.get("slug", ""),
                }
                for u in users
            ]
    except Exception as exc:
        log.warning("Failed to fetch authors from WordPress site %s: %s", base, exc)

    return []


# Author helpers
# ---------------------------------------------------------------------------

async def _resolve_author_id(
    author_name: str,
    auth: tuple,
    site_url: Optional[str] = None,
) -> Optional[int]:
    """
    Resolve post author ID on WordPress without creating any new user accounts.
    Strictly reuses existing approved accounts; NEVER creates new WordPress users.

    Resolution order:
    1. If author_name matches an existing WordPress user's display name, slug, or username,
       return that user's ID.
    2. Fallback to the configured approved default author (settings.WORDPRESS_DEFAULT_AUTHOR, e.g. 'pratiksha_dev').
    3. Fallback to the authenticated API user (auth[0], e.g. 'webdev').
    4. Fallback to the first available user returned by the API.
    """
    url = f"{_base_url(site_url)}/wp-json/wp/v2/users"
    default_author = getattr(settings, "WORDPRESS_DEFAULT_AUTHOR", "pratiksha_dev").lower()
    auth_user = (auth[0] if auth and auth[0] else "").lower()

    try:
        resp = await _wp_request("GET", url, params={"context": "edit", "per_page": 100}, auth=auth)
        if resp.status_code == 200:
            users = resp.json()
            if not users:
                return None

            # 1. Match author_name with an existing WordPress user if one exists
            if author_name and author_name.strip():
                author_lower = author_name.strip().lower()
                clean_slug = re.sub(r"[^a-z0-9]", "", author_lower)
                for user in users:
                    u_name = (user.get("name") or "").lower()
                    u_slug = (user.get("slug") or "").lower().replace("-", "").replace("_", "")
                    u_user = (user.get("username") or "").lower().replace("-", "").replace("_", "")
                    if u_name == author_lower or u_slug == clean_slug or u_user == clean_slug:
                        log.info("Author resolved to existing user: %r → id=%s (%s)", author_name, user["id"], user.get("username"))
                        return user["id"]

            # 2. Match configured approved default author (e.g. 'pratiksha_dev')
            if default_author:
                clean_def = re.sub(r"[^a-z0-9]", "", default_author)
                for user in users:
                    u_name = (user.get("name") or "").lower()
                    u_slug = (user.get("slug") or "").lower().replace("-", "").replace("_", "")
                    u_user = (user.get("username") or "").lower().replace("-", "").replace("_", "")
                    if u_name == default_author or u_slug == clean_def or u_user == clean_def:
                        log.info("Author %r mapped to approved existing user %r → id=%s", author_name, user.get("username"), user["id"])
                        return user["id"]

            # 3. Match authenticated API user (e.g. 'webdev')
            if auth_user:
                clean_auth = re.sub(r"[^a-z0-9]", "", auth_user)
                for user in users:
                    u_name = (user.get("name") or "").lower()
                    u_slug = (user.get("slug") or "").lower().replace("-", "").replace("_", "")
                    u_user = (user.get("username") or "").lower().replace("-", "").replace("_", "")
                    if u_name == auth_user or u_slug == clean_auth or u_user == clean_auth:
                        log.info("Author %r mapped to authenticated user %r → id=%s", author_name, user.get("username"), user["id"])
                        return user["id"]

            # 4. Fallback to first user
            return users[0]["id"]
    except Exception as exc:
        log.warning("Author resolution query failed for %r: %s", author_name, exc)

    return None


# Backward-compatible alias
_get_or_create_author = _resolve_author_id


_ARTICLE_HYPERLINK_STYLE = """<style>
/* Standard article body hyperlink styling */
.entry-content p a, .entry-content li a, .entry-content td a,
.post-content p a, .post-content li a, .post-content td a,
.article-content p a, .article-content li a, .article-content td a {
    color: #0066cc;
    text-decoration: underline;
    text-underline-offset: 2px;
}
.entry-content p a:hover, .entry-content li a:hover, .entry-content td a:hover,
.post-content p a:hover, .post-content li a:hover, .post-content td a:hover,
.article-content p a:hover, .article-content li a:hover, .article-content td a:hover {
    color: #004499;
    text-decoration: underline;
}
/* Ensure article body images fit naturally and do not exceed 700px width without distortion */
.entry-content img, .post-content img, .article-content img, figure.wp-block-image img, .wp-block-image img {
    max-width: 700px;
    height: auto;
    object-fit: contain;
}
</style>
"""


# ---------------------------------------------------------------------------
# Public Draft Creation API
# ---------------------------------------------------------------------------

async def create_draft(
    title: str,
    content: str,
    metadata: dict,
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> dict:
    """
    Create a new draft post on WordPress.
    Strictly creates status="draft" (never publish).
    """
    if not is_configured(site_url, username, app_password):
        return {
            "status": "skipped",
            "post_id": None,
            "url": None,
            "edit_url": None,
            "error": "WordPress is not configured."
        }

    is_authenticated = await verify_auth(site_url, username, app_password)
    if not is_authenticated:
        return {
            "status": "FAILED",
            "post_id": None,
            "url": None,
            "edit_url": None,
            "error": "WordPress authentication failed (401 Unauthorized)."
        }

    auth = _get_auth(username, app_password)
    base = _base_url(site_url)

    # Resolve categories
    category_ids: list[int] = []
    category_names: list[str] = []

    primary_cat_name = metadata.get("category_primary")
    if primary_cat_name:
        primary_id = await _get_or_create_category(primary_cat_name, auth, site_url)
        if primary_id:
            category_ids.append(primary_id)
            category_names.append(primary_cat_name)

    if metadata.get("category_featured"):
        featured_id = await _get_featured_category_id(auth, site_url)
        if featured_id and featured_id not in category_ids:
            category_ids.append(featured_id)
            category_names.append("Featured")

    # Resolve author: use selected author_id if provided; otherwise resolve by name
    selected_author_id = metadata.get("author_id")
    if selected_author_id is not None and str(selected_author_id).strip():
        try:
            author_id = int(selected_author_id)
        except (ValueError, TypeError):
            author_name = metadata.get("author_name")
            author_id = await _resolve_author_id(author_name or "", auth, site_url)
    else:
        author_name = metadata.get("author_name")
        author_id = await _resolve_author_id(author_name or "", auth, site_url)

    log.info("Creating WordPress draft: %r on %s", title, base)
    url = f"{base}/wp-json/wp/v2/posts"

    post_content = content
    if _ARTICLE_HYPERLINK_STYLE:
        if "<style>" in post_content and "max-width: 100%" not in post_content:
            post_content = re.sub(r'<style\b[^>]*>.*?</style>\s*', '', post_content, flags=re.DOTALL | re.IGNORECASE)
        if "<style>" not in post_content:
            post_content = f"{_ARTICLE_HYPERLINK_STYLE}\n{post_content}"

    payload: dict = {
        "title": title,
        "content": post_content,
        "status": "draft",  # DRAFT ONLY
    }

    if metadata.get("featured_media"):
        payload["featured_media"] = metadata["featured_media"]

    if category_ids:
        payload["categories"] = category_ids

    if author_id:
        payload["author"] = author_id

    if metadata.get("slug"):
        payload["slug"] = metadata["slug"]

    if metadata.get("excerpt"):
        payload["excerpt"] = metadata["excerpt"]

    meta_fields: dict = {}
    if metadata.get("focus_keyphrase"):
        meta_fields["_yoast_wpseo_focuskw"] = metadata["focus_keyphrase"]
        meta_fields["yoast_wpseo_focuskw"] = metadata["focus_keyphrase"]
    if metadata.get("meta_description"):
        try:
            from services.seo_optimizer import optimize_meta_description
            final_meta_desc = optimize_meta_description(
                metadata["meta_description"],
                metadata.get("focus_keyphrase", ""),
                title or metadata.get("title", ""),
            )
        except Exception:
            final_meta_desc = metadata["meta_description"]
        meta_fields["_yoast_wpseo_metadesc"] = final_meta_desc
        meta_fields["yoast_wpseo_metadesc"] = final_meta_desc
        # Synchronize WordPress post excerpt with calibrated 140–155 character meta description
        payload["excerpt"] = final_meta_desc
    if metadata.get("seo_title"):
        meta_fields["_yoast_wpseo_title"] = metadata["seo_title"]
        meta_fields["yoast_wpseo_title"] = metadata["seo_title"]
    if metadata.get("synonyms"):
        meta_fields["_yoast_wpseo_focuskw_synonyms"] = metadata["synonyms"]
        meta_fields["yoast_wpseo_focuskw_synonyms"] = metadata["synonyms"]

    if meta_fields:
        payload["meta"] = meta_fields

    try:
        resp = await _wp_request("POST", url, json=payload, auth=auth)
        resp.raise_for_status()

        data = resp.json()
        post_id = data.get("id")
        if not post_id:
            return {
                "status": "error",
                "post_id": None,
                "url": None,
                "edit_url": None,
                "error": "WordPress did not return a post ID.",
            }

        # Build dynamic admin editor URL
        edit_url = f"{base}/wp-admin/post.php?post={post_id}&action=edit"

        return {
            "status": "success",
            "post_id": post_id,
            "url": edit_url,
            "edit_url": edit_url,
            "preview_url": data.get("link"),
            "status_value": data.get("status"),
            "title": data.get("title", {}).get("rendered") or data.get("title"),
            "featured_media": data.get("featured_media"),
            "categories": data.get("categories", []),
            "category_names": category_names,
            "category_primary": primary_cat_name,
            "category_featured": bool(metadata.get("category_featured")),
            "author": data.get("author"),
            "slug": data.get("slug"),
            "error": None,
        }
    except httpx.HTTPStatusError as exc:
        log.error("WordPress create_draft API error %s: %s", exc.response.status_code, exc.response.text[:200])
        return {
            "status": "error",
            "post_id": None,
            "url": None,
            "edit_url": None,
            "error": f"WordPress returned HTTP {exc.response.status_code}."
        }
    except httpx.RequestError as exc:
        log.error("WordPress create_draft request error: %s", exc)
        return {
            "status": "error",
            "post_id": None,
            "url": None,
            "edit_url": None,
            "error": "Could not reach the WordPress REST API."
        }


async def update_draft(
    post_id: int,
    content: Optional[str] = None,
    title: Optional[str] = None,
    metadata: Optional[dict] = None,
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> dict:
    """
    Update an existing WordPress draft post.
    Strictly preserves status="draft" (never publish).
    """
    if not is_configured(site_url, username, app_password):
        return {
            "status": "error",
            "post_id": post_id,
            "error": "WordPress is not configured."
        }

    auth = _get_auth(username, app_password)
    base = _base_url(site_url)
    url = f"{base}/wp-json/wp/v2/posts/{post_id}"

    payload: dict = {
        "status": "draft",  # STRICTLY DRAFT ONLY
    }

    if title is not None:
        payload["title"] = title

    if content is not None:
        post_content = content
        if _ARTICLE_HYPERLINK_STYLE:
            if "<style>" in post_content and "max-width: 100%" not in post_content:
                post_content = re.sub(r'<style\b[^>]*>.*?</style>\s*', '', post_content, flags=re.DOTALL | re.IGNORECASE)
            if "<style>" not in post_content:
                post_content = f"{_ARTICLE_HYPERLINK_STYLE}\n{post_content}"
        payload["content"] = post_content

    if metadata:
        if metadata.get("excerpt"):
            payload["excerpt"] = metadata["excerpt"]

        meta_fields: dict = {}
        if metadata.get("focus_keyphrase"):
            meta_fields["_yoast_wpseo_focuskw"] = metadata["focus_keyphrase"]
            meta_fields["yoast_wpseo_focuskw"] = metadata["focus_keyphrase"]
        if metadata.get("meta_description"):
            try:
                from services.seo_optimizer import optimize_meta_description
                final_meta_desc = optimize_meta_description(
                    metadata["meta_description"],
                    metadata.get("focus_keyphrase", ""),
                    title or metadata.get("title", ""),
                )
            except Exception:
                final_meta_desc = metadata["meta_description"]
            meta_fields["_yoast_wpseo_metadesc"] = final_meta_desc
            meta_fields["yoast_wpseo_metadesc"] = final_meta_desc
        if metadata.get("seo_title"):
            meta_fields["_yoast_wpseo_title"] = metadata["seo_title"]
            meta_fields["yoast_wpseo_title"] = metadata["seo_title"]
        if metadata.get("synonyms"):
            meta_fields["_yoast_wpseo_focuskw_synonyms"] = metadata["synonyms"]
            meta_fields["yoast_wpseo_focuskw_synonyms"] = metadata["synonyms"]

        if meta_fields:
            payload["meta"] = meta_fields

    try:
        resp = await _wp_request("POST", url, json=payload, auth=auth)
        resp.raise_for_status()
        data = resp.json()
        edit_url = f"{base}/wp-admin/post.php?post={post_id}&action=edit"
        return {
            "status": "success",
            "post_id": post_id,
            "url": edit_url,
            "edit_url": edit_url,
            "title": data.get("title", {}).get("raw") or data.get("title", {}).get("rendered"),
            "status_value": data.get("status"),
            "meta": data.get("meta", {}),
            "error": None,
        }
    except httpx.HTTPStatusError as exc:
        log.error("WordPress update_draft error %s: %s", exc.response.status_code, exc.response.text[:200])
        return {
            "status": "error",
            "post_id": post_id,
            "error": f"WordPress returned HTTP {exc.response.status_code}."
        }
    except httpx.RequestError as exc:
        log.error("WordPress update_draft request error: %s", exc)
        return {
            "status": "error",
            "post_id": post_id,
            "error": "Could not reach the WordPress REST API."
        }


async def verify_draft(
    post_id: int,
    expected_title: str,
    expected_media_id: int,
    expected_inline_media_urls: list[str] | None = None,
    expected_focus_keyphrase: Optional[str] = None,
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> dict:
    """Verify a created post remains a draft with expected content/media."""
    if not is_configured(site_url, username, app_password):
        return {
            "status": "FAILED",
            "post_id": post_id,
            "error": "WordPress is not configured.",
            "checks": {},
        }

    base = _base_url(site_url)
    url = f"{base}/wp-json/wp/v2/posts/{post_id}"
    auth = _get_auth(username, app_password)

    try:
        response = await _wp_request("GET", url, params={"context": "edit"}, auth=auth)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        log.error("WordPress draft verification error %s", exc.response.status_code)
        return {
            "status": "FAILED",
            "post_id": post_id,
            "error": f"WordPress draft verification returned HTTP {exc.response.status_code}.",
            "checks": {},
        }
    except httpx.RequestError:
        return {
            "status": "FAILED",
            "post_id": post_id,
            "error": "Could not reach WordPress for draft verification.",
            "checks": {},
        }

    raw_title = data.get("title", {}).get("raw", "")
    rendered_title = data.get("title", {}).get("rendered", "")
    title = html.unescape(raw_title or rendered_title or "")
    content = data.get("content", {}).get("rendered", "")
    inline_urls = [u for u in (expected_inline_media_urls or []) if u]
    inline_images_load = True
    if inline_urls:
        for image_url in inline_urls:
            if image_url not in content:
                inline_images_load = False
                break

    link = data.get("link")
    edit_url = f"{base}/wp-admin/post.php?post={post_id}&action=edit"
    meta = data.get("meta", {})
    focus_kw = meta.get("_yoast_wpseo_focuskw") or meta.get("yoast_wpseo_focuskw") or ""

    checks = {
        "exists": data.get("id") == post_id,
        "status_is_draft": data.get("status") in ("draft", "auto-draft"),
        "title_present": bool(title),
        "title_matches": _normalize_title(title) == _normalize_title(expected_title),
        "content_present": bool(content.strip()),
        "html_structure_present": "<p" in content or "<h2" in content or "<div" in content,
        "inline_images_load": inline_images_load,
        "featured_media_attached": data.get("featured_media") == expected_media_id if expected_media_id else True,
        "not_published": data.get("status") != "publish",
    }
    if expected_focus_keyphrase:
        checks["focus_keyphrase_saved"] = bool(focus_kw) and (
            focus_kw.strip().lower() == expected_focus_keyphrase.strip().lower()
        )

    passed = all(checks.values())
    return {
        "status": "PASSED" if passed else "FAILED",
        "post_id": post_id,
        "status_value": data.get("status"),
        "title": title,
        "url": edit_url,
        "edit_url": edit_url,
        "preview_url": link,
        "featured_media": data.get("featured_media"),
        "categories": data.get("categories", []),
        "author": data.get("author"),
        "slug": data.get("slug"),
        "meta": meta,
        "yoast_focus_keyphrase": focus_kw,
        "checks": checks,
        "data": data,
        "error": None if passed else "One or more WordPress draft QA checks failed.",
    }


async def delete_post(
    post_id: int,
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
    force: bool = True,
) -> dict:
    """Permanently delete a post from WordPress (used for clean test teardowns)."""
    base = _base_url(site_url)
    url = f"{base}/wp-json/wp/v2/posts/{post_id}"
    params = {"force": "true" if force else "false"}
    auth = _get_auth(username, app_password)
    resp = await _wp_request("DELETE", url, params=params, auth=auth)
    return {
        "status": "success" if resp.status_code in (200, 204) else "error",
        "status_code": resp.status_code,
    }


async def upload_media(
    filename: str,
    content: bytes,
    content_type: str,
    alt_text: str = "",
    image_title: str = "",
    caption: str = "",
    source_url: str = "",
    site_url: Optional[str] = None,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
) -> dict:
    """Upload real image bytes to destination WordPress media library."""
    if not is_configured(site_url, username, app_password):
        return {
            "status": "error",
            "media_id": None,
            "url": None,
            "error": "WordPress is not configured.",
        }
    if not content:
        return {
            "status": "error",
            "media_id": None,
            "url": None,
            "error": "Image content is empty.",
        }

    base = _base_url(site_url)
    url = f"{base}/wp-json/wp/v2/media"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": content_type,
    }
    auth = _get_auth(username, app_password)

    try:
        response = await _wp_request("POST", url, content=content, headers=headers, auth=auth, timeout=60.0)
        response.raise_for_status()
        data = response.json()
        media_id = data.get("id")
        if not media_id:
            return {
                "status": "error",
                "media_id": None,
                "url": None,
                "error": "WordPress did not return a media ID.",
            }

        # Update media metadata (alt text, title, caption, source URL)
        update_payload: dict = {}
        if alt_text:
            update_payload["alt_text"] = alt_text
        if image_title:
            update_payload["title"] = image_title
        if caption:
            caption_html = caption
            # If the caption refers to Envato or source_url is an Envato asset, format as envato.com source link
            is_envato = (
                "envato" in caption_html.lower()
                or (source_url and any(domain in source_url.lower() for domain in ["envato.com", "photodune.net"]))
            )
            if is_envato and source_url:
                caption_html = f'<a href="{source_url}" target="_blank" rel="noopener">envato.com</a>'
            elif source_url and source_url not in caption_html:
                caption_html = f'<a href="{source_url}" target="_blank" rel="noopener">{caption}</a>'
            update_payload["caption"] = caption_html
        elif source_url:
            is_envato = any(domain in source_url.lower() for domain in ["envato.com", "photodune.net"])
            link_text = "envato.com" if is_envato else "Image source"
            update_payload["caption"] = f'<a href="{source_url}" target="_blank" rel="noopener">{link_text}</a>'

        if update_payload:
            try:
                alt_response = await _wp_request(
                    "POST",
                    f"{url}/{media_id}",
                    json=update_payload,
                    auth=auth,
                )
                alt_response.raise_for_status()
            except Exception as meta_exc:
                log.warning("Non-fatal: failed to update media metadata: %s", meta_exc)

        return {
            "status": "success",
            "media_id": media_id,
            "url": data.get("source_url"),
            "source_url": source_url,
            "error": None,
        }
    except httpx.HTTPStatusError as exc:
        log.error(
            "WordPress media upload error %s: %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return {
            "status": "error",
            "media_id": None,
            "url": None,
            "error": f"WordPress media upload returned HTTP {exc.response.status_code}.",
        }
    except httpx.RequestError as exc:
        log.error("WordPress media upload request error: %s", exc)
        return {
            "status": "error",
            "media_id": None,
            "url": None,
            "error": "Could not reach the WordPress media API.",
        }
