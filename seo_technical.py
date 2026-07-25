# =============================================================================
# seo_technical.py — Deep technical SEO via Lighthouse, advertools, extruct
# =============================================================================
"""
Replaces the four shallow checks in detectors.seo_check() with a full
technical SEO audit powered by three external sources:

  1. Google PageSpeed Insights API (Lighthouse)
       — Core Web Vitals (LCP, CLS, TBT)
       — Lighthouse SEO category score + sub-audits
       — Lighthouse Performance + Accessibility scores
       — Mobile usability from Google's own renderer

  2. advertools
       — robots.txt: is the site crawlable? are key pages blocked?
       — XML sitemap: present? URL count? last-modified freshness?

  3. extruct
       — Structured data (JSON-LD, Microdata, OpenGraph, Twitter Cards)
       — Detects missing / incomplete schema types

  4. Custom async redirect chain detector (pure aiohttp, no library)
       — Chains longer than 2 hops → MEDIUM
       — Redirect loops → HIGH

All functions are async and return list[AuditIssue].
Graceful fallback on every dependency: if a library isn't installed or an
API call fails, that section is skipped and the original detectors.seo_check()
fills the gap.

Public API
----------
run_technical_seo(url, homepage_html, homepage_data, api_key=None)
    -> TechnicalSEOReport

TechnicalSEOReport
    .issues       list[AuditIssue]
    .lighthouse   dict   raw scores from PSI  (performance/seo/accessibility 0-100)
    .structured   dict   extruct summary
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp

from detectors import AuditIssue, CATEGORY_SEO, CATEGORY_MOBILE, CATEGORY_MISSED_OPPS
from extractors import PageData


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class TechnicalSEOReport:
    issues:     list[AuditIssue]    = field(default_factory=list)
    lighthouse: dict                = field(default_factory=dict)  # raw PSI scores
    structured: dict                = field(default_factory=dict)  # extruct summary
    cwv:        dict                = field(default_factory=dict)  # Core Web Vitals values


# --------------------------------------------------------------------------- #
# 1. Google PageSpeed Insights / Lighthouse
# --------------------------------------------------------------------------- #

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# Lighthouse SEO sub-audits we care about and their severity mappings
_LIGHTHOUSE_SEO_AUDITS = {
    # id                       : (display_title, severity_if_fail, description_template)
    "document-title":           ("Missing page title",              "LOW",
                                 "Lighthouse confirmed no <title> tag — this is the primary text "
                                 "Google shows in search results. Every page needs a unique, "
                                 "descriptive title under 60 characters."),
    "meta-description":         ("Missing meta description",        "LOW",
                                 "Lighthouse found no meta description. Without it Google "
                                 "auto-generates preview text, which is rarely conversion-focused."),
    "http-status-code":         ("Page returns bad HTTP status",    "HIGH",
                                 "Lighthouse detected a non-200 HTTP status. Google cannot "
                                 "index pages that return errors — this is a critical crawl blocker."),
    "link-text":                ("Non-descriptive link text",       "LOW",
                                 "Links using text like 'click here' or 'read more' give Google "
                                 "no context about the linked page's topic, weakening topical authority."),
    "crawlable-anchors":        ("Links not crawlable by Google",   "MEDIUM",
                                 "Some links use JavaScript or invalid href values that Google's "
                                 "crawler cannot follow, leaving pages undiscovered."),
    "is-crawlable":             ("Page is blocked from indexing",   "HIGH",
                                 "A noindex tag or robots meta directive is preventing Google from "
                                 "indexing this page. If intentional, ignore; if not, fix immediately."),
    "robots-txt":               ("robots.txt is invalid or missing","MEDIUM",
                                 "Lighthouse found issues with the robots.txt file. An invalid "
                                 "robots.txt can accidentally block all crawling sitewide."),
    "image-alt":                ("Images missing alt text",         "LOW",
                                 "Images without alt attributes are invisible to Google Image Search "
                                 "and screen readers — both a ranking and accessibility issue."),
    "hreflang":                 ("Invalid hreflang tags",           "MEDIUM",
                                 "Hreflang tags with incorrect values confuse Google about which "
                                 "language/country version to serve, harming international visibility."),
    "canonical":                ("Canonical URL issues",            "MEDIUM",
                                 "Lighthouse detected canonical tag problems. Incorrect canonicals "
                                 "cause Google to index the wrong URL version, splitting link equity."),
    "font-size":                ("Text too small for mobile",       "MEDIUM",
                                 "Lighthouse found text below Google's 12px minimum for mobile. "
                                 "This degrades mobile usability scores and organic rankings."),
    "tap-targets":              ("Tap targets too small on mobile", "MEDIUM",
                                 "Interactive elements are too close together on mobile screens. "
                                 "Google uses this as a negative mobile usability signal."),
    "structured-data":          ("Structured data errors detected", "MEDIUM",
                                 "Lighthouse found invalid structured data (Schema.org markup). "
                                 "Valid schema unlocks rich results in Google — errors block them."),
    "plugins":                  ("Page uses unsupported plugins",   "HIGH",
                                 "Flash or other unsupported plugins are present. Google cannot "
                                 "render or index this content, meaning it is invisible in search."),
}


async def _fetch_psi(
    url: str,
    api_key: Optional[str],
    session: aiohttp.ClientSession,
) -> Optional[dict]:
    """Single PSI call covering performance + seo + accessibility categories."""
    params = {
        "url":      url,
        "strategy": "mobile",   # mobile-first indexing
        "category": ["performance", "seo", "accessibility"],
    }
    if api_key:
        params["key"] = api_key

    try:
        async with session.get(
            PSI_ENDPOINT,
            params=params,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as resp:
            if resp.status != 200:
                print(f"  [PSI] API returned {resp.status}")
                return None
            return await resp.json()
    except Exception as exc:
        print(f"  [PSI] Request failed: {exc}")
        return None


def _extract_lighthouse_issues(psi_data: dict) -> tuple[list[AuditIssue], dict, dict]:
    """
    Parse PSI response into:
      - AuditIssue list
      - lighthouse scores dict  {performance, seo, accessibility}  0-100
      - cwv dict  {lcp_ms, cls, tbt_ms, fcp_ms, si_ms}
    """
    issues: list[AuditIssue] = []
    scores: dict = {}
    cwv: dict = {}

    try:
        lr = psi_data.get("lighthouseResult", {})
        cats = lr.get("categories", {})

        # Category scores
        for cat_id, cat_key in [("performance", "performance"), ("seo", "seo"),
                                  ("accessibility", "accessibility")]:
            cat = cats.get(cat_id, {})
            if "score" in cat and cat["score"] is not None:
                scores[cat_key] = int(cat["score"] * 100)

        # Core Web Vitals from metrics audit
        audits = lr.get("audits", {})
        metrics_items = (
            audits.get("metrics", {})
                  .get("details", {})
                  .get("items", [{}])
        )
        if metrics_items:
            m = metrics_items[0]
            cwv = {
                "lcp_ms":  m.get("largestContentfulPaint"),
                "cls":     m.get("cumulativeLayoutShift"),    # stored as value not ms
                "tbt_ms":  m.get("totalBlockingTime"),
                "fcp_ms":  m.get("firstContentfulPaint"),
                "si_ms":   m.get("speedIndex"),
                "tti_ms":  m.get("interactive"),
            }

        # Core Web Vitals issue generation
        if cwv.get("lcp_ms") and cwv["lcp_ms"] > 4000:
            issues.append(AuditIssue(
                severity    = "HIGH",
                category    = CATEGORY_SEO,
                title       = f"Slow LCP: {cwv['lcp_ms'] / 1000:.1f}s (target <2.5s)",
                description = (
                    f"Largest Contentful Paint is {cwv['lcp_ms'] / 1000:.1f}s on mobile. "
                    "Google's threshold for a 'Good' LCP is under 2.5s — this is a direct "
                    "ranking factor in Core Web Vitals. Slow LCP is typically caused by "
                    "unoptimised hero images, slow server response, or render-blocking resources."
                ),
            ))
        elif cwv.get("lcp_ms") and cwv["lcp_ms"] > 2500:
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_SEO,
                title       = f"LCP needs improvement: {cwv['lcp_ms'] / 1000:.1f}s (target <2.5s)",
                description = (
                    f"LCP is {cwv['lcp_ms'] / 1000:.1f}s — in Google's 'Needs Improvement' band "
                    "(2.5–4s). Optimising images, enabling compression, and using a CDN are the "
                    "fastest ways to get this into the 'Good' range and protect search rankings."
                ),
            ))

        if cwv.get("tbt_ms") and cwv["tbt_ms"] > 600:
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_SEO,
                title       = f"High Total Blocking Time: {cwv['tbt_ms']}ms (target <200ms)",
                description = (
                    f"TBT is {cwv['tbt_ms']}ms — indicating heavy JavaScript is blocking user "
                    "interaction after the page visually loads. This hurts INP (Interaction to "
                    "Next Paint), Google's responsiveness Core Web Vital."
                ),
            ))

        # CLS
        cls_val = cwv.get("cls")
        if cls_val is not None:
            try:
                cls_f = float(cls_val)
                if cls_f > 0.25:
                    issues.append(AuditIssue(
                        severity    = "HIGH",
                        category    = CATEGORY_SEO,
                        title       = f"Poor layout stability (CLS: {cls_f:.2f}, target <0.1)",
                        description = (
                            f"Cumulative Layout Shift is {cls_f:.2f} — well above Google's 0.1 "
                            "threshold. The page visually jumps as it loads, which frustrates "
                            "users and is a Core Web Vital ranking penalty."
                        ),
                    ))
                elif cls_f > 0.1:
                    issues.append(AuditIssue(
                        severity    = "LOW",
                        category    = CATEGORY_SEO,
                        title       = f"Layout shift needs attention (CLS: {cls_f:.2f}, target <0.1)",
                        description = (
                            f"CLS of {cls_f:.2f} is in Google's 'Needs Improvement' band. "
                            "Usually fixed by setting explicit width/height on images and ads, "
                            "and avoiding dynamically injected content above existing content."
                        ),
                    ))
            except (TypeError, ValueError):
                pass

        # Low overall Lighthouse SEO score
        seo_score = scores.get("seo", 100)
        if seo_score < 70:
            issues.append(AuditIssue(
                severity    = "HIGH",
                category    = CATEGORY_SEO,
                title       = f"Low Lighthouse SEO score: {seo_score}/100",
                description = (
                    f"Google's own Lighthouse tool rates this site's SEO at {seo_score}/100. "
                    "Scores below 70 indicate multiple technical SEO failures that will "
                    "suppress organic rankings across all pages."
                ),
            ))
        elif seo_score < 90:
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_SEO,
                title       = f"Lighthouse SEO score has room to improve: {seo_score}/100",
                description = (
                    f"Lighthouse rates SEO at {seo_score}/100. Pushing this above 90 removes "
                    "technical barriers that are holding back organic traffic."
                ),
            ))

        # Performance score
        perf_score = scores.get("performance", 100)
        if perf_score < 50:
            issues.append(AuditIssue(
                severity    = "HIGH",
                category    = CATEGORY_SEO,
                title       = f"Very poor page performance: {perf_score}/100",
                description = (
                    f"Lighthouse rates performance at {perf_score}/100. Page speed is a confirmed "
                    "Google ranking factor — sites in this range typically see significantly "
                    "lower rankings and higher bounce rates than competitors."
                ),
            ))
        elif perf_score < 75:
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_SEO,
                title       = f"Below-average page performance: {perf_score}/100",
                description = (
                    f"Performance score of {perf_score}/100 means the site is slower than most "
                    "competitors. Each second of load time reduces conversions by ~7% on average."
                ),
            ))

        # Accessibility score (affects SEO and usability)
        a11y_score = scores.get("accessibility", 100)
        if a11y_score < 70:
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_SEO,
                title       = f"Low accessibility score: {a11y_score}/100",
                description = (
                    f"Lighthouse rates accessibility at {a11y_score}/100. Accessibility issues "
                    "directly overlap with SEO: missing alt text, poor contrast, and broken "
                    "ARIA labels all reduce Google's ability to understand page content."
                ),
            ))

        # Individual SEO sub-audits
        for audit_id, (title, severity, description) in _LIGHTHOUSE_SEO_AUDITS.items():
            audit = audits.get(audit_id, {})
            score = audit.get("score")
            if score is None:
                continue
            # score = 1 means pass, 0 = fail, 0<x<1 = partial
            if score < 1:
                issues.append(AuditIssue(
                    severity    = severity,
                    category    = CATEGORY_SEO,
                    title       = title,
                    description = description,
                ))

    except Exception as exc:
        print(f"  [PSI] Failed to parse Lighthouse response: {exc}")

    return issues, scores, cwv


# --------------------------------------------------------------------------- #
# 2. advertools — robots.txt + sitemap
# --------------------------------------------------------------------------- #

async def _check_robots_and_sitemap(
    base_url: str,
    session: aiohttp.ClientSession,
) -> list[AuditIssue]:
    """
    Use advertools to parse robots.txt and sitemap.
    Falls back gracefully if advertools not installed.
    """
    issues: list[AuditIssue] = []
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # --- robots.txt ---
    robots_url = f"{origin}/robots.txt"
    try:
        import advertools as adv

        robots_df = adv.robotstxt_to_df(robots_url)

        if robots_df is None or robots_df.empty:
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_SEO,
                title       = "robots.txt missing or empty",
                description = (
                    "No robots.txt file was found. Without it, Google uses default "
                    "crawl rules — but its absence can also trigger crawl warnings in "
                    "Google Search Console. Add a robots.txt that explicitly allows the "
                    "pages you want indexed and points to the XML sitemap."
                ),
            ))
        else:
            # Check if Googlebot (or *) is disallowing /
            disallow_all = robots_df[
                (robots_df["directive"].str.lower() == "disallow") &
                (robots_df["content"].str.strip() == "/") &
                (robots_df["useragent"].str.lower().isin(["*", "googlebot"]))
            ]
            if not disallow_all.empty:
                issues.append(AuditIssue(
                    severity    = "HIGH",
                    category    = CATEGORY_SEO,
                    title       = "robots.txt is blocking all crawlers",
                    description = (
                        "The robots.txt file contains 'Disallow: /' for all user agents or "
                        "Googlebot — meaning Google CANNOT crawl or index any page on this site. "
                        "This is a catastrophic SEO error that must be fixed immediately."
                    ),
                ))

            # Check for sitemap reference in robots.txt
            has_sitemap_ref = "sitemap" in robots_df["directive"].str.lower().values
            if not has_sitemap_ref:
                issues.append(AuditIssue(
                    severity    = "LOW",
                    category    = CATEGORY_SEO,
                    title       = "robots.txt doesn't reference sitemap",
                    description = (
                        "The robots.txt file exists but doesn't include a 'Sitemap:' directive. "
                        "Adding the sitemap URL to robots.txt helps Google discover all pages "
                        "faster, which is especially important for new content."
                    ),
                ))

    except ImportError:
        # advertools not installed — do a lightweight manual check
        try:
            async with session.get(
                robots_url,
                timeout=aiohttp.ClientTimeout(total=8),
                allow_redirects=True,
            ) as resp:
                if resp.status == 404:
                    issues.append(AuditIssue(
                        severity    = "MEDIUM",
                        category    = CATEGORY_SEO,
                        title       = "robots.txt missing",
                        description = (
                            "No robots.txt file was found at the expected location. "
                            "Add one that explicitly allows important pages and references your sitemap."
                        ),
                    ))
                else:
                    text = (await resp.text()).lower()
                    if "disallow: /" in text and "allow: /" not in text:
                        issues.append(AuditIssue(
                            severity    = "HIGH",
                            category    = CATEGORY_SEO,
                            title       = "robots.txt may be blocking all crawlers",
                            description = (
                                "robots.txt appears to contain 'Disallow: /' — verify this is "
                                "not blocking Googlebot from crawling the entire site."
                            ),
                        ))
        except Exception:
            pass

    except Exception as exc:
        print(f"  [advertools] robots.txt check failed: {exc}")

    # --- XML Sitemap ---
    sitemap_candidates = [
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap_index.xml",
        f"{origin}/sitemap-index.xml",
    ]

    sitemap_found = False
    for sitemap_url in sitemap_candidates:
        try:
            async with session.get(
                sitemap_url,
                timeout=aiohttp.ClientTimeout(total=8),
                allow_redirects=True,
            ) as resp:
                if resp.status == 200:
                    sitemap_found = True
                    content = await resp.text()
                    url_count = content.lower().count("<url>") + content.lower().count("<sitemap>")

                    try:
                        import advertools as adv
                        sitemap_df = adv.sitemap_to_df(sitemap_url)
                        if sitemap_df is not None and not sitemap_df.empty:
                            url_count = len(sitemap_df)

                            # Check for stale lastmod dates
                            if "lastmod" in sitemap_df.columns:
                                import pandas as pd
                                lastmod = pd.to_datetime(
                                    sitemap_df["lastmod"], errors="coerce", utc=True
                                )
                                valid = lastmod.dropna()
                                if len(valid) > 0:
                                    from datetime import datetime, timezone
                                    now = datetime.now(timezone.utc)
                                    days_since = (now - valid.max()).days
                                    if days_since > 180:
                                        issues.append(AuditIssue(
                                            severity    = "LOW",
                                            category    = CATEGORY_SEO,
                                            title       = f"Sitemap content appears stale ({days_since} days since last update)",
                                            description = (
                                                f"The most recent lastmod date in the sitemap is "
                                                f"{days_since} days ago. Outdated sitemaps signal "
                                                "low publishing frequency to Google, which can reduce "
                                                "crawl budget allocation."
                                            ),
                                        ))
                    except Exception:
                        pass  # advertools optional for sitemap detail

                    print(f"  [sitemap] Found at {sitemap_url} (~{url_count} URLs)")
                    break
        except Exception:
            continue

    if not sitemap_found:
        issues.append(AuditIssue(
            severity    = "MEDIUM",
            category    = CATEGORY_SEO,
            title       = "No XML sitemap found",
            description = (
                "No sitemap.xml was found at common locations. A sitemap helps Google "
                "discover and index all pages efficiently — its absence means new content "
                "may take much longer to appear in search results, or never be found at all."
            ),
        ))

    return issues


# --------------------------------------------------------------------------- #
# 3. extruct — Structured data audit
# --------------------------------------------------------------------------- #

def _check_structured_data(homepage_html: str, base_url: str) -> tuple[list[AuditIssue], dict]:
    """
    Use extruct to deeply parse all structured data formats.
    Falls back to a lightweight regex check if extruct not installed.
    """
    issues: list[AuditIssue] = []
    summary: dict = {}

    try:
        import extruct

        data = extruct.extract(
            homepage_html,
            base_url       = base_url,
            syntaxes       = ["json-ld", "microdata", "opengraph", "twitter"],
            uniform        = True,
        )

        # --- JSON-LD / Microdata (Schema.org) ---
        schema_items = data.get("json-ld", []) + data.get("microdata", [])
        schema_types = []
        has_errors   = False

        for item in schema_items:
            t = item.get("@type") or item.get("type", "")
            if t:
                if isinstance(t, list):
                    schema_types.extend(t)
                else:
                    schema_types.append(str(t))

            # Basic validation: required fields for common types
            t_lower = str(t).lower() if t else ""
            if "localbusiness" in t_lower or "organization" in t_lower:
                if not item.get("name") and not item.get("legalName"):
                    has_errors = True
                    issues.append(AuditIssue(
                        severity    = "MEDIUM",
                        category    = CATEGORY_SEO,
                        title       = "LocalBusiness/Organization schema missing required fields",
                        description = (
                            "Schema.org markup for the business was found but is missing required "
                            "fields (name, address, telephone). Incomplete schema blocks Google from "
                            "generating rich results and Knowledge Panel entries."
                        ),
                    ))
            if "product" in t_lower:
                if not item.get("offers") and not item.get("price"):
                    has_errors = True

        summary["schema_types"] = schema_types
        summary["has_schema"]   = len(schema_types) > 0

        # Flag if NO schema at all
        if not schema_types:
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_MISSED_OPPS,
                title       = "No Schema.org structured data found",
                description = (
                    "The homepage has no JSON-LD or Microdata structured data. Schema markup "
                    "enables rich results in Google (star ratings, FAQs, business info) and "
                    "is increasingly used by AI search tools to understand and cite businesses. "
                    "At minimum, add Organization or LocalBusiness schema."
                ),
            ))

        # --- OpenGraph ---
        og_items = data.get("opengraph", [])
        og_props = {}
        for og in og_items:
            og_props.update(og)

        summary["has_og"] = bool(og_props)
        og_title = og_props.get("og:title") or og_props.get("title")
        og_image = og_props.get("og:image") or og_props.get("image")
        og_desc  = og_props.get("og:description") or og_props.get("description")

        if not og_title or not og_image or not og_desc:
            missing = []
            if not og_title: missing.append("og:title")
            if not og_image: missing.append("og:image")
            if not og_desc:  missing.append("og:description")
            issues.append(AuditIssue(
                severity    = "LOW",
                category    = CATEGORY_MISSED_OPPS,
                title       = f"Incomplete OpenGraph tags ({', '.join(missing)} missing)",
                description = (
                    "OpenGraph tags control how the site appears when shared on LinkedIn, "
                    "Facebook, WhatsApp, and Slack. Missing og:image especially means "
                    "shares show up without a preview image — significantly reducing "
                    "click-through rates from social sharing."
                ),
            ))

        # --- Twitter Cards ---
        tw_items = data.get("twitter", [])
        tw_props = {}
        for tw in tw_items:
            tw_props.update(tw)

        summary["has_twitter_card"] = bool(tw_props)
        if not tw_props:
            issues.append(AuditIssue(
                severity    = "LOW",
                category    = CATEGORY_MISSED_OPPS,
                title       = "No Twitter/X Card tags found",
                description = (
                    "Twitter Card meta tags are missing. Without them, links shared on X "
                    "(Twitter) show as plain text rather than rich cards with images and "
                    "descriptions — reducing engagement and click-through from social traffic."
                ),
            ))

    except ImportError:
        # extruct not installed — do a minimal check from raw HTML
        has_jsonld    = '"@context"' in homepage_html and '"@type"' in homepage_html
        has_og_title  = 'og:title' in homepage_html
        has_og_image  = 'og:image' in homepage_html

        summary = {
            "has_schema":       has_jsonld,
            "has_og":           has_og_title,
            "has_twitter_card": 'twitter:card' in homepage_html,
        }

        if not has_jsonld:
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_MISSED_OPPS,
                title       = "No Schema.org structured data found",
                description = (
                    "The homepage has no JSON-LD structured data. Schema markup enables "
                    "rich results in Google (star ratings, FAQs, business info) — add "
                    "Organization or LocalBusiness schema at minimum."
                ),
            ))

        if not has_og_title or not has_og_image:
            issues.append(AuditIssue(
                severity    = "LOW",
                category    = CATEGORY_MISSED_OPPS,
                title       = "Incomplete OpenGraph tags",
                description = (
                    "Missing OpenGraph meta tags mean the site displays poorly when "
                    "shared on social platforms — no preview image, wrong title or description."
                ),
            ))

    except Exception as exc:
        print(f"  [extruct] Structured data check failed: {exc}")

    return issues, summary


# --------------------------------------------------------------------------- #
# 4. Redirect chain detector
# --------------------------------------------------------------------------- #

async def _check_redirect_chain(
    url: str,
    session: aiohttp.ClientSession,
) -> list[AuditIssue]:
    """
    Follow redirects manually, tracking the chain.
    Returns issues if chain is longer than 2 hops or contains a loop.
    """
    issues: list[AuditIssue] = []
    visited: list[str] = [url]
    current = url
    max_hops = 10

    try:
        for _ in range(max_hops):
            async with session.get(
                current,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    if not location:
                        break
                    next_url = urljoin(current, location)
                    if next_url in visited:
                        chain_str = " → ".join(visited[-3:]) + " → (loop)"
                        issues.append(AuditIssue(
                            severity    = "HIGH",
                            category    = CATEGORY_SEO,
                            title       = "Redirect loop detected",
                            description = (
                                f"The URL redirects in a loop: {chain_str}. "
                                "Redirect loops make the page completely inaccessible to both "
                                "users and search engines, and will appear as an error in "
                                "Google Search Console."
                            ),
                        ))
                        return issues
                    visited.append(next_url)
                    current = next_url
                else:
                    break  # final destination reached

        hop_count = len(visited) - 1
        if hop_count > 2:
            chain_str = " → ".join(visited)
            issues.append(AuditIssue(
                severity    = "MEDIUM",
                category    = CATEGORY_SEO,
                title       = f"Long redirect chain ({hop_count} hops)",
                description = (
                    f"The homepage goes through {hop_count} redirects before reaching the final "
                    f"URL: {chain_str}. Each redirect adds ~100–200ms to load time and dilutes "
                    "link equity. Redirect chains should be consolidated to a single hop."
                ),
            ))
        elif hop_count == 1:
            # One redirect is fine but check http → https
            if visited[0].startswith("http://") and visited[-1].startswith("https://"):
                pass  # normal, no issue
            elif visited[0].startswith("https://") and visited[-1].startswith("http://"):
                issues.append(AuditIssue(
                    severity    = "HIGH",
                    category    = CATEGORY_SEO,
                    title       = "HTTPS redirecting to HTTP",
                    description = (
                        "The site redirects from HTTPS to HTTP, which is a security downgrade. "
                        "Google requires HTTPS and may penalise or warn users about HTTP sites."
                    ),
                ))

    except Exception as exc:
        print(f"  [redirect] Chain check failed: {exc}")

    return issues


# --------------------------------------------------------------------------- #
# 5. HTTPS check
# --------------------------------------------------------------------------- #

def _check_https(url: str, homepage_html: str) -> list[AuditIssue]:
    issues: list[AuditIssue] = []

    if url.startswith("http://"):
        issues.append(AuditIssue(
            severity    = "HIGH",
            category    = CATEGORY_SEO,
            title       = "Site not served over HTTPS",
            description = (
                "The site is using HTTP rather than HTTPS. Google has used HTTPS as a "
                "ranking signal since 2014, and modern browsers display security warnings "
                "on HTTP sites — both a ranking and conversion issue."
            ),
        ))

    # Mixed content check (HTTPS page loading HTTP assets)
    if url.startswith("https://") and re.search(r'src=["\']http://', homepage_html, re.I):
        issues.append(AuditIssue(
            severity    = "MEDIUM",
            category    = CATEGORY_SEO,
            title       = "Mixed content: HTTP assets on HTTPS page",
            description = (
                "The HTTPS page loads some resources (images, scripts, or styles) over HTTP. "
                "Browsers block or warn on mixed content, causing visual breakage and console "
                "errors — and Google may treat the page as insecure."
            ),
        ))

    return issues


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

async def run_technical_seo(
    url: str,
    homepage_html: str,
    homepage_data: PageData,
    api_key: Optional[str] = None,
) -> TechnicalSEOReport:
    """
    Run the full technical SEO stack concurrently.
    Safe to call even if optional dependencies are missing.

    Parameters
    ----------
    url           : full URL of the homepage
    homepage_html : raw HTML string of the homepage
    homepage_data : PageData extracted from the homepage
    api_key       : Google PSI API key (optional but recommended for production)
    """
    report = TechnicalSEOReport()

    connector = aiohttp.TCPConnector(ssl=False, limit=5)
    async with aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )},
    ) as session:

        # Run PSI + redirect chain + robots/sitemap concurrently
        psi_task      = _fetch_psi(url, api_key, session)
        redirect_task = _check_redirect_chain(url, session)
        crawl_task    = _check_robots_and_sitemap(url, session)

        psi_data, redirect_issues, crawl_issues = await asyncio.gather(
            psi_task, redirect_task, crawl_task,
            return_exceptions=True,
        )

    # PSI results
    if isinstance(psi_data, dict):
        lh_issues, lh_scores, cwv = _extract_lighthouse_issues(psi_data)
        report.issues.extend(lh_issues)
        report.lighthouse = lh_scores
        report.cwv        = cwv
        print(f"  [PSI] Scores — Performance: {lh_scores.get('performance','?')}, "
              f"SEO: {lh_scores.get('seo','?')}, "
              f"Accessibility: {lh_scores.get('accessibility','?')}")
    else:
        if isinstance(psi_data, Exception):
            print(f"  [PSI] Failed: {psi_data}")
        print("  [PSI] Skipping Lighthouse analysis.")

    # Redirect chain results
    if isinstance(redirect_issues, list):
        report.issues.extend(redirect_issues)
    elif isinstance(redirect_issues, Exception):
        print(f"  [redirect] Check failed: {redirect_issues}")

    # Crawl intelligence results
    if isinstance(crawl_issues, list):
        report.issues.extend(crawl_issues)
    elif isinstance(crawl_issues, Exception):
        print(f"  [crawl] Check failed: {crawl_issues}")

    # Structured data (sync, CPU-bound parsing)
    sd_issues, sd_summary = _check_structured_data(homepage_html, url)
    report.issues.extend(sd_issues)
    report.structured = sd_summary

    # HTTPS (instant, no I/O)
    report.issues.extend(_check_https(url, homepage_html))

    print(f"  [technical SEO] {len(report.issues)} issue(s) found.")
    return report