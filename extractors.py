# =============================================================================
# extractors.py — Structured data extraction from fetched pages
# =============================================================================
"""
Converts a raw PageResult into a clean PageData dict that every detector can
consume without knowing anything about HTML parsing.

Public API
----------
extract_page_data(result: PageResult) -> PageData
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from fetcher import PageResult


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class PageData:
    """All structured fields extracted from a single crawled page."""
    url:         str
    page_type:   str                    # homepage | service | about | contact | blog
    title:       str
    meta_desc:   str
    h1:          list[str]
    h2:          list[str]
    text:        str                    # full visible text, lowercased
    html:        str                    # raw HTML string, lowercased
    soup:        BeautifulSoup = field(repr=False)
    links:       list[str]             # all absolute hrefs on this page
    images:      list[str]             # all absolute image src values
    forms:       list[dict]            # each form: {action, method, inputs}
    viewport_ok: bool                  # has correct mobile viewport meta
    canonical:   Optional[str]         # canonical URL if declared
    schema_types: list[str]            # Schema.org @type values present


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _abs_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    return [
        urljoin(base_url, a["href"])
        for a in soup.find_all("a", href=True)
        if a["href"].strip()
    ]


def _abs_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    srcs = []
    for img in soup.find_all("img", src=True):
        src = img["src"].strip()
        if src and not src.startswith("data:"):
            srcs.append(urljoin(base_url, src))
    return srcs


def _extract_forms(soup: BeautifulSoup) -> list[dict]:
    forms = []
    for form in soup.find_all("form"):
        inputs = [
            {
                "type":  inp.get("type", "text"),
                "name":  inp.get("name", ""),
                "placeholder": inp.get("placeholder", ""),
            }
            for inp in form.find_all(["input", "textarea", "select"])
        ]
        forms.append({
            "action": form.get("action", ""),
            "method": form.get("method", "get").lower(),
            "inputs": inputs,
        })
    return forms


def _extract_schema_types(soup: BeautifulSoup) -> list[str]:
    """Find all Schema.org @type values from JSON-LD and microdata."""
    import json, re
    types = []

    # JSON-LD
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                t = data.get("@type")
                if t:
                    types.append(t if isinstance(t, str) else str(t))
            elif isinstance(data, list):
                for item in data:
                    t = item.get("@type") if isinstance(item, dict) else None
                    if t:
                        types.append(str(t))
        except Exception:
            pass

    # Microdata
    for tag in soup.find_all(attrs={"itemtype": True}):
        m = re.search(r"schema\.org/(\w+)", tag["itemtype"])
        if m:
            types.append(m.group(1))

    return list(set(types))


def _has_correct_viewport(soup: BeautifulSoup) -> bool:
    """True if the page declares a mobile-friendly viewport meta tag."""
    vp = soup.find("meta", attrs={"name": re.compile("viewport", re.I)})
    if not vp:
        return False
    content = vp.get("content", "").lower()
    return "width=device-width" in content


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def extract_page_data(result: PageResult, page_type: str = "homepage") -> PageData:
    """
    Transform a PageResult into a fully-populated PageData object.
    All text fields are lowercased for consistent detector pattern matching.
    """
    soup = result.soup
    url  = result.url

    # Title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Meta description
    meta_desc = ""
    meta_tag  = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    if meta_tag:
        meta_desc = meta_tag.get("content", "").strip()

    # Headings
    h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    h2 = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]

    # Full text (lowercased for detector matching)
    text = soup.get_text(" ", strip=True).lower()

    # Raw HTML (lowercased)
    html = result.html.lower()

    # Canonical URL
    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    canonical = canonical_tag["href"] if canonical_tag and canonical_tag.get("href") else None

    return PageData(
        url          = url,
        page_type    = page_type,
        title        = title,
        meta_desc    = meta_desc,
        h1           = h1,
        h2           = h2,
        text         = text,
        html         = html,
        soup         = soup,
        links        = _abs_links(soup, url),
        images       = _abs_images(soup, url),
        forms        = _extract_forms(soup),
        viewport_ok  = _has_correct_viewport(soup),
        canonical    = canonical,
        schema_types = _extract_schema_types(soup),
    )