# =============================================================================
# detectors.py — All 21 audit checks, site-type-aware
# =============================================================================
"""
Every function accepts an optional `site_type` string (default "local_service")
so thresholds, patterns, and issue copy are calibrated per site category.

Full 21-check coverage
──────────────────────
FIRST IMPRESSION   (AI)     #1-3
MESSAGING          (AI)     #4-6
TRUST              (HTML)   #7-9
LEAD GEN           (HTML)   #10-13
MOBILE             (HTML)   #14-15
VISUAL DESIGN      (AI)     #16-18
MISSED OPPS        (HTML)   #19-21
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from config import (
    CTA_CLASS_SIGNALS,
    CTA_CLASS_SIGNALS_BY_TYPE,
    CTA_TEXT_PATTERNS,
    CTA_TEXT_PATTERNS_BY_TYPE,
    CTA_THRESHOLDS,
    CTA_THRESHOLDS_BY_SITE,
    PIXEL_SIGNATURES,
    PIXEL_REQUIRED_BY_SITE,
    BLOG_REQUIRED_BY_SITE,
    RATING_PATTERNS,
    RESULTS_PROOF_PATTERNS,
    RESULTS_PROOF_PATTERNS_DEFAULT,
    REVIEW_APP_SIGNATURES,
    SOCIAL_PROOF_THRESHOLDS_BY_SITE,
    TRUST_PATTERNS,
)
from extractors import PageData


def _safe_text(text: str, limit: int = 100_000) -> str:
    return text[:limit] if text else ""


# --------------------------------------------------------------------------- #
# Category constants
# --------------------------------------------------------------------------- #
CATEGORY_FIRST_IMPRESSION = "First Impression"
CATEGORY_MESSAGING        = "Messaging"
CATEGORY_LEAD_GEN         = "Lead Gen"
CATEGORY_TRUST            = "Trust"
CATEGORY_MOBILE           = "Mobile"
CATEGORY_SEO              = "SEO"
CATEGORY_MISSED_OPPS      = "Missed Opps"
CATEGORY_VISUAL_DESIGN    = "Visual Design"


# --------------------------------------------------------------------------- #
# AuditIssue
# --------------------------------------------------------------------------- #

@dataclass
class AuditIssue:
    severity:    str
    category:    str
    title:       str
    description: str

    def __post_init__(self):
        if self.severity not in ("HIGH", "MEDIUM", "LOW"):
            self.severity = "MEDIUM"
        self.title       = (self.title or "")[:120]
        self.description = (self.description or "")[:800]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.category}: {self.title} -- {self.description}"

    @property
    def tag(self) -> str:
        return f"[{self.severity}]"


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _button_text(data: PageData) -> str:
    return " ".join(
        b.get_text(" ", strip=True).lower()
        for b in data.soup.find_all(["button", "a"])
    )


def _cta_score(data: PageData, site_type: str = "local_service") -> int:
    """Score how prominent/present the CTAs are, using site-type-aware signals."""
    soup      = data.soup
    score     = 0
    class_sigs = CTA_CLASS_SIGNALS_BY_TYPE.get(site_type, CTA_CLASS_SIGNALS)
    text_pats  = CTA_TEXT_PATTERNS_BY_TYPE.get(site_type, CTA_TEXT_PATTERNS)

    # Class-level CTA signals
    for tag in soup.find_all(["a", "button"]):
        classes = " ".join(tag.get("class", [])).lower()
        if any(sig in classes for sig in class_sigs):
            score += 3
            break

    # Form action signals
    for form in data.forms:
        action = form["action"].lower()
        if any(kw in action for kw in ["cart", "checkout", "contact", "submit", "book",
                                        "donate", "subscribe", "signup", "register"]):
            score += 2
            break

    # Text patterns in buttons / links
    btn_text = _safe_text(_button_text(data))
    if any(re.search(p, btn_text) for p in text_pats):
        score += 2

    # Any styled button present at all
    for tag in soup.find_all(["a", "button"]):
        classes = " ".join(tag.get("class", [])).lower()
        if "btn" in classes or "button" in classes:
            score += 1
            break

    return score


def _cta_threshold(site_type: str, page_type: str) -> int:
    """Return the minimum CTA score needed to pass for this site+page combination."""
    site_map  = CTA_THRESHOLDS_BY_SITE.get(site_type, {})
    threshold = site_map.get(page_type, site_map.get("default", CTA_THRESHOLDS.get("default", 2)))
    return threshold


def _social_proof_score(data: PageData) -> int:
    score = 0
    html  = _safe_text(data.html)
    text  = _safe_text(data.text)

    if any(app in html for app in REVIEW_APP_SIGNATURES):
        score += 2
    if "aggregaterating" in html or "reviewcount" in html:
        score += 2
    if any(re.search(p, text) for p in RATING_PATTERNS):
        score += 1
    if any(re.search(p, text) for p in TRUST_PATTERNS):
        score += 1

    for tag in data.soup.find_all(["p", "div", "blockquote", "span"]):
        txt = tag.get_text(" ", strip=True)
        if len(txt.split()) > 15 and (txt.count('"') >= 2 or txt.count("\u201c") >= 1):
            score += 1
            break

    logo_signals = ["logo", "client", "partner", "brand", "trusted-by"]
    for tag in data.soup.find_all(attrs={"class": True}):
        classes = " ".join(tag.get("class", [])).lower()
        if any(sig in classes for sig in logo_signals) and tag.find("img"):
            score += 1
            break

    return score


def _social_proof_threshold(site_type: str) -> int:
    return SOCIAL_PROOF_THRESHOLDS_BY_SITE.get(site_type, 1)


def _has_retargeting_pixel(data: PageData) -> bool:
    html = _safe_text(data.html)
    return any(sig in html for sig in PIXEL_SIGNATURES)


def _has_blog(data: PageData, all_data: dict) -> bool:
    if "blog" in all_data:
        return True
    blog_patterns = ["/blog", "/news", "/articles", "/insights", "/resources",
                     "/magazine", "/posts", "/journal"]
    return any(
        any(p in link.lower() for p in blog_patterns)
        for link in data.links
    )


def _has_contact_details(data: PageData) -> bool:
    text = _safe_text(data.text)
    has_phone   = bool(re.search(r"\+?\d[\d\s\-\(\)]{7,}\d", text))
    has_email   = bool(re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text))
    has_address = any(kw in text for kw in [
        "street", "avenue", "suite", "floor", ", ca", ", ny", ", tx",
        "road", "lane", "drive", "blvd", "high street", "broadway",
    ])
    return has_phone or has_email or has_address


def _form_has_required_fields(form: dict) -> bool:
    inputs             = form.get("inputs", [])
    input_types        = [i.get("type", "").lower() for i in inputs]
    input_names        = [i.get("name", "").lower() for i in inputs]
    input_placeholders = [i.get("placeholder", "").lower() for i in inputs]
    all_hints = " ".join(input_names + input_placeholders)

    has_email_field = (
        "email" in input_types
        or "email" in all_hints
        or any(re.search(r"e[\s-]?mail", h) for h in input_names + input_placeholders)
    )
    has_submit = "submit" in input_types or len(inputs) > 1
    return has_email_field and has_submit


def _has_tap_target_issues(data: PageData) -> bool:
    html       = _safe_text(data.html, 80_000)
    small_font = re.search(r'font-size\s*:\s*([5-9]|1[01])px', html, re.I)
    tiny_btn   = re.search(r'(?:height|min-height)\s*:\s*([1-2]\d)px', html, re.I)
    return bool(small_font or tiny_btn)


def _has_results_proof(data: PageData, site_type: str = "local_service") -> bool:
    """Check 9: proof of results, calibrated per site type."""
    text     = _safe_text(data.text)
    patterns = RESULTS_PROOF_PATTERNS.get(site_type, RESULTS_PROOF_PATTERNS_DEFAULT)
    return any(re.search(p, text) for p in patterns)


# --------------------------------------------------------------------------- #
# CTA description helpers — site-type-aware plain-English copy
# --------------------------------------------------------------------------- #

_CTA_WHAT_TO_DO = {
    "ecommerce":       "a prominent 'Add to Cart' or 'Buy Now' button",
    "saas":            "a clear 'Start Free Trial', 'Get Started', or 'Book a Demo' button",
    "local_service":   "a visible 'Book Now', 'Get a Quote', or 'Call Us' button",
    "agency_creative": "a prominent 'Get a Proposal', 'Book a Call', or 'Let's Talk' button",
    "b2b_corporate":   "a clear 'Request a Demo', 'Contact Sales', or 'Get a Quote' button",
    "content_blog":    "a 'Subscribe' or 'Get Updates' call to action",
    "nonprofit":       "a prominent 'Donate Now' or 'Get Involved' button",
    "portfolio":       "a visible 'Hire Me' or 'Get in Touch' link",
}

_SP_WHAT_TO_ADD = {
    "ecommerce":       "product reviews, star ratings, and customer photo galleries",
    "saas":            "G2 or Capterra badges, customer logos, and usage statistics",
    "local_service":   "Google review stars, Yelp badges, or customer testimonials",
    "agency_creative": "client logos, case study previews, and result statistics",
    "b2b_corporate":   "client logos, case studies, and quantified ROI statements",
    "content_blog":    "subscriber counts or press mentions",
    "nonprofit":       "donor testimonials, impact statistics, or beneficiary stories",
    "portfolio":       "client testimonials and project outcome notes",
}

_FORM_WHAT_TO_ADD = {
    "ecommerce":       "a contact or returns enquiry form",
    "saas":            "a demo request or contact sales form",
    "local_service":   "a quote request or booking form",
    "agency_creative": "a project enquiry or discovery call booking form",
    "b2b_corporate":   "a demo request or RFP contact form",
    "content_blog":    "a newsletter sign-up form",
    "nonprofit":       "a donation form or volunteer sign-up",
    "portfolio":       "a hire / project enquiry form",
}


# --------------------------------------------------------------------------- #
# 1. SEO CHECKS
# --------------------------------------------------------------------------- #

def seo_check(data: PageData, site_type: str = "local_service") -> list:
    issues = []
    page   = data.url

    if not data.title:
        issues.append(AuditIssue(
            severity    = "LOW",
            category    = CATEGORY_SEO,
            title       = "Missing page title",
            description = (
                f"The page at {page} has no title tag. Search engines use this as the primary "
                "ranking signal and it is the first line users see in Google results. "
                "Every page needs a unique, keyword-focused title under 60 characters."
            ),
        ))
    elif len(data.title) > 65:
        issues.append(AuditIssue(
            severity    = "LOW",
            category    = CATEGORY_SEO,
            title       = "Title tag too long",
            description = (
                f"The title on {page} is {len(data.title)} characters — Google cuts off titles "
                "over 60 characters in search results. Trim it so the most important keywords "
                "appear first and are fully visible to searchers."
            ),
        ))

    if not data.meta_desc:
        issues.append(AuditIssue(
            severity    = "LOW",
            category    = CATEGORY_SEO,
            title       = "Missing meta description",
            description = (
                f"There is no meta description on {page}. This short preview text under your "
                "Google listing is a key driver of click-through rate — without it, Google "
                "picks text at random, which is rarely compelling or conversion-focused."
            ),
        ))
    elif len(data.meta_desc) > 160:
        issues.append(AuditIssue(
            severity    = "LOW",
            category    = CATEGORY_SEO,
            title       = "Meta description too long",
            description = (
                f"The meta description on {page} is {len(data.meta_desc)} characters — "
                "Google truncates anything over 155 characters. Rewrite it to fit within "
                "the limit and close with a clear call to action."
            ),
        ))

    if not data.h1:
        issues.append(AuditIssue(
            severity    = "MEDIUM",
            category    = CATEGORY_SEO,
            title       = "No H1 heading on page",
            description = (
                f"The page at {page} has no H1 heading. H1s are the single clearest on-page "
                "signal to search engines about your topic. Every important page needs exactly "
                "one H1, ideally containing the primary target keyword."
            ),
        ))
    elif len(data.h1) > 1:
        issues.append(AuditIssue(
            severity    = "LOW",
            category    = CATEGORY_SEO,
            title       = "Multiple H1 headings",
            description = (
                f"There are {len(data.h1)} H1 headings on {page}. Multiple H1s dilute the "
                "topical relevance signal to search engines. Keep one H1 and use H2/H3 "
                "for all sub-sections."
            ),
        ))

    return issues


# --------------------------------------------------------------------------- #
# 2. LEAD GEN CHECKS  (checks 10-13)
# --------------------------------------------------------------------------- #

def lead_gen_check(data: PageData, site_type: str = "local_service") -> list:
    issues    = []
    page_type = data.page_type

    # Check 10 — CTA
    score     = _cta_score(data, site_type)
    threshold = _cta_threshold(site_type, page_type)
    cta_desc  = _CTA_WHAT_TO_DO.get(site_type, "a clear call-to-action button")

    if score < threshold:
        issues.append(AuditIssue(
            severity    = "HIGH",
            category    = CATEGORY_LEAD_GEN,
            title       = "Weak or missing call to action",
            description = (
                f"The page at {data.url} lacks {cta_desc}. "
                "Without a strong CTA visible without scrolling, most visitors leave without "
                "converting — this is typically the fastest revenue win available."
            ),
        ))

    # Check 11 — Form / booking / lead magnet
    has_form  = len(data.forms) > 0
    form_desc = _FORM_WHAT_TO_ADD.get(site_type, "an enquiry or contact form")

    # content_blog and portfolio: form not strictly required on every page
    form_required_pages = {
        "ecommerce":       ("contact", "homepage"),
        "saas":            ("contact", "homepage", "service"),
        "local_service":   ("contact", "homepage", "service"),
        "agency_creative": ("contact", "homepage", "service"),
        "b2b_corporate":   ("contact", "homepage", "service"),
        "content_blog":    ("contact",),
        "nonprofit":       ("contact", "homepage"),
        "portfolio":       ("contact", "homepage"),
    }
    pages_needing_form = form_required_pages.get(site_type, ("contact", "homepage", "service"))
    if page_type in pages_needing_form and not has_form:
        issues.append(AuditIssue(
            severity    = "HIGH",
            category    = CATEGORY_LEAD_GEN,
            title       = "No lead capture form found",
            description = (
                f"There is no {form_desc} on {data.url}. Forms let prospects "
                "reach out on their own schedule — without one, you are entirely dependent on "
                "visitors picking up the phone or emailing directly, which the majority will not do."
            ),
        ))

    # Check 12 — Contact details
    # Less critical for pure e-commerce and SaaS; essential for local and agency
    contact_required = site_type not in ("content_blog", "ecommerce")
    if contact_required and page_type in ("contact", "homepage") and not _has_contact_details(data):
        issues.append(AuditIssue(
            severity    = "MEDIUM",
            category    = CATEGORY_LEAD_GEN,
            title       = "Contact details hard to find",
            description = (
                f"No phone number or email address was detected on {data.url}. "
                "High-intent prospects who prefer to call or email directly will leave if "
                "contact details are not visible within seconds — display them in the header or footer."
            ),
        ))

    # Check 13 — Lead capture actually works
    if has_form:
        broken_forms = [f for f in data.forms if not _form_has_required_fields(f)]
        if broken_forms and page_type in ("contact", "homepage", "service"):
            issues.append(AuditIssue(
                severity    = "HIGH",
                category    = CATEGORY_LEAD_GEN,
                title       = "Form may not capture leads properly",
                description = (
                    f"A form on {data.url} appears to be missing an email field or submit "
                    "button — meaning submitted enquiries may never be received. Test every "
                    "form by filling it in yourself and confirming the lead arrives in your inbox or CRM."
                ),
            ))

    return issues


# --------------------------------------------------------------------------- #
# 3. TRUST & CREDIBILITY CHECKS  (checks 7-9)
# --------------------------------------------------------------------------- #

def trust_check(data: PageData, site_type: str = "local_service") -> list:
    issues    = []
    page_type = data.page_type
    sp_desc   = _SP_WHAT_TO_ADD.get(site_type, "testimonials, reviews, or client logos")

    # Check 7 — Social proof
    score     = _social_proof_score(data)
    threshold = _social_proof_threshold(site_type)

    if threshold > 0 and score < threshold:
        issues.append(AuditIssue(
            severity    = "HIGH",
            category    = CATEGORY_TRUST,
            title       = "No social proof visible",
            description = (
                f"The page at {data.url} shows no {sp_desc}. "
                "Social proof is the number one conversion driver — without it, even "
                "well-designed pages consistently underperform."
            ),
        ))

    # Check 8 — Real team (about page)
    if page_type == "about":
        team_signals = ["team", "founder", "ceo", "director", "our people", "meet"]
        has_team = any(s in data.text for s in team_signals) and len(data.images) > 2
        if not has_team:
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_TRUST,
                title       = "No real team or people visible",
                description = (
                    f"The About page at {data.url} does not appear to show real team members "
                    "with photos or bios. Buyers need to see the people they will be working "
                    "with — humanising the business builds a level of trust no polished copy can replace."
                ),
            ))

    # Check 9 — Proof of results (calibrated per site type)
    # Skip for content_blog and portfolio where it's not a core expectation
    proof_required_pages = ("homepage", "service", "about")
    proof_not_needed = site_type in ("content_blog",)
    if not proof_not_needed and page_type in proof_required_pages:
        if not _has_results_proof(data, site_type):
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_TRUST,
                title       = "No proof of results or credentials",
                description = (
                    f"No case studies, statistics, awards, certifications, or measurable outcomes "
                    f"were found on {data.url}. One specific, quantified result "
                    "outperforms pages of descriptive copy when it comes to convincing a "
                    "sceptical buyer."
                ),
            ))

    return issues


# --------------------------------------------------------------------------- #
# 4. MOBILE EXPERIENCE CHECKS  (checks 14-15)
# --------------------------------------------------------------------------- #

def mobile_check(data: PageData, site_type: str = "local_service") -> list:
    issues = []

    # Check 14 — viewport / usable on mobile
    if not data.viewport_ok:
        issues.append(AuditIssue(
            severity    = "HIGH",
            category    = CATEGORY_MOBILE,
            title       = "Not configured for mobile devices",
            description = (
                f"The page at {data.url} is missing the mobile viewport meta tag, so it "
                "renders as a shrunken desktop version on phones. Over 60% of web traffic is "
                "now mobile — this issue alone can account for a significant drop in enquiries."
            ),
        ))

    # Check 15 — tap targets / readability
    if _has_tap_target_issues(data):
        issues.append(AuditIssue(
            severity    = "MEDIUM",
            category    = CATEGORY_MOBILE,
            title       = "Small text or tap targets detected",
            description = (
                f"Very small font sizes or button dimensions were found in the code of {data.url}. "
                "Google requires a minimum 16px text size and 48×48px tap targets for mobile "
                "usability — falling short harms both user experience and mobile search rankings."
            ),
        ))

    # Supplementary: fixed-width (only raise alongside viewport failure)
    if (
        bool(re.search(r'width\s*:\s*\d{3,4}px', _safe_text(data.html, 50_000), re.I))
        and not data.viewport_ok
    ):
        issues.append(AuditIssue(
            severity    = "MEDIUM",
            category    = CATEGORY_MOBILE,
            title       = "Fixed-width layout detected",
            description = (
                f"Fixed pixel widths in the HTML of {data.url} suggest the layout does not "
                "adapt to smaller screens. On phones, content may overflow or require horizontal "
                "scrolling, which Google penalises in mobile search rankings."
            ),
        ))

    return issues


# --------------------------------------------------------------------------- #
# 5. MISSED OPPORTUNITIES (checks 19-21)
# --------------------------------------------------------------------------- #

def missed_opps_check(
    homepage_data: PageData,
    all_data: dict,
    site_type: str = "local_service",
) -> list:
    issues = []

    # Check 20 — Retargeting pixel
    pixel_required = PIXEL_REQUIRED_BY_SITE.get(site_type, True)
    if pixel_required and not _has_retargeting_pixel(homepage_data):
        issues.append(AuditIssue(
            severity    = "HIGH",
            category    = CATEGORY_MISSED_OPPS,
            title       = "No retargeting pixel installed",
            description = (
                "No Facebook Pixel, Google Tag Manager, or LinkedIn Insight Tag was found on "
                "the homepage. Without a pixel, it is impossible to run retargeting ads to "
                "visitors who have already shown interest — one of the highest-ROI advertising "
                "channels available, and completely inaccessible without this in place."
            ),
        ))

    # Check 19 — Blog / content
    blog_required = BLOG_REQUIRED_BY_SITE.get(site_type, True)
    if blog_required and not _has_blog(homepage_data, all_data):
        issues.append(AuditIssue(
            severity    = "MEDIUM",
            category    = CATEGORY_MISSED_OPPS,
            title       = "No blog or content section found",
            description = (
                "There is no blog, news, or resources section on this website. Regular, "
                "keyword-optimised content is the most cost-effective long-term source of "
                "organic traffic, and signals to Google the site is authoritative and "
                "actively maintained."
            ),
        ))

    # Check 21 — Social proof sitewide
    sp_threshold      = _social_proof_threshold(site_type)
    any_social_proof  = any(_social_proof_score(pd) >= 1 for pd in all_data.values())
    existing_titles   = {issue.title for issue in issues}

    if (
        sp_threshold > 0
        and not any_social_proof
        and "No social proof across entire site" not in existing_titles
    ):
        sp_desc = _SP_WHAT_TO_ADD.get(site_type, "testimonials, reviews, or client logos")
        issues.append(AuditIssue(
            severity    = "HIGH",
            category    = CATEGORY_MISSED_OPPS,
            title       = "No social proof across entire site",
            description = (
                f"No {sp_desc} were found on any page. "
                "For an established business this is the single most impactful missed "
                "opportunity — buyers require third-party validation before committing, and "
                "its complete absence creates unnecessary doubt at the critical decision moment."
            ),
        ))

    return issues


# --------------------------------------------------------------------------- #
# 6. BROKEN LINKS
# --------------------------------------------------------------------------- #

def broken_links_check(broken_urls: list, page_url: str) -> list:
    if not broken_urls:
        return []

    url_list = ", ".join(broken_urls[:5])
    suffix   = f" (and {len(broken_urls) - 5} more)" if len(broken_urls) > 5 else ""

    return [AuditIssue(
        severity    = "MEDIUM",
        category    = CATEGORY_SEO,
        title       = f"{len(broken_urls)} broken link(s) found",
        description = (
            f"Found {len(broken_urls)} link(s) returning 404 errors on {page_url}: "
            f"{url_list}{suffix}. Broken links damage search rankings, frustrate visitors, "
            "and signal to Google that the site is not properly maintained."
        ),
    )]