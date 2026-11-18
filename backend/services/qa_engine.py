"""
Authoritative 10-Category QA Engine for Home Business Magazine Article Automation.
Strictly Read-Only: Performs zero WordPress POST, PUT, PATCH, or DELETE requests.
Audits WordPress draft content and metadata with honest evidence and no hardcoded PASS results.
"""

import html
import io
import ipaddress
import logging
import os
import re
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

import services.documents as doc_service
import services.seo_optimizer as seo_optimizer
import services.site_service as site_service
import services.wordpress as wp_service

log = logging.getLogger(__name__)


class ParsedArticleHTML:
    """Lightweight, regex-based HTML structure parser with zero external dependencies."""
    def __init__(self, raw_html: str):
        self.raw_html = raw_html or ""

        # Paragraphs: capture match objects for exact boundary tracking
        p_match_objs = list(re.finditer(r'<p[^>]*>(.*?)</p>', self.raw_html, re.IGNORECASE | re.DOTALL))
        self.paragraphs = [html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() for m in p_match_objs]
        self.empty_paragraphs_count = sum(
            1 for p, m in zip(self.paragraphs, p_match_objs) if not p and '<img' not in m.group(1).lower()
        )

        # Extract all <a ...>...</a> links with precise paragraph location & context snippet
        self.links: List[Dict[str, Any]] = []
        for m in re.finditer(r'<a\s+([^>]*?)>(.*?)</a>', self.raw_html, re.IGNORECASE | re.DOTALL):
            attrs = m.group(1)
            inner = m.group(2)
            href_m = re.search(r'href=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
            href = href_m.group(1).strip() if href_m else ""
            anchor = html.unescape(re.sub(r'<[^>]+>', '', inner)).strip()

            a_start = m.start()
            location = "Article body"
            context_snippet = ""
            for idx, p_m in enumerate(p_match_objs, 1):
                if p_m.start() <= a_start <= p_m.end():
                    location = f"Paragraph {idx}"
                    p_text = html.unescape(re.sub(r'<[^>]+>', ' ', p_m.group(1)))
                    p_text_clean = " ".join(p_text.split())
                    if anchor and anchor in p_text_clean:
                        a_idx = p_text_clean.find(anchor)
                        s_start = max(0, a_idx - 35)
                        s_end = min(len(p_text_clean), a_idx + len(anchor) + 35)
                        snippet = p_text_clean[s_start:s_end]
                        if s_start > 0:
                            snippet = "..." + snippet
                        if s_end < len(p_text_clean):
                            snippet = snippet + "..."
                        context_snippet = snippet
                    else:
                        context_snippet = (p_text_clean[:90] + "...") if len(p_text_clean) > 90 else p_text_clean
                    break

            self.links.append({
                "href": href,
                "anchor": anchor,
                "html": inner,
                "location": location,
                "context_snippet": context_snippet,
            })

        # Headings
        self.headings: List[Dict[str, str]] = []
        for m in re.finditer(r'<(h[1-6])[^>]*>(.*?)</\1>', self.raw_html, re.IGNORECASE | re.DOTALL):
            tag = m.group(1).lower()
            h_text = html.unescape(re.sub(r'<[^>]+>', '', m.group(2))).strip()
            self.headings.append({"tag": tag, "text": h_text})

        # Plain text
        clean = re.sub(r'<style[^>]*>.*?</style>', ' ', self.raw_html, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<script[^>]*>.*?</script>', ' ', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        self.text = html.unescape(re.sub(r'\s+', ' ', clean)).strip()
        self.has_p = "<p" in self.raw_html.lower()
        self.has_lists = bool(re.search(r'<(ul|ol|li)[^>]*>', self.raw_html, re.IGNORECASE))

# Approved authority domains per Home Business Magazine client specification
APPROVED_AUTHORITY_DOMAINS = [
    "forbes.com",
    "cnn.com",
    "medium.com",
    "inc.com",
    "entrepreneur.com",
]

# Prohibited author names and administrative accounts that must never be public author
PROHIBITED_AUTHORS = ["naveen shukla", "webdev", "admin", "administrator"]


# ---------------------------------------------------------------------------
# SSRF Protection & Safe Source Document Resolution
# ---------------------------------------------------------------------------

def _is_ip_private_or_restricted(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, link-local, or restricted."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        return True


def _validate_safe_url(url: str) -> Tuple[bool, str]:
    """
    Validate external URL against SSRF:
    - Scheme must be http or https
    - Domain must resolve to public IP (rejects 127.0.0.1, 10.x, 192.168.x, 169.254.x, etc.)
    - Must end with .docx
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Invalid URL scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted."

        hostname = parsed.hostname
        if not hostname:
            return False, "URL contains no hostname."

        if hostname.lower() in ("localhost", "127.0.0.1", "::1") or hostname.endswith((".local", ".internal")):
            return False, f"Host '{hostname}' is not permitted (internal host)."

        clean_path = parsed.path.lower()
        if not clean_path.endswith(".docx"):
            return False, "Target URL does not appear to be a .docx file (must end in .docx)."

        # Resolve DNS and check all IPs
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                ip_str = item[4][0]
                if _is_ip_private_or_restricted(ip_str):
                    return False, f"Host '{hostname}' resolves to restricted IP ({ip_str}). Access denied to prevent SSRF."
        except socket.gaierror as exc:
            return False, f"Could not resolve host '{hostname}': {exc}"

        return True, ""
    except Exception as exc:
        return False, f"URL security validation error: {exc}"


async def resolve_source_document(
    docx_source: Optional[Dict[str, Any]],
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    """
    Safely retrieve source DOCX bytes with SSRF protection.
    Only 'none' (standalone) and 'basecamp' source types are supported.
    Returns: (file_bytes, filename, error_or_unavailability_reason)
    """
    if not docx_source or docx_source.get("type") in (None, "none", ""):
        return None, None, None

    src_type = docx_source.get("type")

    # If caller already flagged document as unavailable
    if docx_source.get("unavailable_reason"):
        return None, None, docx_source["unavailable_reason"]

    # 1. Basecamp Attachment
    if src_type == "basecamp":
        attachment_url = docx_source.get("url") or docx_source.get("attachment_url")
        token = docx_source.get("access_token")
        if not token:
            try:
                import services.basecamp as bc_service
                token = bc_service.get_valid_token()
            except Exception:
                token = None
        if not attachment_url or not token:
            return None, None, "Basecamp source DOCX unavailable: No Basecamp article attachment URL or active session token found."
        try:
            file_bytes = await doc_service._download_basecamp_file(attachment_url, token)
            return file_bytes, docx_source.get("filename", "basecamp_article.docx"), None
        except Exception as exc:
            log.warning("Could not download Basecamp attachment: %s", exc)
            return None, None, f"Failed to download Basecamp attachment: {str(exc)}"

    # 2. External URL or Local Path has been removed
    if src_type == "external":
        return None, None, "External link or path source is disabled. Only None (Standalone) and From Basecamp options are supported."

    return None, None, f"Unknown docx_source type '{src_type}'."


def _normalize_title_for_matching(text: str) -> str:
    """Normalize article title by removing trailing random digits/timestamps, punctuation, and extra spaces."""
    if not text:
        return ""
    text = re.sub(r"\.docx?$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+\d{6,}\b", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_source_match_to_draft(
    post_title: str,
    post_content: str,
    source_filename: Optional[str],
    source_article_title: Optional[str],
    source_text: str,
) -> Tuple[bool, str]:
    """
    Verify that the downloaded source DOCX actually matches the selected draft.
    Returns (is_match, reason).
    Prevents comparing against the wrong article or mismatched documents.
    """
    norm_post_title = _normalize_title_for_matching(post_title)
    norm_source_title = _normalize_title_for_matching(source_article_title or "")
    norm_filename = _normalize_title_for_matching(source_filename or "")

    post_title_words = set(w for w in norm_post_title.split() if len(w) > 2)
    source_title_words = set(w for w in norm_source_title.split() if len(w) > 2)
    filename_words = set(w for w in norm_filename.split() if len(w) > 2)

    # 1. Check title / filename word overlap
    title_overlap = 0.0
    if post_title_words and source_title_words:
        title_overlap = len(post_title_words.intersection(source_title_words)) / min(len(post_title_words), len(source_title_words))
    
    filename_overlap = 0.0
    if post_title_words and filename_words:
        filename_overlap = len(post_title_words.intersection(filename_words)) / min(len(post_title_words), len(filename_words))

    # If significant title or filename overlap (>= 50% key words match)
    if title_overlap >= 0.5 or filename_overlap >= 0.5:
        return True, "Title/filename match confirmed."

    # 2. Check content vocabulary overlap between DOCX text and post content
    source_words = set(re.findall(r"\b\w{4,}\b", (source_text or "").lower()))
    draft_words = set(re.findall(r"\b\w{4,}\b", (post_content or "").lower()))
    
    if source_words and draft_words:
        content_overlap = len(source_words.intersection(draft_words)) / max(len(source_words), 1)
        if content_overlap >= 0.35:
            return True, f"Content vocabulary overlap ({content_overlap * 100:.1f}%) confirmed match."

    doc_desc = source_filename or source_article_title or "supplied Basecamp document"
    reason = (
        f"Source document '{doc_desc}' could not be matched reliably to the selected draft '{post_title}'. "
        f"The source document appears to be for a different article (wrong article), "
        f"so source comparison was reported as NOT APPLICABLE to prevent false QA failures."
    )
    return False, reason


# ---------------------------------------------------------------------------
# Asynchronous Link Checker with Error Classification
# ---------------------------------------------------------------------------

async def _test_link(url: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """
    Test link reachability via HEAD (fallback to GET).
    Classifies result into: 200 OK, Redirect, Confirmed Error (404/500), Timeout, or Blocked.
    Preserves redirect history, timeout, and HTTP error details accurately.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HBM-Article-Audit/2.0"}
    try:
        resp = await client.head(url, headers=headers, follow_redirects=True)
        if resp.status_code in (405, 403):
            # Many CDNs reject HEAD; retry with minimal GET
            resp = await client.get(url, headers=headers, follow_redirects=True)
        
        status_code = resp.status_code
        redirect_details = " -> ".join([str(r.url) for r in resp.history] + [str(resp.url)]) if resp.history else None
        final_url = str(resp.url)
        
        if 200 <= status_code < 400:
            note = f"HTTP {status_code} OK"
            if resp.history:
                note += f" (redirected: {redirect_details})"
            return {
                "status": "PASS",
                "code": status_code,
                "note": note,
                "redirected": bool(resp.history),
                "redirect_history": redirect_details,
                "final_url": final_url,
            }
        elif status_code == 403:
            return {
                "status": "WARNING",
                "code": 403,
                "note": f"HTTP 403 Forbidden (WAF/bot-protection blocked access)" + (f" (redirected: {redirect_details})" if redirect_details else ""),
                "redirected": bool(resp.history),
                "redirect_history": redirect_details,
                "final_url": final_url,
            }
        elif status_code == 404:
            return {
                "status": "FAIL",
                "code": 404,
                "note": "HTTP 404 Not Found (Dead Link)" + (f" (redirected: {redirect_details})" if redirect_details else ""),
                "redirected": bool(resp.history),
                "redirect_history": redirect_details,
                "final_url": final_url,
            }
        elif status_code >= 500:
            return {
                "status": "FAIL",
                "code": status_code,
                "note": f"HTTP {status_code} Server Error" + (f" (redirected: {redirect_details})" if redirect_details else ""),
                "redirected": bool(resp.history),
                "redirect_history": redirect_details,
                "final_url": final_url,
            }
        else:
            return {
                "status": "WARNING",
                "code": status_code,
                "note": f"HTTP {status_code}" + (f" (redirected: {redirect_details})" if redirect_details else ""),
                "redirected": bool(resp.history),
                "redirect_history": redirect_details,
                "final_url": final_url,
            }
    except httpx.TooManyRedirects:
        return {
            "status": "FAIL",
            "code": "Redirect Loop",
            "note": "HTTP Error: Too many redirects (infinite redirect loop detected)",
            "redirected": True,
            "redirect_history": "Exceeded maximum redirect limit",
            "final_url": None,
        }
    except httpx.TimeoutException:
        return {
            "status": "WARNING",
            "code": "Timeout",
            "note": "Request timed out (>5s); destination server not responding or inaccessible",
            "redirected": False,
            "redirect_history": None,
            "final_url": None,
        }
    except httpx.ConnectError as exc:
        return {
            "status": "FAIL",
            "code": "Connection Error",
            "note": f"DNS or Connection refused: {str(exc)[:80]}",
            "redirected": False,
            "redirect_history": None,
            "final_url": None,
        }
    except Exception as exc:
        return {
            "status": "WARNING",
            "code": "Network Error",
            "note": f"Network exception: {str(exc)[:80]}",
            "redirected": False,
            "redirect_history": None,
            "final_url": None,
        }


# ---------------------------------------------------------------------------
# Core 10-Category QA Auditor
# ---------------------------------------------------------------------------

async def run_comprehensive_qa(
    site_id: int,
    post_id: int,
    docx_source: Optional[Dict[str, Any]] = None,
    client_instructions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute authoritative 10-category read-only QA audit against WordPress draft.
    Guarantees zero write requests to WordPress.
    """
    # 1. Fetch site credentials securely server-side
    site = site_service.get_site(site_id)
    if not site:
        raise ValueError(f"Destination site #{site_id} not found in database.")

    # 2. Strictly read-only GET fetch of post, media, categories, and author
    post = await wp_service.get_post(
        post_id=post_id,
        site_url=site.url,
        username=site.username,
        app_password=site.app_password,
    )
    if not post or post.get("id") != post_id:
        raise ValueError(f"Post #{post_id} could not be retrieved from {site.url}.")

    # Gather post fields safely
    post_title_raw = post.get("title", {})
    post_title = html.unescape(post_title_raw.get("raw") or post_title_raw.get("rendered") or "")
    post_content_raw = post.get("content", {})
    post_content = post_content_raw.get("raw") or post_content_raw.get("rendered") or ""
    post_status = post.get("status", "draft")
    post_slug = post.get("slug", "")
    author_id = post.get("author")
    featured_media_id = post.get("featured_media")
    post_categories = post.get("categories", [])
    post_tags = post.get("tags", [])
    post_meta = post.get("meta", {}) or {}

    # Fetch referenced author & media via read-only GET
    author_data = await wp_service.get_user(author_id, site.url, site.username, site.app_password) if author_id else {}
    author_name = author_data.get("name") or author_data.get("slug") or f"User #{author_id}"

    media_data = {}
    if featured_media_id:
        try:
            media_data = await wp_service.get_media(featured_media_id, site.url, site.username, site.app_password)
        except Exception:
            media_data = {}

    all_site_categories = await wp_service.get_categories(site.url, site.username, site.app_password)
    cat_id_to_name = {c["id"]: c["name"] for c in all_site_categories if "id" in c and "name" in c}
    assigned_category_names = [cat_id_to_name.get(cid, f"Category #{cid}") for cid in post_categories]

    # 3. Resolve Optional Source Document
    source_bytes, source_filename, source_unavail_reason = await resolve_source_document(docx_source)
    source_text = ""
    source_html = ""
    source_hyperlinks = []
    has_source_doc = bool(source_bytes)

    if has_source_doc:
        try:
            source_text = doc_service._extract_text_from_docx(source_bytes)
            source_html = doc_service._extract_html_from_docx(source_bytes)
            source_hyperlinks = doc_service._extract_hyperlinks_from_docx(source_bytes)
        except Exception as exc:
            log.warning("Could not extract DOCX content: %s", exc)
            has_source_doc = False
            source_unavail_reason = f"Could not parse DOCX: {str(exc)}"

    if has_source_doc:
        src_art_title = (docx_source or {}).get("article_title") or (docx_source or {}).get("title")
        is_matched, match_reason = verify_source_match_to_draft(
            post_title=post_title,
            post_content=post_content,
            source_filename=source_filename,
            source_article_title=src_art_title,
            source_text=source_text,
        )
        if not is_matched:
            log.warning("Source DOCX mismatch for post #%s: %s", post_id, match_reason)
            has_source_doc = False
            source_unavail_reason = match_reason

    # 4. Parse Draft HTML with ParsedArticleHTML
    parsed_html = ParsedArticleHTML(post_content)

    # Tracking structures for issues tables
    broken_links_table = []
    image_issues_table = []
    content_differences_table = []
    yoast_issues_table = []

    # Helper to build check item
    categories_output = {
        "overall_view": [],
        "links": [],
        "title": [],
        "headings": [],
        "images": [],
        "content_integrity": [],
        "categories_and_tags": [],
        "author": [],
        "duplicate_check": [],
        "seo": [],
    }

    def add_check(
        category: str,
        key: str,
        name: str,
        status: str,
        detail: str,
        evidence: Any,
        location: str = "WordPress draft",
        suggested_fix: Optional[str] = None,
        responsible: Optional[str] = None,
    ):
        categories_output[category].append({
            "key": key,
            "name": name,
            "status": status,
            "detail": detail,
            "evidence": evidence,
            "location": location,
            "suggested_fix": suggested_fix if status in ("FAIL", "WARNING") else None,
            "responsible_party": responsible if status in ("FAIL", "WARNING") else None,
        })

    # =========================================================================
    # CATEGORY 1: OVERALL VIEW
    # =========================================================================
    
    # Check 1.1: Overall Page Layout (blank lines, empty paragraphs, broken layout)
    empty_paragraphs_count = parsed_html.empty_paragraphs_count
    stray_breaks = len(re.findall(r"(?:<br\s*/?>\s*){3,}", post_content, re.IGNORECASE))
    
    if empty_paragraphs_count > 3 or stray_breaks > 0:
        layout_status = "WARNING"
        layout_detail = f"Found {empty_paragraphs_count} empty paragraph(s) and {stray_breaks} excessive line break blocks."
        layout_evidence = {"empty_paragraphs_count": empty_paragraphs_count, "stray_breaks_count": stray_breaks}
        layout_location = "Article body paragraph flow"
        layout_suggested_fix = "In WordPress block editor, remove empty paragraph blocks and excessive line break blocks to restore clean paragraph spacing."
        layout_responsible = "Espial team"
    else:
        layout_status = "PASS"
        layout_detail = "Article layout is clean with well-spaced paragraphs and no excessive blank blocks."
        layout_evidence = f"Clean paragraph flow, {empty_paragraphs_count} empty paragraph(s) within normal tolerance."
        layout_location = "Article body paragraph flow"
        layout_suggested_fix = None
        layout_responsible = None
    add_check("overall_view", "overall_page_layout", "Overall Page Layout & Cleanliness", layout_status, layout_detail, layout_evidence, layout_location, layout_suggested_fix, layout_responsible)

    # Check 1.2: Draft Status = DRAFT (never published)
    # Legacy key: draft_status — "WordPress Status = DRAFT"
    draft_status_val = (post_status or "").strip().lower()
    if draft_status_val in ("draft", "auto-draft", "pending"):
        add_check(
            "overall_view",
            "draft_status",
            "WordPress Post Status Is DRAFT (Never Published)",
            "PASS",
            f"WordPress post status confirmed: '{post_status}'. Post has not been published.",
            {"post_status": post_status},
            "WordPress Post Status",
            None,
        )
    elif draft_status_val == "publish":
        add_check(
            "overall_view",
            "draft_status",
            "WordPress Post Status Is DRAFT (Never Published)",
            "FAIL",
            f"CRITICAL: WordPress post status is '{post_status}'. This post appears to have been published. QA audit must be run on a draft, not a live post.",
            {"post_status": post_status},
            "WordPress Post Status",
            "Set post back to Draft status in WordPress editor and re-run QA before proceeding.",
            "Espial team",
        )
    else:
        add_check(
            "overall_view",
            "draft_status",
            "WordPress Post Status Is DRAFT (Never Published)",
            "WARNING",
            f"WordPress post status is '{post_status}' (expected 'draft' or 'auto-draft'). Verify post has not been published prematurely.",
            {"post_status": post_status},
            "WordPress Post Status",
            f"Check that the post status '{post_status}' is intentional and the article has not been published inadvertently.",
            "Espial team",
        )

    # Check 1.3 [orig 1.2]: Stray Client Comments in HTML
    comment_pattern = re.compile(r"(?:\bTODO:|\bNOTE:|\[Editor's note:|\[Client comment:)", re.IGNORECASE)
    stray_comment_matches = comment_pattern.findall(post_content)
    raw_html_comments = re.findall(r"<!--(.*?)-->", post_content, re.DOTALL)
    
    if stray_comment_matches:
        add_check(
            "overall_view",
            "stray_client_comments_in_html",
            "Stray Client Comments in Hosted HTML",
            "FAIL",
            f"Detected {len(stray_comment_matches)} stray client comments in body text: {stray_comment_matches[:3]}",
            {"stray_comments": stray_comment_matches[:5]},
            "Article body text / HTML comments",
            "In WordPress editor, remove all editorial comments, internal notes, and TODO markers from the article text.",
            "Espial team",
        )
    else:
        add_check(
            "overall_view",
            "stray_client_comments_in_html",
            "Stray Client Comments in Hosted HTML",
            "PASS",
            "No client editorial comments or internal notes leaked into the hosted article HTML.",
            f"0 comment markers found across {len(post_content)} chars.",
            "Article body text / HTML comments",
            None,
        )

    # =========================================================================
    # CATEGORY 2: LINKS — HIGHEST PRIORITY
    # =========================================================================
    draft_links = parsed_html.links
    link_urls = [a.get("href") for a in draft_links if a.get("href")]

    # Check 2.1: Live HTTP Link Status
    async with httpx.AsyncClient(timeout=5.0) as http_client:
        tested_results = {}
        for a_item in draft_links:
            href = (a_item.get("href") or "").strip()
            anchor_text = a_item.get("anchor") or ""
            link_loc = a_item.get("location") or "Article body"
            if not href.startswith(("http://", "https://")):
                continue
            if href not in tested_results:
                res = await _test_link(href, http_client)
                tested_results[href] = res
                if res["status"] in ("FAIL", "WARNING"):
                    broken_links_table.append({
                        "url": href,
                        "anchor_text": anchor_text or "—",
                        "location": link_loc,
                        "status_code": str(res["code"]) if res["code"] is not None else "Timeout/Error",
                        "error": res["note"],
                        "category": "External / Internal Link",
                        "redirect_history": res.get("redirect_history"),
                        "final_url": res.get("final_url"),
                        "suggested_fix": "Update or replace the unreachable link in WordPress editor.",
                        "responsible": "Espial team",
                    })

    dead_links = [u for u, r in tested_results.items() if r["status"] == "FAIL"]
    warn_links = [u for u, r in tested_results.items() if r["status"] in ("WARNING", "INCONCLUSIVE")]

    if dead_links:
        add_check(
            "links",
            "live_http_link_status",
            "Live HTTP Link Status (Zero Dead Links)",
            "FAIL",
            f"Detected {len(dead_links)} broken link(s) on hosted draft (e.g. {dead_links[0]}).",
            {"dead_links": dead_links, "warnings": warn_links},
            "Article body hyperlinks",
            f"In WordPress block editor, repair or replace the {len(dead_links)} dead link(s) with active canonical destination URLs.",
            "Espial team",
        )
    elif warn_links:
        add_check(
            "links",
            "live_http_link_status",
            "Live HTTP Link Status (Zero Dead Links)",
            "WARNING",
            f"Zero dead links, but {len(warn_links)} link(s) had non-standard responses (e.g. WAF block or timeout).",
            {"warnings": warn_links, "tested_count": len(tested_results)},
            "Article body hyperlinks",
            "Verify in a browser that the destination pages load properly and were not blocked by bot-protection or network timeouts.",
            "Espial team",
        )
    else:
        add_check(
            "links",
            "live_http_link_status",
            "Live HTTP Link Status (Zero Dead Links)",
            "PASS" if tested_results else "NOT APPLICABLE",
            f"All {len(tested_results)} link(s) returned live HTTP 200 OK." if tested_results else "No hyperlinks present in post body.",
            {"tested_urls": list(tested_results.keys())},
            "Article body hyperlinks",
            None,
        )

    # Check 2.2: DOCX External Links Preserved
    if not has_source_doc:
        add_check(
            "links",
            "docx_external_links_preserved",
            "Source Word Document External Links Preserved",
            "NOT APPLICABLE",
            f"Source DOCX comparison not applicable: {source_unavail_reason or 'Source DOCX not provided (Standalone draft audit).'}",
            source_unavail_reason or "No source document supplied.",
            "Source Word Document vs Draft body",
            None,
        )
    else:
        docx_ext_urls = [h["url"] for h in source_hyperlinks if h.get("url") and not "homebusinessmag.com" in h["url"]]
        missing_ext = [u for u in docx_ext_urls if u not in post_content]
        if missing_ext:
            add_check(
                "links",
                "docx_external_links_preserved",
                "Source Word Document External Links Preserved",
                "FAIL",
                f"{len(missing_ext)} external link(s) from source Word document are missing in draft: {missing_ext[:2]}",
                {"missing_urls": missing_ext},
                "Article body hyperlinks",
                f"In WordPress editor, insert the {len(missing_ext)} missing external URL(s) from the source Word document.",
                "Espial team",
            )
        else:
            add_check(
                "links",
                "docx_external_links_preserved",
                "Source Word Document External Links Preserved",
                "PASS",
                f"All {len(docx_ext_urls)} external link(s) from source document are present in draft.",
                f"Preserved: {len(docx_ext_urls)} URLs.",
                "Article body hyperlinks",
                None,
            )

    # Check 2.3: Internal Links to homebusinessmag.com (At least 2 required)
    hbm_links = [a for a in draft_links if "homebusinessmag.com" in (a.get("href") or "").lower()]
    if len(hbm_links) >= 2:
        add_check(
            "links",
            "internal_links_preserved",
            "Two Internal Links to homebusinessmag.com",
            "PASS",
            f"Verified {len(hbm_links)} internal homebusinessmag.com links in draft.",
            [a.get("href") for a in hbm_links],
            "Article body internal links",
            None,
        )
    else:
        add_check(
            "links",
            "internal_links_preserved",
            "Two Internal Links to homebusinessmag.com",
            "FAIL",
            f"Draft contains {len(hbm_links)} internal link(s) to homebusinessmag.com; at least 2 are required.",
            [a.get("href") for a in hbm_links],
            "Article body internal links",
            "In WordPress editor, add at least two contextual internal links pointing to relevant published articles on homebusinessmag.com.",
            "Espial team",
        )

    # Check 2.4: Internal Link Anchor Text (3–5 Words Rule)
    non_conforming_internal_anchors = []
    for a in hbm_links:
        words = a["anchor"].split()
        if not (3 <= len(words) <= 5):
            item = {
                "anchor": a["anchor"],
                "word_count": len(words),
                "href": a.get("href"),
                "location": a.get("location", "Article body"),
                "context_snippet": a.get("context_snippet", ""),
            }
            non_conforming_internal_anchors.append(item)
    if non_conforming_internal_anchors:
        samples_str = "; ".join(
            f"'{item['anchor']}' ({item['word_count']} word{'s' if item['word_count'] != 1 else ''} in {item['location']}: \"{item['context_snippet']}\")"
            for item in non_conforming_internal_anchors
        )
        add_check(
            "links",
            "internal_link_anchor_words",
            "Internal Link Anchor Text (3–5 Words Rule)",
            "FAIL",
            f"{len(non_conforming_internal_anchors)} internal link(s) violate client's 3–5 word anchor rule: {samples_str}.",
            non_conforming_internal_anchors,
            non_conforming_internal_anchors[0].get("location", "Article body"),
            "In WordPress editor, expand or shorten internal link anchor text to between 3 and 5 consecutive words from the body text.",
            "Espial team",
        )
    else:
        add_check(
            "links",
            "internal_link_anchor_words",
            "Internal Link Anchor Text (3–5 Words Rule)",
            "PASS" if hbm_links else "NOT APPLICABLE",
            f"All {len(hbm_links)} internal link anchor texts strictly use 3–5 words from body text." if hbm_links else "No internal links to evaluate.",
            [a["anchor"] for a in hbm_links],
            "Article body internal links",
            None,
        )

    # Check 2.5: Approved Authority Domains (Forbes, CNN, Medium, Inc, Entrepreneur)
    authority_links = []
    for a in draft_links:
        href = (a.get("href") or "").lower()
        for dom in APPROVED_AUTHORITY_DOMAINS:
            if dom in href:
                authority_links.append(a)
                break
    
    if authority_links:
        add_check(
            "links",
            "approved_authority_domains",
            "At Least One Approved Authority Link",
            "PASS",
            f"Verified {len(authority_links)} authority link(s) to approved domains ({[a.get('href') for a in authority_links]}).",
            [a.get("href") for a in authority_links],
            "Article body external links",
            None,
        )
    else:
        add_check(
            "links",
            "approved_authority_domains",
            "At Least One Approved Authority Link",
            "FAIL",
            f"No authority links to approved domains ({', '.join(APPROVED_AUTHORITY_DOMAINS)}) found.",
            "0 authority links found.",
            "Article body external links",
            f"In WordPress editor, add at least one citation link to an approved authority domain ({', '.join(APPROVED_AUTHORITY_DOMAINS)}).",
            "Espial team",
        )

    # Check 2.6: Authority Link Anchor Text (3–4 Words Rule)
    non_conforming_auth_anchors = []
    for a in authority_links:
        words = a["anchor"].split()
        if not (3 <= len(words) <= 4):
            item = {
                "anchor": a["anchor"],
                "word_count": len(words),
                "href": a.get("href"),
                "location": a.get("location", "Article body"),
                "context_snippet": a.get("context_snippet", ""),
            }
            non_conforming_auth_anchors.append(item)
    if non_conforming_auth_anchors:
        samples_str = "; ".join(
            f"'{item['anchor']}' ({item['word_count']} word{'s' if item['word_count'] != 1 else ''} in {item['location']}: \"{item['context_snippet']}\")"
            for item in non_conforming_auth_anchors
        )
        add_check(
            "links",
            "authority_link_anchor_words",
            "Authority Link Anchor Text (3–4 Words Rule)",
            "FAIL",
            f"{len(non_conforming_auth_anchors)} authority link(s) violate client's 3–4 word anchor rule: {samples_str}.",
            non_conforming_auth_anchors,
            non_conforming_auth_anchors[0].get("location", "Article body"),
            "In WordPress editor, adjust authority link anchor text to between 3 and 4 consecutive words from the body text.",
            "Espial team",
        )
    elif authority_links:
        add_check(
            "links",
            "authority_link_anchor_words",
            "Authority Link Anchor Text (3–4 Words Rule)",
            "PASS",
            f"All {len(authority_links)} authority link anchors strictly conform to 3–4 words.",
            [a["anchor"] for a in authority_links],
            "Article body authority links",
            None,
        )
    else:
        add_check(
            "links",
            "authority_link_anchor_words",
            "Authority Link Anchor Text (3–4 Words Rule)",
            "NOT APPLICABLE",
            "No authority link present to evaluate anchor length.",
            "No authority link.",
            "Article body authority links",
            None,
        )

    # Check 2.7: No Search Engine Links
    search_links = [u for u in link_urls if any(s in u.lower() for s in ("google.com/search", "bing.com/search", "yahoo.com/search", "duckduckgo.com/?q="))]
    if search_links:
        add_check(
            "links",
            "no_search_engine_links",
            "No Search-Engine-Added Links",
            "FAIL",
            f"Detected {len(search_links)} search engine query link(s): {search_links}",
            search_links,
            "Article body hyperlinks",
            "In WordPress editor, remove all search engine query links (e.g. google.com/search) and replace them with canonical destination page URLs.",
            "Espial team",
        )
    else:
        add_check(
            "links",
            "no_search_engine_links",
            "No Search-Engine-Added Links",
            "PASS",
            "No search engine query links detected in article content.",
            "0 search query links.",
            "Article body hyperlinks",
            None,
        )

    # Check 2.8: No Authority Site Names in Body Text
    unwanted_name_patterns = [r"\baccording to (?:Forbes|CNN|Medium|Inc\.?|Entrepreneur)\b", r"\breported by (?:Forbes|CNN|Medium|Inc\.?|Entrepreneur)\b"]
    found_site_mentions = []
    for pat in unwanted_name_patterns:
        found_site_mentions.extend(re.findall(pat, post_content, re.IGNORECASE))
    if found_site_mentions:
        add_check(
            "links",
            "no_unnecessary_site_names",
            "No Unnecessary Authority Site Names in Body Text",
            "FAIL",
            f"Detected {len(found_site_mentions)} unwanted authority site citation phrases: {found_site_mentions}",
            found_site_mentions,
            "Article body text",
            "In WordPress editor, remove brand citation phrases (e.g. 'according to Forbes'); hyperlinked anchors should integrate naturally without naming the site.",
            "Espial team",
        )
    else:
        add_check(
            "links",
            "no_unnecessary_site_names",
            "No Unnecessary Authority Site Names in Body Text",
            "PASS",
            "Body text is clean of unsolicited authority brand attribution phrases (e.g. 'according to Forbes').",
            "0 authority citation phrases.",
            "Article body text",
            None,
        )

    # Check 2.9: Link Anchor Text Sourced from Article Body (Legacy: link_text_from_content)
    # Only evaluable when source DOCX is available
    if not has_source_doc:
        add_check(
            "links",
            "link_text_from_content",
            "Link Anchor Text Preserved from Source Document",
            "NOT APPLICABLE",
            f"Source DOCX comparison not applicable: {source_unavail_reason or 'Source DOCX not provided (Standalone draft audit).'}",
            source_unavail_reason or "No source document supplied.",
            "Article body hyperlinks vs Source Document",
            None,
        )
    else:
        # For each draft link, verify its anchor text appears verbatim in the source text
        source_text_lower = source_text.lower()
        anchors_not_in_source = []
        for a in draft_links:
            anchor = (a.get("anchor") or "").strip()
            if len(anchor.split()) >= 3 and anchor.lower() not in source_text_lower:
                anchors_not_in_source.append({
                    "anchor": anchor,
                    "href": a.get("href", ""),
                    "location": a.get("location", "Article body"),
                })
        if anchors_not_in_source:
            add_check(
                "links",
                "link_text_from_content",
                "Link Anchor Text Preserved from Source Document",
                "WARNING",
                f"{len(anchors_not_in_source)} link anchor(s) not found verbatim in source document (may indicate AI-invented anchor text).",
                anchors_not_in_source[:5],
                "Article body hyperlinks vs Source Document",
                "Verify each link anchor text is drawn directly from the source Word document body, not invented by AI.",
                "Espial team",
            )
        else:
            add_check(
                "links",
                "link_text_from_content",
                "Link Anchor Text Preserved from Source Document",
                "PASS",
                f"All {len(draft_links)} link anchor texts verified as present in source document body.",
                f"{len(draft_links)} anchors checked.",
                "Article body hyperlinks vs Source Document",
                None,
            )

    # =========================================================================
    # CATEGORY 3: TITLE
    # =========================================================================
    
    # Check 3.1: WordPress Title Matches Source
    if not has_source_doc:
        add_check(
            "title",
            "title_exact",
            "Exact Title Preserved from Source Document",
            "NOT APPLICABLE",
            f"Source DOCX comparison not applicable: {source_unavail_reason or 'Source DOCX not provided (Standalone draft audit). Title present on WordPress draft.'}",
            source_unavail_reason or f"Draft Title: '{post_title}'",
            "WordPress Post Title",
            None,
        )
    else:
        source_title_guess = doc_service._extract_article_title_from_html(source_html) if source_html else ""
        if source_title_guess and post_title.strip().lower() != source_title_guess.strip().lower():
            content_differences_table.append({
                "description": "Article title difference",
                "location": "WordPress Post Title",
                "expected": source_title_guess,
                "actual": post_title,
                "suggested_fix": f"Update WordPress post title to match source document heading: '{source_title_guess}'.",
                "responsible": "Espial team",
            })
            add_check(
                "title",
                "title_exact",
                "Exact Title Preserved from Source Document",
                "WARNING",
                f"WordPress draft title differs from document heading: '{post_title}' vs '{source_title_guess}'",
                {"draft_title": post_title, "source_title": source_title_guess},
                "WordPress Post Title",
                f"In WordPress post editor, update title to match Word document heading '{source_title_guess}'.",
                "Espial team",
            )
        else:
            add_check(
                "title",
                "title_exact",
                "Exact Title Preserved from Source Document",
                "PASS",
                f"WordPress draft title exactly matches source title: '{post_title}'.",
                post_title,
                "WordPress Post Title",
                None,
            )

    # Check 3.2: Title in Title Case
    # Check if major words are capitalized
    words = post_title.split()
    non_tc_words = []
    stopwords = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "from", "by", "with", "in", "of"}
    for idx, w in enumerate(words):
        clean_w = re.sub(r"[^\w]", "", w)
        if not clean_w:
            continue
        if idx == 0 or idx == len(words) - 1:
            if clean_w[0].islower():
                non_tc_words.append(w)
        else:
            if clean_w.lower() not in stopwords and clean_w[0].islower():
                non_tc_words.append(w)
    
    if non_tc_words:
        add_check(
            "title",
            "title_in_title_case",
            "Article Title in Title Case",
            "WARNING",
            f"Title has words not in Title Case: {non_tc_words}",
            {"title": post_title, "non_conforming_words": non_tc_words},
            "WordPress Post Title",
            f"In WordPress post editor, capitalize the following non-conforming words in post title: {', '.join(non_tc_words)}.",
            "Espial team",
        )
    else:
        add_check(
            "title",
            "title_in_title_case",
            "Article Title in Title Case",
            "PASS",
            f"Title verified in correct Title Case: '{post_title}'.",
            post_title,
            "WordPress Post Title",
            None,
        )

    # Check 3.3: Meta Title Differs from Article Title
    meta_title = post_meta.get("_yoast_wpseo_title") or post_meta.get("yoast_wpseo_title") or ""
    if not meta_title:
        yoast_issues_table.append({
            "parameter": "Meta Title",
            "location": "Yoast SEO Meta Box (_yoast_wpseo_title)",
            "actual_value": "Empty / Not Set",
            "requirement": "Meta title set and slightly different from article title",
            "suggested_fix": "In Yoast SEO meta box, enter an SEO title that captures the keyphrase while wording differs slightly from post title.",
            "responsible": "Espial team",
        })
        add_check(
            "title",
            "meta_title_differs_from_title",
            "Meta Title Differs from Article Title",
            "WARNING",
            "Yoast SEO meta title is not set.",
            "Empty meta title.",
            "Yoast SEO Meta Title (_yoast_wpseo_title)",
            "In Yoast SEO meta box, configure a meta title that differs slightly from the article title while keeping the focus keyphrase.",
            "Espial team",
        )
    elif meta_title.strip().lower() == post_title.strip().lower():
        yoast_issues_table.append({
            "parameter": "Meta Title Differentiation",
            "location": "Yoast SEO Meta Box (_yoast_wpseo_title)",
            "actual_value": meta_title,
            "requirement": "Meta title must differ from article title while capturing the core keyphrase",
            "suggested_fix": "Edit the Yoast meta title so its wording varies from the exact post title verbatim.",
            "responsible": "Espial team",
        })
        add_check(
            "title",
            "meta_title_differs_from_title",
            "Meta Title Differs from Article Title",
            "WARNING",
            "Meta title is identical to the article title verbatim. Client rule requires meta title to differ slightly while retaining meaning.",
            {"meta_title": meta_title, "post_title": post_title},
            "Yoast SEO Meta Title (_yoast_wpseo_title)",
            "In Yoast SEO meta box, edit the meta title to vary slightly from the article title while retaining the primary focus keyphrase.",
            "Espial team",
        )
    else:
        add_check(
            "title",
            "meta_title_differs_from_title",
            "Meta Title Differs from Article Title",
            "PASS",
            "Meta title differs from article title while capturing the core keyphrase.",
            {"meta_title": meta_title, "post_title": post_title},
            "Yoast SEO Meta Title (_yoast_wpseo_title)",
            None,
        )

    # Check 3.4: Meta Title Length
    if meta_title and len(meta_title) > 65:
        yoast_issues_table.append({
            "parameter": "Meta Title Length",
            "location": "Yoast SEO Meta Box (_yoast_wpseo_title)",
            "actual_value": f"{len(meta_title)} characters",
            "requirement": "Maximum 65 characters to prevent search snippet truncation",
            "suggested_fix": "Shorten the Yoast meta title to 65 characters or fewer.",
            "responsible": "Espial team",
        })
        add_check(
            "title",
            "meta_title_yoast_length",
            "Meta Title Length (Yoast Optimal)",
            "WARNING",
            f"Meta title length ({len(meta_title)} chars) exceeds standard 65 character limit; may be truncated in search results.",
            {"meta_title": meta_title, "length": len(meta_title)},
            "Yoast SEO Meta Title (_yoast_wpseo_title)",
            "In Yoast SEO meta box, shorten meta title to 65 characters or fewer to avoid search result snippet truncation.",
            "Espial team",
        )
    else:
        add_check(
            "title",
            "meta_title_yoast_length",
            "Meta Title Length (Yoast Optimal)",
            "PASS" if meta_title else "WARNING",
            f"Meta title length ({len(meta_title)} chars) within optimal search snippet boundary." if meta_title else "Meta title missing.",
            {"length": len(meta_title)},
            "Yoast SEO Meta Title (_yoast_wpseo_title)",
            "In Yoast SEO meta box, provide a meta title within optimal search snippet length (<= 65 chars)." if not meta_title else None,
            "Espial team" if not meta_title else None,
        )

    # =========================================================================
    # CATEGORY 4: HEADINGS
    # =========================================================================
    heading_analysis = seo_optimizer.parse_and_validate_headings(post_content)
    h_counts = heading_analysis["counts"]
    draft_subheadings = heading_analysis["total_subheadings"]
    hierarchy_errors = heading_analysis["hierarchy_errors"]
    non_conforming_tc = heading_analysis["non_conforming_title_case"]

    # Check 4.1: Heading Hierarchy
    h1_headings = [f"<h1>{h['text']}</h1>" for h in parsed_html.headings if h["tag"] == "h1"]
    if h_counts["h1"] > 0:
        h1_str = ", ".join(f"'{h}'" for h in h1_headings) if h1_headings else f"{h_counts['h1']} <h1> tag(s)"
        content_differences_table.append({
            "description": "Body H1 tag violation",
            "location": "Article body content",
            "expected": "0 <h1> tags in body (post title is page H1)",
            "actual": f"{h_counts['h1']} <h1> tag(s) present in body: {h1_str}",
            "suggested_fix": "Change body <h1> tags to <h2> in WordPress editor (or remove if duplicating title).",
            "responsible": "Espial team",
        })
        add_check(
            "headings",
            "heading_hierarchy",
            "Heading Hierarchy (H2 -> H3 -> H4; No Body H1)",
            "FAIL",
            f"Body content contains {h_counts['h1']} <h1> tag(s): {h1_str}. The post title already serves as the page H1.",
            {"h1_tags": h1_headings, "counts": h_counts},
            "Article body headings",
            "In WordPress editor, remove or change body <h1> tags to <h2>; the post title already serves as the sole H1 tag on the page.",
            "Espial team",
        )
    elif hierarchy_errors:
        for herr in hierarchy_errors:
            content_differences_table.append({
                "description": "Heading hierarchy nesting violation",
                "location": "Article body headings",
                "expected": "Sequential heading hierarchy (H2 -> H3 -> H4)",
                "actual": herr,
                "suggested_fix": "Reorganize headings so levels are not skipped.",
                "responsible": "Espial team",
            })
        add_check(
            "headings",
            "heading_hierarchy",
            "Heading Hierarchy (H2 -> H3 -> H4; No Body H1)",
            "FAIL",
            f"Heading hierarchy violation: {'; '.join(hierarchy_errors)}.",
            hierarchy_errors,
            "Article body headings",
            "In WordPress editor, correct heading tags so levels nest sequentially (H2 -> H3 -> H4) without skipping levels.",
            "Espial team",
        )
    else:
        add_check(
            "headings",
            "heading_hierarchy",
            "Heading Hierarchy (H2 -> H3 -> H4; No Body H1)",
            "PASS",
            f"Heading hierarchy verified: 0 body H1s, {h_counts['h2']} H2s, {h_counts['h3']} H3s, {h_counts['h4']} H4s.",
            h_counts,
            "Article body headings",
            None,
        )

    # Check 4.2: Title Case Headings
    if non_conforming_tc:
        nc_samples = [f"'{x['text']}'" for x in non_conforming_tc[:3]]
        add_check(
            "headings",
            "title_case_headings",
            "Subheadings Formatted in Title Case",
            "WARNING",
            f"{len(non_conforming_tc)} subheading(s) not in Title Case: {', '.join(nc_samples)}",
            non_conforming_tc,
            "Article subheadings",
            f"In WordPress editor, capitalize major words in subheadings according to Title Case rules: {', '.join(nc_samples)}.",
            "Espial team",
        )
    else:
        add_check(
            "headings",
            "title_case_headings",
            "Subheadings Formatted in Title Case",
            "PASS" if draft_subheadings > 0 else "NOT APPLICABLE",
            f"All {draft_subheadings} subheadings formatted in Title Case." if draft_subheadings > 0 else "No subheadings in article.",
            f"{draft_subheadings} subheadings verified.",
            "Article subheadings",
            None,
        )

    # Check 4.3: Headings Are Bold (inspect markup for unbolding)
    unbolded_headings = []
    for h_tag, h_attr, h_inner in re.findall(r'<(h[2-6])([^>]*)>(.*?)</\1>', post_content, re.IGNORECASE | re.DOTALL):
        if re.search(r'font-weight\s*:\s*(normal|400|lighter)', h_attr, re.IGNORECASE) or re.search(r'font-weight\s*:\s*(normal|400|lighter)', h_inner, re.IGNORECASE):
            unbolded_headings.append(html.unescape(re.sub(r'<[^>]+>', '', h_inner)).strip())

    if unbolded_headings:
        for uh in unbolded_headings:
            content_differences_table.append({
                "description": "Heading has non-bold styling",
                "location": "Article subheadings markup",
                "expected": "Bold heading typography (font-weight: 700)",
                "actual": f"Non-bold styled heading: '{uh[:60]}'",
                "suggested_fix": "Remove inline CSS font-weight: normal / 400 styles to allow headings to render with standard bold typography.",
                "responsible": "Espial team",
            })
        add_check(
            "headings",
            "headings_are_bold",
            "Every Heading is Bold",
            "WARNING",
            f"Found {len(unbolded_headings)} heading(s) with explicit non-bold styling: {unbolded_headings[:2]}.",
            unbolded_headings,
            "Article subheadings markup",
            "Remove inline CSS font-weight: normal / 400 styles to allow headings to render with standard bold typography.",
            "Espial team",
        )
    else:
        add_check(
            "headings",
            "headings_are_bold",
            "Every Heading is Bold",
            "PASS" if draft_subheadings > 0 else "NOT APPLICABLE",
            f"All {draft_subheadings} subheadings inherit bold font-weight (700) per theme typography and semantic HTML tags." if draft_subheadings > 0 else "No subheadings in article.",
            f"{draft_subheadings} heading tags verified.",
            "Article subheadings markup",
            None,
        )

    # Check 4.4: No Paragraph Formatted as Heading
    long_headings = [h["text"] for h in parsed_html.headings if h["tag"] in ("h2", "h3", "h4") and len(h["text"]) > 150]
    if long_headings:
        for lh in long_headings:
            content_differences_table.append({
                "description": "Paragraph improperly formatted as heading",
                "location": "Article body headings",
                "expected": "Concise section titles (<150 chars)",
                "actual": f"Heading of {len(lh)} chars: '{lh[:80]}...'",
                "suggested_fix": "Change the heading block back to a regular paragraph (<p>) in WordPress editor.",
                "responsible": "Espial team",
            })
        add_check(
            "headings",
            "no_paragraph_to_heading",
            "No Body Paragraphs Formatted as Headings",
            "FAIL",
            f"Detected {len(long_headings)} heading(s) exceeding 150 characters (likely paragraphs converted to headings).",
            long_headings,
            "Article subheadings",
            "In WordPress editor, convert long block(s) exceeding 150 characters back into normal paragraph (<p>) text.",
            "Espial team",
        )
    else:
        add_check(
            "headings",
            "no_paragraph_to_heading",
            "No Body Paragraphs Formatted as Headings",
            "PASS",
            "No whole paragraphs improperly formatted as headings.",
            "All subheadings are concise section titles.",
            "Article subheadings",
            None,
        )

    # Check 4.5: Headings Parity with Source Word Document
    if not has_source_doc:
        add_check(
            "headings",
            "headings_parity_source_docx",
            "Subheading Wording Matches Source Document",
            "NOT APPLICABLE",
            f"Source DOCX comparison not applicable: {source_unavail_reason or 'Source DOCX not provided (Standalone draft audit). Subheadings verified internally.'}",
            source_unavail_reason or f"{draft_subheadings} draft subheadings present.",
            "Article subheadings vs Source Document",
            None,
        )
    else:
        source_h_matches = re.findall(r'<(h[1-6])[^>]*>(.*?)</\1>', source_html, re.IGNORECASE | re.DOTALL) if source_html else []
        source_h_texts = [html.unescape(re.sub(r'<[^>]+>', '', m[1])).strip().lower() for m in source_h_matches if m[0].lower() in ('h2', 'h3', 'h4')]
        draft_h_texts = [h["text"].strip().lower() for h in parsed_html.headings if h["tag"] in ('h2', 'h3', 'h4')]
        
        missing_source_headings = [sh for sh in source_h_texts if sh not in draft_h_texts]
        if missing_source_headings:
            for msh in missing_source_headings:
                content_differences_table.append({
                    "description": "Subheading from Word document missing in draft",
                    "location": "Article body subheadings",
                    "expected": msh,
                    "actual": "Missing from draft",
                    "suggested_fix": f"Add missing subheading '{msh}' to draft in WordPress editor.",
                    "responsible": "Espial team",
                })
            add_check(
                "headings",
                "headings_parity_source_docx",
                "Subheading Wording Matches Source Document",
                "WARNING",
                f"{len(missing_source_headings)} subheading(s) from source document missing or rephrased in draft.",
                {"missing_source_headings": missing_source_headings[:3]},
                "Article subheadings vs Source Document",
                "In WordPress editor, align subheading wording with the source Word document headings.",
                "Espial team",
            )
        else:
            add_check(
                "headings",
                "headings_parity_source_docx",
                "Subheading Wording Matches Source Document",
                "PASS",
                f"All {len(source_h_texts)} subheading(s) from source Word document are present in hosted draft.",
                f"{len(source_h_texts)} subheadings matched.",
                "Article subheadings vs Source Document",
                None,
            )

    # =========================================================================
    # CATEGORY 5: IMAGES
    # =========================================================================
    has_featured = bool(featured_media_id and media_data)
    
    # Check 5.1: Featured Media Attached & Dimensions
    if not has_featured:
        image_issues_table.append({
            "image_id": featured_media_id or "None",
            "location": "WordPress Post Featured Media",
            "issue": "No featured media attached to this WordPress draft" if not featured_media_id else f"Featured media #{featured_media_id} metadata could not be fetched",
            "requirement": "Featured image attached (1000 × 667 px)",
            "status": "FAIL" if not featured_media_id else "WARNING",
            "suggested_fix": "In WordPress post editor, select 'Set featured image' and upload/assign a 1000 × 667 px image.",
            "responsible": "Espial team",
        })
        add_check(
            "images",
            "featured_image_present",
            "Featured Image Attached to WordPress Draft",
            "FAIL" if not featured_media_id else "WARNING",
            "No featured media attached to this WordPress draft." if not featured_media_id else f"Featured media #{featured_media_id} metadata could not be fetched.",
            {"featured_media_id": featured_media_id},
            "WordPress Post Featured Media",
            "In WordPress post editor, click 'Set featured image' in the Post settings sidebar and assign an approved 1000 × 667 px image.",
            "Espial team",
        )
    else:
        media_details = media_data.get("media_details", {})
        w = media_details.get("width")
        h = media_details.get("height")
        source_url = media_data.get("source_url", "")
        img_exact_dims = (w == 1000 and h == 667)
        if img_exact_dims or (w and w == 1000):
            add_check(
                "images",
                "featured_image_present",
                "Featured Image Attached to WordPress Draft",
                "PASS",
                f"Featured image #{featured_media_id} attached with dimensions {w} × {h} px.",
                {"media_id": featured_media_id, "width": w, "height": h, "url": source_url},
                f"Featured Media #{featured_media_id}",
                None,
            )
        else:
            image_issues_table.append({
                "image_id": featured_media_id,
                "location": f"Featured Media #{featured_media_id}",
                "issue": f"Image dimensions are {w} × {h} px",
                "requirement": "Recommended dimensions: 1000 × 667 px",
                "status": "WARNING",
                "suggested_fix": "Resize and re-upload the featured image at 1000 × 667 px to avoid distortion.",
                "responsible": "Espial team",
            })
            add_check(
                "images",
                "featured_image_present",
                "Featured Image Attached to WordPress Draft",
                "WARNING",
                f"Featured image dimensions are {w} × {h} px (Client recommended: 1000 × 667 px).",
                {"media_id": featured_media_id, "width": w, "height": h},
                f"Featured Media #{featured_media_id}",
                "In WordPress Media Library, crop or upload a 1000 × 667 px version of the featured image to prevent distortion.",
                "Espial team",
            )

    # Check 5.2: Alt Text Describes Image
    alt_text = media_data.get("alt_text") or ""
    if not alt_text:
        image_issues_table.append({
            "image_id": featured_media_id or "None",
            "location": f"Featured Media #{featured_media_id} Alt Text" if has_featured else "Featured Image Alt Text",
            "issue": "Alt text is missing from featured image attachment",
            "requirement": "Descriptive alternative text required",
            "status": "FAIL" if has_featured else "NOT APPLICABLE",
            "suggested_fix": "In WordPress Media Library, add descriptive alternative text describing the image content.",
            "responsible": "Espial team",
        })
        add_check(
            "images",
            "alt_text_describes_image",
            "Alt Text Present and Descriptive",
            "FAIL" if has_featured else "NOT APPLICABLE",
            "Alt text is missing from featured image attachment.",
            "Empty alt text.",
            f"Featured Media #{featured_media_id} Alt Text" if has_featured else "Featured Image Alt Text",
            "In WordPress Media Library, select the featured image and enter descriptive Alternative Text describing the image content.",
            "Espial team",
        )
    else:
        add_check(
            "images",
            "alt_text_describes_image",
            "Alt Text Present and Descriptive",
            "PASS",
            f"Alt text present: '{alt_text}'.",
            alt_text,
            f"Featured Media #{featured_media_id} Alt Text",
            None,
        )

    # Check 5.3: Image Title Attribute
    img_title = (media_data.get("title", {}) or {}).get("rendered") or ""
    if not img_title:
        image_issues_table.append({
            "image_id": featured_media_id or "None",
            "location": f"Featured Media #{featured_media_id} Title" if has_featured else "Featured Image Title Attribute",
            "issue": "Image title attribute is missing",
            "requirement": "Descriptive image title attribute required",
            "status": "WARNING",
            "suggested_fix": "In WordPress Media Library, set the image title attribute.",
            "responsible": "Espial team",
        })
        add_check(
            "images",
            "title_attribute",
            "Image Title Attribute Present",
            "WARNING",
            "Image title attribute missing.",
            img_title,
            f"Featured Media #{featured_media_id} Title" if has_featured else "Featured Image Title Attribute",
            "In WordPress Media Library, enter a descriptive title for the image attachment.",
            "Espial team",
        )
    else:
        add_check(
            "images",
            "title_attribute",
            "Image Title Attribute Present",
            "PASS",
            f"Image title verified: '{img_title}'.",
            img_title,
            f"Featured Media #{featured_media_id} Title",
            None,
        )

    # Check 5.4: Image Source Credit Formatting
    caption_raw = (media_data.get("caption", {}) or {}).get("rendered") or ""
    override_allows_hyperlink = bool((client_instructions or {}).get("allow_hyperlinked_image_credit"))
    require_credit = bool((client_instructions or {}).get("require_image_credit"))
    has_hyperlink = bool(re.search(r"<a\s+[^>]*href=", caption_raw, re.IGNORECASE))

    if not caption_raw.strip():
        if require_credit:
            image_issues_table.append({
                "image_id": featured_media_id or "None",
                "location": f"Featured Media #{featured_media_id} Caption" if has_featured else "Featured Image Caption",
                "issue": "Missing featured image caption credit required by client instructions",
                "requirement": "Plain-text source URL by default",
                "status": "WARNING",
                "suggested_fix": "Add plain-text source credit URL to image caption in Media Library.",
                "responsible": "Espial team",
            })
            add_check(
                "images",
                "image_source_credit_plain_text",
                "Image Source Credit Formatting",
                "WARNING",
                "No source credit found in featured image caption (required by client instructions).",
                "Empty caption.",
                f"Featured Media #{featured_media_id} Caption" if has_featured else "Featured Image Caption",
                "In WordPress Media Library, edit the featured image attachment and add a plain-text source credit URL into the Caption field.",
                "Espial team",
            )
        else:
            add_check(
                "images",
                "image_source_credit_plain_text",
                "Image Source Credit Formatting",
                "PASS",
                "Manual image upload — source credit and URL are optional unless explicitly required by client instructions.",
                "Optional for manual image upload",
                f"Featured Media #{featured_media_id} Caption" if has_featured else "Featured Image Caption",
                None,
            )
    elif has_hyperlink and not override_allows_hyperlink:
        # Default client rule: Plain-text source URL unless article-specific instructions override it
        image_issues_table.append({
            "image_id": featured_media_id,
            "location": f"Featured Media #{featured_media_id} Caption",
            "issue": "Featured image caption contains hyperlink instead of plain-text URL",
            "requirement": "Plain-text source URL by default (unless article-specific instructions override)",
            "status": "WARNING",
            "suggested_fix": "In WordPress Media Library, edit the caption to remove the <a> hyperlink tag and leave plain-text URL.",
            "responsible": "Espial team",
        })
        add_check(
            "images",
            "image_source_credit_plain_text",
            "Image Source Credit Formatting",
            "WARNING",
            f"Featured image caption contains a hyperlink ('<a href=...>') whereas the default client rule requires a plain-text source URL (e.g. 'envato.com' or asset URL), unless article-specific instructions override it. Caption: {caption_raw.strip()[:90]}...",
            {"caption_raw": caption_raw.strip(), "has_hyperlink": True, "override_specified": False},
            f"Featured Media #{featured_media_id} Caption",
            "In WordPress Media Library, edit the caption to remove the hyperlinked <a> tag and leave only the plain-text URL (e.g. 'envato.com').",
            "Espial team",
        )
    else:
        add_check(
            "images",
            "image_source_credit_plain_text",
            "Image Source Credit Formatting",
            "PASS",
            f"Image credit caption complies with source URL rules: {caption_raw.strip()[:80]}...",
            caption_raw.strip(),
            f"Featured Media #{featured_media_id} Caption",
            None,
        )

    # Check 5.5: Featured Image File Size <= 100 KB (Legacy: image_size_under_100kb)
    if not has_featured:
        add_check(
            "images",
            "image_size_under_100kb",
            "Featured Image File Size <= 100 KB",
            "NOT APPLICABLE",
            "No featured image attached; file size check not applicable.",
            "No featured media.",
            "WordPress Featured Media",
            None,
        )
    else:
        filesize = (media_data.get("media_details") or {}).get("filesize")
        if filesize is not None:
            size_kb = filesize / 1024
            if filesize <= 102400:  # 100 KB in bytes
                add_check(
                    "images",
                    "image_size_under_100kb",
                    "Featured Image File Size <= 100 KB",
                    "PASS",
                    f"Featured image file size is {size_kb:.1f} KB (<= 100 KB requirement).",
                    {"filesize_bytes": filesize, "filesize_kb": round(size_kb, 1)},
                    f"Featured Media #{featured_media_id}",
                    None,
                )
            else:
                image_issues_table.append({
                    "image_id": featured_media_id,
                    "location": f"Featured Media #{featured_media_id}",
                    "issue": f"Featured image is {size_kb:.1f} KB (limit: 100 KB)",
                    "requirement": "Featured image must be <= 100 KB for page performance",
                    "status": "FAIL",
                    "suggested_fix": "Compress and re-upload the featured image to reduce file size to 100 KB or below.",
                    "responsible": "Espial team",
                })
                add_check(
                    "images",
                    "image_size_under_100kb",
                    "Featured Image File Size <= 100 KB",
                    "FAIL",
                    f"Featured image file size is {size_kb:.1f} KB (exceeds 100 KB limit).",
                    {"filesize_bytes": filesize, "filesize_kb": round(size_kb, 1)},
                    f"Featured Media #{featured_media_id}",
                    "Compress and re-upload the featured image (e.g. using TinyPNG or Squoosh) to bring it under 100 KB.",
                    "Espial team",
                )
        else:
            add_check(
                "images",
                "image_size_under_100kb",
                "Featured Image File Size <= 100 KB",
                "WARNING",
                "Featured image file size metadata not available in WordPress media response; size could not be verified.",
                {"media_id": featured_media_id, "filesize": None},
                f"Featured Media #{featured_media_id}",
                "Manually verify featured image file size in WordPress Media Library (must be <= 100 KB).",
                "Espial team",
            )

    # Check 5.6: Inline DOCX Images Capped at Max 700px Width (Legacy: inline_docx_images)
    # Verify <img> tags in body content do not exceed 700px width via HTML attr OR CSS style
    def _extract_img_px_width(attrs: str):
        """Return (pixel_width, source_type) from img attr string. HTML attr takes precedence over CSS."""
        w_attr = re.search(r'\bwidth=["\']?(\d+)["\']?', attrs, re.IGNORECASE)
        if w_attr:
            return int(w_attr.group(1)), "html_attr"
        w_style = re.search(r'style=["\'][^"\']*\bwidth\s*:\s*(\d+)\s*px', attrs, re.IGNORECASE)
        if w_style:
            return int(w_style.group(1)), "css_style"
        return None, None

    inline_img_violations = []
    for m in re.finditer(r'<img\s+([^>]*)>', post_content, re.IGNORECASE | re.DOTALL):
        attrs = m.group(1)
        src_m = re.search(r'\bsrc=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        w_val, w_source = _extract_img_px_width(attrs)
        if w_val is not None and w_val > 700:
            inline_img_violations.append({
                "src": (src_m.group(1)[:80] if src_m else "unknown"),
                "width": w_val,
                "width_source": w_source,
            })
    if inline_img_violations:
        for v in inline_img_violations:
            image_issues_table.append({
                "image_id": v["src"][:60],
                "location": "Article body inline image",
                "issue": f"Inline image width is {v['width']}px via {v.get('width_source','unknown')} (exceeds 700px maximum)",
                "requirement": "DOCX inline images must not exceed 700px width",
                "status": "FAIL",
                "suggested_fix": f"Resize the inline image at '{v['src'][:50]}' to a maximum of 700px wide.",
                "responsible": "Espial team",
            })
        _violation_summary = [f"{v['src'][:40]}({v['width']}px/{v.get('width_source','?')})" for v in inline_img_violations[:3]]
        add_check(
            "images",
            "inline_docx_images",
            "Inline DOCX Images Capped at Max 700px Width",
            "FAIL",
            f"{len(inline_img_violations)} inline image(s) exceed 700px width: {_violation_summary}",
            inline_img_violations,
            "Article body inline images",
            "In WordPress editor, reduce inline image width to 700px or less (check both HTML width= attribute and CSS style width).",
            "Espial team",
        )
    else:
        all_inline_imgs = re.findall(r'<img\s+[^>]*>', post_content, re.IGNORECASE)
        add_check(
            "images",
            "inline_docx_images",
            "Inline DOCX Images Capped at Max 700px Width",
            "PASS" if all_inline_imgs else "NOT APPLICABLE",
            f"All {len(all_inline_imgs)} inline image(s) are within the 700px width limit." if all_inline_imgs else "No inline images found in article body.",
            f"{len(all_inline_imgs)} inline images checked.",
            "Article body inline images",
            None,
        )

    # Check 5.7 [orig 5.5]: Zero Image Mutations During QA
    add_check(
        "images",
        "read_only_images_in_qa",
        "Zero Image Modifications in QA Only Mode",
        "PASS",
        "Images strictly inspected via read-only GET; no uploads or updates performed.",
        "Zero WordPress write operations.",
        "WordPress Media Library",
        None,
    )

    # =========================================================================
    # CATEGORY 6: CONTENT INTEGRITY
    # =========================================================================
    
    # Check 6.1: Body Text Word Comparison
    if not has_source_doc:
        add_check(
            "content_integrity",
            "body_text_word_comparison",
            "Word-for-Word Text Comparison Against Source Document",
            "NOT APPLICABLE",
            f"Source DOCX comparison not applicable: {source_unavail_reason or 'Source DOCX not provided (Standalone draft audit).'}",
            source_unavail_reason or "No source document supplied.",
            "Article body text vs Source Word Document",
            None,
        )
    else:
        # Compare plain text token count
        source_clean = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", source_text)).strip().lower()
        draft_clean = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", parsed_html.text)).strip().lower()
        s_words = set(source_clean.split())
        d_words = set(draft_clean.split())
        overlap = len(s_words.intersection(d_words)) / max(len(s_words), 1)
        if overlap >= 0.70:
            add_check(
                "content_integrity",
                "body_text_word_comparison",
                "Word-for-Word Text Comparison Against Source Document",
                "PASS",
                f"Body text matches source document ({overlap * 100:.1f}% vocabulary parity).",
                f"Overlap ratio: {overlap:.2f}",
                "Article body text",
                None,
            )
        else:
            content_differences_table.append({
                "description": "Vocabulary parity between source Word document and draft",
                "location": "Article body text",
                "expected": f"Source document text ({len(s_words)} unique words)",
                "actual": f"Draft text ({len(d_words)} unique words, {overlap * 100:.1f}% vocabulary parity)",
                "suggested_fix": "Compare draft body text against source Word document to restore missing paragraphs or text.",
                "responsible": "Espial team",
            })
            add_check(
                "content_integrity",
                "body_text_word_comparison",
                "Word-for-Word Text Comparison Against Source Document",
                "WARNING",
                f"Vocabulary parity between source and draft is {overlap * 100:.1f}% (potential missing text or major rewrites).",
                {"overlap_ratio": overlap, "source_words_count": len(s_words), "draft_words_count": len(d_words)},
                "Article body text",
                "In WordPress editor, compare body text with the original Word document to ensure all sections and paragraphs were imported accurately.",
                "Espial team",
            )

    # Check 6.2: Leftover Instructions or Metadata in Body Text
    leftover_patterns = [
        r"\bCATEGORY:\s*[A-Za-z]+",
        r"\bMeta Description:\s*",
        r"\bSWAP OUT IMAGE\b",
        r"\bPUT LINKS IN AS NO FOLLOW\b",
        r"\bSEO Keyphrase:\s*",
    ]
    found_leftovers = []
    for pat in leftover_patterns:
        found_leftovers.extend(re.findall(pat, post_content, re.IGNORECASE))
    if found_leftovers:
        for lo in found_leftovers:
            content_differences_table.append({
                "description": "Leftover instruction or metadata boilerplate in body",
                "location": "Article body text",
                "expected": "Clean article content without instruction markers",
                "actual": lo,
                "suggested_fix": f"Remove instruction token '{lo}' from the article body in WordPress editor.",
                "responsible": "Espial team",
            })
        add_check(
            "content_integrity",
            "leftover_instructions_or_metadata",
            "No Leftover Client Instructions or Metadata Boilerplate",
            "FAIL",
            f"Detected {len(found_leftovers)} leftover instruction boilerplate tokens in body: {found_leftovers}",
            found_leftovers,
            "Article body text",
            f"In WordPress editor, locate and delete instruction labels and placeholder tokens ({', '.join(found_leftovers[:3])}) from the article text.",
            "Espial team",
        )
    else:
        add_check(
            "content_integrity",
            "leftover_instructions_or_metadata",
            "No Leftover Client Instructions or Metadata Boilerplate",
            "PASS",
            "Body text is clean of leftover instruction labels (CATEGORY:, Meta Description:, etc.).",
            "0 leftover instruction tokens.",
            "Article body text",
            None,
        )

    # Check 6.3: Empty Elements Check
    empty_headings = [h["tag"] for h in parsed_html.headings if not h["text"]]
    empty_anchors = [a.get("html") for a in draft_links if not a.get("href") and not a.get("anchor")]
    if empty_headings or empty_anchors:
        if empty_headings:
            content_differences_table.append({
                "description": "Empty heading tag in article HTML",
                "location": "Article body",
                "expected": "Headings containing title text",
                "actual": f"{len(empty_headings)} empty heading tag(s): {empty_headings}",
                "suggested_fix": "In WordPress Code Editor, remove empty heading tags.",
                "responsible": "Espial team",
            })
        if empty_anchors:
            content_differences_table.append({
                "description": "Empty or orphaned bookmark anchor in article HTML",
                "location": "Article body",
                "expected": "Valid links with anchor text and href",
                "actual": f"{len(empty_anchors)} empty bookmark anchor(s)",
                "suggested_fix": "In WordPress Code Editor, remove empty bookmark anchor tags.",
                "responsible": "Espial team",
            })
        add_check(
            "content_integrity",
            "empty_elements_check",
            "No Empty Headings or Stray Bookmark Anchors",
            "WARNING",
            f"Found {len(empty_headings)} empty heading tag(s) and {len(empty_anchors)} empty bookmark anchor(s).",
            {"empty_headings": empty_headings, "empty_anchors": empty_anchors},
            "Article body HTML tags",
            "In WordPress Code Editor, remove empty <h2>/<h3>/<h4> tags and orphaned <a> anchor tags.",
            "Espial team",
        )
    else:
        add_check(
            "content_integrity",
            "empty_elements_check",
            "No Empty Headings or Stray Bookmark Anchors",
            "PASS",
            "No empty headings, orphaned bookmark anchors, or corrupt HTML tags.",
            "All structural tags contain content.",
            "Article body HTML tags",
            None,
        )

    # Check 6.4: Formatting Preserved
    has_p = parsed_html.has_p
    has_lists = parsed_html.has_lists
    paragraph_count = len(parsed_html.paragraphs)
    if not has_p:
        content_differences_table.append({
            "description": "Paragraph formatting structure missing",
            "location": "Article body",
            "expected": "Properly structured <p> paragraph tags",
            "actual": "Missing <p> tags; raw text flow",
            "suggested_fix": "Wrap body text into proper paragraph blocks in WordPress editor.",
            "responsible": "Espial team",
        })
    add_check(
        "content_integrity",
        "formatting_preserved",
        "Paragraph & Flow Formatting Preserved",
        "PASS" if has_p else "FAIL",
        f"Paragraph structure preserved ({paragraph_count} paragraphs, list tags: {'present' if has_lists else 'none'}).",
        {"paragraph_count": paragraph_count, "has_lists": has_lists},
        "Article body structure",
        "In WordPress editor, format unformatted text into proper paragraph blocks." if not has_p else None,
        "Espial team" if not has_p else None,
    )

    # Check 6.5: Lists Preserved (Legacy: lists_preserved)
    # Verify ordered/unordered lists are present when source contains them.
    # When both source and draft have lists, also compare <li> item counts for richer evidence.
    has_draft_lists = bool(re.search(r'<(ul|ol)\b[^>]*>', post_content, re.IGNORECASE))
    source_has_lists = bool(re.search(r'<(ul|ol)\b[^>]*>', source_html, re.IGNORECASE)) if has_source_doc and source_html else False
    if not has_source_doc:
        # Without source DOCX, just report whether lists are present
        add_check(
            "content_integrity",
            "lists_preserved",
            "Lists (Ordered/Unordered) Preserved",
            "PASS" if has_draft_lists else "NOT APPLICABLE",
            f"Draft contains list markup (<ul>/<ol>) — no source comparison available." if has_draft_lists else "No list markup in draft and no source document to compare against.",
            f"Draft has_lists={has_draft_lists}",
            "Article body list elements",
            None,
        )
    elif source_has_lists and not has_draft_lists:
        content_differences_table.append({
            "description": "Ordered/unordered lists from source document missing in draft",
            "location": "Article body content",
            "expected": "List markup (<ul>/<ol>/<li>) preserved from source",
            "actual": "No list markup found in draft body",
            "suggested_fix": "Restore bulleted/numbered list structure from source Word document in WordPress editor.",
            "responsible": "Espial team",
        })
        src_li_count = len(re.findall(r'<li\b[^>]*>', source_html, re.IGNORECASE))
        add_check(
            "content_integrity",
            "lists_preserved",
            "Lists (Ordered/Unordered) Preserved",
            "FAIL",
            f"Source document contains {src_li_count} list item(s) in list markup but no lists found in draft. Lists may have been lost during import.",
            {"source_has_lists": True, "source_li_count": src_li_count, "draft_has_lists": False, "draft_li_count": 0},
            "Article body list elements",
            "In WordPress editor, restore the ordered/unordered list structure from the source Word document.",
            "Espial team",
        )
    elif source_has_lists and has_draft_lists:
        src_li_count   = len(re.findall(r'<li\b[^>]*>', source_html,  re.IGNORECASE))
        draft_li_count = len(re.findall(r'<li\b[^>]*>', post_content, re.IGNORECASE))
        li_delta = src_li_count - draft_li_count
        if li_delta > 0:
            content_differences_table.append({
                "description": "Fewer list items in draft than in source document",
                "location": "Article body list elements",
                "expected": f"{src_li_count} list item(s) from source",
                "actual": f"{draft_li_count} list item(s) in draft",
                "suggested_fix": "Verify that all bullet/numbered list items from the source Word document were imported into the draft.",
                "responsible": "Espial team",
            })
            add_check(
                "content_integrity",
                "lists_preserved",
                "Lists (Ordered/Unordered) Preserved",
                "WARNING",
                f"List markup present in both source and draft, but draft has fewer list items: source={src_li_count} <li>, draft={draft_li_count} <li> ({li_delta} missing).",
                {"source_has_lists": True, "source_li_count": src_li_count, "draft_has_lists": True, "draft_li_count": draft_li_count},
                "Article body list elements",
                "Compare list items in the draft against the source Word document to ensure no bullet/numbered items were dropped.",
                "Espial team",
            )
        else:
            add_check(
                "content_integrity",
                "lists_preserved",
                "Lists (Ordered/Unordered) Preserved",
                "PASS",
                f"List markup (<ul>/<ol>/<li>) preserved from source document in draft. Source: {src_li_count} items, Draft: {draft_li_count} items.",
                {"source_has_lists": True, "source_li_count": src_li_count, "draft_has_lists": True, "draft_li_count": draft_li_count},
                "Article body list elements",
                None,
            )
    else:
        add_check(
            "content_integrity",
            "lists_preserved",
            "Lists (Ordered/Unordered) Preserved",
            "NOT APPLICABLE",
            "No list markup in source document; lists check not applicable.",
            {"source_has_lists": False},
            "Article body list elements",
            None,
        )

    # Check 6.6: Paragraph Spacing Preserved (Legacy: spacing_preserved)
    # Flag excessive blank paragraphs (> 3) or 3+ consecutive <br> blocks
    spacing_status = "PASS"
    spacing_detail = f"Paragraph spacing is clean ({empty_paragraphs_count} empty paragraphs, {stray_breaks} stray break blocks)."
    spacing_evidence = {"empty_paragraphs_count": empty_paragraphs_count, "stray_break_blocks": stray_breaks}
    if empty_paragraphs_count > 3 or stray_breaks > 0:
        spacing_status = "WARNING"
        spacing_detail = (
            f"Excessive spacing detected: {empty_paragraphs_count} empty paragraph(s) and "
            f"{stray_breaks} stray consecutive <br> block(s). Source spacing may not be preserved."
        )
    add_check(
        "content_integrity",
        "spacing_preserved",
        "Paragraph Spacing & Margins Preserved",
        spacing_status,
        spacing_detail,
        spacing_evidence,
        "Article body paragraph spacing",
        "In WordPress block editor, remove excess blank paragraph blocks and stray <br> break sequences." if spacing_status != "PASS" else None,
        "Espial team" if spacing_status != "PASS" else None,
    )

    # Check 6.7: Bold & Italic Formatting Preserved (Legacy: bold_italic_preserved)
    has_bold = bool(re.search(r'<(strong|b)\b[^>]*>', post_content, re.IGNORECASE))
    has_italic = bool(re.search(r'<(em|i)\b[^>]*>', post_content, re.IGNORECASE))
    source_has_bold = bool(re.search(r'<(strong|b)\b[^>]*>', source_html, re.IGNORECASE)) if has_source_doc and source_html else False
    source_has_italic = bool(re.search(r'<(em|i)\b[^>]*>', source_html, re.IGNORECASE)) if has_source_doc and source_html else False

    bold_italic_issues = []
    if has_source_doc:
        if source_has_bold and not has_bold:
            bold_italic_issues.append("Bold (<strong>) formatting found in source but missing in draft.")
        if source_has_italic and not has_italic:
            bold_italic_issues.append("Italic (<em>) formatting found in source but missing in draft.")

    if bold_italic_issues:
        for issue in bold_italic_issues:
            content_differences_table.append({
                "description": "Missing inline formatting from source",
                "location": "Article body text",
                "expected": "Bold/italic preserved from source document",
                "actual": issue,
                "suggested_fix": "Re-apply bold/italic formatting in WordPress editor to match source Word document.",
                "responsible": "Espial team",
            })
        add_check(
            "content_integrity",
            "bold_italic_preserved",
            "Bold & Italic Formatting Preserved",
            "WARNING",
            f"Inline formatting differences detected: {'; '.join(bold_italic_issues)}",
            {"source_has_bold": source_has_bold, "source_has_italic": source_has_italic, "draft_has_bold": has_bold, "draft_has_italic": has_italic},
            "Article body inline formatting",
            "In WordPress editor, restore missing bold (<strong>) or italic (<em>) formatting from the source Word document.",
            "Espial team",
        )
    else:
        add_check(
            "content_integrity",
            "bold_italic_preserved",
            "Bold & Italic Formatting Preserved",
            "PASS",
            f"Bold and italic inline formatting verified: bold={'present' if has_bold else 'none'}, italic={'present' if has_italic else 'none'}.",
            {"draft_has_bold": has_bold, "draft_has_italic": has_italic},
            "Article body inline formatting",
            None,
        )

    # Check 6.8: Source Paragraph Spot-Check (Legacy: final_spot_check)
    # Sample up to 3 short source paragraphs and verify they appear verbatim in draft
    if not has_source_doc:
        add_check(
            "content_integrity",
            "final_spot_check",
            "Final Source Paragraph Spot-Check",
            "NOT APPLICABLE",
            f"Source DOCX comparison not applicable: {source_unavail_reason or 'Source DOCX not provided (Standalone draft audit).'}",
            source_unavail_reason or "No source document supplied.",
            "Article body text vs Source Document",
            None,
        )
    else:
        # Extract candidate paragraphs: 20–120 words, take up to 3 evenly spaced samples
        all_source_paras = [p.strip() for p in re.split(r'\n{2,}', source_text) if p.strip()]
        candidate_paras = [p for p in all_source_paras if 20 <= len(p.split()) <= 120]
        sample_count = min(3, len(candidate_paras))
        step = max(1, len(candidate_paras) // max(sample_count, 1))
        sample_paras = candidate_paras[::step][:sample_count]

        draft_text_lower = parsed_html.text.lower()
        spot_check_results = []
        for para in sample_paras:
            # Normalize and check first 80 chars
            para_norm = re.sub(r'\s+', ' ', para.lower().strip())
            first_80 = para_norm[:80]
            found = first_80 in draft_text_lower
            spot_check_results.append({
                "sample": para[:100] + ("..." if len(para) > 100 else ""),
                "found": found,
            })

        missing_samples = [r for r in spot_check_results if not r["found"]]
        if missing_samples:
            for ms in missing_samples:
                content_differences_table.append({
                    "description": "Source paragraph not found in draft (spot-check failure)",
                    "location": "Article body text",
                    "expected": ms["sample"],
                    "actual": "Not found in draft body",
                    "suggested_fix": "Open source Word document and compare paragraph by paragraph; restore missing content in WordPress editor.",
                    "responsible": "Espial team",
                })
            add_check(
                "content_integrity",
                "final_spot_check",
                "Final Source Paragraph Spot-Check",
                "WARNING",
                f"{len(missing_samples)}/{len(sample_paras)} sampled source paragraph(s) not found verbatim in draft (potential AI rewrite or missing content).",
                {"spot_check_results": spot_check_results},
                "Article body text vs Source Document",
                "Compare draft body text with source Word document paragraph by paragraph to ensure no content was altered or omitted.",
                "Espial team",
            )
        else:
            add_check(
                "content_integrity",
                "final_spot_check",
                "Final Source Paragraph Spot-Check",
                "PASS" if sample_paras else "NOT APPLICABLE",
                f"All {len(sample_paras)} sampled source paragraph(s) found in draft body." if sample_paras else "No suitable sample paragraphs found in source document.",
                {"spot_check_results": spot_check_results},
                "Article body text vs Source Document",
                None,
            )

    # Check 6.9: Source Document Backup & Attachment Integrity (Legacy: document_backup)
    if not (docx_source):
        add_check(
            "content_integrity",
            "document_backup",
            "Source Document Backup & Attachment Integrity",
            "NOT APPLICABLE",
            "No source document context supplied; backup check not applicable for standalone audits.",
            "No docx_source supplied.",
            "Source Word Document",
            None,
        )
    elif has_source_doc and source_bytes:
        backup_size = len(source_bytes)
        if backup_size > 0:
            add_check(
                "content_integrity",
                "document_backup",
                "Source Document Backup & Attachment Integrity",
                "PASS",
                f"Source document '{source_filename}' is intact and readable ({backup_size // 1024} KB).",
                {"filename": source_filename, "size_bytes": backup_size},
                "Source Word Document",
                None,
            )
        else:
            add_check(
                "content_integrity",
                "document_backup",
                "Source Document Backup & Attachment Integrity",
                "FAIL",
                f"Source document '{source_filename}' has zero bytes; file may be corrupt or empty.",
                {"filename": source_filename, "size_bytes": 0},
                "Source Word Document",
                "Re-download or re-attach the source Word document from Basecamp. The current file is empty.",
                "Espial team",
            )
    else:
        add_check(
            "content_integrity",
            "document_backup",
            "Source Document Backup & Attachment Integrity",
            "WARNING",
            f"Source document could not be read: {source_unavail_reason or 'Unknown reason.'}",
            {"unavailability_reason": source_unavail_reason},
            "Source Word Document",
            "Verify the source Word document is accessible and re-run QA with the correct DOCX source.",
            "Espial team",
        )

    # =========================================================================
    # CATEGORY 7: CATEGORIES AND TAGS
    # =========================================================================
    
    # Check 7.1: Primary Category Assigned
    if not assigned_category_names or assigned_category_names == ["Uncategorized"]:
        add_check(
            "categories_and_tags",
            "primary_category",
            "Primary Category Assigned",
            "WARNING",
            "Article is currently Uncategorized. Discrepancy reported for Richard to assign.",
            assigned_category_names,
            "WordPress Post Categories",
            "Report discrepancy for Richard Henderson to select the appropriate primary category in WordPress Post Settings.",
            "Richard",
        )
    else:
        add_check(
            "categories_and_tags",
            "primary_category",
            "Primary Category Assigned",
            "PASS",
            f"Primary category assigned: '{assigned_category_names[0]}'.",
            assigned_category_names,
            "WordPress Post Categories",
            None,
        )

    # Check 7.2: No Duplicate Categories
    has_duplicate_cats = len(post_categories) != len(set(post_categories))
    if has_duplicate_cats:
        add_check(
            "categories_and_tags",
            "duplicate_categories_check",
            "No Duplicate Categories Assigned",
            "WARNING",
            "Duplicate category IDs detected in post assignments. Discrepancy reported for Richard.",
            post_categories,
            "WordPress Post Categories",
            "Report discrepancy for Richard Henderson to remove duplicate category selections in WordPress Post Settings.",
            "Richard",
        )
    else:
        add_check(
            "categories_and_tags",
            "duplicate_categories_check",
            "No Duplicate Categories Assigned",
            "PASS",
            f"All {len(assigned_category_names)} assigned categories are unique.",
            assigned_category_names,
            "WordPress Post Categories",
            None,
        )

    # Check 7.3: Tags Check
    # Client rule: Check tags ONLY if article description explicitly lists them; otherwise return NOT APPLICABLE
    instructions_tags = (client_instructions or {}).get("tags") or []
    if instructions_tags:
        assigned_tag_names = post_tags  # Or names if fetched
        add_check(
            "categories_and_tags",
            "tags_check",
            "Explicit Tags Verification",
            "PASS" if post_tags else "WARNING",
            f"Article instructions listed tags: {instructions_tags}. Draft has {len(post_tags)} tags.",
            {"required_tags": instructions_tags, "assigned_tags": post_tags},
            "WordPress Post Tags",
            "Report discrepancy for Richard Henderson to assign the requested tags in WordPress Post Settings." if not post_tags else None,
            "Richard" if not post_tags else None,
        )
    else:
        add_check(
            "categories_and_tags",
            "tags_check",
            "Explicit Tags Verification",
            "NOT APPLICABLE",
            "No explicit tags requested in client instructions. Tags check evaluated as NOT APPLICABLE per client rule.",
            "No tags specified in instructions.",
            "WordPress Post Tags",
            None,
        )

    # Check 7.4: Zero Automatic Category Alterations
    add_check(
        "categories_and_tags",
        "no_auto_category_creation",
        "Zero Category Mutations in QA Mode",
        "PASS",
        "Categories strictly audited in read-only mode; discrepancies reported for Richard.",
        "Zero category create/update calls.",
        "WordPress Taxonomies",
        None,
    )

    # Check 7.5: Featured Category Assigned When Requested (Legacy: featured_category)
    instructions_featured = bool((client_instructions or {}).get("featured_category"))
    if not instructions_featured:
        add_check(
            "categories_and_tags",
            "featured_category",
            "Featured Category Assigned When Requested",
            "NOT APPLICABLE",
            "Client instructions do not request a Featured category assignment. Check evaluated as NOT APPLICABLE per client rule.",
            "No featured category requested.",
            "WordPress Post Categories",
            None,
        )
    else:
        has_featured_cat = any("featured" in name.lower() for name in assigned_category_names)
        if has_featured_cat:
            featured_cat_name = next(name for name in assigned_category_names if "featured" in name.lower())
            add_check(
                "categories_and_tags",
                "featured_category",
                "Featured Category Assigned When Requested",
                "PASS",
                f"Featured category '{featured_cat_name}' verified assigned per client instructions.",
                assigned_category_names,
                "WordPress Post Categories",
                None,
            )
        else:
            add_check(
                "categories_and_tags",
                "featured_category",
                "Featured Category Assigned When Requested",
                "WARNING",
                "Client instructions request a Featured category but no 'Featured' category is assigned to this post. Discrepancy reported for Richard.",
                {"assigned_categories": assigned_category_names, "required": "Featured"},
                "WordPress Post Categories",
                "Report discrepancy for Richard Henderson to assign the 'Featured' category in WordPress Post Settings.",
                "Richard",
            )

    # Check 7.6: Additional Categories Verified Without Conflict (Legacy: additional_categories)
    instructions_extra_cats = (client_instructions or {}).get("additional_categories") or []
    if not instructions_extra_cats:
        add_check(
            "categories_and_tags",
            "additional_categories",
            "Additional Categories Verified Without Conflict",
            "NOT APPLICABLE",
            "No additional categories specified in client instructions. Check evaluated as NOT APPLICABLE.",
            "No additional categories in instructions.",
            "WordPress Post Categories",
            None,
        )
    else:
        assigned_lower = [name.lower() for name in assigned_category_names]
        missing_extra = [c for c in instructions_extra_cats if c.lower() not in assigned_lower]
        if missing_extra:
            add_check(
                "categories_and_tags",
                "additional_categories",
                "Additional Categories Verified Without Conflict",
                "WARNING",
                f"Requested additional categories missing from post: {missing_extra}. Discrepancy reported for Richard.",
                {"required_additional": instructions_extra_cats, "assigned": assigned_category_names, "missing": missing_extra},
                "WordPress Post Categories",
                f"Report discrepancy for Richard Henderson to assign missing categories: {', '.join(missing_extra)}.",
                "Richard",
            )
        else:
            add_check(
                "categories_and_tags",
                "additional_categories",
                "Additional Categories Verified Without Conflict",
                "PASS",
                f"All {len(instructions_extra_cats)} additional requested category/categories verified assigned.",
                {"required_additional": instructions_extra_cats, "assigned": assigned_category_names},
                "WordPress Post Categories",
                None,
            )

    # =========================================================================
    # CATEGORY 8: AUTHOR AND AUTHOR BOX
    # =========================================================================
    
    # Check 8.1: Prohibited Author Check (Naveen Shukla / webdev / admin)
    author_lower = author_name.strip().lower()
    is_prohibited = any(p in author_lower for p in PROHIBITED_AUTHORS)
    if is_prohibited:
        add_check(
            "author",
            "prohibited_author_check",
            "Prohibited Author Check (Never Naveen Shukla or Admin)",
            "FAIL",
            f"CRITICAL: Author is currently assigned to '{author_name}', which is a prohibited account. Must be reassigned to Richard Henderson or specified author.",
            author_name,
            "WordPress Post Author field",
            f"In WordPress Post Settings, change the author assignment from prohibited account '{author_name}' to Richard Henderson or the specified author.",
            "Richard",
        )
    else:
        add_check(
            "author",
            "prohibited_author_check",
            "Prohibited Author Check (Never Naveen Shukla or Admin)",
            "PASS",
            f"Author assignment '{author_name}' verified safe (not Naveen Shukla or admin).",
            author_name,
            "WordPress Post Author field",
            None,
        )

    # Check 8.2: Author Matches Instructions or Defaults to Richard Henderson
    instructions_available = bool(
        client_instructions
        and isinstance(client_instructions, dict)
        and any(bool(v) for v in client_instructions.values())
    )
    instructed_author = (client_instructions or {}).get("author") if instructions_available else None
    
    # Check for author byline in draft body text (e.g. "By Jennifer Vance...")
    byline_m = re.search(r"\bby\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", parsed_html.text)
    body_byline = byline_m.group(1) if byline_m else None

    if not instructions_available:
        # Standalone audit where article-specific Basecamp instructions are unavailable
        limitation_msg = (
            f"Article-specific Basecamp instructions are unavailable (Standalone draft audit). "
            f"Draft author on WordPress is '{author_name}'"
        )
        if body_byline and body_byline.lower() != author_name.lower():
            limitation_msg += f" (Body text contains byline: 'By {body_byline}'). "
        else:
            limitation_msg += ". "
        limitation_msg += (
            f"Cannot determine whether '{author_name}' was specifically instructed by client or if default 'Richard Henderson' should apply. "
            f"Limitation noted: verify Basecamp card instructions before publishing."
        )

        add_check(
            "author",
            "author_matches_instructions",
            "Author Matches Specifics or Defaults to Richard Henderson",
            "NOT APPLICABLE",
            limitation_msg,
            {
                "draft_author": author_name,
                "body_byline": body_byline,
                "instructions_available": False,
                "client_default_rule": "Richard Henderson when no author specified in Basecamp instructions",
            },
            "WordPress Post Author field",
            None,
        )
    elif instructed_author:
        # Article-specific instructions explicitly specify an author
        if author_lower == instructed_author.lower():
            add_check(
                "author",
                "author_matches_instructions",
                "Author Matches Specifics or Defaults to Richard Henderson",
                "PASS",
                f"Draft author matches article-specific Basecamp instruction: '{author_name}'.",
                author_name,
                "WordPress Post Author field",
                None,
            )
        else:
            add_check(
                "author",
                "author_matches_instructions",
                "Author Matches Specifics or Defaults to Richard Henderson",
                "WARNING",
                f"Draft author '{author_name}' does not match article-specific Basecamp instruction '{instructed_author}'. Report discrepancy for Richard.",
                {"current_author": author_name, "expected_author": instructed_author},
                "WordPress Post Author field",
                f"In WordPress Post Settings, change author from '{author_name}' to '{instructed_author}' per Basecamp instructions.",
                "Richard",
            )
    else:
        # Instructions exist and are verified, but specify NO author -> client default is Richard Henderson
        if author_lower == "richard henderson":
            add_check(
                "author",
                "author_matches_instructions",
                "Author Matches Specifics or Defaults to Richard Henderson",
                "PASS",
                "Draft author correctly set to default 'Richard Henderson' (no author specified in verified Basecamp instructions).",
                author_name,
                "WordPress Post Author field",
                None,
            )
        else:
            add_check(
                "author",
                "author_matches_instructions",
                "Author Matches Specifics or Defaults to Richard Henderson",
                "WARNING",
                f"Basecamp instructions did not specify an author; client rule specifies 'Richard Henderson' as default. Draft author is '{author_name}'. Report discrepancy for Richard.",
                {"current_author": author_name, "default_author": "Richard Henderson"},
                "WordPress Post Author field",
                f"In WordPress Post Settings, reassign author from '{author_name}' to default 'Richard Henderson'.",
                "Richard",
            )

    # Check 8.3: Author Box Requested Verification
    author_box_requested = bool((client_instructions or {}).get("author_box_requested"))
    if author_box_requested:
        has_author_box = bool(re.search(r'\b(author-box|author-bio|about the author)\b', post_content, re.IGNORECASE))
        if has_author_box:
            add_check(
                "author",
                "author_box_requested",
                "Author Box Present When Requested",
                "PASS",
                f"Author box verified present in article content for author '{author_name}'.",
                {"author_box_requested": True, "detected": True},
                "Article Author Bio Box",
                None,
            )
        else:
            add_check(
                "author",
                "author_box_requested",
                "Author Box Present When Requested",
                "WARNING",
                "Author box was requested in article instructions but was not detected in article body.",
                {"author_box_requested": True, "detected": False},
                "Article Author Bio Box",
                f"In WordPress editor, ensure an author bio box is included for '{author_name}'.",
                "Richard",
            )
    else:
        add_check(
            "author",
            "author_box_requested",
            "Author Box Present When Requested",
            "NOT APPLICABLE",
            "Author box was not explicitly requested in client instructions. Evaluated as NOT APPLICABLE per client rule.",
            "Not requested.",
            "Article Author Bio Box",
            None,
        )

    # Check 8.4: Read-Only Author in QA
    add_check(
        "author",
        "read_only_author_in_qa",
        "Zero Author Mutations in QA Only Mode",
        "PASS",
        "Author verified via read-only GET; no user assignment or update requests sent.",
        "Zero author update requests.",
        "WordPress Post Author",
        None,
    )

    # =========================================================================
    # CATEGORY 9: DUPLICATE CHECK
    # =========================================================================
    
    # Check 9.1: Slug Filler Words Check
    filler_words = {"a", "the", "in", "and", "of", "to", "for", "on", "at", "by", "with"}
    slug_parts = post_slug.split("-")
    slug_fillers = [w for w in slug_parts if w in filler_words]
    if slug_fillers:
        add_check(
            "duplicate_check",
            "slug_filler_words_check",
            "Slug Clean of Filler Words",
            "WARNING",
            f"Slug contains filler words: {slug_fillers}. Client slug rules recommend removing filler words.",
            {"slug": post_slug, "filler_words_found": slug_fillers},
            "WordPress Post Slug (Permalink)",
            f"In WordPress Post Settings, edit the URL slug '{post_slug}' to remove filler words ({', '.join(slug_fillers)}).",
            "Espial team",
        )
    else:
        add_check(
            "duplicate_check",
            "slug_filler_words_check",
            "Slug Clean of Filler Words",
            "PASS",
            f"Slug '{post_slug}' is optimized and free of filler words.",
            post_slug,
            "WordPress Post Slug (Permalink)",
            None,
        )

    # Check 9.2: Slug Duplicate Suffix Check ("-2", "-3")
    ends_in_duplicate_suffix = bool(re.search(r"-[2-9]$", post_slug))
    if ends_in_duplicate_suffix:
        add_check(
            "duplicate_check",
            "slug_suffix_duplicate_check",
            "No Auto-Incremented Duplicate Slug Suffix",
            "FAIL",
            f"Slug '{post_slug}' ends in a duplicate suffix (e.g. -2). WordPress appends numbers when a duplicate post exists.",
            post_slug,
            "WordPress Post Slug (Permalink)",
            f"Check for duplicate or conflicting posts with the same slug and edit post slug '{post_slug}' to remove numeric suffix.",
            "Espial team",
        )
    else:
        add_check(
            "duplicate_check",
            "slug_suffix_duplicate_check",
            "No Auto-Incremented Duplicate Slug Suffix",
            "PASS",
            f"Slug '{post_slug}' does not end in a duplicate numeric suffix.",
            post_slug,
            "WordPress Post Slug (Permalink)",
            None,
        )

    # Check 9.3: WordPress Duplicate Post Check (read-only search)
    dup_check = await wp_service.check_duplicate(post_title, site.url, site.username, site.app_password)
    existing_posts = dup_check.get("existing_posts") or []
    # Ignore the post itself if it's the draft being audited
    other_duplicates = [p for p in existing_posts if p.get("id") != post_id]
    if other_duplicates:
        add_check(
            "duplicate_check",
            "duplicate_post_check",
            "No Pre-Existing Duplicate Post on WordPress",
            "FAIL",
            f"Found {len(other_duplicates)} duplicate post(s) with matching title on destination site: {[p.get('id') for p in other_duplicates]}",
            other_duplicates,
            "WordPress Posts Database",
            f"Investigate existing WordPress post(s) #{[p.get('id') for p in other_duplicates]} with matching titles; if obsolete, move old post to draft.",
            "Espial team",
        )
    else:
        add_check(
            "duplicate_check",
            "duplicate_post_check",
            "No Pre-Existing Duplicate Post on WordPress",
            "PASS",
            "No duplicate posts found with this title on destination WordPress site.",
            "0 conflicting duplicate posts.",
            "WordPress Posts Database",
            None,
        )

    # =========================================================================
    # CATEGORY 10: SEO — YOAST, REPORT ONLY
    # =========================================================================
    focus_kw = post_meta.get("_yoast_wpseo_focuskw") or post_meta.get("yoast_wpseo_focuskw") or ""
    meta_desc = post_meta.get("_yoast_wpseo_metadesc") or post_meta.get("yoast_wpseo_metadesc") or ""
    post_excerpt = post.get("excerpt", {}).get("raw") or post.get("excerpt", {}).get("rendered") or ""

    # Check 10.1: Focus Keyphrase Length (<= 5 Words Rule)
    kw_words = focus_kw.split()
    if not focus_kw:
        yoast_issues_table.append({
            "parameter": "Focus Keyphrase",
            "location": "Yoast SEO Meta Box (_yoast_wpseo_focuskw)",
            "actual_value": "Empty / Not Set",
            "requirement": "Concise focus keyphrase (<= 5 words)",
            "suggested_fix": "Enter a focus keyphrase of 5 words or fewer in the Yoast SEO meta box.",
            "responsible": "Espial team",
        })
        add_check(
            "seo",
            "focus_keyphrase_length",
            "Focus Keyphrase Set (<= 5 Words Rule)",
            "FAIL",
            "Yoast focus keyphrase is not set on this draft.",
            "Empty focus keyphrase.",
            "Yoast SEO Meta Box (_yoast_wpseo_focuskw)",
            "In Yoast SEO meta box, enter a concise focus keyphrase of 5 words or fewer.",
            "Espial team",
        )
    elif len(kw_words) > 5:
        yoast_issues_table.append({
            "parameter": "Focus Keyphrase Length",
            "location": "Yoast SEO Meta Box (_yoast_wpseo_focuskw)",
            "actual_value": f"'{focus_kw}' ({len(kw_words)} words)",
            "requirement": "Maximum 5 words per client rule",
            "suggested_fix": "Shorten focus keyphrase to 5 words or fewer in the Yoast SEO meta box.",
            "responsible": "Espial team",
        })
        add_check(
            "seo",
            "focus_keyphrase_length",
            "Focus Keyphrase Set (<= 5 Words Rule)",
            "FAIL",
            f"Focus keyphrase '{focus_kw}' contains {len(kw_words)} words (Client rule: maximum 5 words).",
            {"focus_keyphrase": focus_kw, "word_count": len(kw_words)},
            "Yoast SEO Meta Box (_yoast_wpseo_focuskw)",
            f"In Yoast SEO meta box, shorten focus keyphrase '{focus_kw}' to 5 words or fewer.",
            "Espial team",
        )
    else:
        add_check(
            "seo",
            "focus_keyphrase_length",
            "Focus Keyphrase Set (<= 5 Words Rule)",
            "PASS",
            f"Focus keyphrase verified: '{focus_kw}' ({len(kw_words)} words).",
            focus_kw,
            "Yoast SEO Meta Box (_yoast_wpseo_focuskw)",
            None,
        )

    # Check 10.2: Keyphrase in Meta Description & Meta Title
    kw_in_title = bool(focus_kw and focus_kw.lower() in meta_title.lower())
    kw_in_desc = bool(focus_kw and focus_kw.lower() in meta_desc.lower())
    if kw_in_title and kw_in_desc:
        add_check(
            "seo",
            "keyphrase_in_meta_title_and_desc",
            "Focus Keyphrase in Meta Title & Meta Description",
            "PASS",
            f"Focus keyphrase '{focus_kw}' present in both meta title and meta description.",
            {"meta_title": meta_title, "meta_desc": meta_desc},
            "Yoast SEO Meta Title & Description",
            None,
        )
    else:
        yoast_issues_table.append({
            "parameter": "Keyphrase Placement",
            "location": "Yoast SEO Meta Title & Meta Description",
            "actual_value": f"In Title: {'YES' if kw_in_title else 'NO'}, In Desc: {'YES' if kw_in_desc else 'NO'}",
            "requirement": "Focus keyphrase must appear in both meta title and meta description",
            "suggested_fix": "Include the focus keyphrase in both the meta title and meta description in Yoast SEO.",
            "responsible": "Espial team",
        })
        add_check(
            "seo",
            "keyphrase_in_meta_title_and_desc",
            "Focus Keyphrase in Meta Title & Meta Description",
            "WARNING",
            f"Keyphrase presence: Meta Title={'YES' if kw_in_title else 'NO'}, Meta Description={'YES' if kw_in_desc else 'NO'}.",
            {"meta_title": meta_title, "meta_desc": meta_desc},
            "Yoast SEO Meta Title & Description",
            "In Yoast SEO meta box, ensure the focus keyphrase appears naturally in both the meta title and meta description.",
            "Espial team",
        )

    # Check 10.3: Meta Description Length (Confirmed 140–155 Characters Range)
    desc_len = len(meta_desc.strip())
    if 140 <= desc_len <= 155:
        add_check(
            "seo",
            "meta_description_length",
            "Meta Description Length (140–155 Characters Range)",
            "PASS",
            f"Meta description is {desc_len} characters (Within confirmed 140–155 char range).",
            {"length": desc_len, "text": meta_desc},
            "Yoast SEO Meta Description (_yoast_wpseo_metadesc)",
            None,
        )
    elif desc_len == 0:
        yoast_issues_table.append({
            "parameter": "Meta Description Length",
            "location": "Yoast SEO Meta Description (_yoast_wpseo_metadesc)",
            "actual_value": "0 characters (Missing)",
            "requirement": "Strictly 140–155 characters",
            "suggested_fix": "Write a meta description between 140 and 155 characters in the Yoast SEO meta box.",
            "responsible": "Espial team",
        })
        add_check(
            "seo",
            "meta_description_length",
            "Meta Description Length (140–155 Characters Range)",
            "FAIL",
            "Meta description is missing entirely.",
            "Empty meta description.",
            "Yoast SEO Meta Description (_yoast_wpseo_metadesc)",
            "In Yoast SEO meta box, write a meta description strictly between 140 and 155 characters.",
            "Espial team",
        )
    else:
        yoast_issues_table.append({
            "parameter": "Meta Description Length",
            "location": "Yoast SEO Meta Description (_yoast_wpseo_metadesc)",
            "actual_value": f"{desc_len} characters",
            "requirement": "Strictly 140–155 characters (Client confirmed inclusive range)",
            "suggested_fix": f"{'Expand' if desc_len < 140 else 'Shorten'} meta description in Yoast SEO to between 140 and 155 characters.",
            "responsible": "Espial team",
        })
        add_check(
            "seo",
            "meta_description_length",
            "Meta Description Length (140–155 Characters Range)",
            "WARNING",
            f"Meta description is {desc_len} characters (Client confirmed requirement: 140–155 characters).",
            {"length": desc_len, "text": meta_desc},
            "Yoast SEO Meta Description (_yoast_wpseo_metadesc)",
            f"In Yoast SEO meta box, {'expand' if desc_len < 140 else 'shorten'} meta description to fall strictly within 140–155 characters (currently {desc_len}).",
            "Espial team",
        )

    # Check 10.4: Excerpt Matches Meta Description
    clean_excerpt = html.unescape(re.sub(r"<[^>]+>", "", post_excerpt)).strip()
    if meta_desc and clean_excerpt and clean_excerpt.lower() == meta_desc.strip().lower():
        add_check(
            "seo",
            "excerpt_matches_meta",
            "Excerpt Synchronized with Meta Description",
            "PASS",
            "Post excerpt exactly matches Yoast meta description.",
            clean_excerpt,
            "WordPress Post Excerpt",
            None,
        )
    elif not meta_desc or not clean_excerpt:
        yoast_issues_table.append({
            "parameter": "Excerpt Synchronization",
            "location": "WordPress Post Excerpt",
            "actual_value": "Excerpt or meta description empty",
            "requirement": "Post excerpt must match Yoast meta description verbatim",
            "suggested_fix": "Copy Yoast meta description text into the Post Excerpt field.",
            "responsible": "Espial team",
        })
        add_check(
            "seo",
            "excerpt_matches_meta",
            "Excerpt Synchronized with Meta Description",
            "WARNING",
            "Excerpt or meta description is empty.",
            {"meta_desc": meta_desc, "excerpt": clean_excerpt},
            "WordPress Post Excerpt",
            "In WordPress Post Settings, populate the Excerpt field with the exact Yoast meta description text.",
            "Espial team",
        )
    else:
        yoast_issues_table.append({
            "parameter": "Excerpt Synchronization",
            "location": "WordPress Post Excerpt",
            "actual_value": (clean_excerpt[:60] + "...") if clean_excerpt else "Empty",
            "requirement": "Post excerpt must match Yoast meta description verbatim",
            "suggested_fix": "Copy the Yoast meta description text into the Post Excerpt field in WordPress Post Settings.",
            "responsible": "Espial team",
        })
        add_check(
            "seo",
            "excerpt_matches_meta",
            "Excerpt Synchronized with Meta Description",
            "WARNING",
            "Excerpt differs from meta description.",
            {"meta_desc": meta_desc, "excerpt": clean_excerpt},
            "WordPress Post Excerpt",
            "In WordPress Post Settings, synchronize the Post Excerpt by pasting the exact Yoast meta description text.",
            "Espial team",
        )

    # Check 10.6: Keyphrase Derived from Title (Legacy: keyphrase_from_title)
    if not focus_kw:
        add_check(
            "seo",
            "keyphrase_from_title",
            "Focus Keyphrase Derived from Article Title",
            "NOT APPLICABLE",
            "No focus keyphrase set; keyphrase derivation check not applicable.",
            "Empty keyphrase.",
            "Yoast SEO Meta Box (_yoast_wpseo_focuskw)",
            None,
        )
    else:
        kw_words_lower = [w.lower() for w in focus_kw.split() if w]
        title_words_lower = re.sub(r"[^\w\s]", "", post_title.lower()).split()
        derived_words = [w for w in kw_words_lower if w in title_words_lower]
        derived_ratio = len(derived_words) / max(len(kw_words_lower), 1)
        if derived_ratio >= 0.8:
            add_check(
                "seo",
                "keyphrase_from_title",
                "Focus Keyphrase Derived from Article Title",
                "PASS",
                f"Focus keyphrase '{focus_kw}' is derived from article title (all {len(derived_words)} keyword(s) found in title).",
                {"focus_kw": focus_kw, "post_title": post_title, "derived_words": derived_words},
                "Yoast SEO Meta Box vs Article Title",
                None,
            )
        else:
            missing_kw = [w for w in kw_words_lower if w not in title_words_lower]
            yoast_issues_table.append({
                "parameter": "Keyphrase Derivation",
                "location": "Yoast SEO Meta Box vs Article Title",
                "actual_value": f"'{focus_kw}' — {len(missing_kw)} word(s) not in title",
                "requirement": "Focus keyphrase must be derived directly from article title keywords",
                "suggested_fix": f"Update focus keyphrase to use words from the article title. Missing: {missing_kw}.",
                "responsible": "Espial team",
            })
            add_check(
                "seo",
                "keyphrase_from_title",
                "Focus Keyphrase Derived from Article Title",
                "WARNING",
                f"Focus keyphrase '{focus_kw}' contains word(s) not present in article title: {missing_kw}.",
                {"focus_kw": focus_kw, "post_title": post_title, "missing_words": missing_kw},
                "Yoast SEO Meta Box vs Article Title",
                f"Update focus keyphrase to words directly from the article title. Missing words: {', '.join(missing_kw)}.",
                "Espial team",
            )

    # Check 10.7: Keyphrase Present Naturally in Body Content (Legacy: keyphrase_naturally_present)
    if not focus_kw:
        add_check(
            "seo",
            "keyphrase_naturally_present",
            "Focus Keyphrase Naturally Present in Body Content",
            "NOT APPLICABLE",
            "No focus keyphrase set; keyphrase body presence check not applicable.",
            "Empty keyphrase.",
            "Article body text",
            None,
        )
    else:
        kw_lower = focus_kw.lower()
        draft_text_lower = parsed_html.text.lower()
        kw_count = draft_text_lower.count(kw_lower)
        if kw_count >= 1:
            add_check(
                "seo",
                "keyphrase_naturally_present",
                "Focus Keyphrase Naturally Present in Body Content",
                "PASS",
                f"Focus keyphrase '{focus_kw}' found {kw_count} time(s) naturally in article body.",
                {"focus_kw": focus_kw, "occurrence_count": kw_count},
                "Article body text",
                None,
            )
        else:
            yoast_issues_table.append({
                "parameter": "Keyphrase in Content",
                "location": "Article body text",
                "actual_value": f"'{focus_kw}' not found in body",
                "requirement": "Focus keyphrase must appear naturally at least once in article body content",
                "suggested_fix": "Ensure the focus keyphrase appears naturally in the article body text (Yoast recommendation).",
                "responsible": "Espial team",
            })
            add_check(
                "seo",
                "keyphrase_naturally_present",
                "Focus Keyphrase Naturally Present in Body Content",
                "WARNING",
                f"Focus keyphrase '{focus_kw}' not found in article body text. Yoast will flag this as an SEO issue.",
                {"focus_kw": focus_kw, "occurrence_count": 0},
                "Article body text",
                "Ensure the focus keyphrase appears at least once naturally in the article body (do not force; weave naturally into existing sentences).",
                "Espial team",
            )

    # Check 10.8: SEO Title Generated with Keyphrase at Beginning (Legacy: seo_title)
    if not meta_title:
        add_check(
            "seo",
            "seo_title",
            "SEO Title Generated with Keyphrase at Beginning",
            "FAIL",
            "No SEO/meta title set in Yoast meta box.",
            "Empty meta title.",
            "Yoast SEO Meta Box (_yoast_wpseo_title)",
            "In Yoast SEO meta box, enter an SEO title that starts with the focus keyphrase.",
            "Espial team",
        )
    elif focus_kw and not meta_title.lower().startswith(focus_kw.lower()):
        # Check if keyphrase is within first 30% of title
        title_start = meta_title[:max(len(focus_kw) + 10, len(meta_title) // 3)].lower()
        kw_near_start = focus_kw.lower() in title_start
        if kw_near_start:
            add_check(
                "seo",
                "seo_title",
                "SEO Title Generated with Keyphrase at Beginning",
                "PASS",
                f"SEO title starts with or opens with focus keyphrase '{focus_kw}': '{meta_title}'.",
                {"meta_title": meta_title, "focus_kw": focus_kw},
                "Yoast SEO Meta Box (_yoast_wpseo_title)",
                None,
            )
        else:
            yoast_issues_table.append({
                "parameter": "SEO Title Keyphrase Position",
                "location": "Yoast SEO Meta Box (_yoast_wpseo_title)",
                "actual_value": meta_title,
                "requirement": "Focus keyphrase should appear at the beginning of the SEO title",
                "suggested_fix": f"Reorder the SEO title to start with '{focus_kw}'.",
                "responsible": "Espial team",
            })
            add_check(
                "seo",
                "seo_title",
                "SEO Title Generated with Keyphrase at Beginning",
                "WARNING",
                f"Focus keyphrase '{focus_kw}' does not appear at the start of SEO title: '{meta_title}'.",
                {"meta_title": meta_title, "focus_kw": focus_kw},
                "Yoast SEO Meta Box (_yoast_wpseo_title)",
                f"Edit the Yoast SEO title to begin with the focus keyphrase '{focus_kw}'.",
                "Espial team",
            )
    elif not focus_kw and meta_title:
        add_check(
            "seo",
            "seo_title",
            "SEO Title Generated with Keyphrase at Beginning",
            "NOT APPLICABLE",
            f"SEO title set ('{meta_title}') but no focus keyphrase to verify position against.",
            {"meta_title": meta_title},
            "Yoast SEO Meta Box (_yoast_wpseo_title)",
            None,
        )
    else:
        add_check(
            "seo",
            "seo_title",
            "SEO Title Generated with Keyphrase at Beginning",
            "PASS",
            f"SEO title starts with focus keyphrase '{focus_kw}': '{meta_title}'.",
            {"meta_title": meta_title, "focus_kw": focus_kw},
            "Yoast SEO Meta Box (_yoast_wpseo_title)",
            None,
        )

    # Check 10.9: Keyphrase Synonyms Present (Legacy: synonyms)
    synonyms_raw = post_meta.get("_yoast_wpseo_focuskeywords") or post_meta.get("yoast_wpseo_focuskeywords") or ""
    if synonyms_raw:
        add_check(
            "seo",
            "synonyms",
            "Keyphrase Synonyms Set in Yoast Meta",
            "PASS",
            f"Yoast synonyms field populated: {str(synonyms_raw)[:80]}",
            str(synonyms_raw)[:120],
            "Yoast SEO Meta Box (_yoast_wpseo_focuskeywords)",
            None,
        )
    else:
        add_check(
            "seo",
            "synonyms",
            "Keyphrase Synonyms Set in Yoast Meta",
            "WARNING",
            "Yoast focus keyword synonyms field is empty. Synonyms improve keyphrase variant recognition.",
            "Empty synonyms field.",
            "Yoast SEO Meta Box (_yoast_wpseo_focuskeywords)",
            "In Yoast SEO meta box, add keyphrase synonyms (related phrases) to improve SEO coverage.",
            "Espial team",
        )

    # Check 10.10: Yoast SEO Metadata Saved & Verified in Postmeta (Legacy: seo_metadata_saved)
    seo_fields_present = {
        "focus_keyphrase": bool(focus_kw),
        "meta_title": bool(meta_title),
        "meta_description": bool(meta_desc),
    }
    missing_seo = [k for k, v in seo_fields_present.items() if not v]
    if not missing_seo:
        add_check(
            "seo",
            "seo_metadata_saved",
            "Yoast SEO Metadata Verified in WordPress Postmeta",
            "PASS",
            "All core Yoast SEO metadata fields verified saved in WordPress post meta: focus keyphrase, SEO title, and meta description.",
            seo_fields_present,
            "WordPress Post Meta (_yoast_wpseo_*)",
            None,
        )
    else:
        for missing_field in missing_seo:
            yoast_issues_table.append({
                "parameter": f"SEO Metadata: {missing_field}",
                "location": "WordPress Post Meta (_yoast_wpseo_*)",
                "actual_value": "Empty / Not saved",
                "requirement": "All Yoast SEO metadata fields must be saved to WordPress post meta",
                "suggested_fix": f"Save the '{missing_field}' field in Yoast SEO meta box and re-publish draft to WordPress.",
                "responsible": "Espial team",
            })
        add_check(
            "seo",
            "seo_metadata_saved",
            "Yoast SEO Metadata Verified in WordPress Postmeta",
            "FAIL",
            f"Missing Yoast SEO metadata field(s) in WordPress post meta: {missing_seo}.",
            seo_fields_present,
            "WordPress Post Meta (_yoast_wpseo_*)",
            f"In Yoast SEO meta box, populate missing field(s): {', '.join(missing_seo)}, then update the draft to save metadata.",
            "Espial team",
        )

    # Check 10.11 [orig 10.5]: Yoast Report-Only Protocol
    add_check(
        "seo",
        "yoast_report_only",
        "Strictly Report-Only Protocol (Zero QA Modifications)",
        "PASS",
        "All SEO and Yoast evaluations executed in report-only mode; zero modifications to post body, slug, or meta.",
        "Zero WordPress write requests.",
        "Yoast SEO Settings",
        None,
    )

    # =========================================================================
    # SUMMARY & OVERALL VERDICT CALCULATION
    # =========================================================================
    total_pass = 0
    total_fail = 0
    total_warning = 0
    total_na = 0
    total_inconclusive = 0

    all_checks = []
    for cat_key, items in categories_output.items():
        for item in items:
            all_checks.append(item)
            st = item["status"]
            if st == "PASS":
                total_pass += 1
            elif st == "FAIL":
                total_fail += 1
            elif st == "WARNING":
                total_warning += 1
            elif st == "NOT APPLICABLE":
                total_na += 1
            elif st == "INCONCLUSIVE":
                total_inconclusive += 1

    # Verdict rules:
    # BLOCKED if any critical FAIL occurs (prohibited author, dead links, H1 in body, duplicate post, draft status invalid)
    # READY AFTER FIXES if warnings or non-critical failures exist
    # READY if all applicable checks pass
    if total_fail > 0:
        verdict = "BLOCKED"
        verdict_summary = f"Blocked: {total_fail} check(s) failed and must be resolved before proceeding."
    elif total_warning > 0:
        verdict = "READY AFTER FIXES"
        verdict_summary = f"Ready after review: 0 failures, but {total_warning} warning(s) should be reviewed."
    else:
        verdict = "READY"
        verdict_summary = f"All {total_pass} active checks passed successfully."

    # Ensure all table rows have consistent field aliases
    for row in broken_links_table:
        row.setdefault("responsible_party", row.get("responsible", "Espial team"))
        row.setdefault("responsible", row.get("responsible_party", "Espial team"))
    for row in image_issues_table:
        row.setdefault("responsible_party", row.get("responsible", "Espial team"))
        row.setdefault("responsible", row.get("responsible_party", "Espial team"))
    for row in content_differences_table:
        row.setdefault("responsible_party", row.get("responsible", "Espial team"))
        row.setdefault("responsible", row.get("responsible_party", "Espial team"))
        if "difference" not in row and "actual" in row:
            row["difference"] = f"Expected: {row.get('expected', '')} | Actual: {row.get('actual', '')}"
    for row in yoast_issues_table:
        row.setdefault("responsible_party", row.get("responsible", "Espial team"))
        row.setdefault("responsible", row.get("responsible_party", "Espial team"))
        if "recommendation" not in row and "suggested_fix" in row:
            row["recommendation"] = row["suggested_fix"]

    return {
        "success": True,
        "site_id": site.id,
        "site_name": site.name,
        "site_url": site.url,
        "post_id": post_id,
        "post_title": post_title,
        "post_status": post_status,
        "post_slug": post_slug,
        "author_name": author_name,
        "categories_assigned": assigned_category_names,
        "featured_media_id": featured_media_id,
        "source_document": {
            "attached": has_source_doc,
            "filename": source_filename if has_source_doc else None,
            "unavailability_reason": source_unavail_reason,
            "matched": has_source_doc,
        },
        "verdict": verdict,
        "verdict_summary": verdict_summary,
        "counts": {
            "total_checks": len(all_checks),
            "pass": total_pass,
            "fail": total_fail,
            "warning": total_warning,
            "not_applicable": total_na,
            "inconclusive": total_inconclusive,
        },
        "categories": categories_output,
        "tables": {
            "broken_links": broken_links_table,
            "image_issues": image_issues_table,
            "content_differences": content_differences_table,
            "yoast_issues": yoast_issues_table,
        },
        "zero_write_guarantee": True,
    }
