# =============================================================================
# fetcher.py — Async HTTP fetching and smart page targeting
# =============================================================================
"""
All network I/O lives here.  Uses aiohttp for concurrent page fetching so a
5-page crawl takes ~the time of the slowest single page rather than 5× that.

Public API
----------
fetch_all_target_pages(base_url) -> dict[str, PageResult]
    Returns a mapping of page-type → PageResult for each target page found.
    Always includes "homepage".  Adds "service", "about", "contact", "blog"
    when discovered.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from config import (
    MAX_LINKS_TO_CHECK,
    PAGE_TYPE_PATTERNS,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    TARGET_PAGE_TYPES,
)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class PageResult:
    url:    str
    status: int
    html:   str
    soup:   BeautifulSoup = field(repr=False)

    @property
    def ok(self) -> bool:
        return self.status < 400


# --------------------------------------------------------------------------- #
# Low-level async fetch
# --------------------------------------------------------------------------- #

async def _fetch(session: aiohttp.ClientSession, url: str) -> Optional[PageResult]:
    """Fetch a single URL.  Returns None on any error."""
    try:
        async with session.get(url, allow_redirects=True) as resp:
            html = await resp.text(errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            return PageResult(url=str(resp.url), status=resp.status, html=html, soup=soup)
    except Exception as exc:
        print(f"  [fetcher] Could not fetch {url}: {exc}")
        return None


# --------------------------------------------------------------------------- #
# Smart page targeting
# --------------------------------------------------------------------------- #

def _score_link_for_type(path: str, page_type: str) -> int:
    """Return a match score (higher = better) for a URL path vs page type."""
    path_lower = path.lower()
    patterns   = PAGE_TYPE_PATTERNS.get(page_type, [])
    for pattern in patterns:
        if pattern in path_lower:
            # Prefer exact segment matches, e.g. /about over /about-the-company/team
            depth = path_lower.count("/")
            return 10 - depth  # shallower = more likely the canonical page
    return 0


def _pick_best_link(candidates: list[str], page_type: str) -> Optional[str]:
    """Return the best URL for a given page type from a list of candidates."""
    scored = [
        (url, _score_link_for_type(urlparse(url).path, page_type))
        for url in candidates
    ]
    scored = [(url, s) for url, s in scored if s > 0]
    if not scored:
        return None
    return max(scored, key=lambda x: x[1])[0]


def _extract_internal_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """
    Collect all unique internal href links from a page.
    Strips fragments, query strings, mailto:, and tel: links.
    """
    domain = urlparse(base_url).netloc
    seen: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        full_url = urljoin(base_url, a_tag["href"])
        parsed   = urlparse(full_url)
        clean    = parsed._replace(fragment="", query="").geturl()

        if (
            parsed.netloc == domain
            and not clean.startswith(("mailto:", "tel:", "javascript:"))
        ):
            seen.add(clean)

    return list(seen)


def _detect_page_type_from_content(soup: BeautifulSoup) -> Optional[str]:
    """
    Supplement URL-pattern matching with on-page signals.
    Used as a fallback when URL patterns alone are ambiguous.
    """
    text = soup.get_text(" ", strip=True).lower()[:3000]

    if any(k in text for k in ["get in touch", "send us a message", "contact form", "fill out the form"]):
        return "contact"
    if any(k in text for k in ["meet the team", "about us", "our story", "founded in"]):
        return "about"
    if any(k in text for k in ["our services", "what we do", "how we help", "our solutions"]):
        return "service"
    return None


# --------------------------------------------------------------------------- #
# Broken link checker (async)
# --------------------------------------------------------------------------- #

async def check_broken_links(
    session: aiohttp.ClientSession,
    links: list[str],
    domain: str,
) -> list[str]:
    """
    HEAD-request internal links and return those that return 4xx/5xx.
    Skips mailto:, tel:, and fragment-only links.
    """
    candidates = [
        link for link in links
        if not link.startswith(("mailto:", "tel:", "#", "javascript:"))
        and urlparse(link).netloc == domain
    ][:MAX_LINKS_TO_CHECK]

    broken: list[str] = []

    async def _head(url: str) -> None:
        try:
            async with session.head(url, allow_redirects=True) as resp:
                if resp.status >= 400:
                    broken.append(url)
        except Exception:
            broken.append(url)

    await asyncio.gather(*[_head(u) for u in candidates])
    return broken


# --------------------------------------------------------------------------- #
# Main public entry point
# --------------------------------------------------------------------------- #

async def fetch_all_target_pages(base_url: str) -> dict[str, PageResult]:
    """
    1. Fetch the homepage.
    2. Extract all internal links.
    3. For each TARGET_PAGE_TYPES (service, about, contact, blog), pick the
       best matching link and fetch it concurrently.

    Returns a dict mapping page_type → PageResult (only types that were found).
    """
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    connector = aiohttp.TCPConnector(ssl=False, limit=10)

    async with aiohttp.ClientSession(
        headers=REQUEST_HEADERS,
        timeout=timeout,
        connector=connector,
    ) as session:

        # --- Step 1: Homepage ---
        print(f"  Fetching homepage: {base_url}")
        homepage = await _fetch(session, base_url)
        if homepage is None or not homepage.ok:
            return {}  # caller checks for empty dict

        results: dict[str, PageResult] = {"homepage": homepage}
        all_links = _extract_internal_links(homepage.soup, base_url)
        domain    = urlparse(base_url).netloc

        # --- Step 2: Identify best candidate URL for each target page type ---
        to_fetch: dict[str, str] = {}  # page_type → url

        for page_type in TARGET_PAGE_TYPES[1:]:  # skip "homepage"
            best = _pick_best_link(all_links, page_type)
            if best and best != homepage.url:
                to_fetch[page_type] = best

        # --- Step 3: Fetch all targets concurrently ---
        if to_fetch:
            tasks = {pt: _fetch(session, url) for pt, url in to_fetch.items()}
            fetched = await asyncio.gather(*tasks.values())

            for page_type, result in zip(tasks.keys(), fetched):
                if result and result.ok:
                    # Refine page type using content signals if needed
                    detected = _detect_page_type_from_content(result.soup)
                    key = detected if detected and detected not in results else page_type
                    results[key] = result
                    print(f"  ✓ Found {key} page: {result.url}")
                else:
                    print(f"  ✗ Could not fetch {page_type} page: {to_fetch[page_type]}")

        print(f"\n  Crawl complete — {len(results)} page(s) analysed.\n")
        return results