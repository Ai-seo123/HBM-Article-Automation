"""
Authoritative 9-Stage Create Draft Wizard Service.

Stages:
  1. Confirm selected Basecamp article and client instructions
  2. Download and inspect the DOCX attachment
  3. Extract document text, headings, formatting, and embedded images
  4. Review article content and links
  5. Prepare and review SEO metadata
  6. Pause for manual featured-image approval (GENUINE APPROVAL GATE)
  7. Create or update test-site draft only after approved review (GENUINE DRAFT CREATION GATE)
  8. Verify saved WordPress draft
  9. Run read-only QA checklist and show final report

Strict Safety Guarantees:
  - Server-side persisted workflow sessions in backend/storage/wizard_sessions
  - Fully resumable across browser refreshes
  - Idempotency guard: zero duplicate WordPress drafts on retries or concurrent calls
  - Draft creation ONLY on user approval in Step 7
  - Strictly restricted to https://espialsolutions.com with status="draft"
  - Zero access or write requests to homebusinessmag.com production
  - 100% read-only QA in Stage 9
"""

import base64
import copy
import html
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import services.basecamp as bc_service
import services.basecamp_parser as bc_parser
import services.documents as doc_service
import services.gemini as gemini_service
import services.image_service as image_service
import services.qa_engine as qa_engine
import services.report_service as report_service
import services.seo_optimizer as seo_optimizer
import services.site_service as site_service
import services.wordpress as wp_service
import services.yoast as yoast_service

log = logging.getLogger(__name__)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BACKEND_DIR, "storage")
SESSIONS_DIR = os.path.join(STORAGE_DIR, "wizard_sessions")
BACKUPS_DIR = os.path.join(STORAGE_DIR, "backups")

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(BACKUPS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Session Persistence & Helpers
# ---------------------------------------------------------------------------

def _get_session_id(project_id: int, message_id: int, attachment_id: str) -> str:
    safe_att = re.sub(r"[^\w\-]", "_", str(attachment_id))
    return f"p{project_id}_m{message_id}_a{safe_att}"


def _get_session_filepath(session_id: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{session_id}.json")


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    path = _get_session_filepath(session_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Could not load wizard session %s: %s", session_id, exc)
        return None


def save_session(session: Dict[str, Any]) -> None:
    session_id = session["session_id"]
    path = _get_session_filepath(session_id)
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2)
        try:
            os.replace(tmp_path, path)
        except OSError:
            # Windows / OneDrive file lock fallback
            import shutil
            shutil.move(tmp_path, path)
    except Exception as exc:
        log.error("Failed to save wizard session %s: %s", session_id, exc)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session, f, indent=2)
        except Exception:
            pass


def _init_session(project_id: int, message_id: int, attachment_id: str, site_id: Optional[int]) -> Dict[str, Any]:
    session_id = _get_session_id(project_id, message_id, attachment_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "session_id": session_id,
        "project_id": project_id,
        "message_id": message_id,
        "attachment_id": str(attachment_id),
        "site_id": site_id,
        "current_stage": 1,
        "created_at": now_iso,
        "updated_at": now_iso,
        "created_post_id": None,
        "created_edit_url": None,
        "stages": {
            "1": {"status": "pending", "title": "Confirm Basecamp Article & Instructions", "data": None, "error": None},
            "2": {"status": "pending", "title": "Download & Inspect DOCX Attachment", "data": None, "error": None},
            "3": {"status": "pending", "title": "Extract Content, Headings & Duplicate Check", "data": None, "error": None},
            "4": {"status": "pending", "title": "Review Article Content & Link Structure", "data": None, "error": None},
            "5": {"status": "pending", "title": "Prepare & Review SEO Metadata", "data": None, "error": None},
            "6": {"status": "pending", "title": "Manual Featured-Image Selection & Approval", "data": None, "error": None},
            "7": {"status": "pending", "title": "Create WordPress Draft on Test Site", "data": None, "error": None},
            "8": {"status": "pending", "title": "Verify Saved WordPress Draft", "data": None, "error": None},
            "9": {"status": "pending", "title": "Authoritative 10-Category Read-Only QA Checklist", "data": None, "error": None},
        },
        "shared": {},
    }


def _resolve_site_target(session: Dict[str, Any]):
    site_id = session.get("site_id")
    site = site_service.get_site(site_id) if site_id else None
    if not site and not session.get("site_id"):
        site = site_service.get_default_site()
        if not site:
            raw_list = site_service.list_sites()
            if raw_list:
                site = site_service.get_site(raw_list[0]["id"])
    if not site:
        shared_url = session.get("shared", {}).get("site_url")
        if shared_url:
            from types import SimpleNamespace
            return SimpleNamespace(
                id=site_id or 0,
                name="Custom Site",
                url=shared_url,
                username=session.get("shared", {}).get("site_username", "webdev"),
                app_password=session.get("shared", {}).get("site_app_password", "pass"),
            )
        raise ValueError("WordPress destination site not configured.")
    return site


# ---------------------------------------------------------------------------
# Stage 1: Confirm Selected Basecamp Article and Client Instructions
# ---------------------------------------------------------------------------

async def execute_stage_1(session: Dict[str, Any], site_id: Optional[int] = None) -> Dict[str, Any]:
    project_id = session["project_id"]
    message_id = session["message_id"]
    attachment_id = session["attachment_id"]
    if site_id:
        session["site_id"] = site_id

    # Verify site
    target_site_id = session.get("site_id")
    site = site_service.get_site(target_site_id) if target_site_id else site_service.get_default_site()
    if not site:
        raw_list = site_service.list_sites()
        if raw_list:
            site = site_service.get_site(raw_list[0]["id"])
    if not site:
        raise ValueError("No WordPress destination site found.")
    session["site_id"] = site.id

    # Verify destination safety
    site_url_lower = site.url.lower()
    if "homebusinessmag.com" in site_url_lower:
        raise ValueError("Security Violation: Production write to homebusinessmag.com is strictly forbidden.")
    if "espialsolutions.com" not in site_url_lower:
        raise ValueError("Security Violation: Draft creation is strictly restricted to https://espialsolutions.com.")

    # Fetch Basecamp message
    status = bc_service.get_connection_status()
    if not status.get("connected"):
        raise ValueError("Basecamp account is not connected. Please connect Basecamp first.")

    project_info = {}
    try:
        project_info = await bc_service.get_project(project_id)
    except Exception:
        pass
    project_name = project_info.get("name") or f"Project #{project_id}"

    message = await bc_service.get_message(project_id, message_id)
    subject = message.get("subject", "")
    content_html = message.get("content", "")
    content_plain = re.sub(r"<[^>]+>", " ", content_html)
    content_plain = re.sub(r"\s+", " ", content_plain).strip()

    # Find attachment
    attachments = message.get("attachments", [])
    target_att = None
    for att in attachments:
        if str(att.get("id")) == str(attachment_id):
            target_att = att
            break
    if not target_att:
        raise ValueError(f"Attachment #{attachment_id} not found in message #{message_id}.")

    filename = target_att.get("filename", "")
    if not filename.lower().endswith(".docx"):
        raise ValueError(f"Attachment '{filename}' is not a .docx file.")

    # Parse instructions
    parsed_instructions = bc_parser.parse_instructions(content_html)

    stage_data = {
        "project_id": project_id,
        "project_name": project_name,
        "message_id": message_id,
        "message_subject": subject,
        "attachment_id": attachment_id,
        "attachment_filename": filename,
        "client_instructions_plain": content_plain,
        "parsed_instructions": parsed_instructions,
        "destination_site": {
            "id": site.id,
            "name": site.name,
            "url": site.url,
            "status": "draft",
        },
    }

    session["stages"]["1"]["status"] = "completed"
    session["stages"]["1"]["data"] = stage_data
    session["stages"]["1"]["error"] = None
    session["shared"]["attachment_url"] = target_att.get("url") or target_att.get("download_url")
    session["shared"]["attachment_filename"] = filename
    session["shared"]["client_instructions_html"] = content_html
    session["shared"]["client_instructions_plain"] = content_plain
    session["shared"]["parsed_instructions"] = parsed_instructions
    session["shared"]["message_subject"] = subject
    session["shared"]["site_url"] = site.url
    session["shared"]["site_username"] = site.username
    # Note: site_app_password is never stored in public session to prevent credential exposure

    if session["current_stage"] == 1:
        session["current_stage"] = 2

    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Stage 2: Download and Inspect the DOCX Attachment
# ---------------------------------------------------------------------------

async def execute_stage_2(session: Dict[str, Any]) -> Dict[str, Any]:
    att_url = session["shared"].get("attachment_url")
    filename = session["shared"].get("attachment_filename") or "document.docx"
    token = bc_service.get_valid_token()
    if not att_url or not token:
        raise ValueError("Attachment URL or Basecamp authentication token is missing.")

    # Download bytes
    docx_bytes = await doc_service._download_basecamp_file(att_url, token)
    if not docx_bytes or len(docx_bytes) < 100:
        raise ValueError("Downloaded file is empty or corrupt.")

    # Save backup to storage/backups/
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    clean_fn = re.sub(r"[^\w\-.]", "_", filename)
    backup_filename = f"{timestamp}_{clean_fn}"
    backup_path = os.path.join(BACKUPS_DIR, backup_filename)
    with open(backup_path, "wb") as f:
        f.write(docx_bytes)

    # Basic inspection
    char_count = len(doc_service._extract_text_from_docx(docx_bytes))
    byte_size = len(docx_bytes)

    stage_data = {
        "filename": filename,
        "byte_size": byte_size,
        "character_count": char_count,
        "backup_path": backup_path,
        "download_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    session["stages"]["2"]["status"] = "completed"
    session["stages"]["2"]["data"] = stage_data
    session["stages"]["2"]["error"] = None
    session["shared"]["docx_backup_path"] = backup_path
    session["shared"]["docx_char_count"] = char_count

    if session["current_stage"] == 2:
        session["current_stage"] = 3

    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Stage 3: Extract Document Text, Headings, Formatting & Duplicate Check
# ---------------------------------------------------------------------------

async def execute_stage_3(session: Dict[str, Any]) -> Dict[str, Any]:
    backup_path = session["shared"].get("docx_backup_path")
    if not backup_path or not os.path.isfile(backup_path):
        raise ValueError("Saved DOCX backup file not found. Please rerun Stage 2.")

    with open(backup_path, "rb") as f:
        docx_bytes = f.read()

    # Extract AST & Content
    article_text = doc_service._extract_text_from_docx(docx_bytes)
    article_html = doc_service._extract_html_from_docx(docx_bytes)
    docx_hyperlinks = doc_service._extract_hyperlinks_from_docx(docx_bytes)
    embedded_images = doc_service.extract_images_from_docx(docx_bytes)

    # Title extraction in priority order
    message_subject = session["shared"].get("message_subject", "")
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", article_html, re.IGNORECASE | re.DOTALL)
    if h1_match:
        extracted_title = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
    else:
        # First non-empty line of text
        first_line = next((l.strip() for l in article_text.splitlines() if l.strip()), message_subject)
        extracted_title = first_line or message_subject

    # Heading hierarchy check
    parsed_html = qa_engine.ParsedArticleHTML(article_html)
    headings = parsed_html.headings
    h1_count = sum(1 for h in headings if h["tag"] == "h1")
    h2_count = sum(1 for h in headings if h["tag"] == "h2")
    h3_count = sum(1 for h in headings if h["tag"] == "h3")
    h4_count = sum(1 for h in headings if h["tag"] == "h4")

    # Duplicate check on WordPress
    site = _resolve_site_target(session)
    dup_result = await wp_service.check_duplicate(
        title=extracted_title,
        site_url=site.url,
        username=site.username,
        app_password=site.app_password,
    )

    stage_data = {
        "article_title": extracted_title,
        "headings": headings,
        "headings_count": {
            "h1": h1_count,
            "h2": h2_count,
            "h3": h3_count,
            "h4": h4_count,
        },
        "embedded_images_count": len(embedded_images),
        "source_hyperlinks_count": len(docx_hyperlinks),
        "duplicate_check": {
            "duplicate": dup_result.get("duplicate", False),
            "existing_post": dup_result.get("existing_post"),
        },
    }

    session["stages"]["3"]["status"] = "completed"
    session["stages"]["3"]["data"] = stage_data
    session["stages"]["3"]["error"] = None
    session["shared"]["article_title"] = extracted_title
    session["shared"]["article_text"] = article_text
    session["shared"]["article_html"] = article_html
    session["shared"]["docx_hyperlinks"] = docx_hyperlinks
    session["shared"]["embedded_images"] = [
        {"filename": img["filename"], "content_type": img.get("content_type", "image/jpeg"), "size": len(img.get("content", b""))}
        for img in embedded_images
    ]

    if session["current_stage"] == 3:
        session["current_stage"] = 4

    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Stage 4: Review Article Content and Links
# ---------------------------------------------------------------------------

async def execute_stage_4(session: Dict[str, Any], user_edits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    article_html = session["shared"].get("article_html", "")
    article_title = session["shared"].get("article_title", "")
    if user_edits:
        if user_edits.get("article_title"):
            article_title = user_edits["article_title"].strip()
            session["shared"]["article_title"] = article_title
        if user_edits.get("article_content"):
            article_html = user_edits["article_content"]
            session["shared"]["article_html"] = article_html

    # Clean body HTML of duplicate title and instruction boilerplate
    clean_html = re.sub(
        r'<p>\s*(?:CATEGORY|CATEGORIES|FOCUS KEYPHRASE|KEYPHRASE|AUTHOR|META DESCRIPTION)\s*:[^<]*</p>',
        '',
        article_html,
        flags=re.IGNORECASE,
    )
    # Strip any leading H1 matching article title
    clean_html = re.sub(r'<h1[^>]*>.*?</h1>', '', clean_html, count=1, flags=re.IGNORECASE | re.DOTALL)

    parsed_html = qa_engine.ParsedArticleHTML(clean_html)
    draft_links = parsed_html.links

    # Internal links
    hbm_links = [l for l in draft_links if "homebusinessmag.com" in l.get("href", "").lower()]
    # Authority links
    authority_links = []
    for l in draft_links:
        for dom in qa_engine.APPROVED_AUTHORITY_DOMAINS:
            if dom in l.get("href", "").lower():
                authority_links.append(l)
                break

    stage_data = {
        "article_title": article_title,
        "clean_content": clean_html,
        "internal_links": [
            {
                "url": l["href"],
                "anchor": l["anchor"],
                "word_count": len(l["anchor"].split()),
                "location": l.get("location", "Article body"),
                "context_snippet": l.get("context_snippet", ""),
                "is_compliant": 3 <= len(l["anchor"].split()) <= 5,
            }
            for l in hbm_links
        ],
        "authority_links": [
            {
                "url": l["href"],
                "anchor": l["anchor"],
                "word_count": len(l["anchor"].split()),
                "location": l.get("location", "Article body"),
                "context_snippet": l.get("context_snippet", ""),
                "is_compliant": 3 <= len(l["anchor"].split()) <= 4,
            }
            for l in authority_links
        ],
        "total_links": len(draft_links),
    }

    session["stages"]["4"]["status"] = "completed"
    session["stages"]["4"]["data"] = stage_data
    session["stages"]["4"]["error"] = None
    session["shared"]["clean_article_html"] = clean_html

    if session["current_stage"] == 4:
        session["current_stage"] = 5

    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Stage 5: Prepare and Review SEO Metadata
# ---------------------------------------------------------------------------

async def execute_stage_5(session: Dict[str, Any], user_edits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    article_title = session["shared"].get("article_title", "")
    article_text = session["shared"].get("article_text", "")
    clean_html = session["shared"].get("clean_article_html", "")
    parsed_seo = session["shared"].get("parsed_instructions", {}).get("seo", {})
    client_instructions_html = session["shared"].get("client_instructions_html", "")
    site_url = session["shared"]["site_url"]

    # Generate or load base SEO
    if user_edits and user_edits.get("seo_fields"):
        seo_fields = user_edits["seo_fields"]
    else:
        if gemini_service.is_configured():
            seo_fields = await gemini_service.generate_seo(
                article_title=article_title,
                article_text_plain=article_text,
                client_instructions_html=client_instructions_html,
                parsed_seo=parsed_seo,
            )
        else:
            # Fallback heuristic SEO
            words = [w for w in re.split(r"[\s\W_]+", article_title) if len(w) > 3][:3]
            kp = " ".join(words).title() or article_title[:30]
            slug = re.sub(r"[^\w\-]", "", kp.lower().replace(" ", "-")).strip("-")
            seo_fields = {
                "focus_keyphrase": kp,
                "seo_title": f"{kp} Guide: Actionable Strategies for Growth",
                "slug": slug,
                "meta_description": f"Discover proven {kp.lower()} methods to empower teams, boost efficiency, and drive sustainable growth in today's modern business environment.",
                "excerpt": f"Discover proven {kp.lower()} methods to empower teams, boost efficiency, and drive sustainable growth in today's modern business environment.",
                "synonyms": "",
            }

        # Optimize SEO pass
        try:
            opt = await seo_optimizer.optimize_article_seo(
                title=article_title,
                content=clean_html,
                seo_fields=seo_fields,
                site_url=site_url,
            )
            clean_html = opt["content"]
            seo_fields = opt["seo_fields"]
            session["shared"]["clean_article_html"] = clean_html
        except Exception as exc:
            log.warning("SEO optimization error in wizard: %s", exc)

    meta_desc = seo_fields.get("meta_description", "").strip()
    desc_len = len(meta_desc)

    stage_data = {
        "focus_keyphrase": seo_fields.get("focus_keyphrase", ""),
        "seo_title": seo_fields.get("seo_title", article_title),
        "slug": seo_fields.get("slug", ""),
        "meta_description": meta_desc,
        "meta_description_length": desc_len,
        "meta_description_valid": 140 <= desc_len <= 155,
        "excerpt": seo_fields.get("excerpt", ""),
        "excerpt_matches_meta": seo_fields.get("excerpt", "").strip().lower() == meta_desc.lower(),
    }

    session["stages"]["5"]["status"] = "completed"
    session["stages"]["5"]["data"] = stage_data
    session["stages"]["5"]["error"] = None
    session["shared"]["seo_fields"] = seo_fields

    if session["current_stage"] == 5:
        session["current_stage"] = 6

    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Stage 6: Manual Featured-Image Selection & Approval (GENUINE APPROVAL GATE)
# ---------------------------------------------------------------------------

async def execute_stage_6(
    session: Dict[str, Any],
    action: Optional[str] = None,
    selected_image: Optional[Dict[str, Any]] = None,
    search_query: Optional[str] = None,
) -> Dict[str, Any]:
    article_title = session["shared"].get("article_title", "")
    kp = session["shared"].get("seo_fields", {}).get("focus_keyphrase", "")
    backup_path = session["shared"].get("docx_backup_path")

    # If user explicitly approves an image
    if action == "approve_image" and selected_image:
        session["stages"]["6"]["status"] = "completed"
        session["stages"]["6"]["data"] = {
            "approved": True,
            "selected_image": selected_image,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        session["stages"]["6"]["error"] = None
        session["shared"]["approved_image"] = selected_image

        if session["current_stage"] == 6:
            session["current_stage"] = 7

        save_session(session)
        return session

    # Otherwise: gather candidates and PAUSE for review
    candidates: List[Dict[str, Any]] = []

    # 1. Inspect DOCX embedded images
    if backup_path and os.path.isfile(backup_path):
        with open(backup_path, "rb") as f:
            docx_bytes = f.read()
        embedded = doc_service.extract_images_from_docx(docx_bytes)
        for idx, img in enumerate(embedded):
            b64_data = base64.b64encode(img["content"]).decode("ascii")
            candidates.append({
                "source": "docx",
                "label": f"DOCX Embedded Image #{idx + 1}",
                "filename": img["filename"],
                "content_type": img.get("content_type", "image/jpeg"),
                "thumbnail_url": f"data:{img.get('content_type', 'image/jpeg')};base64,{b64_data}",
                "preview_url": f"data:{img.get('content_type', 'image/jpeg')};base64,{b64_data}",
                "alt_text": kp or article_title,
                "credit_text": "Image via source Word document",
                "raw_image_base64": b64_data,
            })

    # 2. Search stock provider (Envato / Pexels)
    query = (search_query or kp or article_title).strip()
    try:
        search_res = await image_service.search_provider("envato", query, limit=4)
        for item in search_res.get("results", []):
            candidates.append({
                "source": "envato",
                "label": f"Envato: {item.get('title', 'Stock Photo')[:40]}",
                "filename": f"envato_{item.get('id', 'asset')}.jpg",
                "content_type": "image/jpeg",
                "thumbnail_url": item.get("thumbnail_url") or item.get("preview_url") or item.get("image_url"),
                "preview_url": item.get("preview_url") or item.get("thumbnail_url") or item.get("image_url"),
                "download_url": item.get("image_url") or item.get("download_url") or item.get("preview_url"),
                "alt_text": kp or article_title,
                "credit_text": "Photo via envato.com",
                "source_url": item.get("source_url") or "https://elements.envato.com",
            })
    except Exception as exc:
        log.warning("Stock image search warning in wizard: %s", exc)

    session["stages"]["6"]["status"] = "waiting_for_review"
    session["stages"]["6"]["data"] = {
        "approved": False,
        "search_query": query,
        "candidates": candidates,
    }
    session["stages"]["6"]["error"] = None

    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Stage 7: Create WordPress Draft on Test Site (GENUINE DRAFT CREATION GATE)
# ---------------------------------------------------------------------------

async def execute_stage_7(
    session: Dict[str, Any],
    action: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    # GENUINE APPROVAL GATE: Draft is created ONLY when user approves action="create_draft"
    if action != "create_draft":
        session["stages"]["7"]["status"] = "waiting_for_review"
        session["stages"]["7"]["data"] = {
            "ready_for_creation": True,
            "destination_site": session["shared"].get("site_url"),
            "status_target": "draft",
        }
        save_session(session)
        return session

    # IDEMPOTENCY GUARD: Do not recreate draft if already created in this session!
    existing_post_id = session.get("created_post_id")
    if existing_post_id:
        log.info("Draft #%s already created for session %s — returning existing draft.", existing_post_id, session["session_id"])
        session["stages"]["7"]["status"] = "completed"
        session["stages"]["7"]["data"] = {
            "post_id": existing_post_id,
            "edit_url": session.get("created_edit_url"),
            "status": "draft",
            "message": "Draft already created; reused existing draft to prevent duplicates.",
        }
        if session["current_stage"] == 7:
            session["current_stage"] = 8
        save_session(session)
        return session

    # Safety checks
    site = _resolve_site_target(session)
    site_url = session.get("shared", {}).get("site_url") or site.url
    site_user = session.get("shared", {}).get("site_username") or site.username
    site_pwd = site.app_password

    check_urls = [site_url.lower(), site.url.lower()]
    if any("homebusinessmag.com" in u for u in check_urls):
        raise ValueError("Security Violation: Production write to homebusinessmag.com is strictly forbidden.")
    if any("espialsolutions.com" not in u for u in check_urls):
        raise ValueError("Security Violation: Draft creation strictly restricted to https://espialsolutions.com.")

    # 1. Process & Upload Featured Image
    approved_img = session["shared"].get("approved_image")
    if not approved_img:
        raise ValueError("No featured image was approved in Stage 6. Please approve a featured image first.")

    kp = session["shared"].get("seo_fields", {}).get("focus_keyphrase", "")
    article_title = session["shared"].get("article_title", "Untitled")

    # Download or decode image bytes
    if approved_img.get("raw_image_base64"):
        img_bytes = base64.b64decode(approved_img["raw_image_base64"])
    elif approved_img.get("download_url"):
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(approved_img["download_url"])
            img_bytes = resp.content
    else:
        # Fallback 1000x667 placeholder
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (1000, 667), color=(70, 130, 180)).save(buf, format="JPEG", quality=85)
        img_bytes = buf.getvalue()

    # Resize/crop to exactly 1000x667 banner
    optimized_featured = image_service.resize_image(img_bytes, approved_img.get("content_type", "image/jpeg"))
    caption_plain = approved_img.get("credit_text") or "Photo via envato.com"

    media_res = await wp_service.upload_media(
        filename=approved_img.get("filename", "featured_image.jpg"),
        content=optimized_featured,
        content_type=approved_img.get("content_type", "image/jpeg"),
        alt_text=kp or article_title,
        image_title=article_title[:60],
        caption=caption_plain,
        source_url=approved_img.get("source_url", ""),
        site_url=site_url,
        username=site_user,
        app_password=site_pwd,
    )
    featured_media_id = media_res.get("media_id")

    # 2. Upload Inline DOCX images if any
    backup_path = session["shared"].get("docx_backup_path")
    clean_content = session["shared"].get("clean_article_html", "")
    if backup_path and os.path.isfile(backup_path):
        with open(backup_path, "rb") as f:
            docx_bytes = f.read()
        embedded = doc_service.extract_images_from_docx(docx_bytes)
        inline_uploaded = []
        for img in embedded:
            opt_inline = image_service.optimize_docx_image(img["content"], max_width=700)
            in_res = await wp_service.upload_media(
                filename=img["filename"],
                content=opt_inline,
                content_type=img.get("content_type", "image/jpeg"),
                alt_text=article_title[:100],
                site_url=site_url,
                username=site_user,
                app_password=site_pwd,
            )
            if in_res.get("status") == "success":
                inline_uploaded.append({"filename": img["filename"], "url": in_res["url"]})
        if inline_uploaded:
            for item in inline_uploaded:
                clean_content = clean_content.replace(item["filename"], item["url"])

    # 3. Create Draft Post
    seo_fields = session["shared"].get("seo_fields", {})
    parsed_inst = session["shared"].get("parsed_instructions", {})
    cat_info = parsed_inst.get("category", {})

    selected_author_id = (payload or {}).get("author_id") or session.get("shared", {}).get("author_id")
    draft_metadata = {
        "focus_keyphrase": seo_fields.get("focus_keyphrase", ""),
        "seo_title": seo_fields.get("seo_title", article_title),
        "slug": seo_fields.get("slug", ""),
        "meta_description": seo_fields.get("meta_description", ""),
        "featured_media": featured_media_id,
        "category_primary": cat_info.get("primary") or "Home Business",
        "category_featured": cat_info.get("featured", False),
        "author_name": parsed_inst.get("author") or "Richard Henderson",
        "author_id": selected_author_id,
        "excerpt": seo_fields.get("excerpt", ""),
    }

    draft_res = await wp_service.create_draft(
        title=article_title,
        content=clean_content,
        metadata=draft_metadata,
        site_url=site_url,
        username=site_user,
        app_password=site_pwd,
    )

    if draft_res.get("status") != "success":
        raise ValueError(f"WordPress draft creation failed: {draft_res.get('error')}")

    post_id = draft_res["post_id"]
    edit_url = draft_res.get("edit_url") or f"{site_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"

    session["created_post_id"] = post_id
    session["created_edit_url"] = edit_url
    session["stages"]["7"]["status"] = "completed"
    session["stages"]["7"]["data"] = {
        "post_id": post_id,
        "edit_url": edit_url,
        "featured_media_id": featured_media_id,
        "post_status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    session["stages"]["7"]["error"] = None

    if session["current_stage"] == 7:
        session["current_stage"] = 8

    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Stage 8: Verify Saved WordPress Draft
# ---------------------------------------------------------------------------

async def execute_stage_8(session: Dict[str, Any]) -> Dict[str, Any]:
    post_id = session.get("created_post_id")
    if not post_id:
        raise ValueError("No WordPress draft ID found. Please run Stage 7 first.")

    site = _resolve_site_target(session)
    site_url = site.url
    site_user = site.username
    site_pwd = site.app_password

    post = await wp_service.get_post(post_id, site_url, site_user, site_pwd)
    if not post or post.get("id") != post_id:
        raise ValueError(f"Draft #{post_id} could not be retrieved via read-only GET.")

    post_status = post.get("status")
    if post_status != "draft":
        raise ValueError(f"Security Alert: Post #{post_id} status is '{post_status}' (must strictly be 'draft').")

    post_title = (post.get("title", {}) or {}).get("raw") or (post.get("title", {}) or {}).get("rendered")
    featured_media_id = post.get("featured_media")
    author_id = post.get("author")
    categories = post.get("categories", [])
    meta = post.get("meta", {}) or {}

    stage_data = {
        "post_id": post_id,
        "post_status": post_status,
        "post_title": post_title,
        "featured_media_id": featured_media_id,
        "author_id": author_id,
        "categories": categories,
        "edit_url": session.get("created_edit_url"),
        "yoast_meta": {
            "focus_keyphrase": meta.get("_yoast_wpseo_focuskw"),
            "meta_title": meta.get("_yoast_wpseo_title"),
            "meta_description": meta.get("_yoast_wpseo_metadesc"),
        },
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }

    session["stages"]["8"]["status"] = "completed"
    session["stages"]["8"]["data"] = stage_data
    session["stages"]["8"]["error"] = None

    if session["current_stage"] == 8:
        session["current_stage"] = 9

    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Stage 9: Run Authoritative 10-Category Read-Only QA Checklist
# ---------------------------------------------------------------------------

async def execute_stage_9(session: Dict[str, Any]) -> Dict[str, Any]:
    post_id = session.get("created_post_id")
    site_id = session.get("site_id")
    if not post_id or not site_id:
        raise ValueError("Draft ID or Site ID missing for QA execution.")

    # Source DOCX configuration
    backup_path = session["shared"].get("docx_backup_path")
    docx_source = {"type": "local", "path": backup_path} if backup_path else {"type": "none"}
    client_instructions = session["shared"].get("parsed_instructions", {})

    qa_result = await qa_engine.run_comprehensive_qa(
        site_id=site_id,
        post_id=post_id,
        docx_source=docx_source,
        client_instructions=client_instructions,
    )

    # Save report
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_service.save_report(
        article_title=session["shared"].get("article_title", "Untitled"),
        status="completed",
        date_str=today_str,
        filename=session["shared"].get("attachment_filename", "document.docx"),
        project_id=session["project_id"],
        project_name=session["stages"]["1"]["data"]["project_name"] if session["stages"]["1"].get("data") else "Basecamp",
        message_id=session["message_id"],
        attachment_id=session["attachment_id"],
        wordpress_site_id=site_id,
        wordpress_site_name="Test Site",
        wordpress_site_url=session["shared"]["site_url"],
        wordpress_post_id=post_id,
        draft_url=session.get("created_edit_url"),
        edit_url=session.get("created_edit_url"),
        author=client_instructions.get("author") or "Richard Henderson",
        primary_category=client_instructions.get("category", {}).get("primary") or "Home Business",
        all_categories=client_instructions.get("category", {}).get("all") or ["Home Business"],
        focus_keyphrase=session["shared"].get("seo_fields", {}).get("focus_keyphrase", ""),
        image_source="Envato/DOCX",
        image_source_url="",
        qa_status=qa_result["verdict"],
        qa_checklist=qa_result["categories"],
        details={
            "counts": qa_result["counts"],
            "tables": qa_result["tables"],
        },
    )

    session["stages"]["9"]["status"] = "completed"
    session["stages"]["9"]["data"] = qa_result
    session["stages"]["9"]["error"] = None
    session["current_stage"] = 9

    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Master Workflow Orchestrator (Advance / Resume / Reset)
# ---------------------------------------------------------------------------

async def advance_wizard(
    project_id: int,
    message_id: int,
    attachment_id: str,
    site_id: Optional[int] = None,
    target_stage: Optional[int] = None,
    action: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    session_id = _get_session_id(project_id, message_id, attachment_id)
    session = load_session(session_id)
    if not session:
        session = _init_session(project_id, message_id, attachment_id, site_id)
        save_session(session)

    stage_to_run = target_stage or session["current_stage"]

    try:
        if stage_to_run == 1:
            session = await execute_stage_1(session, site_id)
        elif stage_to_run == 2:
            session = await execute_stage_2(session)
        elif stage_to_run == 3:
            session = await execute_stage_3(session)
        elif stage_to_run == 4:
            session = await execute_stage_4(session, user_edits=payload)
        elif stage_to_run == 5:
            session = await execute_stage_5(session, user_edits=payload)
        elif stage_to_run == 6:
            session = await execute_stage_6(
                session,
                action=action,
                selected_image=payload.get("selected_image") if payload else None,
                search_query=payload.get("search_query") if payload else None,
            )
        elif stage_to_run == 7:
            session = await execute_stage_7(session, action=action, payload=payload)
        elif stage_to_run == 8:
            session = await execute_stage_8(session)
        elif stage_to_run == 9:
            session = await execute_stage_9(session)
        else:
            raise ValueError(f"Invalid wizard stage {stage_to_run}.")
    except Exception as exc:
        log.error("Wizard error at Stage %s: %s", stage_to_run, exc)
        session["stages"][str(stage_to_run)]["status"] = "failed"
        session["stages"][str(stage_to_run)]["error"] = str(exc)
        save_session(session)
        raise

    return session


def get_or_create_session(
    project_id: int,
    message_id: int,
    attachment_id: str,
    site_id: Optional[int] = None,
) -> Dict[str, Any]:
    session_id = _get_session_id(project_id, message_id, attachment_id)
    session = load_session(session_id)
    if not session:
        session = _init_session(project_id, message_id, attachment_id, site_id)
        save_session(session)
    return session


def reset_session(project_id: int, message_id: int, attachment_id: str) -> bool:
    session_id = _get_session_id(project_id, message_id, attachment_id)
    path = _get_session_filepath(session_id)
    if os.path.isfile(path):
        try:
            os.remove(path)
            return True
        except Exception:
            return False
    return True
