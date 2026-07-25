#!/usr/bin/env python3
# =============================================================================
# main.py — Web Audit Agent entry point
# =============================================================================
"""
Orchestrates the full audit pipeline:

  1. Async crawl      — fetch homepage + up to 4 targeted pages concurrently
  2. Extract          — parse each page into structured PageData
  3. HTML checks      — run all HTML-based checks (SEO, CTA, trust, mobile, etc.)
  4. Technical SEO    — Lighthouse/PSI + advertools + extruct + redirect chains
  5. Screenshot       — capture hero fold of homepage (optional, requires playwright)
  6. AI analysis      — qualitative + visual checks in one API call
  7. Score            — blend HTML + Lighthouse + AI scores per category
  8. Report           — generate prose narrative via AI
  9. PDF              — produce client-ready PDF report

Usage
-----
    python main.py
    # then enter the URL when prompted
"""
# ## Tech Stack

# **Language & Runtime**
# Python 3 (async-first with `asyncio`)

# **Web Crawling & Scraping**
# - `aiohttp` — async HTTP fetching for concurrent page crawling
# - `BeautifulSoup4` — HTML parsing and structured data extraction
# - `Playwright` — headless Chromium browser for hero screenshots

# **AI & LLM**
# - `openai` Python SDK — API client
# - `python-dotenv` — environment variable management for API keys

# **PDF Generation**
# - `ReportLab` — full PDF layout engine (cover pages, tables, score cards, charts)

# **Optional/Enhanced SEO**
# - `advertools` — robots.txt and XML sitemap parsing
# - `extruct` — deep structured data extraction (JSON-LD, OpenGraph, Twitter Cards, Microdata)
# - Google PageSpeed Insights API — Lighthouse scores via HTTP

# ## Models Used

# | Model | Where Used | Purpose |
# | `gpt-4o` | `ai_analysis.py` → `run_qualitative_analysis()` | Primary qualitative audit — evaluates 9 subjective checks (first impression, messaging, visual design) and optionally analyzes the hero screenshot via vision |
# | `gpt-4o-mini` | `ai_analysis.py` → `generate_narrative_report()` | Generates the 350–450 word prose narrative for the PDF — cheaper model used since no vision is needed |
# | `gpt-4o-mini` | `ai_report.py` → `generate_report()` | Legacy report builder (appears to be an older module, largely superseded by `ai_analysis.py`) |

# Summary: `gpt-4o` handles anything requiring vision or nuanced qualitative judgment, while `gpt-4o-mini` handles pure text generation tasks where cost efficiency matters more than top-tier capability.

import asyncio
import os
import sys
from urllib.parse import urlparse

import aiohttp

#Internal modules 
from fetcher        import fetch_all_target_pages, check_broken_links, PageResult
from extractors     import extract_page_data, PageData
from detectors      import (
    AuditIssue,
    seo_check,
    lead_gen_check,
    trust_check,
    mobile_check,
    missed_opps_check,
    broken_links_check,
)
from seo_technical  import run_technical_seo, TechnicalSEOReport
from screenshot     import capture_hero
from ai_analysis    import run_qualitative_analysis, generate_narrative_report
from scoring        import score_all, pretty_category
from pdf_report     import generate_pdf
from config         import REPORTS_DIR, PSI_API_KEY
from site_classifier import classify_site

# Helpers

def _print_separator(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _print_issues(issues: list[AuditIssue]) -> None:
    if not issues:
        print("  ✓ No issues detected.")
        return
    for issue in sorted(issues, key=lambda i: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[i.severity]):
        icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(issue.severity, "•")
        print(f"  {icon} [{issue.severity}] {issue.category}: {issue.title}")
        print(f"       {issue.description}")


def _print_scores(scores: dict[str, int]) -> None:
    _print_separator()
    print("SCORES")
    _print_separator()
    display_order = [
        "first_impression", "messaging", "lead_gen", "trust",
        "seo", "performance", "accessibility", "mobile",
        "visual_design", "missed_opps", "overall",
    ]
    for bucket in display_order:
        if bucket not in scores:
            continue
        score = scores[bucket]
        bar   = "█" * (score // 5) + "░" * (20 - score // 5)
        label = pretty_category(bucket).ljust(22)
        print(f"  {label} {bar} {score:3d}/100")
    _print_separator()


# --------------------------------------------------------------------------- #
# Async pipeline
# --------------------------------------------------------------------------- #

async def _run_audit(url: str) -> tuple[list[AuditIssue], dict[str, int], list[str], str, TechnicalSEOReport] | None:
    """
    Full async pipeline.
    Returns (all_issues, scores, quick_wins, narrative, tech_seo_report)
    or None on fatal error.
    """
    domain = urlparse(url).netloc

    # ── Step 1: Async crawl ────────────────────────────────────────────────
    print("\n[1/8] Crawling website …")
    pages: dict[str, PageResult] = await fetch_all_target_pages(url)

    if not pages:
        print("  ✗ Could not fetch the homepage. Check the URL and your internet connection.")
        return None

    # ── Step 2: Extract structured data ───────────────────────────────────
    print("[2/8] Extracting page data …")
    page_data: dict[str, PageData] = {}
    for page_type, result in pages.items():
        pd = extract_page_data(result, page_type=page_type)
        page_data[page_type] = pd

    homepage_data   = page_data["homepage"]
    homepage_result = pages["homepage"]

    # ── Step 2b: Classify site type ────────────────────────────────────────
    site_classification = classify_site(
        homepage_html = homepage_result.html.lower(),
        homepage_text = homepage_data.text,
        all_links     = homepage_data.links,
    )
    site_type = site_classification.site_type
    print(f"  Site type detected: {site_classification.label} (confidence: {site_classification.confidence})")


    # ── Step 3: HTML detector checks ──────────────────────────────────────
    print("[3/8] Running HTML checks …")
    all_issues: list[AuditIssue] = []

    for page_type, pd in page_data.items():
        all_issues.extend(seo_check(pd))
        all_issues.extend(lead_gen_check(pd))
        all_issues.extend(trust_check(pd))
        all_issues.extend(mobile_check(pd))

    # Missed opportunities — assessed across all pages
    all_issues.extend(missed_opps_check(homepage_data, page_data))

    # Broken links — check homepage links async
    print("    Checking for broken links …")
    timeout   = aiohttp.ClientTimeout(total=8)
    connector = aiohttp.TCPConnector(ssl=False, limit=10)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        broken = await check_broken_links(session, homepage_data.links, domain)
    all_issues.extend(broken_links_check(broken, homepage_data.url))

    # ── Step 4: Technical SEO (PSI + advertools + extruct + redirects) ────
    print("[4/8] Running technical SEO analysis …")
    if PSI_API_KEY:
        print(f"    Using PSI API key (high quota mode)")
    else:
        print("    No PSI_API_KEY set — using keyless mode (may be rate-limited).")
        print("    Set PSI_API_KEY in config.py for reliable production use.")

    tech_report: TechnicalSEOReport = await run_technical_seo(
        url           = url,
        homepage_html = homepage_result.html,
        homepage_data = homepage_data,
        api_key       = PSI_API_KEY,
    )
    all_issues.extend(tech_report.issues)

    # Deduplicate: HTML seo_check() and Lighthouse may flag the same things
    # (e.g. missing title). Keep the Lighthouse version — it's more authoritative.
    seen_titles: set[str] = set()
    unique_issues: list[AuditIssue] = []

    # Process Lighthouse/technical issues first so they "win" deduplication
    technical_titles = {issue.title for issue in tech_report.issues}
    html_only = [i for i in all_issues if i not in tech_report.issues]

    # Add technical issues first
    for issue in tech_report.issues:
        key = f"{issue.category}:{issue.title}"
        if key not in seen_titles:
            seen_titles.add(key)
            unique_issues.append(issue)

    # Then add HTML issues that aren't duplicated
    for issue in html_only:
        # Skip HTML SEO issues that Lighthouse already covered better
        if issue.category == "SEO" and any(
            _titles_overlap(issue.title, t) for t in technical_titles
        ):
            continue
        key = f"{issue.category}:{issue.title}"
        if key not in seen_titles:
            seen_titles.add(key)
            unique_issues.append(issue)

    all_issues = unique_issues

    # ── Step 5: Hero screenshot ────────────────────────────────────────────
    print("[5/8] Capturing hero screenshot …")
    hero_b64 = await capture_hero(url)
    if hero_b64:
        print("    Hero captured.")
    else:
        print("    Skipping visual analysis (playwright not available).")

    # ── Step 6: AI qualitative + visual analysis ───────────────────────────
    print("[6/8] Running AI qualitative analysis …")
    all_page_texts = {pt: pd.text for pt, pd in page_data.items()}
    qual_report    = run_qualitative_analysis(
        homepage_text  = homepage_data.text,
        all_page_texts = all_page_texts,
        hero_b64       = hero_b64,
        site_classification = site_classification,
    )
    all_issues.extend(qual_report.issues)

    # Final dedup pass after AI adds its issues
    seen_titles_2: set[str] = set()
    final_issues: list[AuditIssue] = []
    for issue in all_issues:
        key = f"{issue.category}:{issue.title}"
        if key not in seen_titles_2:
            seen_titles_2.add(key)
            final_issues.append(issue)
    all_issues = final_issues

    # ── Step 7: Scoring ────────────────────────────────────────────────────
    print("[7/8] Calculating scores …")
    scores = score_all(
        html_issues       = all_issues,
        ai_scores         = qual_report.scores,
        lighthouse_scores = tech_report.lighthouse,
    )

    # ── Step 8: AI narrative ───────────────────────────────────────────────
    print("[8/8] Generating narrative …")
    narrative = generate_narrative_report(
        all_issues         = all_issues,
        scores             = scores,
        qual_report        = qual_report,
        website_url        = url,
        site_classification= site_classification,
    )

    return all_issues, scores, qual_report.quick_wins, narrative, tech_report


def _titles_overlap(title_a: str, title_b: str) -> bool:
    """Rough check for whether two issue titles cover the same problem."""
    a = title_a.lower()
    b = title_b.lower()
    # Key anchor words that signal the same underlying issue
    anchors = [
        "title", "meta description", "h1", "robots", "sitemap",
        "https", "redirect", "canonical", "hreflang", "alt",
        "lcp", "cls", "tbt", "performance",
    ]
    for anchor in anchors:
        if anchor in a and anchor in b:
            return True
    return False


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    print("\n" + "═" * 60)
    print("  🔍  WEBSITE AUDIT AGENT")
    print("═" * 60)

    url = input("\nEnter website URL: ").strip()
    if not url:
        sys.exit("No URL provided.")
    if not url.startswith("http"):
        url = "https://" + url

    domain = urlparse(url).netloc

    # Run async pipeline
    result = asyncio.run(_run_audit(url))
    if result is None:
        sys.exit(1)

    all_issues, scores, quick_wins, narrative, tech_report = result

    # ── Print results to terminal ──────────────────────────────────────────
    print("\n")
    _print_separator("═")
    print("  AUDIT RESULTS")
    _print_separator("═")

    _print_scores(scores)

    # Print Core Web Vitals if available
    if tech_report.cwv:
        cwv = tech_report.cwv
        print("\nCORE WEB VITALS (mobile):")
        if cwv.get("lcp_ms"):
            lcp = cwv["lcp_ms"] / 1000
            flag = "✓" if lcp <= 2.5 else ("⚠" if lcp <= 4.0 else "✗")
            print(f"  {flag} LCP  {lcp:.1f}s   (target ≤2.5s)")
        if cwv.get("tbt_ms") is not None:
            tbt = cwv["tbt_ms"]
            flag = "✓" if tbt <= 200 else ("⚠" if tbt <= 600 else "✗")
            print(f"  {flag} TBT  {tbt}ms  (target ≤200ms)")
        if cwv.get("cls") is not None:
            try:
                cls = float(cwv["cls"])
                flag = "✓" if cls <= 0.1 else ("⚠" if cls <= 0.25 else "✗")
                print(f"  {flag} CLS  {cls:.2f}    (target ≤0.1)")
            except (TypeError, ValueError):
                pass

    print("\nALL ISSUES:")
    _print_issues(all_issues)

    if quick_wins:
        print("\nQUICK WINS:")
        for i, win in enumerate(quick_wins, 1):
            print(f"  {i}. {win}")

    if narrative:
        print("\nNARRATIVE SUMMARY:")
        print(f"  {narrative}\n")

    # ── Generate PDF ───────────────────────────────────────────────────────
    print("\n" + "─" * 60)
    prospect_name = input("Prospect / company name for the report: ").strip() or domain
    agency_name   = input("Your agency name (leave blank to use 'Your Agency'): ").strip() or "Your Agency"

    os.makedirs(REPORTS_DIR, exist_ok=True)
    safe_domain = domain.replace(".", "_").replace(":", "")
    output_path = os.path.join(REPORTS_DIR, f"audit_{safe_domain}.pdf")

    print(f"\nGenerating PDF → {output_path} …")
    try:
        generate_pdf(
            all_issues    = all_issues,
            scores        = scores,
            quick_wins    = quick_wins,
            narrative     = narrative,
            prospect_name = prospect_name,
            website_url   = domain,
            agency_name   = agency_name,
            output_path   = output_path,
            cwv           = tech_report.cwv,
            lighthouse    = tech_report.lighthouse,
        )
        print(f"✓ Report saved: {output_path}")
    except Exception as exc:
        print(f"✗ PDF generation failed: {exc}")
        raise


if __name__ == "__main__":
    main()