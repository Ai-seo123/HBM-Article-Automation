"""
Basecamp OAuth 2.0 service for Espial Article Publishing.

Features:
- Individual employee OAuth token isolation stored encrypted in SQLite.
- Every authenticated employee uses their own stored OAuth account_id and encrypted access/refresh tokens.
- Global BASECAMP_ACCOUNT_ID never overrides an employee's connected account.
- Multiple Basecamp accounts selection support when OAuth returns more than one account.
- Strictly manual-only token refresh. Zero automated background refresh, zero silent refresh on 401.
"""

import os
import time
import logging
from contextvars import ContextVar
from urllib.parse import urlencode
from typing import Optional, Tuple
import httpx
from sqlalchemy.orm import Session

from core.config import settings
from core.database import SessionLocal
from core.security import encrypt_token, decrypt_token
from models.employee import EmployeeBasecampToken

log = logging.getLogger(__name__)

# Context variable for the current request's authenticated employee ID
_current_employee_id: ContextVar[Optional[int]] = ContextVar("current_employee_id", default=None)

def set_current_employee_id(emp_id: Optional[int]) -> None:
    """Set the authenticated employee ID for the current request context."""
    _current_employee_id.set(emp_id)

def get_current_employee_id() -> Optional[int]:
    """Get the authenticated employee ID for the current request context."""
    return _current_employee_id.get()


# ---------------------------------------------------------------------------
# Basecamp OAuth endpoints
# ---------------------------------------------------------------------------
BASECAMP_AUTHORIZE_URL = "https://launchpad.37signals.com/authorization/new"
BASECAMP_TOKEN_URL = "https://launchpad.37signals.com/authorization/token"
BASECAMP_IDENTITY_URL = "https://launchpad.37signals.com/authorization.json"
BASECAMP_API_BASE = "https://3.basecampapi.com"

# User-Agent is required by Basecamp API
_USER_AGENT = "Espial Article Publishing (espial.contact@gmail.com)"

# Temporary cache for pending multi-account OAuth selections: {employee_id: {"tokens": dict, "accounts": list, "time": float}}
_pending_accounts: dict[int, dict] = {}


# ---------------------------------------------------------------------------
# Fallback in-memory token store (Used only for unit tests without employee sessions)
# ---------------------------------------------------------------------------
class _TokenStore:
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    token_type: Optional[str] = None

    def clear(self) -> None:
        self.access_token = None
        self.refresh_token = None
        self.expires_in = None
        self.token_type = None

    @property
    def is_connected(self) -> bool:
        return bool(self.access_token)

_token_store = _TokenStore()


def is_configured() -> bool:
    """Return True if the required OAuth credentials are present in config."""
    return bool(settings.BASECAMP_CLIENT_ID and settings.BASECAMP_CLIENT_SECRET)


def build_authorization_url(state: Optional[str] = None) -> str:
    """
    Construct the Basecamp OAuth authorization URL.
    Optionally includes a state parameter to associate the flow with an employee session.
    """
    if not is_configured():
        raise RuntimeError(
            "Basecamp OAuth credentials are not configured. "
            "Set BASECAMP_CLIENT_ID, BASECAMP_CLIENT_SECRET, and BASECAMP_REDIRECT_URI in backend/.env."
        )

    params = {
        "type": "web_server",
        "client_id": settings.BASECAMP_CLIENT_ID,
        "redirect_uri": settings.BASECAMP_REDIRECT_URI,
    }
    if state:
        params["state"] = state
    return f"{BASECAMP_AUTHORIZE_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Employee Token Resolution & Database Persistence
# ---------------------------------------------------------------------------

def get_employee_token_record(db: Session, employee_id: int) -> Optional[EmployeeBasecampToken]:
    """Retrieve an employee's Basecamp token record from SQLite."""
    return db.query(EmployeeBasecampToken).filter(EmployeeBasecampToken.employee_id == employee_id).first()


def save_employee_tokens(
    db: Session,
    employee_id: int,
    account_id: str,
    account_name: str,
    access_token: str,
    refresh_token: str,
    expires_in: Optional[int] = None,
    token_type: str = "Bearer",
) -> EmployeeBasecampToken:
    """
    Store per-employee encrypted Basecamp OAuth credentials in SQLite.
    Strictly isolated: stores employee's OWN OAuth account_id.
    """
    enc_access = encrypt_token(access_token)
    enc_refresh = encrypt_token(refresh_token)
    expires_at = int(time.time() + (expires_in or 1209600))  # Default 14 days

    record = get_employee_token_record(db, employee_id)
    if record:
        record.account_id = str(account_id)
        record.account_name = account_name
        record.encrypted_access_token = enc_access
        record.encrypted_refresh_token = enc_refresh
        record.token_type = token_type
        record.expires_at = expires_at
    else:
        record = EmployeeBasecampToken(
            employee_id=employee_id,
            account_id=str(account_id),
            account_name=account_name,
            encrypted_access_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            token_type=token_type,
            expires_at=expires_at,
        )
        db.add(record)

    db.commit()
    db.refresh(record)
    log.info("Encrypted Basecamp tokens saved for employee %s with account_id=%s", employee_id, account_id)
    return record


async def exchange_code_for_employee(
    code: str,
    employee_id: int,
    db: Session,
) -> dict:
    """
    Exchange authorization code for tokens, query accessible accounts,
    and either save single account or return multi-account choices for the employee.
    """
    if not code:
        raise ValueError("Authorization code is missing.")
    if not is_configured():
        raise RuntimeError("Basecamp OAuth credentials are not configured.")

    payload = {
        "type": "web_server",
        "client_id": settings.BASECAMP_CLIENT_ID,
        "client_secret": settings.BASECAMP_CLIENT_SECRET,
        "redirect_uri": settings.BASECAMP_REDIRECT_URI,
        "code": code,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(BASECAMP_TOKEN_URL, data=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            log.error("Basecamp token exchange HTTP error: %s", exc.response.text)
            raise RuntimeError(f"Token exchange failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            log.error("Basecamp token exchange request error: %s", exc)
            raise RuntimeError("Could not connect to Basecamp token endpoint.") from exc

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")
    token_type = data.get("token_type", "Bearer")

    if not access_token:
        raise RuntimeError("No access token returned from Basecamp.")

    # Fetch accessible accounts using the access token
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        id_resp = await client.get(BASECAMP_IDENTITY_URL, headers=headers)
        id_resp.raise_for_status()
        id_data = id_resp.json()

    accounts_raw = id_data.get("accounts", [])
    bc3_accounts = [
        {"id": str(a["id"]), "name": a.get("name", f"Account {a['id']}"), "href": a.get("href")}
        for a in accounts_raw if a.get("product") == "bc3"
    ]

    if not bc3_accounts:
        raise RuntimeError("No Basecamp 3 accounts found associated with this user identity.")

    # Single account case: connect immediately
    if len(bc3_accounts) == 1:
        single_acc = bc3_accounts[0]
        save_employee_tokens(
            db=db,
            employee_id=employee_id,
            account_id=single_acc["id"],
            account_name=single_acc["name"],
            access_token=access_token,
            refresh_token=refresh_token or "",
            expires_in=expires_in,
            token_type=token_type,
        )
        return {
            "status": "connected",
            "multiple_accounts": False,
            "account": single_acc,
        }

    # Multiple accounts case: store pending selection
    _pending_accounts[employee_id] = {
        "tokens": data,
        "accounts": bc3_accounts,
        "time": time.time(),
    }
    log.info("Basecamp returned %d accounts for employee %s. Awaiting employee account selection.", len(bc3_accounts), employee_id)
    return {
        "status": "pending_selection",
        "multiple_accounts": True,
        "accounts": bc3_accounts,
    }


def get_pending_accounts_for_employee(employee_id: int) -> list[dict]:
    """Retrieve pending Basecamp accounts for an employee awaiting selection."""
    entry = _pending_accounts.get(employee_id)
    if not entry:
        return []
    # Expire pending entries older than 15 minutes
    if time.time() - entry["time"] > 900:
        _pending_accounts.pop(employee_id, None)
        return []
    return entry["accounts"]


def select_account_for_employee(
    db: Session,
    employee_id: int,
    selected_account_id: str,
) -> dict:
    """
    Finalize Basecamp connection with employee's explicitly selected account.
    Never falls back to global BASECAMP_ACCOUNT_ID.
    """
    entry = _pending_accounts.get(employee_id)
    if not entry:
        raise ValueError("No pending Basecamp connection found. Please start the connection process again.")

    matching_acc = next((a for a in entry["accounts"] if str(a["id"]) == str(selected_account_id)), None)
    if not matching_acc:
        raise ValueError("Selected account is not in the list of authorized Basecamp accounts.")

    data = entry["tokens"]
    save_employee_tokens(
        db=db,
        employee_id=employee_id,
        account_id=matching_acc["id"],
        account_name=matching_acc["name"],
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or "",
        expires_in=data.get("expires_in"),
        token_type=data.get("token_type", "Bearer"),
    )
    _pending_accounts.pop(employee_id, None)
    return {
        "status": "connected",
        "account": matching_acc,
    }


# ---------------------------------------------------------------------------
# Strict Manual-Only Token Refresh
# ---------------------------------------------------------------------------

async def refresh_employee_token_manual(db: Session, employee_id: int) -> dict:
    """
    Manually refresh the authenticated employee's access token using their stored refresh token.
    Strictly manual: only executed when employee explicitly clicks 'Refresh Connection'.
    Zero automatic retries or background refresh.
    """
    record = get_employee_token_record(db, employee_id)
    if not record or not record.encrypted_refresh_token:
        return {
            "success": False,
            "error": "not_connected",
            "message": "No active Basecamp connection found to refresh. Please connect Basecamp first.",
        }

    try:
        plain_refresh_token = decrypt_token(record.encrypted_refresh_token)
    except Exception as exc:
        log.error("Failed to decrypt refresh token for employee %s: %s", employee_id, exc)
        return {
            "success": False,
            "error": "decryption_failed",
            "message": "Token decryption failed. Please reconnect your Basecamp account.",
        }

    payload = {
        "type": "refresh",
        "client_id": settings.BASECAMP_CLIENT_ID,
        "client_secret": settings.BASECAMP_CLIENT_SECRET,
        "refresh_token": plain_refresh_token,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(BASECAMP_TOKEN_URL, data=payload)
            if resp.status_code != 200:
                log.warning("Basecamp refresh returned HTTP %s for employee %s: %s", resp.status_code, employee_id, resp.text)
                return {
                    "success": False,
                    "error": "refresh_rejected",
                    "message": "Basecamp token refresh was rejected or revoked. Please click 'Reconnect Basecamp'.",
                }
            data = resp.json()
        except Exception as exc:
            log.error("Basecamp token refresh request error for employee %s: %s", employee_id, exc)
            return {
                "success": False,
                "error": "network_error",
                "message": f"Could not reach Basecamp authorization server: {exc}",
            }

    new_access = data.get("access_token")
    if not new_access:
        return {
            "success": False,
            "error": "no_token",
            "message": "No access token in refresh response. Please reconnect Basecamp.",
        }

    record.encrypted_access_token = encrypt_token(new_access)
    new_refresh = data.get("refresh_token")
    if new_refresh:
        record.encrypted_refresh_token = encrypt_token(new_refresh)

    expires_in = data.get("expires_in") or 1209600
    record.expires_at = int(time.time() + expires_in)

    db.commit()
    db.refresh(record)
    log.info("Employee %s Basecamp token successfully refreshed manually.", employee_id)
    return {
        "success": True,
        "message": "Basecamp connection refreshed successfully.",
        "expires_at": record.expires_at,
    }


def disconnect_employee(db: Session, employee_id: int) -> dict:
    """Clear Basecamp connection for an employee."""
    record = get_employee_token_record(db, employee_id)
    if record:
        db.delete(record)
        db.commit()
    _pending_accounts.pop(employee_id, None)
    log.info("Basecamp connection disconnected for employee %s.", employee_id)
    return {"connected": False}


def get_connection_status(employee_id: Optional[int] = None) -> dict:
    """
    Return connection status for the authenticated employee.
    If employee_id is None, checks active request context or test singleton.
    Never exposes raw tokens.
    """
    emp_id = employee_id if employee_id is not None else get_current_employee_id()
    if emp_id is not None:
        db = SessionLocal()
        try:
            record = get_employee_token_record(db, emp_id)
            if not record:
                # Check if there is a pending account selection
                pending = get_pending_accounts_for_employee(emp_id)
                if pending:
                    return {
                        "connected": False,
                        "pending_selection": True,
                        "accounts": pending,
                    }
                return {"connected": False}

            return {
                "connected": True,
                "account_id": record.account_id,
                "account_name": record.account_name or f"Account {record.account_id}",
                "is_expired": record.is_expired(),
                "expires_at": record.expires_at,
            }
        finally:
            db.close()

    # Fallback for unit testing singleton
    return {"connected": _token_store.is_connected}


# ---------------------------------------------------------------------------
# Authenticated Basecamp API Queries (Employee Isolated)
# ---------------------------------------------------------------------------

def _resolve_employee_auth(employee_id: Optional[int] = None) -> Tuple[str, str]:
    """
    Resolve (access_token, account_id) for the active employee.
    Strictly isolated: Uses employee's stored account_id and decrypted access token.
    Global BASECAMP_ACCOUNT_ID never overrides an employee's connected account.
    Raises RuntimeError if not connected or expired (manual refresh required).
    """
    emp_id = employee_id if employee_id is not None else get_current_employee_id()
    if emp_id is not None:
        db = SessionLocal()
        try:
            record = get_employee_token_record(db, emp_id)
            if not record:
                raise RuntimeError("not_connected")
            if record.is_expired():
                raise RuntimeError("basecamp_token_expired")

            access_token = decrypt_token(record.encrypted_access_token)
            account_id = str(record.account_id)
            return access_token, account_id
        finally:
            db.close()

    # Fallback for test suite when no employee context is set
    if _token_store.is_connected:
        acc = (settings.BASECAMP_ACCOUNT_ID or "1").strip()
        return _token_store.access_token, acc

    raise RuntimeError("not_connected")


def get_valid_token(employee_id: Optional[int] = None) -> str:
    """Helper to return valid decrypted access token for attachment download."""
    token, _ = _resolve_employee_auth(employee_id)
    return token


async def _bc_get(url: str, employee_id: Optional[int] = None) -> dict | list:
    """
    Perform an authenticated GET request to Basecamp API.
    Zero automated refresh: on 401 raises basecamp_token_expired requiring user click.
    """
    token, _ = _resolve_employee_auth(employee_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 401:
                log.warning("Basecamp returned 401 Unauthorized for URL %s. Manual refresh required.", url)
                raise RuntimeError("basecamp_token_expired")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.error("Basecamp API error %s for %s: %s", exc.response.status_code, url, exc.response.text)
            raise RuntimeError(f"Basecamp API returned {exc.response.status_code} for {url}") from exc
        except httpx.RequestError as exc:
            log.error("Basecamp API request error for %s: %s", url, exc)
            raise RuntimeError("Could not reach the Basecamp API.") from exc
    return resp.json()


async def _bc_get_paginated(
    url: str,
    employee_id: Optional[int] = None,
    max_pages: Optional[int] = None,
    stop_before_date: Optional[str] = None,
) -> list:
    """
    Fetch pages of a Basecamp API endpoint.
    Zero automated refresh: on 401 raises basecamp_token_expired.
    Optionally limits to max_pages or stops if all items on a page are older than stop_before_date.
    """
    token, _ = _resolve_employee_auth(employee_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    results = []
    next_url: Optional[str] = url
    page_count = 0

    async with httpx.AsyncClient(timeout=20) as client:
        while next_url:
            if max_pages is not None and page_count >= max_pages:
                break
            try:
                resp = await client.get(next_url, headers=headers)
                if resp.status_code == 401:
                    log.warning("Basecamp returned 401 Unauthorized for paginated URL %s. Manual refresh required.", next_url)
                    raise RuntimeError("basecamp_token_expired")
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                log.error("Basecamp paginated API error %s for %s: %s", exc.response.status_code, next_url, exc.response.text)
                raise RuntimeError(f"Basecamp API returned {exc.response.status_code}") from exc
            except httpx.RequestError as exc:
                log.error("Basecamp request error for %s: %s", next_url, exc)
                raise RuntimeError("Could not reach the Basecamp API.") from exc

            page_data = resp.json()
            items = page_data if isinstance(page_data, list) else [page_data]
            results.extend(items)
            page_count += 1

            # Early exit if filtering by date and the items on this page are already older than stop_before_date
            if stop_before_date and items:
                from core.date_utils import normalize_timestamp_to_date
                last_item = items[-1]
                raw_ts = (
                    last_item.get("created_at")
                    or (last_item.get("recording") or {}).get("created_at")
                    or (last_item.get("message") or {}).get("created_at")
                    or last_item.get("date")
                )
                _, last_date = normalize_timestamp_to_date(raw_ts)
                if last_date and last_date < stop_before_date:
                    break

            link_header = resp.headers.get("Link", "")
            next_url = _parse_next_link(link_header)

    return results


def _parse_next_link(link_header: str) -> Optional[str]:
    """Extract next URL from Link header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            url_part = part.split(";")[0].strip()
            return url_part.strip("<>")
    return None


# ---------------------------------------------------------------------------
# Data transformation helpers
# ---------------------------------------------------------------------------

def _clean_project(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "description": p.get("description") or "",
        "status": p.get("status"),
        "purpose": p.get("purpose"),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
        "url": p.get("app_url"),
        "bookmark_url": p.get("bookmark_url"),
    }


def _find_tool(project: dict, name: str) -> Optional[dict]:
    for tool in project.get("dock", []):
        if tool.get("name") == name and tool.get("enabled"):
            return tool
    return None


def _extract_bc_attachments(html: str) -> list[dict]:
    attachments = []
    if not html:
        return attachments
    import re
    matches = re.finditer(r'<bc-attachment\s+([^>]+?)(?:/?>|></bc-attachment>)', html, re.IGNORECASE)
    for match in matches:
        attrs_str = match.group(1)
        attr_matches = re.finditer(r'([a-zA-Z0-9_-]+)=[\'"]([^\'"]+)[\'"]', attrs_str)
        attrs = {m.group(1).lower(): m.group(2) for m in attr_matches}
        if "sgid" in attrs:
            attachments.append({
                "id": attrs.get("sgid"),
                "filename": attrs.get("filename", "unknown"),
                "content_type": attrs.get("content-type", "application/octet-stream"),
                "byte_size": int(attrs.get("filesize", 0)) if attrs.get("filesize", "").isdigit() else 0,
                "url": attrs.get("href") or attrs.get("url"),
                "created_at": None,
            })
    return attachments


def _clean_message(m: dict, include_body: bool = False) -> dict:
    creator = m.get("creator") or {}
    created_at = (
        m.get("created_at")
        or (m.get("recording") or {}).get("created_at")
        or (m.get("message") or {}).get("created_at")
        or m.get("date")
    )
    result = {
        "id": m.get("id"),
        "subject": m.get("subject"),
        "author": creator.get("name"),
        "author_avatar": creator.get("avatar_url"),
        "created_at": created_at,
        "updated_at": m.get("updated_at"),
        "url": m.get("app_url"),
        "comments_count": m.get("comments_count", 0),
    }

    body_html = m.get("content", "") or ""
    parsed_attachments = _extract_bc_attachments(body_html)

    if include_body:
        result["content"] = body_html
        result["attachments"] = parsed_attachments
        result["attachment_count"] = len(parsed_attachments)
        try:
            from services.basecamp_parser import parse_instructions
            result["parsed_instructions"] = parse_instructions(body_html)
        except Exception as exc:
            log.warning("Could not parse message instructions: %s", exc)
            result["parsed_instructions"] = None
    else:
        import re
        plain = re.sub(r"<[^>]+>", " ", body_html)
        plain = " ".join(plain.split())
        result["preview"] = plain[:200]
        result["attachment_count"] = len(parsed_attachments)
    return result


# ---------------------------------------------------------------------------
# High-Level Project and Message Operations
# ---------------------------------------------------------------------------

async def get_identity(employee_id: Optional[int] = None) -> dict:
    """Return identity and accessible Basecamp accounts."""
    data = await _bc_get(BASECAMP_IDENTITY_URL, employee_id=employee_id)
    accounts_raw = data.get("accounts", [])
    bc_accounts = [a for a in accounts_raw if a.get("product") == "bc3"]
    return {
        "identity": {
            "id": data.get("identity", {}).get("id"),
            "first_name": data.get("identity", {}).get("first_name"),
            "last_name": data.get("identity", {}).get("last_name"),
            "email_address": data.get("identity", {}).get("email_address"),
        },
        "accounts": [
            {"id": a.get("id"), "name": a.get("name"), "href": a.get("href")}
            for a in bc_accounts
        ],
    }


async def get_projects(employee_id: Optional[int] = None) -> list[dict]:
    """
    List Basecamp projects accessible to the employee.
    Uses the employee's OWN stored account_id.
    """
    _, account_id = _resolve_employee_auth(employee_id)
    url = f"{BASECAMP_API_BASE}/{account_id}/projects.json"
    raw_projects = await _bc_get_paginated(url, employee_id=employee_id)
    return [
        {**_clean_project(project), "account_id": account_id}
        for project in raw_projects
    ]


async def get_project(project_id: int, employee_id: Optional[int] = None) -> dict:
    """Return single Basecamp project details using employee's own account_id."""
    _, account_id = _resolve_employee_auth(employee_id)
    url = f"{BASECAMP_API_BASE}/{account_id}/projects/{project_id}.json"
    raw = await _bc_get(url, employee_id=employee_id)
    return _clean_project(raw)


async def get_messages(
    project_id: int,
    employee_id: Optional[int] = None,
    date: Optional[str] = None,
    max_pages: int = 5,
) -> list[dict]:
    """Return messages for a project using employee's own account_id."""
    _, account_id = _resolve_employee_auth(employee_id)
    project_url = f"{BASECAMP_API_BASE}/{account_id}/projects/{project_id}.json"
    project_raw = await _bc_get(project_url, employee_id=employee_id)

    message_board_tool = _find_tool(project_raw, "message_board")
    if not message_board_tool:
        log.info("Project %s has no message board.", project_id)
        return []

    mb_data = await _bc_get(message_board_tool["url"], employee_id=employee_id)
    messages_url = mb_data.get("messages_url")
    if not messages_url:
        mb_id = mb_data.get("id")
        messages_url = (
            f"{BASECAMP_API_BASE}/{account_id}/buckets/{project_id}"
            f"/message_boards/{mb_id}/messages.json"
        )

    # When date is specified, allow scanning up to 10 pages; otherwise default to max_pages
    pages_limit = 10 if date else max_pages
    raw_messages = await _bc_get_paginated(
        messages_url,
        employee_id=employee_id,
        max_pages=pages_limit,
        stop_before_date=date.strip() if date else None,
    )
    return [_clean_message(m, include_body=False) for m in raw_messages]


async def get_message(project_id: int, message_id: int, employee_id: Optional[int] = None) -> dict:
    """Return full message body and attachments using employee's own account_id."""
    _, account_id = _resolve_employee_auth(employee_id)
    url = f"{BASECAMP_API_BASE}/{account_id}/buckets/{project_id}/messages/{message_id}.json"
    raw = await _bc_get(url, employee_id=employee_id)
    return _clean_message(raw, include_body=True)
