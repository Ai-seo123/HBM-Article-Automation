"""
SEO Optimizer Service for HBM Article Automation.

Handles:
1. Meta description optimization (120-156 characters, natural focus keyphrase inclusion, synchronized with post excerpt).
2. Contextual internal links injection (Home Business Magazine priority, relevant categories/articles, Espial Solutions).
3. Contextual external high-authority links injection (Forbes, Entrepreneur, Inc, CNN).
4. Focus keyphrase density optimization (natural, non-stuffed, targeting Yoast green range).
5. Focus keyphrase in subheadings (contextual adaptation of 30%-50% of H2/H3 subheadings).
6. Post-optimization Yoast analysis validation.
"""

import html
import logging
import re
from typing import Optional

import services.yoast as yoast_service

log = logging.getLogger(__name__)

# Approved authority links mapping with verified active URLs (Forbes / Entrepreneur)
VERIFIED_AUTHORITY_LINKS = [
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/leadership/how-to-build-a-culture-of-recognition-in-the-workplace/367329",
        "pattern": r"\b(corporate gifts?|corporate gifting|employee recognition|workplace recognition|client gifts?|gift-giving|culture of recognition|company culture|employee appreciation|corporate tokens?)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/growing-a-business/how-to-choose-the-right-pricing-strategy-for-your-small/471188",
        "pattern": r"\b(pricing strateg(?:y|ies)|pricing structure|profit margins?|cash flow|financial planning|revenue model|pricing model|financial records?)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/starting-a-business/conducting-market-research/217388",
        "pattern": r"\b(market research|target market|customer demographics|consumer behavior|audience insights|market analysis)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/starting-a-business/the-step-by-step-guide-to-finding-your-niche-and-target/413458",
        "pattern": r"\b(finding your niche|target audience|brand positioning|niche market|marketing campaign|brand awareness|branding strategy)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/growing-a-business/the-ultimate-guide-to-competitive-research-for-small/412183",
        "pattern": r"\b(competitive research|competitor analysis|market competitors?|competitive landscape|strategic positioning)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/starting-a-business/is-your-business-idea-worth-pursuing-use-these-3-tips-to/480571",
        "pattern": r"\b(business idea|worth pursuing|idea validation|startup concept|business plan|new venture)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/growing-a-business/how-to-hire-the-right-person-for-your-business/435134",
        "pattern": r"\b(hiring process|hiring decisions?|hiring the right person|recruiting candidates?|talent acquisition|employee selection)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/growing-a-business/how-to-conduct-an-employee-background-check/422896",
        "pattern": r"\b(employee background checks?|background screening|pre-employment screening|verify credentials|screening measures?|criminal record checks?)\b",
    },
    {
        "domain": "forbes.com",
        "url": "https://www.forbes.com/councils/forbescommunicationscouncil/2019/07/23/improve-your-email-sender-reputation-in-three-steps/",
        "pattern": r"\b(sender reputation|email deliverability|email campaigns?|email marketing|spam complaints?)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/growing-a-business/7-essentials-of-great-customer-service/220268",
        "pattern": r"\b(customer service|customer support|client relationships?|call center|customer experience|client retention|client satisfaction)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/productivity/7-ways-to-dramatically-increase-workplace-efficiency/342938",
        "pattern": r"\b(workplace efficiency|increase efficiency|productivity|time management|streamlin(?:e|ing)|routine paperwork|manual data entry|automate repetitive jobs)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/leadership/why-clear-communication-is-vital-for-business-success/366710",
        "pattern": r"\b(clear communication|business communication|effective communication|workplace communication|clear writing)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/starting-a-business/how-to-start-a-real-estate-business-in-8-simple-steps/439772",
        "pattern": r"\b(real estate|property management|commercial real estate|office spaces?|rental properties|property investments?)\b",
    },
    {
        "domain": "entrepreneur.com",
        "url": "https://www.entrepreneur.com/starting-a-business/10-ways-to-make-your-business-stand-out-from-the-competition/447291",
        "pattern": r"\b(stand out from the competition|competitive advantage|business strategy|market differentiation|differentiat(?:e|ion)|business growth)\b",
    },
]

# Approved internal links mapping with verified active Home Business Magazine URLs
INTERNAL_LINKS_CONFIG = [
    {
        "name": "HBM Management & Leadership",
        "url": "https://homebusinessmag.com/management/leadership/small-business-build-accountability-without-fear/",
        "pattern": r"\b(accountability|leadership|management practices?|workplace culture|workplace safety|workplace rituals?|workplace environment|team dynamics?)\b",
    },
    {
        "name": "HBM Working Smarter & Systems",
        "url": "https://homebusinessmag.com/management/working-smarter/systems-behind-business-runs-smoothly/",
        "pattern": r"\b(systems behind a business|operational workflows?|due diligence|practical\s+[^<>\n]{1,30}?\s+process|best practices|clear workflow|systems?|business processes?|streamline|streamlining|workflow automation|automate repetitive jobs|manual data entry|automated AP operations|automation)\b",
    },
    {
        "name": "HBM Working Smarter & Productivity",
        "url": "https://homebusinessmag.com/management/working-smarter/",
        "pattern": r"\b(working smarter|productivity|office efficiency|improving efficiency|efficiency|time management|productive habits?|routine paperwork|pain points)\b",
    },
    {
        "name": "HBM Getting Organized & Knowledge Management",
        "url": "https://homebusinessmag.com/management/getting-organized/knowledge-management-practical-workplace-guide/",
        "pattern": r"\b(knowledge management|getting organized|workplace guide|information sharing|documentation|collaboration|team communication)\b",
    },
    {
        "name": "HBM Human Resources & Talent",
        "url": "https://homebusinessmag.com/management/",
        "pattern": r"\b(human resources(?:\s+teams?)?|hr\s+(?:departments?|teams?|guidance)|personnel management|hiring practices?|employees?|workforce|staff|talent)\b",
    },
    {
        "name": "HBM Business Operations",
        "url": "https://homebusinessmag.com/management/business-operations/",
        "pattern": r"\b(business operations?|team management|operational processes?|coaching programs?|finance tasks?|invoices?|operations?|accounts payable|bookkeeping|accounting|financial management)\b",
    },
    {
        "name": "HBM Sales and Marketing",
        "url": "https://homebusinessmag.com/marketing/advertising/marketing-and-advertising-closer-look-what-makes-different/",
        "pattern": r"\b(sales and marketing|marketing strategy|content marketing|lead generation|customer relationships?|clients?|advertising)\b",
    },
    {
        "name": "HBM Email Marketing",
        "url": "https://homebusinessmag.com/marketing/direct-marketing/email-marketing-home-business-tools-tactics-may-need/",
        "pattern": r"\b(previous campaigns?|marketing campaigns?|email marketing|digital marketing|email campaigns?|newsletters?|deliverability)\b",
    },
    {
        "name": "HBM Growing a Business",
        "url": "https://homebusinessmag.com/categories/growing-a-business/",
        "pattern": r"\b(growing a business|business growth|scale your business|sustainable growth|helps? the business grow|business(?:es)?|companies|enterprise|firm)\b",
    },
    {
        "name": "HBM Business Start-Up",
        "url": "https://homebusinessmag.com/categories/business-start-up/",
        "pattern": r"\b(business start-up|start a business|entrepreneurship|new business|remote entrepreneur|founders?)\b",
    },
    {
        "name": "HBM Remote Work & Home Office",
        "url": "https://homebusinessmag.com/categories/home-office/",
        "pattern": r"\b(home office|remote work|independent business|work from home|remote team)\b",
    },
    {
        "name": "Home Business Magazine Homepage",
        "url": "https://homebusinessmag.com/",
        "pattern": r"\b(home business|small business(?:es)?|b2b company|canadian smbs?|commercial enterprise|entrepreneur)\b",
    },
]


def remove_forbidden_meta_words(text: str, focus_keyphrase: str = "") -> str:
    """
    Mandatory rule: Before finalizing every meta description, remove:
      - our
      - and (including '&')
      - to
    Also remove unnecessary commas.
    Protects the focus keyphrase if it naturally contains any of these words.
    Performs contextual linguistic replacements so grammar, flow, and meaning are preserved.
    """
    if not text:
        return ""

    kp = (focus_keyphrase or "").strip()
    placeholder = "___FOCUS_KEYPHRASE___"
    matched_kp = ""
    s = text

    # Protect focus keyphrase if present in text
    if kp and kp.lower() in s.lower():
        pattern = re.compile(re.escape(kp), re.IGNORECASE)
        m = pattern.search(s)
        if m:
            matched_kp = m.group(0)
            s = s[:m.start()] + placeholder + s[m.end():]

    # 1. Transform common verb infinitives with 'to' into active gerunds/verbs
    to_verb_map = [
        (r"\bto\s+improve\b", "improving"),
        (r"\bto\s+reach\b", "reaching"),
        (r"\bto\s+boost\b", "boosting"),
        (r"\bto\s+scale\b", "scaling"),
        (r"\bto\s+grow\b", "growing"),
        (r"\bto\s+build\b", "building"),
        (r"\bto\s+ensure\b", "ensuring"),
        (r"\bto\s+thrive\b", "thriving"),
        (r"\bto\s+optimize\b", "optimizing"),
        (r"\bto\s+maximize\b", "maximizing"),
        (r"\bto\s+elevate\b", "elevating"),
        (r"\bto\s+enhance\b", "enhancing"),
        (r"\bto\s+strengthen\b", "strengthening"),
        (r"\bto\s+help\b", "helping"),
        (r"\bto\s+drive\b", "driving"),
        (r"\bto\s+deliver\b", "delivering"),
        (r"\bto\s+achieve\b", "achieving"),
        (r"\bto\s+maintain\b", "maintaining"),
        (r"\bto\s+protect\b", "protecting"),
        (r"\bto\s+avoid\b", "avoiding"),
        (r"\bto\s+prevent\b", "preventing"),
        (r"\bto\s+resolve\b", "resolving"),
        (r"\bto\s+fix\b", "fixing"),
        (r"\bto\s+succeed\b", "succeeding"),
        (r"\bto\s+excel\b", "excelling"),
        (r"\bto\s+navigate\b", "navigating"),
        (r"\bto\s+lead\b", "leading"),
        (r"\bto\s+manage\b", "managing"),
        (r"\bto\s+create\b", "creating"),
        (r"\bto\s+streamline\b", "streamlining"),
        (r"\bto\s+discover\b", "discover"),
        (r"\bto\s+explore\b", "explore"),
        (r"\bto\s+learn\b", "learn"),
        (r"\bto\s+master\b", "master"),
        (r"\bto\s+understand\b", "understand"),
        (r"\bto\s+secure\b", "securing"),
        (r"\bto\s+attract\b", "attracting"),
        (r"\bto\s+connect\b", "connecting"),
        (r"\bto\s+pitch\b", "pitching"),
        (r"\bto\s+fund\b", "funding"),
        (r"\bto\s+support\b", "supporting"),
        (r"\bto\s+raise\b", "raising"),
        (r"\bto\s+close\b", "closing"),
        (r"\bto\s+generate\b", "generating"),
        (r"\bto\s+expand\b", "expanding"),
        (r"\bto\s+establish\b", "establishing"),
        (r"\bto\s+implement\b", "implementing"),
        (r"\bto\s+leverage\b", "leveraging"),
        (r"\bto\s+transform\b", "transforming"),
        (r"\bto\s+adapt\b", "adapting"),
        (r"\bto\s+address\b", "addressing"),
        (r"\bto\s+handle\b", "handling"),
        (r"\bto\s+foster\b", "fostering"),
        (r"\bto\s+empower\b", "empowering"),
        (r"\bto\s+partner\b", "partnering"),
        (r"\bto\s+launch\b", "launching"),
        (r"\bto\s+execute\b", "executing"),
        (r"\bto\s+communicate\b", "communicating"),
        (r"\bto\s+identify\b", "identifying"),
        (r"\bto\s+assess\b", "assessing"),
        (r"\bto\s+evaluate\b", "evaluating"),
        (r"\bto\s+monitor\b", "monitoring"),
        (r"\bto\s+automate\b", "automating"),
        (r"\bto\s+reduce\b", "reducing"),
        (r"\bto\s+increase\b", "increasing"),
    ]
    for pat, repl in to_verb_map:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)

    # 2. Transform prepositional phrases with 'to'
    prep_map = [
        (r"\bhow\s+to\b", "methods for"),
        (r"\btips\s+to\b", "tips for"),
        (r"\bsteps\s+to\b", "steps for"),
        (r"\bways\s+to\b", "ways for"),
        (r"\bmethods\s+to\b", "methods for"),
        (r"\bsecrets\s+to\b", "secrets for"),
        (r"\bstrategies\s+to\b", "strategies for"),
        (r"\bbest\s+practices\s+to\b", "best practices for"),
        (r"\bguide\s+to\b", "guide for"),
        (r"\bkey\s+to\b", "key for"),
        (r"\bpath\s+to\b", "path toward"),
        (r"\broad\s+to\b", "road toward"),
        (r"\baccess\s+to\b", "access for"),
        (r"\btransition\s+to\b", "transition toward"),
        (r"\bapproach\s+to\b", "approach for"),
        (r"\bsolution\s+to\b", "solution for"),
        (r"\bdedicated\s+to\b", "dedicated toward"),
        (r"\bwelcome\s+to\b", "welcome into"),
        (r"\bto\s+local\s+businesses\b", "for local businesses"),
        (r"\bto\s+businesses\b", "for businesses"),
        (r"\bto\s+customers\b", "for customers"),
        (r"\bto\s+clients\b", "for clients"),
        (r"\bto\s+sponsors\b", "for sponsors"),
        (r"\bto\s+partners\b", "for partners"),
        (r"\bto\s+teams\b", "for teams"),
        (r"\bto\s+readers\b", "for readers"),
    ]
    for pat, repl in prep_map:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)

    # 3. Transform 'our' phrases into objective third-party phrasing
    our_map = [
        (r"\bwith\s+our\s+comprehensive\s+guide\b", "with this comprehensive guide"),
        (r"\bwith\s+our\s+guide\b", "with this guide"),
        (r"\bwith\s+our\b", "with this"),
        (r"\bin\s+our\s+comprehensive\s+guide\b", "in this comprehensive guide"),
        (r"\bin\s+our\s+guide\b", "in this guide"),
        (r"\bin\s+our\b", "in this"),
        (r"\bfrom\s+our\b", "from this"),
        (r"\bread\s+our\s+comprehensive\s+guide\b", "Read this comprehensive guide"),
        (r"\bread\s+our\s+guide\b", "Read this guide"),
        (r"\bread\s+our\b", "Read this"),
        (r"\bcheck\s+our\b", "Check this"),
        (r"\bour\s+comprehensive\s+guide\b", "this comprehensive guide"),
        (r"\bour\s+guide\b", "this guide"),
        (r"\bour\s+team\b", "the team"),
        (r"\bour\s+tips\b", "proven tips"),
        (r"\bour\s+proven\b", "proven"),
        (r"\bour\s+strategies\b", "proven strategies"),
        (r"\bour\s+insights\b", "practical insights"),
        (r"\bour\s+article\b", "this article"),
        (r"\bour\s+", "the "),
    ]
    for pat, repl in our_map:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)

    # 4. Transform 'and' patterns (including '&') into clean lists / active clauses
    and_map = [
        (r",\s*and\b", ","),
        (r"\band\s+explore\b", "explore"),
        (r"\band\s+discover\b", "discover"),
        (r"\band\s+learn\b", "learn"),
        (r"\band\s+reach\b", ", reaching"),
        (r"\band\s+improve\b", ", improving"),
        (r"\band\s+grow\b", ", growing"),
        (r"\band\s+scale\b", ", scaling"),
        (r"\band\s+build\b", ", building"),
        (r"\band\s+thrive\b", ", thriving"),
        (r"\btips\s+and\s+strategies\b", "proven tips, strategies"),
        (r"\band\s+", ", "),
        (r"\s*&\s*", ", "),
    ]
    for pat, repl in and_map:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)

    # 5. Strict removal of any remaining standalone 'our', 'and', 'to'
    s = re.sub(r"\bour\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\band\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bto\b", "", s, flags=re.IGNORECASE)

    # 6. Restore protected keyphrase
    if matched_kp:
        s = s.replace(placeholder, matched_kp)

    # 7. Clean unnecessary commas, punctuation, spaces
    s = re.sub(r",\s*,+", ",", s)                    # multiple commas
    s = re.sub(r"\s+,", ",", s)                      # spaces before comma
    s = re.sub(r",\s*([\.!\?])", r"\1", s)           # comma before punctuation
    s = re.sub(r"^\s*,\s*", "", s)                   # leading comma
    s = re.sub(r"\(\s*,", "(", s)
    s = re.sub(r",\s*\)", ")", s)
    s = re.sub(r"\s{2,}", " ", s).strip()

    # 8. Ensure proper sentence capitalization after sentence-ending punctuation
    parts = re.split(r"([\.!\?]\s+)", s)
    capitalized = []
    for i, p in enumerate(parts):
        if i % 2 == 0 and p:
            capitalized.append(p[0].upper() + p[1:] if len(p) > 1 else p.upper())
        else:
            capitalized.append(p)
    s = "".join(capitalized).strip()

    return s


def optimize_meta_description(current_desc: str, focus_keyphrase: str, article_title: str) -> str:
    """
    Generate or optimize a meta description:
    - Must include the exact focus keyphrase, preserving its wording and order naturally.
    - Do not independently rewrite or shorten the focus keyphrase, SEO title, or meta description.
    - Strictly enforce 140-155 characters (client confirmed range for HBM and Yoast green).
    """
    desc = (current_desc or "").strip()
    kp = (focus_keyphrase or "").strip()
    clean_title = re.sub(r"[^\w\s\?-]", "", article_title or "").strip()
    effective_kp = kp or clean_title[:40].strip() or "business strategy"

    # If current description already contains the exact keyphrase and is in 140-155 char range, keep it!
    if desc and effective_kp.lower() in desc.lower() and 140 <= len(desc) <= 155 and desc.endswith(('.', '!', '?')):
        return desc

    # Clean and sanitize forbidden words outside of the protected keyphrase
    cleaned = remove_forbidden_meta_words(desc, effective_kp) if desc else ""

    # Ensure focus keyphrase is present
    if effective_kp and effective_kp.lower() not in cleaned.lower():
        if cleaned:
            cleaned = f"Explore {effective_kp}. {cleaned}".strip()
        else:
            cleaned = f"Master {effective_kp} through this comprehensive guide."
        cleaned = remove_forbidden_meta_words(cleaned, effective_kp)

    if not cleaned.endswith(('.', '!', '?')):
        cleaned += "."

    # Check if cleaned is already in 140-155 char range
    if 140 <= len(cleaned) <= 155 and (effective_kp.lower() in cleaned.lower()):
        return cleaned

    # Rich list of extensions specifically calibrated for 140-155 character compliance
    extensions = [
        "Discover actionable frameworks, proven tactics, and scalable strategies to empower your modern business for sustainable long-term success.",
        "Learn actionable business strategies, proven methods, and scalable leadership advice to drive long-term organizational success.",
        "Discover actionable frameworks, proven tactics, and scalable strategies for sustainable business growth and long-term success.",
        "Discover practical methods to empower teams, boost daily output, and drive scalable organizational success in modern markets.",
        "Discover proven strategies to empower teams, streamline complex workflows, and drive measurable organizational growth.",
        "Learn actionable strategies to streamline daily operations, empower teams, and drive sustainable business growth.",
        "Discover practical strategies to streamline operations, enhance productivity, and drive sustainable business growth.",
        "Discover practical methods for sustained business growth, scalable success, and improved organizational clarity.",
        "Discover proven techniques for sustained business growth, scalable success, and improved workplace productivity.",
        "Discover actionable methods for sustained business growth, scalable success, and high-impact team leadership.",
        "Discover practical frameworks to empower teams and scale business operations for long-term commercial success.",
        "Discover actionable strategies for sustained business growth, enhanced productivity, and team success.",
        "Discover practical methods to empower teams, boost output, and drive success across your entire business.",
        "Discover proven methods for sustained business growth, improved performance, and scalable success.",
        "Discover practical methods for sustained business growth and scalable success across all operations.",
        "Discover actionable methods for scalable business growth, operational efficiency, and leadership.",
        "Discover proven techniques for sustained business growth and measurable operational efficiency.",
        "Discover practical methods for sustained business growth, higher efficiency, and team output.",
        "Discover actionable methods for scalable success, higher efficiency, and team productivity.",
        "Discover proven techniques for scalable success, operational excellence, and team growth.",
        "Discover practical methods for scalable success, continuous growth, and team efficiency.",
        "Discover actionable strategies for success, improved workflows, and sustainable growth.",
        "Discover proven methods for scalable growth, improved workflows, and workplace clarity.",
        "Discover practical methods for sustained growth, team alignment, and business success.",
        "Discover actionable methods for success, team efficiency, and sustainable expansion.",
        "Discover practical methods for success, team alignment, and operational clarity.",
        "Discover proven methods for success, team collaboration, and ongoing growth.",
        "Discover actionable methods for growth, team clarity, and lasting business success.",
        "Discover practical methods for growth, operational alignment, and team success.",
        "Discover proven methods for growth, team productivity, and sustainable results.",
        "Discover practical strategies for success, team alignment, and business growth.",
        "Discover proven strategies for growth, team collaboration, and daily success.",
        "Learn actionable methods for success, team alignment, and workplace clarity.",
        "Learn practical methods for success, team alignment, and daily productivity.",
        "Learn proven methods for growth, operational clarity, and lasting success.",
        "Discover actionable insights for success and long-term business growth.",
        "Discover practical methods for success and long-term business growth.",
        "Discover proven methods for growth and long-term business success.",
        "Discover practical tips for success and long-term business growth.",
        "Learn proven tips for growth and long-term business success.",
        "Discover actionable insights for lasting success.",
        "Discover practical methods for ongoing success.",
        "Discover proven methods for lasting growth.",
        "Discover practical tips for team success.",
        "Learn proven tips for team success.",
    ]

    # If longer than 155, try trimming cleanly
    if len(cleaned) > 155 and effective_kp.lower() in cleaned.lower():
        # Sentence splitting
        sentences = re.split(r"(?<=[\.!\?])\s+", cleaned)
        cand = ""
        for s in sentences:
            test = (cand + " " + s).strip() if cand else s
            if 140 <= len(test) <= 155 and effective_kp.lower() in test.lower():
                return test
            if len(test) < 140:
                cand = test

        # Word boundary cut
        for cut_idx in range(154, 138, -1):
            if cut_idx < len(cleaned) and cleaned[cut_idx] in (' ', '.', ',', ';', ':'):
                candidate = cleaned[:cut_idx].rstrip(' ,;:-') + '.'
                if 140 <= len(candidate) <= 155 and effective_kp.lower() in candidate.lower():
                    return candidate

    # If shorter than 140, try extensions on cleaned base
    s_base = cleaned.rstrip(".!? ")
    for ext in extensions:
        cand = remove_forbidden_meta_words(f"{s_base}. {ext}", effective_kp)
        if 140 <= len(cand) <= 155 and effective_kp.lower() in cand.lower():
            return cand

    # Candidate bases paired with extensions
    candidate_bases = [
        f"Master {effective_kp} through this comprehensive guide",
        f"Explore {effective_kp} through this comprehensive guide",
        f"Learn how {effective_kp} empowers modern organizations",
        f"Discover essential insights regarding {effective_kp}",
        f"Gain practical clarity and strategy on {effective_kp}",
        f"Unlock actionable methods for {effective_kp}",
    ]

    for base_text in candidate_bases:
        base_clean = remove_forbidden_meta_words(base_text, effective_kp).rstrip(".!? ")
        for ext in extensions:
            cand = remove_forbidden_meta_words(f"{base_clean}. {ext}", effective_kp)
            if 140 <= len(cand) <= 155 and effective_kp.lower() in cand.lower():
                return cand

    # Calibrated fallback to guarantee 140-155 characters
    base_prefix = f"Explore {effective_kp}. "
    long_tail = "Discover actionable business strategies, proven methods, and scalable leadership advice to drive long-term organizational success and steady team growth."
    combined = base_prefix + long_tail
    for end_idx in range(154, 139, -1):
        if end_idx < len(combined) and combined[end_idx] == ' ':
            return combined[:end_idx].rstrip(' ,;:-') + '.'

    return combined[:150].rstrip(' ,;:-') + '.'


MINOR_HEADING_WORDS = {
    'a', 'an', 'the', 'and', 'but', 'or', 'nor', 'for', 'yet', 'so',
    'as', 'at', 'by', 'in', 'of', 'off', 'on', 'per', 'to', 'up', 'via',
    'vs', 'with', 'from', 'into', 'onto', 'upon'
}

KNOWN_HEADING_ACRONYMS = {
    'smb': 'SMB', 'smbs': 'SMBs', 'b2b': 'B2B', 'b2c': 'B2C',
    'hr': 'HR', 'ai': 'AI', 'seo': 'SEO', 'crm': 'CRM',
    'roi': 'ROI', 'ap': 'AP', 'it': 'IT', 'usa': 'USA', 'uk': 'UK'
}


def to_title_case(text: str) -> str:
    """
    Format heading text in proper Title Case according to editorial guidelines:
    - Capitalizes the first and last word.
    - Capitalizes the first word after punctuation breaks (colon, question mark, em-dash).
    - Preserves list numbering / prefixes ('1.', '1)', 'Step 1:').
    - Capitalizes all major words.
    - Keeps short minor words lowercase unless at start, end, or after colon/break.
    - Capitalizes both parts of hyphenated major words ('Cost-Effective', 'Step-by-Step').
    - Canonicalizes standard business acronyms ('SMB', 'SMBs', 'HR', 'B2B', 'ROI', 'AP', 'AI').
    """
    if not text or not text.strip():
        return text

    words = text.split()
    if not words:
        return text

    letter_indices = [i for i, w in enumerate(words) if re.search(r'[A-Za-z]', w)]
    if not letter_indices:
        return text

    first_text_idx = letter_indices[0]
    last_text_idx = letter_indices[-1]

    def _capitalize_part(part: str) -> str:
        clean = re.sub(r'^[^\w]+|[^\w]+$', '', part).lower()
        if clean in KNOWN_HEADING_ACRONYMS:
            prefix = re.match(r'^[^\w]+', part)
            suffix = re.search(r'[^\w]+$', part)
            p_str = prefix.group(0) if prefix else ''
            s_str = suffix.group(0) if suffix else ''
            return f"{p_str}{KNOWN_HEADING_ACRONYMS[clean]}{s_str}"
        if re.match(r'^[A-Z]{2,}[s]?$', part):
            return part
        if part.isupper() and len(clean) > 3:
            part = part.capitalize()
        m = re.search(r'[a-zA-Z]', part)
        if m:
            idx = m.start()
            return part[:idx] + part[idx].upper() + part[idx+1:]
        return part

    def _format_word(w: str, is_first: bool, is_last: bool, after_break: bool) -> str:
        if '-' in w:
            subparts = w.split('-')
            titled_subparts = []
            for j, sp in enumerate(subparts):
                clean_sp = re.sub(r'^[^\w]+|[^\w]+$', '', sp).lower()
                sp_is_first = is_first and j == 0
                sp_is_last = is_last and j == len(subparts) - 1
                if sp_is_first or sp_is_last or (clean_sp not in MINOR_HEADING_WORDS and len(clean_sp) > 0):
                    titled_subparts.append(_capitalize_part(sp))
                else:
                    titled_subparts.append(sp.lower())
            return '-'.join(titled_subparts)

        clean = re.sub(r'^[^\w]+|[^\w]+$', '', w).lower()
        if not clean:
            return w

        if clean in KNOWN_HEADING_ACRONYMS:
            return _capitalize_part(w)

        if is_first or is_last or after_break or clean not in MINOR_HEADING_WORDS:
            return _capitalize_part(w)
        else:
            return re.sub(r'([A-Za-z]+)', lambda m: m.group(1).lower() if not re.match(r'^[A-Z]{2,}[s]?$', m.group(1)) else m.group(1), w)

    result_words = []
    prev_ended_with_break = False

    for i, w in enumerate(words):
        is_first = (i == first_text_idx)
        is_last = (i == last_text_idx)
        after_break = prev_ended_with_break

        formatted = _format_word(w, is_first, is_last, after_break)
        result_words.append(formatted)
        prev_ended_with_break = bool(re.search(r'[:\?]\s*$|[—–]\s*$', w))

    return ' '.join(result_words)


def format_headings_title_case(content: str) -> tuple[str, list[dict]]:
    """
    Apply Title Case to all <h2>, <h3>, <h4> subheadings in article HTML.
    Preserves inner tags and formatting, and corrects mismatched closing tags or unclosed inline tags.
    """
    changes = []

    def replace_heading(m: re.Match) -> str:
        tag = m.group(1).lower()
        attrs = m.group(2)
        inner = m.group(3)

        if "<" not in inner:
            new_inner = to_title_case(inner)
        else:
            parts = re.split(r'(<[^>]+>)', inner)
            new_parts = []
            for p in parts:
                if p.startswith("<"):
                    new_parts.append(p)
                else:
                    new_parts.append(to_title_case(p) if p.strip() else p)
            new_inner = "".join(new_parts)

        # Close any unclosed inline tags inside heading (e.g. <a>, <strong>, <em>, <span>)
        for inline_tag in ("a", "strong", "em", "b", "i", "span"):
            open_count = len(re.findall(rf'<{inline_tag}\b[^>]*>', new_inner, re.IGNORECASE))
            close_count = len(re.findall(rf'</{inline_tag}>', new_inner, re.IGNORECASE))
            if open_count > close_count:
                new_inner += f"</{inline_tag}>" * (open_count - close_count)

        if new_inner != inner:
            changes.append({"old": inner, "new": new_inner})
        return f"<{tag}{attrs}>{new_inner}</{tag}>"

    pattern = re.compile(r'<(h[2-4])(\b[^>]*)>(.*?)</(h[2-4])>', re.IGNORECASE | re.DOTALL)
    formatted_content = pattern.sub(replace_heading, content)
    return formatted_content, changes


def is_title_case_heading(heading_text: str) -> tuple[bool, str]:
    """
    Check if a single heading text conforms to Title Case guidelines.
    Returns: (is_conforming: bool, expected_title_case: str)
    """
    clean = re.sub(r'<[^>]+>', ' ', heading_text)
    clean = html.unescape(clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if not clean:
        return True, ""

    expected = to_title_case(clean)

    # Compare tokens ignoring insignificant punctuation differences
    words_actual = clean.split()
    words_exp = expected.split()
    if len(words_actual) != len(words_exp):
        return False, expected

    for wa, we in zip(words_actual, words_exp):
        clean_wa = re.sub(r'^[^\w]+|[^\w]+$', '', wa)
        clean_we = re.sub(r'^[^\w]+|[^\w]+$', '', we)
        if clean_wa.lower() != clean_we.lower():
            return False, expected
        if clean_wa != clean_we:
            return False, expected

    return True, expected


def parse_and_validate_headings(content: str) -> dict:
    """
    Dynamically analyze all heading tags in HTML content:
    - Detects H1, H2, H3, H4, H5, H6 tags.
    - Detects malformed markup (mismatched tags, empty tags, unclosed inner tags).
    - Checks Title Case compliance across H2/H3/H4 subheadings.
    - Validates heading hierarchy (no body H1, logical nesting, no skipped levels).
    """
    if not content or not content.strip():
        return {
            "has_headings": False,
            "headings": [],
            "counts": {"h1": 0, "h2": 0, "h3": 0, "h4": 0, "h5": 0, "h6": 0},
            "total_subheadings": 0,
            "malformed_errors": [],
            "hierarchy_errors": [],
            "non_conforming_title_case": [],
            "all_title_case": True,
        }

    # 1. Detect malformed headings (e.g. <h2 ... </h3> or <h2 without closing)
    malformed_errors = []

    # Check for mismatched closing tags: <hX>...</hY> where X != Y
    mismatched_pat = re.compile(r'<h([1-6])\b[^>]*>(.*?)</h([1-6])>', re.IGNORECASE | re.DOTALL)
    for m in mismatched_pat.finditer(content):
        lvl_open, inner, lvl_close = int(m.group(1)), m.group(2), int(m.group(3))
        if lvl_open != lvl_close:
            malformed_errors.append(f"Mismatched heading tags: <h{lvl_open}> closed with </h{lvl_close}>")

    # Check for empty headings: <hX></hX> or <hX>&nbsp;</hX>
    empty_pat = re.compile(r'<h([1-6])\b[^>]*>(.*?)</h\1>', re.IGNORECASE | re.DOTALL)
    for m in empty_pat.finditer(content):
        inner_plain = re.sub(r'<[^>]+>', '', m.group(2))
        inner_plain = html.unescape(inner_plain).strip()
        if not inner_plain:
            malformed_errors.append(f"Empty <h{m.group(1)}> heading tag detected")

    # Check for unclosed inner tags (e.g. <a href="..."> without </a>)
    for m in empty_pat.finditer(content):
        inner = m.group(2)
        if '<a ' in inner.lower() and '</a>' not in inner.lower():
            malformed_errors.append(f"Unclosed <a> link tag inside <h{m.group(1)}> heading")

    # 2. Extract all properly formed headings in document order
    heading_pat = re.compile(r'<(h[1-6])\b([^>]*)>(.*?)</\1>', re.IGNORECASE | re.DOTALL)
    raw_matches = list(heading_pat.finditer(content))

    headings = []
    counts = {"h1": 0, "h2": 0, "h3": 0, "h4": 0, "h5": 0, "h6": 0}
    levels_in_order = []
    non_conforming_tc = []

    for m in raw_matches:
        tag = m.group(1).lower()
        level = int(tag[1])
        counts[tag] += 1
        levels_in_order.append(level)

        inner_html = m.group(3)
        clean_text = re.sub(r'<[^>]+>', ' ', inner_html)
        clean_text = html.unescape(clean_text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        # Check title case on subheadings H2, H3, H4
        is_tc, expected_tc = is_title_case_heading(clean_text)
        if level in (2, 3, 4) and not is_tc:
            non_conforming_tc.append({
                "tag": tag,
                "text": clean_text,
                "expected": expected_tc,
            })

        headings.append({
            "tag": tag,
            "level": level,
            "raw_html": m.group(0),
            "inner_html": inner_html,
            "clean_text": clean_text,
            "is_title_case": is_tc,
            "expected_title_case": expected_tc,
        })

    total_subheadings = counts["h2"] + counts["h3"] + counts["h4"]

    # 3. Check Hierarchy
    hierarchy_errors = []

    # Body content should NOT contain H1 (the page title is the single H1)
    if counts["h1"] > 0:
        hierarchy_errors.append(f"Body content contains {counts['h1']} <h1> tag(s); post title already serves as the page H1")

    # If subheadings exist, check level progression
    if total_subheadings > 0:
        # First subheading must not be H3 or H4 without preceding H2
        first_sub_lvl = next((lvl for lvl in levels_in_order if lvl >= 2), None)
        if first_sub_lvl and first_sub_lvl > 2:
            hierarchy_errors.append(f"Subheading hierarchy starts with <h{first_sub_lvl}> before any <h2>")

        # Check for skipped levels (e.g. H2 directly to H4 without H3)
        curr_lvl = 2
        for lvl in levels_in_order:
            if lvl == 1:
                continue
            if lvl > curr_lvl + 1:
                hierarchy_errors.append(f"Heading hierarchy skips level: <h{curr_lvl}> jumps directly to <h{lvl}>")
            curr_lvl = lvl

    return {
        "has_headings": len(headings) > 0,
        "headings": headings,
        "counts": counts,
        "total_subheadings": total_subheadings,
        "malformed_errors": malformed_errors,
        "hierarchy_errors": hierarchy_errors,
        "non_conforming_title_case": non_conforming_tc,
        "all_title_case": len(non_conforming_tc) == 0,
    }


def optimize_introduction(content: str, focus_keyphrase: str) -> tuple[str, bool]:
    """
    Ensure the focus keyphrase appears naturally in the opening paragraph.
    Preserves original meaning and flow, satisfying Yoast's introductionKeyword check.
    """
    kp = (focus_keyphrase or "").strip()
    if not kp:
        return content, False

    kp_lower = kp.lower()

    # Match the first paragraph <p>...</p> after any <style> or comment blocks
    p_pattern = re.compile(r'(<p\b[^>]*>)(.*?)(</p>)', re.IGNORECASE | re.DOTALL)
    m = p_pattern.search(content)
    if not m:
        return content, False

    p_open, p_text, p_close = m.group(1), m.group(2), m.group(3)

    # If keyphrase already present in opening paragraph
    if kp_lower in p_text.lower():
        return content, False

    opt_p = p_text

    first_word = kp.split()[0].lower() if kp.split() else ""
    is_verb = first_word in {
        "reduce", "improving", "improve", "hand", "handling", "boost", "boosting",
        "scale", "scaling", "manage", "managing", "automate", "automating",
        "build", "building", "streamline", "streamlining", "protect", "protecting",
        "cut", "cutting", "grow", "growing", "drive", "driving", "hire", "hiring"
    } or first_word.endswith("ing")

    # Specific contextual matches if present
    if "For Canadian SMBs, the consequences of a poor hiring decision" in opt_p:
        opt_p = opt_p.replace(
            "For Canadian SMBs, the consequences of a poor hiring decision can be particularly significant.",
            f"For Canadian SMBs looking to {kp_lower}, the consequences of a poor hiring decision can be particularly significant.",
            1
        )
    # Generic dynamic placement for sentences starting with "For [Entity], ..."
    elif re.search(r'\bFor\s+([A-Z][\w\s-]{2,30}?),\s*(the\b|finding\b|understanding\b|background\b)', opt_p):
        opt_p = re.sub(
            r'\bFor\s+([A-Z][\w\s-]{2,30}?),\s*',
            rf'For \1 looking to {kp_lower}, ' if is_verb else rf'For \1 as a {kp_lower}, ',
            opt_p,
            count=1
        )
    elif ". " in opt_p:
        first_sentence, rest = opt_p.split(". ", 1)
        if is_verb:
            opt_p = f"{first_sentence}. Taking proactive steps to {kp_lower} is essential: {rest}"
        else:
            opt_p = f"{first_sentence}. For any {kp_lower}, establishing clear priorities is essential: {rest}"
    else:
        if is_verb:
            opt_p = f"{opt_p.rstrip('.')} to {kp_lower}."
        else:
            opt_p = f"{opt_p.rstrip('.')} for the {kp_lower}."

    if opt_p != p_text:
        new_content = content[:m.start()] + p_open + opt_p + p_close + content[m.end():]
        return new_content, True

    return content, False


def optimize_subheadings(content: str, focus_keyphrase: str) -> tuple[str, list[dict]]:
    """
    Check existing H2/H3 subheadings and naturally incorporate the focus keyphrase
    or meaningful key terms into relevant subheadings (aiming for 1 to 2 headings,
    or 30%-50% of them) without breaking hierarchy or meaning.
    """
    kp = (focus_keyphrase or "").strip()
    if not kp:
        return content, []

    # Identify all H2/H3 headings
    heading_pattern = re.compile(r'(<(h[23])\b[^>]*>)(.*?)(</\2>)', re.IGNORECASE | re.DOTALL)
    headings = list(heading_pattern.finditer(content))
    if not headings:
        return content, []

    kp_lower = kp.lower()
    total_headings = len(headings)
    
    # Check how many headings already contain the keyphrase
    already_matched = sum(1 for m in headings if kp_lower in re.sub(r'<[^>]+>', '', m.group(3)).lower())
    
    # If at least 1 heading (and at least 25% of headings) already contains the keyphrase, Yoast is satisfied
    if already_matched >= 1 and (already_matched / total_headings >= 0.25):
        return content, []

    changes = []
    opt_content = content
    kp_title = to_title_case(kp)

    first_word = kp.split()[0].lower() if kp.split() else ""
    is_verb = first_word in {
        "reduce", "improving", "improve", "hand", "handling", "boost", "boosting",
        "scale", "scaling", "manage", "managing", "automate", "automating",
        "build", "building", "streamline", "streamlining", "protect", "protecting",
        "cut", "cutting", "grow", "growing", "drive", "driving", "hire", "hiring"
    } or first_word.endswith("ing")

    # Select 1 or at most 2 headings to update (never force into every heading)
    max_to_update = 2 if total_headings >= 4 else 1
    updated_count = 0

    for m in headings:
        if updated_count >= max_to_update:
            break
        tag_open, tag_name, inner, tag_close = m.group(1), m.group(2), m.group(3), m.group(4)
        clean_inner = re.sub(r'<[^>]+>', '', inner).strip()

        # Skip if already contains keyphrase or is a conclusion heading
        if kp_lower in clean_inner.lower() or any(term in clean_inner.lower() for term in ["conclusion", "final thoughts", "summary", "wrap up"]):
            continue

        # Check for leading number or bullet like "1. ", "Step 1: "
        num_match = re.match(r'^(\d+[\.:\)]\s*|Step\s+\d+[\.:\)]\s*)(.*)$', clean_inner, re.IGNORECASE)
        if num_match:
            prefix = num_match.group(1)
            rest = num_match.group(2).strip()
            if is_verb:
                new_inner = f"{prefix}{to_title_case(rest)} to {kp_title}"
            else:
                new_inner = f"{prefix}{to_title_case(rest)} for the {kp_title}"
        else:
            if is_verb:
                if ":" in clean_inner or "?" in clean_inner or "—" in clean_inner:
                    new_inner = f"{to_title_case(clean_inner)} — How to {kp_title}"
                else:
                    new_inner = f"{to_title_case(clean_inner)} to {kp_title}"
            else:
                if ":" in clean_inner or "?" in clean_inner or "—" in clean_inner:
                    new_inner = f"{to_title_case(clean_inner)}: Guide for the {kp_title}"
                else:
                    new_inner = f"{to_title_case(clean_inner)} for the {kp_title}"

        changes.append({"old": inner, "new": new_inner})
        full_old = m.group(0)
        full_new = f"{tag_open}{new_inner}{tag_close}"
        opt_content = opt_content.replace(full_old, full_new, 1)
        updated_count += 1

    return opt_content, changes


def optimize_keyphrase_density(content: str, focus_keyphrase: str, min_required: Optional[int] = None) -> tuple[str, int]:
    """
    Ensure the focus keyphrase occurs frequently enough to meet Yoast's recommended
    density (approx. 0.4% - 1.5%), dynamically calculated from actual article length.
    Makes minimal, natural edits to candidate paragraphs, avoiding keyword stuffing.
    """
    kp = (focus_keyphrase or "").strip()
    if not kp:
        return content, 0

    clean_text = re.sub(r'<[^>]+>', ' ', content)
    words = re.findall(r'\b[a-zA-Z0-9_\'-]+\b', clean_text)
    word_count = len(words)

    # Calculate dynamic minimum required by Yoast based on word count
    if min_required is None:
        if word_count < 300:
            calc_min = 1
        else:
            calc_min = max(2, int(word_count / 300) + 1)
    else:
        calc_min = max(1, min_required)

    target_count = calc_min + 1

    current_matches = len(re.findall(re.escape(kp), content, re.IGNORECASE))
    if current_matches >= target_count:
        return content, current_matches

    needed = target_count - current_matches
    opt_content = content

    first_word = kp.split()[0].lower() if kp.split() else ""
    is_verb = first_word in {
        "reduce", "improving", "improve", "hand", "handling", "boost", "boosting",
        "scale", "scaling", "manage", "managing", "automate", "automating",
        "build", "building", "streamline", "streamlining", "protect", "protecting",
        "cut", "cutting", "grow", "growing", "drive", "driving", "hire", "hiring"
    } or first_word.endswith("ing")

    p_pattern = re.compile(r'(<p\b[^>]*>)(.*?)(</p>)', re.IGNORECASE | re.DOTALL)
    paragraphs = list(p_pattern.finditer(opt_content))

    candidates = []
    for idx, p in enumerate(paragraphs):
        if idx == 0:
            continue
        p_inner = p.group(2)
        if kp.lower() in p_inner.lower():
            continue
        if len(p_inner.split()) < 15:
            continue
        candidates.append((idx, p))

    if not candidates:
        for idx, p in enumerate(paragraphs):
            p_inner = p.group(2)
            if kp.lower() not in p_inner.lower() and len(p_inner.split()) >= 10:
                candidates.append((idx, p))

    chosen = []
    if len(candidates) <= needed:
        chosen = candidates
    else:
        step = len(candidates) / needed
        for i in range(needed):
            idx = int(i * step)
            chosen.append(candidates[idx])

    added = 0
    for _, p_match in reversed(chosen):
        if added >= needed:
            break
        tag_open = p_match.group(1)
        p_inner = p_match.group(2).strip()
        tag_close = p_match.group(3)

        if is_verb:
            enhancement_options = [
                f"Taking a proactive approach to {kp.lower()} helps ensure long-term stability and success.",
                f"This gives organizations a proven path to {kp.lower()} effectively.",
                f"When looking to {kp.lower()}, maintaining this discipline makes a significant difference.",
                f"Having structured systems in place makes it easier to {kp.lower()} sustainably.",
            ]
        else:
            enhancement_options = [
                f"This remains an essential consideration for every {kp.lower()}.",
                f"Building these routines allows any {kp.lower()} to maintain consistent results.",
                f"Addressing these operational factors helps ensure {kp.lower()} success.",
                f"For any {kp.lower()}, maintaining this clear focus provides a strong advantage.",
            ]

        enhancement = enhancement_options[added % len(enhancement_options)]

        if p_inner.endswith("."):
            new_inner = f"{p_inner} {enhancement}"
        else:
            new_inner = f"{p_inner}. {enhancement}"

        old_full = p_match.group(0)
        new_full = f"{tag_open}{new_inner}{tag_close}"
        opt_content = opt_content.replace(old_full, new_full, 1)
        added += 1

    final_count = len(re.findall(re.escape(kp), opt_content, re.IGNORECASE))
    return opt_content, final_count


def inject_internal_links(content: str, focus_keyphrase: str, site_url: str = "") -> tuple[str, list[dict]]:
    """
    Ensure there are at least two (2) relevant internal links to existing articles on homebusinessmag.com.
    Normalizes any existing www.homebusinessmag.com to homebusinessmag.com so Yoast recognizes them.
    Inspects links already present before adding new ones. Avoids duplicate links.
    """
    # 1. Normalize existing HBM links to publication domain (without www.)
    opt_content = re.sub(
        r'href=(["\'])https?://(?:www\.)?homebusinessmag\.com',
        r'href=\1https://homebusinessmag.com',
        content,
        flags=re.IGNORECASE
    )
    added_links = []
    kp_lower = (focus_keyphrase or "").lower().strip()

    # Count existing links to homebusinessmag.com
    existing_hbm_links = len(re.findall(r'href=["\']https://homebusinessmag\.com', opt_content, re.IGNORECASE))
    if existing_hbm_links >= 2:
        return opt_content, []

    def _is_inside_anchor(text: str, start_pos: int) -> bool:
        pre = text[:start_pos]
        open_a = pre.rfind('<a')
        close_a = pre.rfind('</a>')
        return open_a > close_a

    def _is_inside_heading(text: str, start_pos: int) -> bool:
        pre = text[:start_pos]
        for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            open_h = pre.rfind(f"<{tag}")
            close_h = pre.rfind(f"</{tag}>")
            if open_h > close_h:
                return True
        return False

    # Primary pass: Configured primary topic mappings
    for item in INTERNAL_LINKS_CONFIG:
        if existing_hbm_links + len(added_links) >= 2:
            break
        if item["url"] in opt_content:
            continue

        pattern = re.compile(item["pattern"], re.IGNORECASE)
        match = None
        for m in pattern.finditer(opt_content):
            matched_text = m.group(0)
            m_low = matched_text.lower()
            if m_low == kp_lower or (kp_lower and (kp_lower in m_low or m_low in kp_lower)):
                continue
            if _is_inside_anchor(opt_content, m.start()) or _is_inside_heading(opt_content, m.start()):
                continue
            match = m
            break

        if match:
            start, end = match.span()
            matched_word = match.group(0)
            linked = f'<a href="{item["url"]}">{matched_word}</a>'
            opt_content = opt_content[:start] + linked + opt_content[end:]
            added_links.append({
                "name": item["name"],
                "url": item["url"],
                "anchor": matched_word,
            })

    # Secondary fallback pass: General high-relevance business hubs
    if existing_hbm_links + len(added_links) < 2:
        fallback_internal = [
            (r"\b(operational workflows?|business processes?|systems?|workflow automation|automated AP operations|automation)\b", "https://homebusinessmag.com/management/working-smarter/systems-behind-business-runs-smoothly/", "HBM Working Smarter & Systems"),
            (r"\b(office efficiency|improving efficiency|working smarter|productivity|time management|routine paperwork)\b", "https://homebusinessmag.com/management/working-smarter/", "HBM Working Smarter & Productivity"),
            (r"\b(workplace rituals?|workplace culture|workplace environment|workplace|team dynamics?|accountability)\b", "https://homebusinessmag.com/management/leadership/small-business-build-accountability-without-fear/", "HBM Management & Leadership"),
            (r"\b(growing a business|business growth|scale your business|helps? the business grow|small business(?:es)?|business(?:es)?)\b", "https://homebusinessmag.com/categories/growing-a-business/", "HBM Growing a Business"),
            (r"\b(human resources|hiring practices?|employees?|workforce|staff|talent|management)\b", "https://homebusinessmag.com/management/", "HBM Human Resources & Talent"),
            (r"\b(financial management|bookkeeping|accounting|financial records?|finances?)\b", "https://homebusinessmag.com/management/business-operations/", "HBM Business Operations & Finance"),
        ]
        for pat, url, name in fallback_internal:
            if existing_hbm_links + len(added_links) >= 2:
                break
            if url in opt_content:
                continue
            pattern = re.compile(pat, re.IGNORECASE)
            for m in pattern.finditer(opt_content):
                matched_text = m.group(0)
                m_low = matched_text.lower()
                if m_low == kp_lower or (kp_lower and (kp_lower in m_low or m_low in kp_lower)):
                    continue
                if _is_inside_anchor(opt_content, m.start()) or _is_inside_heading(opt_content, m.start()):
                    continue
                start, end = m.span()
                linked = f'<a href="{url}">{matched_text}</a>'
                opt_content = opt_content[:start] + linked + opt_content[end:]
                added_links.append({
                    "name": name,
                    "url": url,
                    "anchor": matched_text,
                })
                break

    # Tertiary universal fallback: Any standard business noun terms
    if existing_hbm_links + len(added_links) < 2:
        universal_fallbacks = [
            (r"\b(small business(?:es)?|businesses|business)\b", "https://homebusinessmag.com/categories/growing-a-business/", "HBM Growing a Business"),
            (r"\b(operations?|workflows?|routines?|processes?)\b", "https://homebusinessmag.com/management/working-smarter/systems-behind-business-runs-smoothly/", "HBM Working Smarter & Systems"),
            (r"\b(management|organization|strategy|leadership)\b", "https://homebusinessmag.com/management/leadership/small-business-build-accountability-without-fear/", "HBM Management & Leadership"),
            (r"\b(resources?|insights?|tips|guides?|information|articles?|topics?|details)\b", "https://homebusinessmag.com/management/working-smarter/", "HBM Working Smarter & Resources"),
        ]
        for pat, url, name in universal_fallbacks:
            if existing_hbm_links + len(added_links) >= 2:
                break
            if url in opt_content:
                continue
            pattern = re.compile(pat, re.IGNORECASE)
            for m in pattern.finditer(opt_content):
                matched_text = m.group(0)
                m_low = matched_text.lower()
                if m_low == kp_lower or (kp_lower and (kp_lower in m_low or m_low in kp_lower)):
                    continue
                if _is_inside_anchor(opt_content, m.start()) or _is_inside_heading(opt_content, m.start()):
                    continue
                start, end = m.span()
                linked = f'<a href="{url}">{matched_text}</a>'
                opt_content = opt_content[:start] + linked + opt_content[end:]
                added_links.append({
                    "name": name,
                    "url": url,
                    "anchor": matched_word if 'matched_word' in locals() else matched_text,
                })
                break

    return opt_content, added_links


def inject_external_authority_links(content: str, focus_keyphrase: str) -> tuple[str, list[dict]]:
    """
    Include one relevant, authoritative article from either Forbes or Entrepreneur.
    Inspects existing links first. If present, preserves. If missing, injects one verified link.
    """
    opt_content = content
    added_links = []
    kp_lower = (focus_keyphrase or "").lower().strip()

    # Check if a Forbes or Entrepreneur link already exists
    existing_auth = len(re.findall(r'href=["\']https?://(?:www\.)?(?:forbes\.com|entrepreneur\.com)', opt_content, re.IGNORECASE))
    if existing_auth >= 1:
        return opt_content, []

    def _is_inside_anchor(text: str, start_pos: int) -> bool:
        pre = text[:start_pos]
        open_a = pre.rfind('<a')
        close_a = pre.rfind('</a>')
        return open_a > close_a

    def _is_inside_heading(text: str, start_pos: int) -> bool:
        pre = text[:start_pos]
        for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            open_h = pre.rfind(f"<{tag}")
            close_h = pre.rfind(f"</{tag}>")
            if open_h > close_h:
                return True
        return False

    # Primary pass: Configured verified authority mappings
    for item in VERIFIED_AUTHORITY_LINKS:
        if item["domain"] in opt_content or item["url"] in opt_content:
            continue

        pattern = re.compile(item["pattern"], re.IGNORECASE)
        match = None
        for m in pattern.finditer(opt_content):
            matched_text = m.group(0)
            m_low = matched_text.lower()
            if m_low == kp_lower or (kp_lower and (kp_lower in m_low or m_low in kp_lower)):
                continue

            if _is_inside_anchor(opt_content, m.start()) or _is_inside_heading(opt_content, m.start()):
                continue

            match = m
            break

        if match:
            start, end = match.span()
            matched_word = match.group(0)
            linked = f'<a href="{item["url"]}">{matched_word}</a>'
            opt_content = opt_content[:start] + linked + opt_content[end:]
            added_links.append({
                "domain": item["domain"],
                "url": item["url"],
                "anchor": matched_word,
            })
            break

    # Secondary fallback pass: General high-authority entrepreneur/productivity/strategy articles if 0 authority links
    if existing_auth + len(added_links) < 1:
        fallback_authority = [
            (r"\b(corporate gifts?|corporate gifting|employee recognition|workplace recognition|client gifts?|gift-giving|culture of recognition|company culture|employee appreciation)\b", "https://www.entrepreneur.com/leadership/how-to-build-a-culture-of-recognition-in-the-workplace/367329", "entrepreneur.com"),
            (r"\b(financial management|bookkeeping|accounting|financial records?|finances?|pricing strateg(?:y|ies)|profit margins?)\b", "https://www.entrepreneur.com/growing-a-business/how-to-choose-the-right-pricing-strategy-for-your-small/471188", "entrepreneur.com"),
            (r"\b(workplace efficiency|increase efficiency|productivity|time management|streamlin(?:e|ing)|routine paperwork)\b", "https://www.entrepreneur.com/productivity/7-ways-to-dramatically-increase-workplace-efficiency/342938", "entrepreneur.com"),
            (r"\b(stand out from the competition|competitive advantage|business strategy|market differentiation|differentiat(?:e|ion)|scale operations?|small businesses?|business(?:es)?)\b", "https://www.entrepreneur.com/starting-a-business/10-ways-to-make-your-business-stand-out-from-the-competition/447291", "entrepreneur.com"),
            (r"\b(clear communication|business communication|effective communication|workplace communication|communications?|accountability)\b", "https://www.entrepreneur.com/leadership/why-clear-communication-is-vital-for-business-success/366710", "entrepreneur.com"),
            (r"\b(customer service|customer support|client relationships?)\b", "https://www.entrepreneur.com/growing-a-business/7-essentials-of-great-customer-service/220268", "entrepreneur.com"),
            (r"\b(hiring process|hiring decisions?|hiring the right person|recruiting candidates?)\b", "https://www.entrepreneur.com/growing-a-business/how-to-hire-the-right-person-for-your-business/435134", "entrepreneur.com"),
        ]
        for pat, url, domain in fallback_authority:
            if url in opt_content or domain in opt_content:
                continue
            pattern = re.compile(pat, re.IGNORECASE)
            for m in pattern.finditer(opt_content):
                matched_text = m.group(0)
                m_low = matched_text.lower()
                if m_low == kp_lower or (kp_lower and (kp_lower in m_low or m_low in kp_lower)):
                    continue
                if _is_inside_anchor(opt_content, m.start()) or _is_inside_heading(opt_content, m.start()):
                    continue
                start, end = m.span()
                linked = f'<a href="{url}">{matched_text}</a>'
                opt_content = opt_content[:start] + linked + opt_content[end:]
                added_links.append({
                    "domain": domain,
                    "url": url,
                    "anchor": matched_text,
                })
                break
            if added_links:
                break

    # Tertiary universal fallback: Any business/strategy terms
    if existing_auth + len(added_links) < 1:
        universal_auth = [
            (r"\b(business strategy|competitive advantage|market|strategy|differentiation)\b", "https://www.entrepreneur.com/starting-a-business/10-ways-to-make-your-business-stand-out-from-the-competition/447291", "entrepreneur.com"),
            (r"\b(productivity|efficiency|time management|systems)\b", "https://www.entrepreneur.com/productivity/7-ways-to-dramatically-increase-workplace-efficiency/342938", "entrepreneur.com"),
            (r"\b(communication|leadership|collaboration|team)\b", "https://www.entrepreneur.com/leadership/why-clear-communication-is-vital-for-business-success/366710", "entrepreneur.com"),
        ]
        for pat, url, domain in universal_auth:
            if url in opt_content or domain in opt_content:
                continue
            pattern = re.compile(pat, re.IGNORECASE)
            for m in pattern.finditer(opt_content):
                matched_text = m.group(0)
                m_low = matched_text.lower()
                if m_low == kp_lower or (kp_lower and (kp_lower in m_low or m_low in kp_lower)):
                    continue
                if _is_inside_anchor(opt_content, m.start()) or _is_inside_heading(opt_content, m.start()):
                    continue
                start, end = m.span()
                linked = f'<a href="{url}">{matched_text}</a>'
                opt_content = opt_content[:start] + linked + opt_content[end:]
                added_links.append({
                    "domain": domain,
                    "url": url,
                    "anchor": matched_text,
                })
                break
            if added_links:
                break

    return opt_content, added_links


async def optimize_article_seo(
    title: str,
    content: str,
    seo_fields: dict,
    site_url: str = "",
) -> dict:
    """
    Orchestrate the complete SEO optimization pass on article content & metadata.
    Enforces:
    1. Title Case on all H2/H3/H4 headings
    2. Meta description optimization (120-156 chars, no our/and/to, commas cleaned, synced to excerpt)
    3. Dynamic contextual subheadings with keyphrase
    4. Dynamic keyphrase density optimization
    5. At least 2 relevant HBM internal links (normalized to publication domain)
    6. Exactly 1 verified Forbes/Entrepreneur external link
    7. Post-optimization Yoast analysis with dynamic density feedback loop
    """
    focus_kw = seo_fields.get("focus_keyphrase", "")
    slug = seo_fields.get("slug", "")

    # 1. Format headings to Title Case
    opt_content, heading_title_case = format_headings_title_case(content)

    # 2. Optimize Meta Description
    opt_meta_desc = optimize_meta_description(
        seo_fields.get("meta_description", ""),
        focus_kw,
        title,
    )
    seo_fields["meta_description"] = opt_meta_desc
    seo_fields["excerpt"] = opt_meta_desc

    # 2.5. Optimize Introduction (Keyphrase in opening paragraph)
    opt_content, intro_changed = optimize_introduction(opt_content, focus_kw)

    # 3. Optimize Subheadings (dynamically incorporate keyphrase into 1-2 headings)
    opt_content, heading_changes = optimize_subheadings(opt_content, focus_kw)

    # 4. Optimize Keyphrase Density (dynamically calculated from article length)
    opt_content, kp_count = optimize_keyphrase_density(opt_content, focus_kw)

    # 5. Inject Internal Links (at least 2 relevant homebusinessmag.com links, normalized)
    opt_content, internal_links = inject_internal_links(opt_content, focus_kw, site_url)

    # 6. Inject External Authority Links (1 Forbes or Entrepreneur link)
    opt_content, external_links = inject_external_authority_links(opt_content, focus_kw)

    # 7. Run Real Yoast Analysis on homebusinessmag.com publication domain
    clean_slug = slug.strip("/") if slug else "article"
    permalink = f"https://homebusinessmag.com/{clean_slug}/"
    generated_seo = {
        **seo_fields,
        "title": title,
        "permalink": permalink,
        "site_url": "https://homebusinessmag.com",
    }
    seo_requirements = {
        "explicit_fields": {
            k: v for k, v in seo_fields.items() if v
        }
    }

    yoast_res = await yoast_service.analyze(opt_content, seo_requirements, generated_seo)

    # 8. Dynamic Feedback Loop: Check if Yoast reports keyphrase density under recommended minimum
    yoast_results = (yoast_res.get("data") or {}).get("seo", {}).get("results", [])
    dens_res = next((r for r in yoast_results if r.get("id") == "keyphraseDensity"), None)
    if dens_res and dens_res.get("score", 9) < 6:
        # Parse exact recommended minimum from Yoast's assessment text if available
        dens_text = dens_res.get("text", "")
        match = re.search(r'recommended minimum of (\d+) times?', dens_text)
        if match:
            req_min = int(match.group(1))
            opt_content, kp_count = optimize_keyphrase_density(opt_content, focus_kw, min_required=req_min)
            yoast_res = await yoast_service.analyze(opt_content, seo_requirements, generated_seo)

    return {
        "content": opt_content,
        "seo_fields": seo_fields,
        "heading_changes": heading_changes + heading_title_case,
        "keyphrase_count": kp_count,
        "internal_links_added": internal_links,
        "external_links_added": external_links,
        "yoast_analysis": yoast_res,
    }

