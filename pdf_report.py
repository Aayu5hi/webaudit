# =============================================================================
# pdf_report.py — Professional PDF audit report
# =============================================================================
"""
Generates a polished, client-ready PDF using ReportLab.

Layout
------
Page 1  -- Cover: prospect name, website, audit date, overall score ring, score cards
Page 2+ -- Executive summary (narrative) -> 21-check checklist -> per-category
           issue tables -> quick wins

Public API
----------
generate_pdf(
    all_issues, scores, qual_report, narrative,
    prospect_name, website_url, agency_name, output_path
) -> None | bytes
"""

from __future__ import annotations

import uuid
from datetime import datetime
from io import BytesIO
from math import pi
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from detectors import (
    AuditIssue,
    CATEGORY_FIRST_IMPRESSION,
    CATEGORY_MESSAGING,
    CATEGORY_LEAD_GEN,
    CATEGORY_TRUST,
    CATEGORY_MOBILE,
    CATEGORY_SEO,
    CATEGORY_MISSED_OPPS,
    CATEGORY_VISUAL_DESIGN,
)
from scoring import pretty_category

# --------------------------------------------------------------------------- #
# Colour palette
# --------------------------------------------------------------------------- #
NAVY      = colors.HexColor("#0D1B2A")
INDIGO    = colors.HexColor("#1B3A6B")
ELECTRIC  = colors.HexColor("#2563EB")
CYAN_BG   = colors.HexColor("#EFF6FF")
SLATE     = colors.HexColor("#64748B")
OFF_WHITE = colors.HexColor("#F8FAFC")
WHITE     = colors.white

RED       = colors.HexColor("#DC2626")
RED_BG    = colors.HexColor("#FEF2F2")
AMBER     = colors.HexColor("#D97706")
AMBER_BG  = colors.HexColor("#FFFBEB")
GREEN     = colors.HexColor("#16A34A")
GREEN_BG  = colors.HexColor("#F0FDF4")
BORDER    = colors.HexColor("#E2E8F0")
LIGHT_BG  = colors.HexColor("#F1F5F9")

PAGE_W, PAGE_H = A4
MARGIN    = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# Canonical display order
DISPLAY_ORDER = [
    CATEGORY_FIRST_IMPRESSION,
    CATEGORY_MESSAGING,
    CATEGORY_LEAD_GEN,
    CATEGORY_TRUST,
    CATEGORY_MOBILE,
    CATEGORY_SEO,
    CATEGORY_MISSED_OPPS,
    CATEGORY_VISUAL_DESIGN,
]

_COVER_BUCKETS_ROW1 = ["first_impression", "messaging", "lead_gen", "trust"]
_COVER_BUCKETS_ROW2 = ["seo", "mobile", "visual_design", "missed_opps"]
_ALL_BUCKETS        = _COVER_BUCKETS_ROW1 + _COVER_BUCKETS_ROW2

# The 21 checks mapped to category for the checklist table
# Each entry: (category, check_number, label, html_or_ai)
TWENTY_ONE_CHECKS = [
    (CATEGORY_FIRST_IMPRESSION, 1,  "Value proposition clear within 5 seconds",       "AI"),
    (CATEGORY_FIRST_IMPRESSION, 2,  "Hero is compelling, not generic",                 "AI"),
    (CATEGORY_FIRST_IMPRESSION, 3,  "Overall feel is credible, not dated",             "AI"),
    (CATEGORY_MESSAGING,        4,  "Copy is benefit-driven, not a service list",      "AI"),
    (CATEGORY_MESSAGING,        5,  "Speaks to customer pain points",                  "AI"),
    (CATEGORY_MESSAGING,        6,  "Has a clear differentiator",                      "AI"),
    (CATEGORY_TRUST,            7,  "Has testimonials, case studies or client logos",  "HTML"),
    (CATEGORY_TRUST,            8,  "Real team / about page with actual people",       "HTML"),
    (CATEGORY_TRUST,            9,  "Proof of results or credibility markers",         "HTML"),
    (CATEGORY_LEAD_GEN,         10, "Clear, prominent call to action",                 "HTML"),
    (CATEGORY_LEAD_GEN,         11, "Enquiry form, booking flow or lead magnet",       "HTML"),
    (CATEGORY_LEAD_GEN,         12, "Contact details easy to find",                    "HTML"),
    (CATEGORY_LEAD_GEN,         13, "Lead capture mechanism actually works",           "HTML"),
    (CATEGORY_MOBILE,           14, "Site is usable and well laid-out on mobile",      "HTML"),
    (CATEGORY_MOBILE,           15, "Buttons tappable, text readable without zooming", "HTML"),
    (CATEGORY_VISUAL_DESIGN,    16, "Design reflects quality of their actual business","AI"),
    (CATEGORY_VISUAL_DESIGN,    17, "Branding is consistent throughout",               "AI"),
    (CATEGORY_VISUAL_DESIGN,    18, "Uses authentic imagery, not generic stock photos","AI"),
    (CATEGORY_MISSED_OPPS,      19, "Has blog / SEO content",                          "HTML"),
    (CATEGORY_MISSED_OPPS,      20, "Has retargeting pixels or lead capture",          "HTML"),
    (CATEGORY_MISSED_OPPS,      21, "Social proof present (established business)",     "HTML"),
]

# Category colour map for the checklist
CATEGORY_COLOURS = {
    CATEGORY_FIRST_IMPRESSION: colors.HexColor("#7C3AED"),
    CATEGORY_MESSAGING:        colors.HexColor("#0891B2"),
    CATEGORY_TRUST:            colors.HexColor("#B45309"),
    CATEGORY_LEAD_GEN:         colors.HexColor("#DC2626"),
    CATEGORY_MOBILE:           colors.HexColor("#16A34A"),
    CATEGORY_VISUAL_DESIGN:    colors.HexColor("#DB2777"),
    CATEGORY_MISSED_OPPS:      colors.HexColor("#EA580C"),
    CATEGORY_SEO:              colors.HexColor("#2563EB"),
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _safe_score(scores: dict, key: str) -> int:
    val = scores.get(key, 0)
    try:
        return max(0, min(100, int(val)))
    except (TypeError, ValueError):
        return 0


def _escape_xml(text: str) -> str:
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _issue_affects_check(issue: AuditIssue, check_label: str) -> bool:
    """
    Roughly determine if a given issue maps to a specific check label.
    Used to mark checks as failing in the 21-check table.
    """
    title_lower = (issue.title or "").lower()
    label_lower = check_label.lower()

    # Extract key words from both and look for overlap
    label_words = set(w for w in label_lower.split() if len(w) > 3)
    for word in label_words:
        if word in title_lower:
            return True
    return False


def _get_failing_check_numbers(all_issues: list, category: str) -> set:
    """Return check numbers that have associated issues for the given category."""
    failing = set()
    cat_issues = [i for i in all_issues if i.category == category]
    if not cat_issues:
        return failing

    for _, num, label, _ in TWENTY_ONE_CHECKS:
        for issue in cat_issues:
            if _issue_affects_check(issue, label):
                failing.add(num)
                break
    return failing


# --------------------------------------------------------------------------- #
# Typography
# --------------------------------------------------------------------------- #
def _mk_styles() -> dict:
    base = getSampleStyleSheet()["Normal"]
    _u   = uuid.uuid4().hex[:8]

    def s(name: str, **kw) -> ParagraphStyle:
        return ParagraphStyle(f"{name}_{_u}", parent=base, **kw)

    return {
        # Cover
        "cov_label":    s("cov_label",  fontName="Helvetica",      fontSize=9,  textColor=colors.HexColor("#93C5FD"), spaceAfter=2, letterSpacing=1.5),
        "cov_title":    s("cov_title",  fontName="Helvetica-Bold",  fontSize=34, leading=40, textColor=WHITE, spaceAfter=4),
        "cov_url":      s("cov_url",    fontName="Helvetica",       fontSize=13, textColor=colors.HexColor("#CBD5E1"), spaceAfter=2),
        "cov_date":     s("cov_date",   fontName="Helvetica",       fontSize=9,  textColor=colors.HexColor("#94A3B8")),
        "cov_tagline":  s("cov_tagline",fontName="Helvetica",       fontSize=11, textColor=colors.HexColor("#93C5FD"), spaceAfter=8),
        # Body
        "h1":           s("h1",         fontName="Helvetica-Bold",  fontSize=15, leading=20, textColor=NAVY, spaceBefore=12, spaceAfter=6),
        "h2":           s("h2",         fontName="Helvetica-Bold",  fontSize=11, leading=15, textColor=INDIGO, spaceBefore=8, spaceAfter=4),
        "body":         s("body",       fontName="Helvetica",       fontSize=9.5, leading=15, textColor=colors.HexColor("#1E293B"), spaceAfter=6),
        "body_indent":  s("body_indent",fontName="Helvetica",       fontSize=9.5, leading=15, textColor=colors.HexColor("#1E293B"), leftIndent=12, spaceAfter=4), #1E293B
        "small":        s("small",      fontName="Helvetica",       fontSize=8.5, leading=13, textColor=SLATE),
        "small_bold":   s("small_bold", fontName="Helvetica-Bold",  fontSize=8.5, leading=13, textColor=SLATE),
        "score_num":    s("score_num",  fontName="Helvetica-Bold",  fontSize=26, leading=30, alignment=TA_CENTER),
        "score_lbl":    s("score_lbl",  fontName="Helvetica",       fontSize=8,  leading=11, textColor=SLATE, alignment=TA_CENTER),
        "tag":          s("tag",        fontName="Helvetica-Bold",  fontSize=7.5, alignment=TA_CENTER),
        "qw_num":       s("qw_num",     fontName="Helvetica-Bold",  fontSize=20, textColor=ELECTRIC, alignment=TA_CENTER),
        "footer":       s("footer",     fontName="Helvetica",       fontSize=7.5, textColor=SLATE),
        "tbl_hdr":      s("tbl_hdr",    fontName="Helvetica-Bold",  fontSize=8.5, textColor=WHITE),
        "check_cat":    s("check_cat",  fontName="Helvetica-Bold",  fontSize=8,  textColor=WHITE, alignment=TA_CENTER),
        "check_num":    s("check_num",  fontName="Helvetica-Bold",  fontSize=8,  textColor=SLATE, alignment=TA_CENTER),
        "check_label":  s("check_label",fontName="Helvetica",       fontSize=8.5,textColor=colors.HexColor("#1E293B")),
        "check_pass":   s("check_pass", fontName="Helvetica-Bold",  fontSize=9,  textColor=GREEN, alignment=TA_CENTER),
        "check_fail":   s("check_fail", fontName="Helvetica-Bold",  fontSize=9,  textColor=RED,   alignment=TA_CENTER),
        "check_na":     s("check_na",   fontName="Helvetica",       fontSize=9,  textColor=SLATE, alignment=TA_CENTER),
        "stat_num":     s("stat_num",   fontName="Helvetica-Bold",  fontSize=22, leading=26, alignment=TA_CENTER, textColor=ELECTRIC),
        "stat_lbl":     s("stat_lbl",   fontName="Helvetica",       fontSize=7.5,alignment=TA_CENTER, textColor=SLATE),
        "callout":      s("callout",    fontName="Helvetica",       fontSize=9,  leading=14, textColor=INDIGO, leftIndent=10),
        "callout_bold": s("callout_bold",fontName="Helvetica-Bold", fontSize=9,  leading=14, textColor=INDIGO, leftIndent=10),
    }


# --------------------------------------------------------------------------- #
# Document template
# --------------------------------------------------------------------------- #
class AuditDoc(BaseDocTemplate):
    def __init__(self, buf, prospect_name, website_url, agency_name, **kw):
        super().__init__(buf, **kw)
        self.prospect_name = prospect_name
        self.website_url   = website_url
        self.agency_name   = agency_name

        body = Frame(
            MARGIN, MARGIN + 8 * mm,
            CONTENT_W, PAGE_H - 2 * MARGIN - 20 * mm,
            id="body",
        )
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[body], onPage=self._cover_bg),
            PageTemplate(id="main",  frames=[body], onPage=self._main_bg),
        ])

    def _cover_bg(self, canvas, doc):
        c = canvas
        c.saveState()
        # Deep navy background
        c.setFillColor(NAVY)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        # Layered accent bands
        c.setFillColor(INDIGO)
        p = c.beginPath()
        p.moveTo(0, PAGE_H * 0.44)
        p.lineTo(PAGE_W, PAGE_H * 0.48)
        p.lineTo(PAGE_W, PAGE_H * 0.46)
        p.lineTo(0, PAGE_H * 0.42)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        # Electric accent bar
        c.setFillColor(ELECTRIC)
        c.rect(0, PAGE_H * 0.415, PAGE_W, 3.5, fill=1, stroke=0)
        # Side accent bar
        c.setFillColor(ELECTRIC)
        c.rect(0, 0, 5, PAGE_H, fill=1, stroke=0)
        # Bottom band
        c.setFillColor(colors.HexColor("#0A1628"))
        c.rect(0, 0, PAGE_W, PAGE_H * 0.09, fill=1, stroke=0)
        # Footer
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.drawString(MARGIN, 10 * mm, f"Prepared by {doc.agency_name}")
        c.drawRightString(PAGE_W - MARGIN, 10 * mm, datetime.now().strftime("%B %d, %Y"))
        c.restoreState()

    def _main_bg(self, canvas, doc):
        c = canvas
        c.saveState()
        c.setFillColor(OFF_WHITE)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        # Left accent bar
        c.setFillColor(ELECTRIC)
        c.rect(0, 0, 4, PAGE_H, fill=1, stroke=0)
        # Top nav bar
        c.setFillColor(NAVY)
        c.rect(0, PAGE_H - 10 * mm, PAGE_W, 10 * mm, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(WHITE)
        c.drawString(MARGIN, PAGE_H - 6.5 * mm, f"Website Audit -- {doc.prospect_name}")
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#93C5FD"))
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 6.5 * mm, doc.website_url)
        # Footer
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.line(MARGIN, 10 * mm, PAGE_W - MARGIN, 10 * mm)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(SLATE)
        c.drawString(MARGIN, 6.5 * mm, f"Confidential -- Prepared by {doc.agency_name}")
        c.drawRightString(PAGE_W - MARGIN, 6.5 * mm, f"Page {doc.page}")
        c.restoreState()


# --------------------------------------------------------------------------- #
# Score cards
# --------------------------------------------------------------------------- #
def _score_color(score: int):
    if score >= 75: return GREEN,  GREEN_BG
    if score >= 50: return AMBER,  AMBER_BG
    return RED, RED_BG


def _score_card(label: str, score: int, st: dict) -> Table:
    fg, bg = _score_color(score)
    num_st = ParagraphStyle(
        f"sn_{label}_{uuid.uuid4().hex[:6]}",
        parent=st["score_num"],
        textColor=fg,
    )
    rows = [
        [Paragraph(str(score),  num_st)],
        [Paragraph("/ 100",     st["score_lbl"])],
        [Paragraph(_escape_xml(label), st["score_lbl"])],
    ]
    t = Table(rows, colWidths=[36 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("BOX",           (0, 0), (-1, -1), 1.5, fg),
        ("TOPPADDING",    (0, 0), (-1,  0), 10),
        ("BOTTOMPADDING", (0,-1), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
    ]))
    return t


def _score_row(scores: dict, st: dict, buckets: list) -> Table:
    cards  = []
    col_ws = []
    for b in buckets:
        score = _safe_score(scores, b)
        cards.append(_score_card(pretty_category(b), score, st))
        col_ws.append(38 * mm)
    if not cards:
        return Table([[Paragraph("--", st["body"])]])
    t = Table([cards], colWidths=col_ws)
    t.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
    ]))
    return t


# --------------------------------------------------------------------------- #
# Overall score gauge (drawn on cover with canvas)
# --------------------------------------------------------------------------- #
def _draw_score_ring(canvas, cx, cy, score, radius=28):
    """Draw a circular score ring directly on the canvas."""
    fg, _ = _score_color(score)
    bg_col = colors.HexColor("#1B3A6B")

    # Background ring
    canvas.setStrokeColor(bg_col)
    canvas.setLineWidth(6)
    canvas.circle(cx, cy, radius, fill=0, stroke=1)

    # Score arc (approximated with multiple short arcs)
    angle = 360 * score / 100
    canvas.setStrokeColor(fg)
    canvas.setLineWidth(6)
    # Draw arc from top (90deg) clockwise
    from reportlab.graphics.shapes import Drawing, ArcPath, String
    start_angle = 90
    end_angle   = 90 - angle  # clockwise

    # Use path to draw arc
    p = canvas.beginPath()
    # ReportLab arcs go counter-clockwise, so we negate
    canvas.arc(cx - radius, cy - radius, cx + radius, cy + radius,
               startAng=90, extent=-angle)
    canvas.drawPath(p, stroke=1, fill=0)

    # Score text
    canvas.setFont("Helvetica-Bold", 22)
    canvas.setFillColor(WHITE)
    canvas.drawCentredString(cx, cy - 4, str(score))

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#94A3B8"))
    canvas.drawCentredString(cx, cy - 16, "/ 100")


# --------------------------------------------------------------------------- #
# 21-check summary table
# --------------------------------------------------------------------------- #
def _build_checklist_table(all_issues: list, st: dict) -> Table:
    """
    Render all 21 checks as a colour-coded pass/fail table.
    Groups checks by category with a coloured category header row.
    """
    # Determine which checks are failing based on issue titles
    failing_checks = set()
    for issue in all_issues:
        for _, num, label, _ in TWENTY_ONE_CHECKS:
            if issue.category in (CATEGORY_FIRST_IMPRESSION, CATEGORY_MESSAGING,
                                   CATEGORY_VISUAL_DESIGN) and issue.category == issue.category:
                # For AI categories, match by category + partial title
                if _issue_affects_check(issue, label):
                    failing_checks.add(num)
            elif _issue_affects_check(issue, label):
                failing_checks.add(num)

    rows     = []
    col_w    = [8 * mm, CONTENT_W - 8 * mm - 16 * mm - 20 * mm, 16 * mm, 20 * mm]

    # Header row
    rows.append([
        Paragraph("#",        st["tbl_hdr"]),
        Paragraph("CHECK",    st["tbl_hdr"]),
        Paragraph("STATUS",   st["tbl_hdr"]),
        Paragraph("METHOD",   st["tbl_hdr"]),
    ])

    prev_cat   = None
    row_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("GRID",       (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 7),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 7),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]

    row_idx = 1  # track row index for styling

    for cat_name, num, label, method in TWENTY_ONE_CHECKS:
        # Category divider row
        if cat_name != prev_cat:
            cat_color = CATEGORY_COLOURS.get(cat_name, INDIGO)
            cat_p     = Paragraph(_escape_xml(cat_name.upper()), st["check_cat"])
            rows.append(["", cat_p, "", ""])
            row_styles.append(("BACKGROUND",  (0, row_idx), (-1, row_idx), cat_color))
            row_styles.append(("SPAN",        (0, row_idx), (-1, row_idx)))
            row_styles.append(("ALIGN",       (0, row_idx), (-1, row_idx), "LEFT"))
            row_styles.append(("LEFTPADDING", (0, row_idx), (-1, row_idx), 10))
            row_idx += 1
            prev_cat = cat_name

        # Check row
        is_fail = num in failing_checks
        status_text = "FAIL" if is_fail else "PASS"
        status_st   = st["check_fail"] if is_fail else st["check_pass"]
        bg = RED_BG if is_fail else (WHITE if row_idx % 2 == 0 else OFF_WHITE)

        rows.append([
            Paragraph(str(num), st["check_num"]),
            Paragraph(_escape_xml(label), st["check_label"]),
            Paragraph(status_text, status_st),
            Paragraph(method, st["check_na"]),
        ])
        row_styles.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))
        if is_fail:
            row_styles.append(("TEXTCOLOR", (1, row_idx), (1, row_idx), RED))
        row_idx += 1

    t = Table(rows, colWidths=col_w, repeatRows=1, splitByRow=True)
    t.setStyle(TableStyle(row_styles))
    return t


# --------------------------------------------------------------------------- #
# Issues table
# --------------------------------------------------------------------------- #
PRIORITY_META = {
    "HIGH":   (RED,   RED_BG),
    "MEDIUM": (AMBER, AMBER_BG),
    "LOW":    (GREEN, GREEN_BG),
}


def _issues_table(issues: list, st: dict) -> Table:
    header = [
        Paragraph("ISSUE",    st["tbl_hdr"]),
        Paragraph("PRIORITY", st["tbl_hdr"]),
    ]
    rows = [header]

    for issue in issues:
        fg, _bg = PRIORITY_META.get(issue.severity, PRIORITY_META["MEDIUM"])
        tag_st  = ParagraphStyle(
            f"tag_{uuid.uuid4().hex[:6]}",
            parent=st["tag"],
            textColor=fg,
        )
        title_text = _escape_xml(issue.title or "")
        desc_text  = _escape_xml((issue.description or "")[:800])
        title_para = Paragraph(
            f"<b>{title_text}</b><br/>"
            f'<font size="8.5" color="#64748B">{desc_text}</font>',
            st["body"],
        )
        rows.append([
            title_para,
            Paragraph(_escape_xml(issue.severity or "MEDIUM"), tag_st),
        ])

    col_w = [CONTENT_W - 22 * mm, 22 * mm]
    t = Table(rows, colWidths=col_w, repeatRows=1, splitByRow=True)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1,  0), INDIGO),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, OFF_WHITE]),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 9),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 9),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


# --------------------------------------------------------------------------- #
# Stats summary bar
# --------------------------------------------------------------------------- #
def _stats_bar(all_issues: list, st: dict) -> Table:
    """Render a visual issue count summary row."""
    high   = sum(1 for i in all_issues if i.severity == "HIGH")
    medium = sum(1 for i in all_issues if i.severity == "MEDIUM")
    low    = sum(1 for i in all_issues if i.severity == "LOW")
    total  = len(all_issues)

    def _cell(num, label, fg):
        num_st = ParagraphStyle(
            f"sbar_{label}_{uuid.uuid4().hex[:6]}",
            parent=st["stat_num"], textColor=fg,
        )
        return [Paragraph(str(num), num_st), Paragraph(label, st["stat_lbl"])]

    cells = [
        _cell(total,  "TOTAL ISSUES",  NAVY),
        _cell(high,   "HIGH PRIORITY", RED),
        _cell(medium, "MEDIUM",        AMBER),
        _cell(low,    "LOW",           GREEN),
    ]
    col_w = [CONTENT_W / 4] * 4
    inner_tables = []
    for cell in cells:
        inner = Table([[c] for c in cell])
        inner.setStyle(TableStyle([
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        inner_tables.append(inner)

    t = Table([inner_tables], colWidths=col_w)
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), CYAN_BG),
        ("BOX",         (0, 0), (-1, -1), 1, ELECTRIC),
        ("LINEAFTER",   (0, 0), (2, 0),   0.5, BORDER),
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


# --------------------------------------------------------------------------- #
# Quick wins
# --------------------------------------------------------------------------- #
def _quick_wins_table(wins: list, st: dict) -> Table:
    rows = []
    for i, win in enumerate(wins[:3], 1):
        if not win:
            continue
        rows.append([
            Paragraph(str(i), st["qw_num"]),
            Paragraph(_escape_xml(win), st["body"]),
        ])
    if not rows:
        return Table([[Paragraph("No quick wins identified.", st["body"])]])
    t = Table(rows, colWidths=[14 * mm, CONTENT_W - 14 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), CYAN_BG),
        ("BOX",           (0, 0), (-1, -1), 1.5, ELECTRIC),
        ("LINEBELOW",     (0, 0), (-1, -2), 0.4, colors.HexColor("#BFDBFE")),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), ( 0, -1), 10),
        ("LEFTPADDING",   (1, 0), ( 1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


# --------------------------------------------------------------------------- #
# Category description helper
# --------------------------------------------------------------------------- #
CATEGORY_CONTEXT = {
    CATEGORY_FIRST_IMPRESSION: (
        "A visitor decides whether to stay or leave within 5 seconds of landing. "
        "First impression issues directly reduce the number of prospects who even "
        "read the offer, making them the most upstream conversion problem to fix."
    ),
    CATEGORY_MESSAGING: (
        "Messaging determines whether visitors feel understood and motivated to act. "
        "Benefit-driven copy that speaks to pain points consistently outperforms "
        "service lists -- this is a high-leverage, low-cost area to improve."
    ),
    CATEGORY_TRUST: (
        "Trust signals are the primary reason a qualified visitor either converts "
        "or leaves to check competitors. For service businesses, social proof, "
        "real people, and proof of results are non-negotiable conversion requirements."
    ),
    CATEGORY_LEAD_GEN: (
        "Lead generation issues directly translate to lost enquiries. Every friction "
        "point -- missing CTAs, broken forms, hidden contact details -- reduces "
        "the number of prospects who reach out, even when they are ready to buy."
    ),
    CATEGORY_MOBILE: (
        "Over 60% of web traffic is now on mobile devices. Mobile experience issues "
        "do not just frustrate visitors -- they also reduce Google search rankings, "
        "cutting the flow of new visitors to the site."
    ),
    CATEGORY_SEO: (
        "SEO issues reduce the visibility of the site in search results, limiting "
        "the number of qualified prospects who discover the business organically. "
        "Technical SEO fixes are typically straightforward and have a compounding "
        "effect on traffic over time."
    ),
    CATEGORY_MISSED_OPPS: (
        "Missed opportunity issues represent easy wins that are not yet being "
        "captured. Retargeting pixels, content marketing, and sitewide social proof "
        "are all high-ROI levers that cost little to implement but deliver "
        "meaningful long-term returns."
    ),
    CATEGORY_VISUAL_DESIGN: (
        "Visual design is the silent salesperson. A design that does not reflect "
        "the quality of the actual business undermines all other marketing efforts "
        "-- no matter how good the product or service, a dated or inconsistent "
        "site creates doubt at the exact moment a decision is being made."
    ),
}


# --------------------------------------------------------------------------- #
# Page builders
# --------------------------------------------------------------------------- #

def _cwv_panel(cwv: dict, lighthouse: dict, st: dict) -> Table:
    """Render a compact Core Web Vitals + Lighthouse scores strip for the cover."""

    def _cwv_cell(label: str, value: str, status: str) -> list:
        """status: 'good' | 'warn' | 'poor'"""
        colour = {
            "good": colors.HexColor("#16A34A"),
            "warn": colors.HexColor("#D97706"),
            "poor": colors.HexColor("#DC2626"),
        }.get(status, SLATE)

        val_st = ParagraphStyle(
            f"cwv_val_{label}_{uuid.uuid4().hex[:4]}",
            parent=st["stat_num"],
            textColor=colour,
            fontSize=14,
            leading=17,
        )
        return [
            Paragraph(_escape_xml(value), val_st),
            Paragraph(_escape_xml(label), st["stat_lbl"]),
        ]

    cells = []

    if cwv.get("lcp_ms"):
        lcp = cwv["lcp_ms"] / 1000
        status = "good" if lcp <= 2.5 else ("warn" if lcp <= 4.0 else "poor")
        cells.append(_cwv_cell("LCP", f"{lcp:.1f}s", status))

    if cwv.get("tbt_ms") is not None:
        tbt = cwv["tbt_ms"]
        status = "good" if tbt <= 200 else ("warn" if tbt <= 600 else "poor")
        cells.append(_cwv_cell("TBT", f"{tbt}ms", status))

    if cwv.get("cls") is not None:
        try:
            cls = float(cwv["cls"])
            status = "good" if cls <= 0.1 else ("warn" if cls <= 0.25 else "poor")
            cells.append(_cwv_cell("CLS", f"{cls:.2f}", status))
        except (TypeError, ValueError):
            pass

    for lh_key, label in [("performance", "Perf"), ("seo", "SEO"), ("accessibility", "A11y")]:
        if lh_key in lighthouse:
            val = lighthouse[lh_key]
            status = "good" if val >= 90 else ("warn" if val >= 50 else "poor")
            cells.append(_cwv_cell(f"LH {label}", f"{val}", status))

    if not cells:
        return Table([[Paragraph("", st["body"])]])

    # Build inner cell tables
    inner_tables = []
    for cell in cells:
        inner = Table([[c] for c in cell])
        inner.setStyle(TableStyle([
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        inner_tables.append(inner)

    col_w = [CONTENT_W / len(inner_tables)] * len(inner_tables)
    t = Table([inner_tables], colWidths=col_w)
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), colors.HexColor("#0F2540")),
        ("BOX",         (0, 0), (-1, -1), 1, ELECTRIC),
        ("LINEAFTER",   (0, 0), (-2, 0),  0.5, colors.HexColor("#1B3A6B")),
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _cover_story(
    prospect_name: str,
    website_url: str,
    scores: dict,
    st: dict,
    cwv: Optional[dict] = None,
    lighthouse: Optional[dict] = None,
) -> list:
    story = []
    story.append(Spacer(1, PAGE_H * 0.07))
    story.append(Paragraph("WEBSITE AUDIT REPORT", st["cov_label"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(_escape_xml(prospect_name), st["cov_title"]))
    story.append(Paragraph(_escape_xml(website_url),   st["cov_url"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Comprehensive 21-Point Conversion Audit", st["cov_tagline"]))
    story.append(Spacer(1, PAGE_H * 0.04))

    story.append(_score_row(scores, st, _COVER_BUCKETS_ROW1))
    story.append(Spacer(1, 8))
    story.append(_score_row(scores, st, _COVER_BUCKETS_ROW2))

    # Core Web Vitals / Lighthouse strip — shown only if PSI data available
    if (cwv and any(cwv.values())) or lighthouse:
        story.append(Spacer(1, 10))
        story.append(_cwv_panel(cwv or {}, lighthouse or {}, st))

    story.append(Spacer(1, PAGE_H * 0.04))
    story.append(Paragraph(
        f"Prepared {datetime.now().strftime('%B %d, %Y')}  •  Powered by Google Lighthouse",
        st["cov_date"],
    ))
    return story


def _report_story(
    all_issues: list,
    scores: dict,
    narrative: str,
    quick_wins: list,
    st: dict,
    cwv: Optional[dict] = None,
    lighthouse: Optional[dict] = None,
) -> list:
    story = []
    story.append(Spacer(1, 4 * mm))

    # ── Executive Summary ──────────────────────────────────────────────────
    story.append(Paragraph("Executive Summary", st["h1"]))
    story.append(HRFlowable(width="100%", thickness=2, color=ELECTRIC, spaceAfter=10))

    if narrative:
        story.append(Paragraph(_escape_xml(narrative), st["body"]))
    else:
        story.append(Paragraph("No narrative summary was generated for this audit.", st["body"]))

    story.append(Spacer(1, 6))

    # ── Issue count stats bar ──────────────────────────────────────────────
    if all_issues:
        story.append(_stats_bar(all_issues, st))
        story.append(Spacer(1, 10))

    # ── Core Web Vitals / Lighthouse Section ───────────────────────────────
    if (cwv and any(v for v in cwv.values() if v is not None)) or lighthouse:
        story.append(Paragraph("Core Web Vitals & Lighthouse Scores", st["h1"]))
        story.append(HRFlowable(width="100%", thickness=1.5, color=ELECTRIC, spaceAfter=6))
        story.append(Paragraph(
            "Measured by Google's own Lighthouse engine via the PageSpeed Insights API. "
            "Core Web Vitals (LCP, TBT, CLS) are confirmed Google ranking signals. "
            "Lighthouse scores cover Performance, SEO technical checks, and Accessibility — "
            "all assessed on mobile, which matches Google's mobile-first indexing.",
            st["small"],
        ))
        story.append(Spacer(1, 6))
        story.append(_cwv_panel(cwv or {}, lighthouse or {}, st))
        story.append(Spacer(1, 4))

        # Threshold legend
        legend_data = [
            [
                Paragraph('<font color="#16A34A">■</font> Good (target range)', st["small"]),
                Paragraph('<font color="#D97706">■</font> Needs Improvement', st["small"]),
                Paragraph('<font color="#DC2626">■</font> Poor', st["small"]),
            ]
        ]
        legend_t = Table(legend_data, colWidths=[CONTENT_W / 3] * 3)
        legend_t.setStyle(TableStyle([
            ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(legend_t)
        story.append(Spacer(1, 10))

    # ── 21-Check Summary Table ─────────────────────────────────────────────
    story.append(Paragraph("21-Point Audit Checklist", st["h1"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=ELECTRIC, spaceAfter=8))
    story.append(Paragraph(
        "Every website is assessed against the same 21 checks across 8 categories. "
        "HTML checks are detected automatically from page code; AI checks are assessed "
        "by a trained language model reviewing content, copy, and visual design.",
        st["small"],
    ))
    story.append(Spacer(1, 6))
    story.append(_build_checklist_table(all_issues, st))
    story.append(Spacer(1, 10))

    # ── Issues by category ─────────────────────────────────────────────────
    story.append(Paragraph("Detailed Findings", st["h1"]))
    story.append(HRFlowable(width="100%", thickness=2, color=ELECTRIC, spaceAfter=10))

    grouped: dict = {}
    for issue in all_issues:
        grouped.setdefault(issue.category, []).append(issue)

    seen_cats = set()
    ordered_cats = DISPLAY_ORDER + [c for c in grouped if c not in DISPLAY_ORDER]

    for cat in ordered_cats:
        if cat not in grouped or cat in seen_cats:
            continue
        seen_cats.add(cat)

        issues_in_cat = sorted(
            grouped[cat],
            key=lambda i: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(i.severity, 3),
        )

        # Category context blurb
        context_text = CATEGORY_CONTEXT.get(cat, "")
        cat_color    = CATEGORY_COLOURS.get(cat, INDIGO)

        # Build a coloured category title block
        cat_title_st = ParagraphStyle(
            f"cathead_{cat}_{uuid.uuid4().hex[:6]}",
            parent=st["h1"],
            textColor=cat_color,
            spaceBefore=16,
            spaceAfter=4,
        )

        section_elems = [
            Spacer(1, 4),
            Paragraph(_escape_xml(cat), cat_title_st),
            HRFlowable(width="100%", thickness=1, color=cat_color, spaceAfter=5),
        ]
        if context_text:
            section_elems.append(Paragraph(_escape_xml(context_text), st["small"]))
            section_elems.append(Spacer(1, 5))

        section_elems.append(_issues_table(issues_in_cat, st))

        if len(issues_in_cat) <= 3:
            story.append(KeepTogether(section_elems))
        else:
            story.extend(section_elems)

    if not all_issues:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "No significant issues were detected -- excellent work!",
            st["body"],
        ))

    # ── Quick Wins ─────────────────────────────────────────────────────────
    valid_wins = [w for w in (quick_wins or []) if w and isinstance(w, str)]
    if valid_wins:
        qw_block = [
            Spacer(1, 10),
            Paragraph("Quick Wins This Week", st["h1"]),
            HRFlowable(width="100%", thickness=2, color=ELECTRIC, spaceAfter=6),
            Paragraph(
                "Three high-impact, low-effort improvements that can be actioned immediately "
                "without a full website rebuild -- each one has a direct impact on leads and revenue.",
                st["small"],
            ),
            Spacer(1, 5),
            _quick_wins_table(valid_wins, st),
        ]
        story.append(KeepTogether(qw_block))

    # ── What Happens Next ──────────────────────────────────────────────────
    next_block = [
        Spacer(1, 12),
        Paragraph("What Happens Next?", st["h1"]),
        HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=6),
        Paragraph(
            "This audit is a starting point, not an end point. Every issue identified here "
            "has a clear solution, and most can be addressed without a full website rebuild. "
            "The quick wins listed above are designed to have an immediate impact -- "
            "each one removes friction from the path between a prospect and an enquiry.",
            st["body"],
        ),
        Paragraph(
            "The highest-priority improvements are those in the Lead Generation and Trust "
            "categories. Fixing these directly increases the percentage of visitors who "
            "convert into enquiries, which means more revenue from the same traffic.",
            st["body"],
        ),
        Spacer(1, 6),
        Paragraph(
            "Prioritisation framework: address HIGH severity issues first, then MEDIUM. "
            "LOW severity issues are refinements -- they matter, but they will not move "
            "the needle the way the higher-priority fixes will.",
            st["callout"],
        ),
    ]
    story.append(KeepTogether(next_block))

    return story


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def generate_pdf(
    all_issues: list,
    scores: dict,
    quick_wins: list,
    narrative: str,
    prospect_name: str,
    website_url: str,
    agency_name: str = "Your Agency",
    output_path: Optional[str] = None,
    cwv: Optional[dict] = None,
    lighthouse: Optional[dict] = None,
) -> Optional[bytes]:
    """
    Render the complete audit as a PDF.

    Parameters
    ----------
    all_issues    : combined list of AuditIssue from detectors + AI
    scores        : {bucket: 0-100} from scoring.score_all()
    quick_wins    : list of up to 3 quick-win strings
    narrative     : prose narrative from ai_analysis.generate_narrative_report()
    prospect_name : company name shown on cover
    website_url   : audited URL
    agency_name   : preparer shown in header/footer
    output_path   : save to disk if given; otherwise return bytes
    cwv           : Core Web Vitals dict {lcp_ms, cls, tbt_ms} from PSI
    lighthouse    : Lighthouse scores {performance, seo, accessibility} 0-100
    """
    st  = _mk_styles()
    buf = output_path or BytesIO()

    doc = AuditDoc(
        buf,
        prospect_name = prospect_name,
        website_url   = website_url,
        agency_name   = agency_name,
        pagesize      = A4,
        leftMargin    = MARGIN,
        rightMargin   = MARGIN,
        topMargin     = MARGIN + 12 * mm,
        bottomMargin  = MARGIN + 8 * mm,
    )

    cover  = [NextPageTemplate("cover")] + _cover_story(
        prospect_name, website_url, scores, st, cwv=cwv, lighthouse=lighthouse
    )
    report = [NextPageTemplate("main")]  + _report_story(
        all_issues, scores, narrative, quick_wins, st, cwv=cwv, lighthouse=lighthouse
    )

    doc.build(cover + report)

    if output_path:
        return None
    buf.seek(0)
    return buf.read()