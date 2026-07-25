# =============================================================================
# site_classifier.py — Detect website type from crawled page data
# =============================================================================
"""
Classifies any website into one of 8 site types so that all downstream
checks, thresholds, and AI prompts can be tuned appropriately.

Site types
----------
  ecommerce       — Online store (Shopify, WooCommerce, Magento, custom)
  saas            — Software-as-a-Service / app product
  local_service   — Tradesperson, clinic, salon, restaurant, local SMB
  agency_creative — Marketing agency, design studio, consultancy, PR firm
  b2b_corporate   — Enterprise, B2B services, professional services firm
  content_blog    — Publisher, news site, personal blog, media outlet
  nonprofit       — Charity, NGO, foundation, cause-led organisation
  portfolio       — Freelancer, artist, photographer, personal showcase

Public API
----------
classify_site(homepage_data, all_page_texts) -> SiteClassification
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# --------------------------------------------------------------------------- #
# Site type registry
# --------------------------------------------------------------------------- #

SITE_TYPES = [
    "ecommerce",
    "saas",
    "local_service",
    "agency_creative",
    "b2b_corporate",
    "content_blog",
    "nonprofit",
    "portfolio",
]

SITE_TYPE_LABELS = {
    "ecommerce":       "E-Commerce Store",
    "saas":            "SaaS / Software Product",
    "local_service":   "Local Service Business",
    "agency_creative": "Agency / Creative Studio",
    "b2b_corporate":   "B2B / Corporate Services",
    "content_blog":    "Content / Blog / Media",
    "nonprofit":       "Non-Profit / Charity",
    "portfolio":       "Portfolio / Freelancer",
}

SITE_TYPE_DESCRIPTIONS = {
    "ecommerce": (
        "An online retail site where visitors can browse products and complete "
        "purchases. Key conversion actions are Add to Cart and Checkout."
    ),
    "saas": (
        "A software product or platform sold via subscription or freemium. "
        "Key conversion actions are Free Trial, Demo, and Sign Up."
    ),
    "local_service": (
        "A geographically-anchored service business (tradesperson, clinic, salon, "
        "restaurant). Key conversion actions are Call, Book, and Get a Quote."
    ),
    "agency_creative": (
        "A creative, marketing, or professional services agency. "
        "Key conversion actions are Get a Proposal, Book a Call, and Contact Us."
    ),
    "b2b_corporate": (
        "A B2B company or enterprise services firm. "
        "Key conversion actions are Request a Demo, Contact Sales, and Download."
    ),
    "content_blog": (
        "A content-first site: publisher, news outlet, or personal blog. "
        "Key conversion actions are Subscribe, Follow, and Share."
    ),
    "nonprofit": (
        "A charity, NGO, or cause-led organisation. "
        "Key conversion actions are Donate, Volunteer, and Join."
    ),
    "portfolio": (
        "A personal showcase for a freelancer, artist, or photographer. "
        "Key conversion actions are Hire Me, View Work, and Get in Touch."
    ),
}


# --------------------------------------------------------------------------- #
# Signal dictionaries
# --------------------------------------------------------------------------- #

# HTML / text signals per site type (checked against lowercased HTML + text)
_HTML_SIGNALS: dict[str, list[str]] = {
    "ecommerce": [
        "add to cart", "add-to-cart", "addtocart", "buy now", "buynow",
        "product-form__submit", "shopify-payment-button", "woocommerce",
        "magento", "bigcommerce", "checkout", "/cart", "/shop", "/product",
        "variant", "sku", "inventory", "in stock", "out of stock",
        "free shipping", "return policy", "shopping bag", "shopping cart",
        "price__regular", "product__price", "atc-btn",
    ],
    "saas": [
        "start free trial", "free trial", "start trial", "sign up free",
        "get started free", "request a demo", "book a demo", "watch a demo",
        "pricing", "/pricing", "per month", "per user", "billed annually",
        "monthly plan", "enterprise plan", "integrations", "api docs",
        "/changelog", "dashboard", "login", "log in", "sign in",
        "app.sumo", "saas", "software", "platform", "product tour",
    ],
    "local_service": [
        "book an appointment", "book now", "schedule", "call us", "call today",
        "free quote", "get a quote", "request a quote", "emergency",
        "serving", "areas we serve", "our service area", "licensed",
        "insured", "certified", "years of experience", "same day",
        "opening hours", "hours of operation", "directions", "find us",
        "google maps", "yelp", "tripadvisor", "zomato", "opentable",
    ],
    "agency_creative": [
        "our work", "case studies", "portfolio", "client results",
        "what we do", "our services", "our process", "let's talk",
        "book a call", "discovery call", "get a proposal", "start a project",
        "branding", "web design", "digital marketing", "seo agency",
        "creative agency", "growth agency", "performance marketing",
    ],
    "b2b_corporate": [
        "enterprise", "b2b", "solutions", "industries", "our clients",
        "request a demo", "contact sales", "speak to sales", "whitepaper",
        "ebook", "download", "webinar", "case study", "roi calculator",
        "compliance", "security", "sla", "dedicated account manager",
        "procurement", "rfp",
    ],
    "content_blog": [
        "subscribe", "newsletter", "latest articles", "read more",
        "latest posts", "categories", "tags", "author", "published",
        "comments", "share this", "follow us", "rss", "/tag/", "/category/",
        "pagination", "next post", "previous post", "wordpress", "ghost",
        "substack", "medium",
    ],
    "nonprofit": [
        "donate", "donation", "donate now", "support us", "give",
        "fundraising", "charity", "nonprofit", "non-profit", "ngo",
        "volunteer", "mission", "our cause", "impact", "beneficiaries",
        "grant", "foundation", "registered charity",
    ],
    "portfolio": [
        "hire me", "available for hire", "freelance", "my work",
        "selected work", "projects", "dribbble", "behance", "codepen",
        "github.com", "resume", "cv", "download cv", "about me",
        "i'm a", "i am a", "based in", "let's work together",
    ],
}

# URL path signals per site type
_URL_SIGNALS: dict[str, list[str]] = {
    "ecommerce":       ["/shop", "/store", "/product", "/cart", "/checkout", "/collection"],
    "saas":            ["/pricing", "/features", "/integrations", "/changelog", "/docs", "/api"],
    "local_service":   ["/book", "/booking", "/appointment", "/location", "/directions", "/menu"],
    "agency_creative": ["/work", "/portfolio", "/case-studies", "/process", "/clients"],
    "b2b_corporate":   ["/solutions", "/industries", "/enterprise", "/partners", "/resources"],
    "content_blog":    ["/blog", "/articles", "/news", "/magazine", "/tag", "/category", "/author"],
    "nonprofit":       ["/donate", "/volunteer", "/mission", "/impact", "/give", "/cause"],
    "portfolio":       ["/projects", "/work", "/resume", "/cv", "/hire", "/commission"],
}

# Scoring weights: each matched signal adds this many points
_HTML_WEIGHT = 1
_URL_WEIGHT  = 2   # URL path matches are stronger signals


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class SiteClassification:
    site_type:   str                    # one of SITE_TYPES
    label:       str                    # human-readable label
    description: str                    # one-line description
    confidence:  float                  # 0.0 – 1.0
    scores:      dict = field(repr=False, default_factory=dict)  # raw scores per type

    @property
    def is_ecommerce(self) -> bool:
        return self.site_type == "ecommerce"

    @property
    def is_saas(self) -> bool:
        return self.site_type == "saas"

    @property
    def is_local(self) -> bool:
        return self.site_type == "local_service"


# --------------------------------------------------------------------------- #
# Classifier
# --------------------------------------------------------------------------- #

def classify_site(
    homepage_html: str,
    homepage_text: str,
    all_links: list[str],
) -> SiteClassification:
    """
    Score each site type against the homepage HTML, text, and all internal
    links, then return the best-matching SiteClassification.

    Parameters
    ----------
    homepage_html : lowercased raw HTML of the homepage
    homepage_text : lowercased visible text of the homepage
    all_links     : list of absolute internal href strings from the homepage
    """
    combined = (homepage_html[:80_000] + " " + homepage_text[:20_000]).lower()
    link_str = " ".join(all_links).lower()

    scores: dict[str, float] = {t: 0.0 for t in SITE_TYPES}

    for site_type, signals in _HTML_SIGNALS.items():
        for signal in signals:
            if signal in combined:
                scores[site_type] += _HTML_WEIGHT

    for site_type, patterns in _URL_SIGNALS.items():
        for pattern in patterns:
            if pattern in link_str:
                scores[site_type] += _URL_WEIGHT

    # Normalise
    max_score = max(scores.values()) if scores else 1
    if max_score == 0:
        # No signals matched at all — default to local_service (most common SMB)
        best = "local_service"
        confidence = 0.1
    else:
        best = max(scores, key=lambda t: scores[t])
        second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
        # Confidence = how much better the winner is vs the runner-up
        confidence = round(min(1.0, (scores[best] - second) / max(scores[best], 1) + 0.4), 2)

    return SiteClassification(
        site_type   = best,
        label       = SITE_TYPE_LABELS[best],
        description = SITE_TYPE_DESCRIPTIONS[best],
        confidence  = confidence,
        scores      = scores,
    )