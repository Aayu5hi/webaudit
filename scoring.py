from __future__ import annotations

from config import SCORE_WEIGHTS
from detectors import (
    AuditIssue,
    CATEGORY_FIRST_IMPRESSION, CATEGORY_MESSAGING, CATEGORY_LEAD_GEN,
    CATEGORY_TRUST, CATEGORY_MOBILE, CATEGORY_SEO,
    CATEGORY_MISSED_OPPS, CATEGORY_VISUAL_DESIGN,
)


# Maps detector category constants to score buckets
CATEGORY_BUCKET: dict[str, str] = {
    CATEGORY_SEO:              "seo",
    CATEGORY_LEAD_GEN:         "lead_gen",
    CATEGORY_TRUST:            "trust",
    CATEGORY_MOBILE:           "mobile",
    CATEGORY_MISSED_OPPS:      "missed_opps",
    CATEGORY_FIRST_IMPRESSION: "first_impression",
    CATEGORY_MESSAGING:        "messaging",
    CATEGORY_VISUAL_DESIGN:    "visual_design",
}

ALL_BUCKETS = list(dict.fromkeys(CATEGORY_BUCKET.values()))


def _clamp(val) -> int:
    try:
        return max(0, min(100, int(val)))
    except (TypeError, ValueError):
        return 0


def _deduct(base: int, issues: list[AuditIssue]) -> int:
    score = base
    for issue in issues:
        score -= SCORE_WEIGHTS.get(issue.severity, 0)
    return max(0, min(100, score))


def score_all(
    html_issues: list[AuditIssue],
    ai_scores: dict[str, int],
    lighthouse_scores: dict[str, int] | None = None,
) -> dict[str, int]:
    """
    Parameters
    ----------
    html_issues       : all AuditIssues from the HTML detectors + technical SEO
    ai_scores         : {category_key: 0-100} from QualReport.scores
    lighthouse_scores : {performance, seo, accessibility} 0-100 from PSI

    Returns
    -------
    dict with one key per ALL_BUCKETS plus an "overall" key.
    Also includes "performance" and "accessibility" if Lighthouse data available.
    """
    lighthouse_scores = lighthouse_scores or {}

    # ✅ Sanitize scores
    ai_scores         = {k: _clamp(v) for k, v in ai_scores.items()}
    lighthouse_scores = {k: _clamp(v) for k, v in lighthouse_scores.items()}

    # Group HTML issues by bucket
    bucket_issues: dict[str, list[AuditIssue]] = {b: [] for b in ALL_BUCKETS}
    for issue in html_issues:
        bucket = CATEGORY_BUCKET.get(issue.category)
        if bucket:
            bucket_issues[bucket].append(issue)

    # HTML-derived scores (issue-deduction method)
    scores: dict[str, int] = {}
    for bucket in ALL_BUCKETS:
        scores[bucket] = _deduct(100, bucket_issues[bucket])

    # Blend AI qualitative scores (40% AI, 60% HTML for shared buckets)
    ai_bucket_map = {
        "first_impression": "first_impression",
        "messaging":        "messaging",
        "trust":            "trust",
        "visual_design":    "visual_design",
    }
    for ai_key, bucket in ai_bucket_map.items():
        if ai_key in ai_scores:
            html_score = scores.get(bucket, 100)
            scores[bucket] = int(0.6 * html_score + 0.4 * ai_scores[ai_key])

    # Blend Lighthouse SEO score into seo bucket (50% Lighthouse, 50% HTML detectors)
    # Lighthouse is Google's own data — it gets significant weight
    if "seo" in lighthouse_scores:
        html_seo = scores.get("seo", 100)
        scores["seo"] = int(0.5 * html_seo + 0.5 * lighthouse_scores["seo"])

    # Lighthouse performance score blended into a dedicated bucket
    # Also influences mobile score (performance matters a lot on mobile)
    if "performance" in lighthouse_scores:
        scores["performance"] = lighthouse_scores["performance"]
        # Nudge mobile score down if performance is poor (mobile experience suffers)
        if lighthouse_scores["performance"] < 50:
            scores["mobile"] = int(scores.get("mobile", 100) * 0.8)
        elif lighthouse_scores["performance"] < 75:
            scores["mobile"] = int(scores.get("mobile", 100) * 0.9)

    # Accessibility as standalone bucket if Lighthouse data available
    if "accessibility" in lighthouse_scores:
        scores["accessibility"] = lighthouse_scores["accessibility"]

    # Overall — weighted average across core buckets
    weights = {
        "first_impression": 2,
        "messaging":        2,
        "lead_gen":         3,
        "trust":            2,
        "seo":              2,   # increased now that SEO score is richer
        "mobile":           1,
        "missed_opps":      1,
        "visual_design":    1,
    }
    # Add performance weight if available
    if "performance" in scores:
        weights["performance"] = 2

    total_w  = sum(weights.values())
    weighted = sum(scores.get(b, 100) * w for b, w in weights.items())
    scores["overall"] = max(0, min(100, weighted // total_w))

    return scores


def pretty_category(bucket: str) -> str:
    """Human-readable category name for reports."""
    return {
        "seo":              "SEO",
        "lead_gen":         "Lead Generation",
        "trust":            "Trust & Credibility",
        "mobile":           "Mobile Experience",
        "missed_opps":      "Missed Opportunities",
        "first_impression": "First Impression",
        "messaging":        "Messaging & Copy",
        "visual_design":    "Visual Design",
        "performance":      "Page Performance",
        "accessibility":    "Accessibility",
        "overall":          "Overall",
    }.get(bucket, bucket.replace("_", " ").title())