# =============================================================================
# ai_analysis.py — AI-powered qualitative and visual audit checks
# =============================================================================
"""
Handles all checks that require human-like judgement (checks 1-6, 16-18).
Now site-type-aware: prompts, scoring guidance, and issue descriptions are
all tailored to the detected site type.

Public API
----------
run_qualitative_analysis(homepage_text, all_page_texts, hero_b64, site_classification) -> QualReport
generate_narrative_report(all_issues, scores, qual_report, website_url, site_classification) -> str
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

from config import AI_MAX_TOKENS, AI_MODEL, AI_TEXT_MODEL
from detectors import AuditIssue

from detectors import (
    CATEGORY_FIRST_IMPRESSION, CATEGORY_MESSAGING, CATEGORY_LEAD_GEN,
    CATEGORY_TRUST, CATEGORY_MOBILE, CATEGORY_SEO,
    CATEGORY_MISSED_OPPS, CATEGORY_VISUAL_DESIGN,
)

_AI_VALID_CATEGORIES = {
    c.lower(): c for c in [
        CATEGORY_FIRST_IMPRESSION, CATEGORY_MESSAGING, CATEGORY_LEAD_GEN,
        CATEGORY_TRUST, CATEGORY_MOBILE, CATEGORY_SEO,
        CATEGORY_MISSED_OPPS, CATEGORY_VISUAL_DESIGN,
    ]
}


def _normalise_category(raw: str) -> str:
    return _AI_VALID_CATEGORIES.get(raw.strip().lower(), CATEGORY_MESSAGING)


load_dotenv()
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class QualReport:
    scores:     dict = field(default_factory=dict)
    issues:     list = field(default_factory=list)
    summary:    str  = ""
    quick_wins: list = field(default_factory=list)
    raw_json:   dict = field(default_factory=dict, repr=False)


# --------------------------------------------------------------------------- #
# Site-type-aware prompt context blocks
# --------------------------------------------------------------------------- #

# What the AI should focus on per site type for each check group
_SITE_TYPE_CONTEXT: dict[str, dict] = {
    "ecommerce": {
        "label":        "E-Commerce Store",
        "first_imp_focus": (
            "For an online store, the hero should immediately communicate what products "
            "are sold, who they are for, and why to buy here (USP). Offer/promotion "
            "visibility and trust signals (secure checkout, free shipping) matter most."
        ),
        "messaging_focus": (
            "Copy should be product and outcome focused. It should surface the benefit "
            "of owning the product, not just describe it. Urgency, social proof ('1,200 sold'), "
            "and specificity ('handmade in Italy') are strong signals."
        ),
        "visual_focus": (
            "Product photography quality is the single most important visual element. "
            "Lifestyle imagery outperforms plain white-background shots for conversion. "
            "Brand consistency across product pages, homepage, and checkout matters greatly."
        ),
        "quick_win_guidance": (
            "Focus quick wins on product page conversion: better photos, "
            "reviews integration, and clearer sizing/spec information."
        ),
    },
    "saas": {
        "label":        "SaaS / Software Product",
        "first_imp_focus": (
            "The hero must answer: what does this software do, who is it for, "
            "and what is the outcome? Jargon-free headlines, a short product demo "
            "or screenshot, and a frictionless trial/signup CTA are critical."
        ),
        "messaging_focus": (
            "SaaS copy should focus on outcomes, not features. 'Save 5 hours a week' "
            "beats 'Advanced automation engine'. Pain-point language ('Tired of juggling "
            "spreadsheets?') converts better than capability lists."
        ),
        "visual_focus": (
            "Product screenshots or UI demos in the hero are the strongest trust signal "
            "for SaaS. A clean, modern interface suggests a quality product. "
            "Generic team photos or abstract illustrations are red flags."
        ),
        "quick_win_guidance": (
            "Focus quick wins on the trial/demo flow: reduce steps to first value, "
            "add social proof near the CTA, and show the product UI prominently."
        ),
    },
    "local_service": {
        "label":        "Local Service Business",
        "first_imp_focus": (
            "Local service businesses need to establish location, service, and trust "
            "immediately. The visitor should know within 5 seconds: what you do, "
            "where you operate, and that you are legitimate and established."
        ),
        "messaging_focus": (
            "Copy should speak to local pain points and urgency (emergency plumber, "
            "same-day service, free quotes). Specific service areas build confidence. "
            "Avoid generic corporate language — warmth and directness convert."
        ),
        "visual_focus": (
            "Real photos of the team, vehicle fleet, finished jobs, or premises "
            "dramatically outperform stock imagery for local service businesses. "
            "Authenticity is the primary visual trust signal."
        ),
        "quick_win_guidance": (
            "Focus quick wins on contact friction: phone number in header, "
            "Google review widget, and a simple quote-request form above the fold."
        ),
    },
    "agency_creative": {
        "label":        "Agency / Creative Studio",
        "first_imp_focus": (
            "An agency's homepage must immediately demonstrate creative credibility. "
            "The hero should communicate the agency's specialism, client calibre, "
            "and a clear next step (portfolio, case studies, or book a call)."
        ),
        "messaging_focus": (
            "Agency copy should be benefit-led and outcome-focused: 'We help X "
            "brands grow Y'. Avoid vague positioning ('We tell stories'). "
            "Clear articulation of who the ideal client is builds confidence."
        ),
        "visual_focus": (
            "Design quality IS the product for an agency. The site itself must "
            "demonstrate the level of work the agency delivers. Generic templates, "
            "inconsistent typography, or stock photos are immediate credibility killers."
        ),
        "quick_win_guidance": (
            "Focus quick wins on social proof: add 3 client logos above the fold, "
            "link directly to a standout case study, and add a results statistic."
        ),
    },
    "b2b_corporate": {
        "label":        "B2B / Corporate Services",
        "first_imp_focus": (
            "B2B buyers need to quickly assess: is this company credible, do they "
            "understand my industry, and is there a clear next step? Enterprise buyers "
            "are risk-averse — reassurance signals matter as much as capability claims."
        ),
        "messaging_focus": (
            "Copy should speak to business outcomes (revenue, efficiency, risk reduction) "
            "and industry-specific language. Avoid generic statements. Specificity "
            "about client size, industry, and results builds confidence."
        ),
        "visual_focus": (
            "Professional, authoritative visual design signals enterprise-grade quality. "
            "Client logos, award badges, and compliance certifications are high-value "
            "trust signals. The site should feel like it belongs in the same league "
            "as the enterprise clients it serves."
        ),
        "quick_win_guidance": (
            "Focus quick wins on trust signals: add a client logo strip, "
            "a headline case study with a specific ROI stat, and a demo CTA "
            "that is visible without scrolling."
        ),
    },
    "content_blog": {
        "label":        "Content / Blog / Media",
        "first_imp_focus": (
            "Content sites need to immediately communicate topic focus and quality. "
            "Visitors should know in seconds what subjects are covered and why "
            "this publication is worth their time and subscription."
        ),
        "messaging_focus": (
            "Headlines and introductions are the primary conversion tool. "
            "Copy should demonstrate expertise and a distinct editorial voice. "
            "Generic or thin content without a clear niche is a red flag."
        ),
        "visual_focus": (
            "Clean reading experience, fast loading, and consistent visual presentation "
            "of content are key. Photography quality matters for individual articles. "
            "Intrusive advertising or cluttered layouts undermine credibility."
        ),
        "quick_win_guidance": (
            "Focus quick wins on email capture: add a prominent newsletter signup, "
            "improve content categorisation, and add author bio boxes to build trust."
        ),
    },
    "nonprofit": {
        "label":        "Non-Profit / Charity",
        "first_imp_focus": (
            "Nonprofit sites must immediately convey mission, impact, and urgency. "
            "The visitor should feel the cause within seconds and have a clear "
            "path to donating, volunteering, or learning more."
        ),
        "messaging_focus": (
            "Copy should lead with human impact, not organisational jargon. "
            "Specific beneficiary stories, tangible impact numbers ('£25 feeds "
            "a child for a month'), and emotional resonance convert donors."
        ),
        "visual_focus": (
            "Authentic imagery of beneficiaries, volunteers, or real-world impact "
            "is essential. Stock photography of smiling people undermines credibility. "
            "The site should feel transparent, mission-driven, and professionally maintained."
        ),
        "quick_win_guidance": (
            "Focus quick wins on donation friction: reduce steps to donate, "
            "add a specific impact statement next to the donate button, "
            "and add donor testimonials or impact numbers near the CTA."
        ),
    },
    "portfolio": {
        "label":        "Portfolio / Freelancer",
        "first_imp_focus": (
            "A portfolio site must immediately establish who you are, what you do, "
            "and show work quality. The visitor — typically a potential client — "
            "should be able to assess fit within seconds without scrolling."
        ),
        "messaging_focus": (
            "Copy should be direct and personal. Avoid corporate language. "
            "Clearly state the type of work taken on, industries served, and "
            "availability. One specific differentiator (specialisation, style, process) "
            "is worth more than a list of skills."
        ),
        "visual_focus": (
            "Work quality is the primary trust signal. Featured projects should "
            "be high quality and well-presented. The site design itself should "
            "reflect the designer/creator's level of craft."
        ),
        "quick_win_guidance": (
            "Focus quick wins on conversion: add a prominent 'Hire Me' or "
            "'Get in Touch' CTA, feature one standout project case study, "
            "and add a short client testimonial near the contact link."
        ),
    },
}

# Default fallback
_DEFAULT_SITE_CONTEXT = _SITE_TYPE_CONTEXT["local_service"]

SYSTEM_PROMPT = """
You are a senior digital marketing and conversion rate optimisation expert.
You audit websites for B2B agencies and produce reports for non-technical
salespeople. Your writing is direct, jargon-free, and focused on revenue impact.
"""


def _build_user_prompt(
    homepage_text: str,
    all_texts: dict,
    site_classification,
) -> str:
    hp_excerpt = homepage_text[:4000]
    other_excerpts = "\n\n".join(
        f"=== {pt.upper()} PAGE ===\n{text[:1500]}"
        for pt, text in all_texts.items()
        if pt != "homepage"
    )

    # Pull site-type-specific context
    ctx = _SITE_TYPE_CONTEXT.get(
        site_classification.site_type if site_classification else "local_service",
        _DEFAULT_SITE_CONTEXT,
    )
    site_label       = ctx["label"]
    first_imp_focus  = ctx["first_imp_focus"]
    messaging_focus  = ctx["messaging_focus"]
    visual_focus     = ctx["visual_focus"]
    quick_win_guide  = ctx["quick_win_guidance"]
    site_description = site_classification.description if site_classification else ""

    return f"""
Audit the website content below and return ONLY valid JSON -- no markdown fences,
no preamble, no trailing text.

SITE TYPE: {site_label}
SITE DESCRIPTION: {site_description}

HOMEPAGE TEXT (first 4000 chars):
{hp_excerpt}

OTHER PAGES:
{other_excerpts}

Return this exact JSON structure:

{{
  "summary": "2-3 sentence plain-English overview of the site's biggest strengths and weaknesses.",
  "scores": {{
    "first_impression": 0-100,
    "messaging": 0-100,
    "trust": 0-100,
    "visual_design": 0-100
  }},
  "issues": [
    {{
      "severity": "HIGH" | "MEDIUM" | "LOW",
      "category": "First Impression" | "Messaging" | "Trust" | "Visual Design",
      "title": "Short title (max 8 words)",
      "description": "One plain-English sentence a salesperson can act on."
    }}
  ],
  "quick_wins": [
    "First quick win -- plain English, one sentence.",
    "Second quick win -- plain English, one sentence.",
    "Third quick win -- plain English, one sentence."
  ]
}}

This is a {site_label} site. Evaluate EVERY check below in that context.
Include an issue only if the site genuinely fails it for this type of business.

FIRST IMPRESSION (checks 1-3)
Context for this site type: {first_imp_focus}
- CHECK 1: Is the value proposition clear within 5 seconds of landing on the page?
- CHECK 2: Is the hero section compelling, or is it generic for this industry?
- CHECK 3: Does the overall site feel credible and appropriate for this type of business?

MESSAGING & COPY (checks 4-6)
Context for this site type: {messaging_focus}
- CHECK 4: Is the copy benefit-driven (outcomes for the customer) or just a list of services/features?
- CHECK 5: Does the copy speak to specific customer pain points for this type of business?
- CHECK 6: Is there a clear, memorable differentiator from competitors in this space?

VISUAL DESIGN (checks 16-18 -- text-only; screenshot will supplement)
Context for this site type: {visual_focus}
- CHECK 16: Does the design quality match what a credible {site_label} would present?
- CHECK 17: Is branding visually consistent across pages?
- CHECK 18: Is imagery authentic and appropriate, or does it look like generic stock photography?

QUICK WINS GUIDANCE for {site_label}: {quick_win_guide}

Only include an issue if the site genuinely fails the check for this site type.
Do not fabricate issues. Scores: 80-100 = strong, 60-79 = average, below 60 = weak.
"""


def _build_vision_addendum(site_type: str = "local_service") -> str:
    ctx          = _SITE_TYPE_CONTEXT.get(site_type, _DEFAULT_SITE_CONTEXT)
    visual_focus = ctx["visual_focus"]

    return f"""

A screenshot of the homepage hero is included as an image.
Evaluate the three visual design checks from the screenshot directly.

VISUAL DESIGN -- screenshot assessment (checks 16-18)
Site type context: {visual_focus}

- CHECK 16: Does the visual design quality match what a credible {ctx['label']} would present?
- CHECK 17: Is the branding visually consistent -- colours, fonts, and logo placement coherent?
- CHECK 18: Does the imagery appear authentic and appropriate for this type of business,
  or does it look like generic stock photography?

Scoring: if checks 16-18 all pass, visual_design should be 75-100.
If one or two fail, adjust downward proportionally.
"""


def _parse_response(text: str) -> dict:
    import re
    text = re.sub(r"```[a-z]*\n?", "", text).replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI response was not valid JSON: {e}\nRaw: {text[:300]}")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def run_qualitative_analysis(
    homepage_text:   str,
    all_page_texts:  dict,
    hero_b64:        Optional[str] = None,
    site_classification = None,
) -> QualReport:
    """
    Send one API call covering all 9 AI-assessed checks (1-6, 16-18),
    with prompts calibrated to the detected site type.
    """
    user_text = _build_user_prompt(homepage_text, all_page_texts, site_classification)
    site_type = site_classification.site_type if site_classification else "local_service"

    if hero_b64:
        user_text += _build_vision_addendum(site_type)

    content = [{"type": "text", "text": user_text}]
    if hero_b64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url":    f"data:image/jpeg;base64,{hero_b64}",
                "detail": "low",
            },
        })

    try:
        response = _client.chat.completions.create(
            model       = AI_MODEL,
            messages    = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": content},
            ],
            max_tokens  = AI_MAX_TOKENS,
            temperature = 0.3,
        )
        raw_text = response.choices[0].message.content or ""
        data     = _parse_response(raw_text)

    except Exception as exc:
        print(f"  [ai_analysis] API call failed: {exc}")
        return QualReport(
            summary    = "AI analysis could not be completed due to an API error.",
            quick_wins = [],
        )

    ai_issues = []
    for item in data.get("issues", []):
        try:
            ai_issues.append(AuditIssue(
                severity    = item.get("severity", "MEDIUM"),
                category    = _normalise_category(item.get("category", "")),
                title       = item.get("title", "Issue detected"),
                description = item.get("description", ""),
            ))
        except Exception:
            pass

    raw_quick_wins = data.get("quick_wins", [])
    quick_wins = [w for w in raw_quick_wins if w and isinstance(w, str) and w.strip()][:3]

    return QualReport(
        scores     = data.get("scores", {}),
        issues     = ai_issues,
        summary    = data.get("summary", ""),
        quick_wins = quick_wins,
        raw_json   = data,
    )


# --------------------------------------------------------------------------- #
# Narrative report
# --------------------------------------------------------------------------- #

def generate_narrative_report(
    all_issues:          list,
    scores:              dict,
    qual_report:         QualReport,
    website_url:         str,
    site_classification  = None,
) -> str:
    """
    Generate a polished, detailed prose narrative from the combined issues and scores,
    contextualised for the detected site type.
    """
    high_issues   = [i for i in all_issues if i.severity == "HIGH"]
    medium_issues = [i for i in all_issues if i.severity == "MEDIUM"]

    high_block   = "\n".join(f"  - [{i.category}] {i.title}: {i.description}" for i in high_issues[:6])
    medium_block = "\n".join(f"  - [{i.category}] {i.title}: {i.description}" for i in medium_issues[:6])

    strengths     = [k for k, v in scores.items() if isinstance(v, int) and v >= 75 and k != "overall"]
    strength_text = ", ".join(strengths) if strengths else "none identified"
    overall       = scores.get("overall", 0)

    site_label = ""
    site_desc  = ""
    if site_classification:
        site_label = site_classification.label
        site_desc  = site_classification.description

    prompt = f"""
You are a senior website auditor writing a detailed, professional client-facing report
for {website_url}. The audience is a non-technical salesperson who will present this
to a prospect to help win their business.

SITE TYPE: {site_label}
{site_desc}

Write a 5-6 paragraph narrative that:
1. Opens by identifying this as a {site_label} site and giving a candid overall assessment
   (state the overall score {overall}/100 naturally)
2. Dedicates a full paragraph to the most critical revenue-impacting issues
   (focus on HIGH severity issues — explain WHY each hurts this type of business)
3. Covers medium-priority issues as clear improvement opportunities
4. Acknowledges genuine strengths (categories scoring 75+: {strength_text})
5. Closes with a motivating, action-oriented summary — these are fixable problems
   and fixing them will have a measurable impact on leads and revenue for a {site_label}

Overall score: {overall}/100
Category scores: {json.dumps(scores, indent=2)}

HIGH priority issues:
{high_block or "None"}

MEDIUM priority issues:
{medium_block or "None"}

AI qualitative summary: {qual_report.summary}

Writing guidelines:
- No bullet points. No section headings. Clean, flowing paragraphs only.
- Use plain English — no jargon. Write as if explaining to a smart non-technical person.
- Be direct and honest about problems, but constructive in tone.
- 350-450 words total.
- Reference the site type naturally where relevant (e.g. "for a local service business...").
- Make the prospect feel the urgency of fixing this, but also confident it is achievable.
"""
    try:
        resp = _client.chat.completions.create(
            model       = AI_TEXT_MODEL,
            messages    = [{"role": "user", "content": prompt}],
            max_tokens  = 600,
            temperature = 0.4,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        print(f"  [ai_analysis] Narrative generation failed: {exc}")
        return qual_report.summary