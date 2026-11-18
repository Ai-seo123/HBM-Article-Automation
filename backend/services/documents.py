import io
import logging
import os
import re
from typing import Optional
import httpx

log = logging.getLogger(__name__)
_USER_AGENT = 'HBM Article Automation (espial.contact@gmail.com)'



async def _download_basecamp_file(url: str, access_token: str) -> bytes:
    """
    Download a file from Basecamp using the API/auth hop pattern.
    1. Hit the API URL with the OAuth token (returns 302).
    2. Follow the 302 redirect to the signed storage URL without the OAuth token.
    """
    if not access_token or str(access_token).strip() in ("", "None"):
        raise ValueError("Basecamp access token is required for attachment download. Please connect or refresh Basecamp.")

    # The URL parsed from HTML is often the web UI URL. 
    # We must hit the API domain to use our OAuth token.
    if "storage.app.basecamp.com" in url:
        url = url.replace("storage.app.basecamp.com", "3.basecampapi.com")

    headers = {
        'Authorization': f'Bearer {access_token.strip()}',
        'User-Agent': _USER_AGENT,
        'Accept': '*/*',
    }
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        try:
            # Step 1: Authenticated hop
            log.info("Requesting attachment download from Basecamp API: url=%s (authenticated hop)", url)
            resp = await client.get(url, headers=headers)
            log.info("Basecamp API responded with status %s", resp.status_code)
            if resp.status_code in (301, 302, 303, 307, 308):
                # Step 2: Unauthenticated hop to signed storage URL
                redirect_url = resp.headers.get('Location')
                if not redirect_url:
                    raise RuntimeError(f"Basecamp returned redirect status {resp.status_code} without Location header.")
                log.info("Following redirect to storage backend (unauthenticated hop)")
                resp2 = await client.get(redirect_url, follow_redirects=True)
                log.info("Storage backend responded with status %s, content length %s bytes", resp2.status_code, len(resp2.content))
                resp2.raise_for_status()
                return resp2.content
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPStatusError as exc:
            log.error('Attachment download failed: HTTP %s for %s. Response preview: %s', exc.response.status_code, url, exc.response.text[:200] if exc.response.text else 'None')
            raise RuntimeError(
                f'Basecamp returned HTTP {exc.response.status_code} when downloading attachment.'
            ) from exc
        except httpx.RequestError as exc:
            log.error('Attachment download request error: %s', exc)
            raise RuntimeError('Network error while downloading attachment from Basecamp.') from exc
    return resp.content


def _extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract plain text from DOCX (used for AI processing / duplicate check title)."""
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError('python-docx is not installed. Add it to requirements.txt.') from exc
    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as exc:
        log.error('Failed to open DOCX: %s', exc)
        raise ValueError(f'Could not open DOCX file: {exc}') from exc
    parts: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)
    for table in doc.tables:
        for row in table.rows:
            row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if row_cells:
                parts.append('\t'.join(row_cells))
    if not parts:
        raise ValueError('The DOCX file contains no readable text.')
    return '\n\n'.join(parts)


def _extract_html_from_docx(file_bytes: bytes) -> str:
    """
    Extract article content as HTML from DOCX, PRESERVING:
      - Paragraph structure
      - Heading levels (h1–h6)
      - Hyperlinks with exact URL and anchor text
      - Bold / italic (as <strong> / <em>)
      - Lists (ul/ol)
      - Tables

    This is the source-of-truth content. The AI MUST NOT alter this HTML —
    it is only used for SEO metadata generation and structure analysis.
    """
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from lxml import etree
    except ImportError as exc:
        raise RuntimeError(
            'python-docx and lxml are required. Add them to requirements.txt.'
        ) from exc

    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as exc:
        log.error('Failed to open DOCX for HTML extraction: %s', exc)
        raise ValueError(f'Could not open DOCX file: {exc}') from exc

    # Build a relationship map: rId -> target URL
    hyperlink_rels: dict[str, str] = {}
    for rel in doc.part.rels.values():
        if "hyperlink" in rel.reltype.lower():
            target_val = getattr(rel, "target_ref", None) or getattr(rel, "_target", "")
            hyperlink_rels[rel.rId] = target_val

    def _run_html(run) -> str:
        """Convert a single run to HTML, preserving bold/italic."""
        text = run.text
        if not text:
            return ""
        # Escape HTML entities
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if run.bold:
            text = f"<strong>{text}</strong>"
        if run.italic:
            text = f"<em>{text}</em>"
        return text

    def _para_html(para) -> str:
        """Convert a paragraph to HTML, following heading styles and hyperlinks."""
        heading_level = None

        # 1. Detect heading level from paragraph outline level in XML properties (w:pPr -> w:outlineLvl)
        p_pr = getattr(para._element, "pPr", None)
        if p_pr is not None:
            for child in p_pr:
                tag_local = etree.QName(child.tag).localname if child.tag else ""
                if tag_local == "outlineLvl":
                    val_str = child.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") or child.get("val")
                    if val_str and val_str.isdigit():
                        val = int(val_str)
                        if 0 <= val <= 5:
                            heading_level = val + 1
                    break

        # 2. Detect heading level from style name or style ID
        if not heading_level and getattr(para, "style", None):
            style_name = (para.style.name or "").lower()
            style_id = (getattr(para.style, "style_id", None) or "").lower()
            combined = f"{style_name} {style_id}".strip()

            if "title" in combined:
                heading_level = 1
            elif "subtitle" in combined:
                heading_level = 2
            else:
                m = re.search(r"\bheading\s*([1-6])\b|\bheading([1-6])\b|\bh([1-6])\b", combined)
                if m:
                    heading_level = int(m.group(1) or m.group(2) or m.group(3))

        # Flatten structured tags if any (w:sdt, w:ins, w:smartTag)
        def _flatten_children(container):
            items = []
            for ch in container:
                ch_tag = etree.QName(ch.tag).localname if ch.tag else ""
                if ch_tag in ("sdt", "ins", "smartTag"):
                    content_elem = next((sub for sub in ch if etree.QName(sub.tag).localname == "sdtContent"), ch)
                    items.extend(_flatten_children(content_elem))
                else:
                    items.append(ch)
            return items

        children = _flatten_children(para._element)
        inner_parts: list[str] = []
        i = 0

        while i < len(children):
            child = children[i]
            tag = etree.QName(child.tag).localname if child.tag else ""

            if tag == "hyperlink":
                # Extract rId attribute with multiple namespace fallbacks
                r_id = (
                    child.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                    or child.get("r:id")
                    or child.get("id")
                    or next((v for k, v in child.attrib.items() if k.endswith("}id") or k == "id" or k.endswith(":id")), "")
                )
                href = hyperlink_rels.get(r_id, "") if r_id else ""
                if not href:
                    anchor_attr = child.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}anchor") or child.get("w:anchor") or child.get("anchor")
                    if anchor_attr and (anchor_attr.startswith("http://") or anchor_attr.startswith("https://")):
                        href = anchor_attr
                # Collect all run text inside the hyperlink
                link_text = "".join(
                    (run.text or "") for run in child.iter()
                    if etree.QName(run.tag).localname == "t"
                )
                link_text = link_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if href and link_text:
                    inner_parts.append(f'<a href="{href}">{link_text}</a>')
                elif link_text:
                    inner_parts.append(link_text)
                i += 1
                continue

            elif tag == "fldSimple":
                # Handle simple fields: <w:fldSimple w:instr=" HYPERLINK \"url\" ">
                instr = (
                    child.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instr")
                    or child.get("w:instr")
                    or child.get("instr")
                    or ""
                )
                m_url = re.search(r'HYPERLINK\s+"?([^"\s>]+)"?', instr, re.IGNORECASE)
                fld_href = m_url.group(1).strip() if m_url else ""
                link_text = "".join(
                    (run.text or "") for run in child.iter()
                    if etree.QName(run.tag).localname == "t"
                )
                link_text = link_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if fld_href and link_text:
                    inner_parts.append(f'<a href="{fld_href}">{link_text}</a>')
                elif link_text:
                    inner_parts.append(link_text)
                i += 1
                continue

            elif tag == "r":
                # Check for complex field begin: <w:fldChar w:fldCharType="begin"/>
                fc_begin = next(
                    (
                        e for e in child
                        if etree.QName(e.tag).localname == "fldChar"
                        and (e.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType") or e.get("w:fldCharType") or e.get("fldCharType")) == "begin"
                    ),
                    None,
                )
                if fc_begin is not None:
                    field_url = ""
                    field_text_parts = []
                    j = i + 1
                    in_separate = False
                    while j < len(children):
                        next_ch = children[j]
                        next_tag = etree.QName(next_ch.tag).localname if next_ch.tag else ""
                        if next_tag == "r":
                            it_elem = next((e for e in next_ch if etree.QName(e.tag).localname == "instrText"), None)
                            if it_elem is not None and it_elem.text:
                                m_hl = re.search(r'HYPERLINK\s+"?([^"\s>]+)"?', it_elem.text, re.IGNORECASE)
                                if m_hl:
                                    field_url = m_hl.group(1).strip()
                            fc_elem = next((e for e in next_ch if etree.QName(e.tag).localname == "fldChar"), None)
                            if fc_elem is not None:
                                fct = fc_elem.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType") or fc_elem.get("w:fldCharType") or fc_elem.get("fldCharType")
                                if fct == "separate":
                                    in_separate = True
                                elif fct == "end":
                                    j += 1
                                    break
                            elif in_separate:
                                t_elem = next((e for e in next_ch if etree.QName(e.tag).localname == "t"), None)
                                if t_elem is not None and t_elem.text:
                                    field_text_parts.append(t_elem.text)
                        j += 1

                    fld_text = "".join(field_text_parts).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    if field_url and fld_text:
                        inner_parts.append(f'<a href="{field_url}">{fld_text}</a>')
                        i = j
                        continue
                    elif fld_text:
                        inner_parts.append(fld_text)
                        i = j
                        continue

                # Check for inline drawings/images
                drawings = child.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing")
                for drawing in drawings:
                    blip = next((e for e in drawing.iter() if e.tag.endswith("}blip")), None)
                    if blip is not None:
                        embed_id = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                        rel = doc.part.rels.get(embed_id) if embed_id else None
                        if rel:
                            img_filename = os.path.basename(str(rel.target_part.partname))
                            doc_pr = next((e for e in drawing.iter() if e.tag.endswith("}docPr")), None)
                            alt_text = doc_pr.get("descr") or doc_pr.get("name") or "" if doc_pr is not None else ""
                            alt_clean = alt_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
                            inner_parts.append(f'<img src="{img_filename}" alt="{alt_clean}" style="max-width: 700px; height: auto;" />')

                # Regular run
                from docx.text.run import Run
                try:
                    run_obj = Run(child, para)
                    inner_parts.append(_run_html(run_obj))
                except Exception:
                    t_elems = child.findall(
                        ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                    )
                    text = "".join((e.text or "") for e in t_elems)
                    if text:
                        inner_parts.append(
                            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        )
                i += 1
                continue

            i += 1

        inner = "".join(inner_parts).strip()
        if not inner:
            return ""

        if heading_level:
            return f"<h{heading_level}>{inner}</h{heading_level}>"

        # List detection
        num_pr = para._element.find(
            ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr"
        )
        if num_pr is not None:
            return f"<li>{inner}</li>"

        return f"<p>{inner}</p>"

    # Process all paragraphs
    html_parts: list[str] = []
    in_list = False

    for para in doc.paragraphs:
        part = _para_html(para)
        if not part:
            continue

        is_list_item = part.startswith("<li>")
        if is_list_item and not in_list:
            html_parts.append("<ul>")
            in_list = True
        elif not is_list_item and in_list:
            html_parts.append("</ul>")
            in_list = False

        html_parts.append(part)

    if in_list:
        html_parts.append("</ul>")

    # Process tables with hyperlink and formatting preservation
    for table in doc.tables:
        html_parts.append("<table>")
        for row in table.rows:
            html_parts.append("<tr>")
            for cell in row.cells:
                cell_p_parts = []
                for p in cell.paragraphs:
                    p_res = _para_html(p)
                    if p_res:
                        p_inner = re.sub(r"^<p\b[^>]*>(.*?)</p>$", r"\1", p_res.strip(), flags=re.DOTALL | re.IGNORECASE)
                        cell_p_parts.append(p_inner)
                cell_td_content = "<br/>".join(cell_p_parts) if cell_p_parts else cell.text.strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_parts.append(f"<td>{cell_td_content}</td>")
            html_parts.append("</tr>")
        html_parts.append("</table>")

    result = "\n".join(part for part in html_parts if part)

    # Re-verify all hyperlinks from relationships: if any anchor text exists in extracted HTML without <a>, wrap it
    for r_id, target_url in hyperlink_rels.items():
        if target_url and target_url.startswith(("http://", "https://")) and target_url not in result:
            # Look for paragraphs or elements with this link's anchor
            for p in doc.paragraphs:
                for child in p._element:
                    if etree.QName(child.tag).localname == "hyperlink":
                        child_rid = child.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") or child.get("r:id") or child.get("id")
                        if child_rid == r_id:
                            anchor_t = "".join((run.text or "") for run in child.iter() if etree.QName(run.tag).localname == "t").strip()
                            if anchor_t and anchor_t in result and target_url not in result:
                                pat = re.compile(rf'(?<!<a[^>]*>)(\b{re.escape(anchor_t)}\b)(?![^<]*</a>)')
                                result, _ = pat.subn(f'<a href="{target_url}">{anchor_t}</a>', result, count=1)

    log.info("DOCX HTML extraction complete: %d characters", len(result))
    return result


def _extract_hyperlinks_from_docx(file_bytes: bytes) -> list[dict]:
    """
    Extract all hyperlinks from a DOCX file.

    Returns a list of dicts: { url, anchor_text }
    These must be preserved exactly in the final WordPress article.
    """
    try:
        from docx import Document
        from lxml import etree
    except ImportError as exc:
        raise RuntimeError('python-docx and lxml are required.') from exc

    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(f'Could not open DOCX file: {exc}') from exc

    # Relationship map: rId -> URL
    hyperlink_rels: dict[str, str] = {}
    for rel in doc.part.rels.values():
        if "hyperlink" in rel.reltype.lower():
            target_val = getattr(rel, "target_ref", None) or getattr(rel, "_target", "")
            hyperlink_rels[rel.rId] = target_val

    links: list[dict] = []
    seen_urls: set[str] = set()

    # Collect all paragraphs from both body and tables
    all_paras = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_paras.extend(cell.paragraphs)

    def _flatten_children(container):
        items = []
        for ch in container:
            ch_tag = etree.QName(ch.tag).localname if ch.tag else ""
            if ch_tag in ("sdt", "ins", "smartTag"):
                content_elem = next((sub for sub in ch if etree.QName(sub.tag).localname == "sdtContent"), ch)
                items.extend(_flatten_children(content_elem))
            else:
                items.append(ch)
        return items

    for para in all_paras:
        children = _flatten_children(para._element)
        i = 0
        while i < len(children):
            child = children[i]
            tag = etree.QName(child.tag).localname if child.tag else ""
            if tag == "hyperlink":
                r_id = (
                    child.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                    or child.get("r:id")
                    or child.get("id")
                    or next((v for k, v in child.attrib.items() if k.endswith("}id") or k == "id" or k.endswith(":id")), "")
                )
                href = hyperlink_rels.get(r_id, "") if r_id else ""
                if not href:
                    anchor_attr = child.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}anchor") or child.get("w:anchor") or child.get("anchor")
                    if anchor_attr and (anchor_attr.startswith("http://") or anchor_attr.startswith("https://")):
                        href = anchor_attr
                anchor = "".join(
                    (run.text or "") for run in child.iter()
                    if etree.QName(run.tag).localname == "t"
                )
                if href and href not in seen_urls:
                    seen_urls.add(href)
                    links.append({"url": href, "anchor_text": anchor.strip()})
                i += 1
                continue

            elif tag == "fldSimple":
                instr = (
                    child.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instr")
                    or child.get("w:instr")
                    or child.get("instr")
                    or ""
                )
                m_url = re.search(r'HYPERLINK\s+"?([^"\s>]+)"?', instr, re.IGNORECASE)
                fld_href = m_url.group(1).strip() if m_url else ""
                anchor = "".join(
                    (run.text or "") for run in child.iter()
                    if etree.QName(run.tag).localname == "t"
                )
                if fld_href and fld_href not in seen_urls:
                    seen_urls.add(fld_href)
                    links.append({"url": fld_href, "anchor_text": anchor.strip()})
                i += 1
                continue

            elif tag == "r":
                fc_begin = next(
                    (
                        e for e in child
                        if etree.QName(e.tag).localname == "fldChar"
                        and (e.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType") or e.get("w:fldCharType") or e.get("fldCharType")) == "begin"
                    ),
                    None,
                )
                if fc_begin is not None:
                    field_url = ""
                    field_text_parts = []
                    j = i + 1
                    in_separate = False
                    while j < len(children):
                        next_ch = children[j]
                        next_tag = etree.QName(next_ch.tag).localname if next_ch.tag else ""
                        if next_tag == "r":
                            it_elem = next((e for e in next_ch if etree.QName(e.tag).localname == "instrText"), None)
                            if it_elem is not None and it_elem.text:
                                m_hl = re.search(r'HYPERLINK\s+"?([^"\s>]+)"?', it_elem.text, re.IGNORECASE)
                                if m_hl:
                                    field_url = m_hl.group(1).strip()
                            fc_elem = next((e for e in next_ch if etree.QName(e.tag).localname == "fldChar"), None)
                            if fc_elem is not None:
                                fct = fc_elem.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType") or fc_elem.get("w:fldCharType") or fc_elem.get("fldCharType")
                                if fct == "separate":
                                    in_separate = True
                                elif fct == "end":
                                    j += 1
                                    break
                            elif in_separate:
                                t_elem = next((e for e in next_ch if etree.QName(e.tag).localname == "t"), None)
                                if t_elem is not None and t_elem.text:
                                    field_text_parts.append(t_elem.text)
                        j += 1
                    fld_text = "".join(field_text_parts).strip()
                    if field_url and field_url not in seen_urls:
                        seen_urls.add(field_url)
                        links.append({"url": field_url, "anchor_text": fld_text})
                    i = j
                    continue
            i += 1

    log.info("DOCX hyperlink extraction: %d links found", len(links))
    return links


def _extract_embedded_images(file_bytes: bytes) -> list[dict]:
    """Extract image parts embedded in a DOCX, preserving their source names."""
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError('python-docx is not installed. Add it to requirements.txt.') from exc

    doc = Document(io.BytesIO(file_bytes))
    images: list[dict] = []
    seen_parts: set[str] = set()
    for shape in doc.inline_shapes:
        embed_id = next(
            (
                element.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                for element in shape._inline.iter()
                if element.tag.endswith('}blip')
            ),
            None,
        )
        if not embed_id:
            continue
        relationship = doc.part.rels.get(embed_id)
        if relationship is None or relationship.target_ref in seen_parts:
            continue
        target_part = relationship.target_part
        part_name = str(target_part.partname)
        seen_parts.add(part_name)
        filename = os.path.basename(part_name)
        description = getattr(shape._inline.docPr, 'descr', '') or ''
        images.append({
            'filename': filename,
            'content': target_part.blob,
            'content_type': target_part.content_type,
            'alt_text': description,
        })
    return images


def _extract_article_title_from_html(html_content: str) -> str:
    """Extract the H1 title from the HTML content for duplicate check purposes."""
    import re
    h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html_content, re.IGNORECASE | re.DOTALL)
    if h1_match:
        # Strip tags inside the h1
        title = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()
        return title
    # Fall back to first <p> text
    p_match = re.search(r'<p[^>]*>(.*?)</p>', html_content, re.IGNORECASE | re.DOTALL)
    if p_match:
        return re.sub(r'<[^>]+>', '', p_match.group(1)).strip()[:120]
    return ""


async def download_and_extract(
    attachment_url: str,
    filename: str,
    content_type: str,
    byte_size: Optional[int],
    access_token: str,
) -> dict:
    lower_name = (filename or '').lower()
    lower_ct = (content_type or '').lower()
    is_docx = (
        lower_name.endswith('.docx')
        or 'application/vnd.openxmlformats' in lower_ct
        or 'officedocument.wordprocessingml' in lower_ct
    )
    if not is_docx:
        raise ValueError(
            f'Unsupported file type: {repr(filename)}. Only .docx files are supported.'
        )
    log.info('Downloading attachment: %s (%s bytes)', filename, byte_size)
    file_bytes = await _download_basecamp_file(attachment_url, access_token)
    if not file_bytes:
        raise ValueError('Downloaded file is empty.')

    log.info('Extracting text from DOCX: %s', filename)
    extracted_text = _extract_text_from_docx(file_bytes)

    log.info('Extracting HTML with hyperlinks from DOCX: %s', filename)
    try:
        extracted_html = _extract_html_from_docx(file_bytes)
    except Exception as exc:
        log.warning('HTML extraction failed, falling back to plain text: %s', exc)
        extracted_html = ""

    log.info('Extracting hyperlinks from DOCX: %s', filename)
    try:
        docx_hyperlinks = _extract_hyperlinks_from_docx(file_bytes)
    except Exception as exc:
        log.warning('Hyperlink extraction failed: %s', exc)
        docx_hyperlinks = []

    embedded_images = _extract_embedded_images(file_bytes)
    char_count = len(extracted_text)
    log.info(
        'Extracted %d characters, %d hyperlinks, and %d embedded images from %s',
        char_count,
        len(docx_hyperlinks),
        len(embedded_images),
        filename,
    )

    # Extract article title from HTML for duplicate checking
    article_title_from_h1 = _extract_article_title_from_html(extracted_html) if extracted_html else ""

    return {
        'filename': filename,
        'content_type': content_type,
        'byte_size': byte_size or len(file_bytes),
        'character_count': char_count,
        'extracted_text': extracted_text,
        'extracted_html': extracted_html,
        'docx_hyperlinks': docx_hyperlinks,
        'embedded_images': embedded_images,
        'article_title_from_h1': article_title_from_h1,
    }