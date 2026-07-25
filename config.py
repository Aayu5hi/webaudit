# =============================================================================
# config.py — All tunable constants for the Web Audit Agent
# =============================================================================

# --------------------------------------------------------------------------- #
# HTTP & NETWORK
# --------------------------------------------------------------------------- #
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT     = 12   # seconds per page fetch (aiohttp)
BROKEN_LINK_TIMEOUT = 6    # seconds per HEAD request
MAX_LINKS_TO_CHECK  = 20   # max links tested for 404s per page

# --------------------------------------------------------------------------- #
# CRAWL SETTINGS
# --------------------------------------------------------------------------- #
TARGET_PAGE_TYPES = ["homepage", "service", "about", "contact", "blog"]

PAGE_TYPE_PATTERNS = {
    "service": [
        "/service", "/services", "/product", "/products", "/solutions",
        "/solution", "/offering", "/what-we-do", "/work", "/portfolio",
        "/shop", "/store", "/collection", "/features", "/pricing",
    ],
    "about": [
        "/about", "/about-us", "/team", "/our-team", "/who-we-are",
        "/company", "/story", "/our-story", "/mission",
    ],
    "contact": [
        "/contact", "/contact-us", "/get-in-touch", "/reach-us",
        "/hire-us", "/book", "/schedule", "/appointment",
    ],
    "blog": [
        "/blog", "/news", "/articles", "/insights", "/resources",
        "/journal", "/updates", "/posts", "/magazine",
    ],
}

# --------------------------------------------------------------------------- #
# SCREENSHOT & VISUALS
# --------------------------------------------------------------------------- #
SCREENSHOT_HERO_HEIGHT  = 800  # px
SCREENSHOT_WIDTH        = 1280 # px
SCREENSHOT_JPEG_QUALITY = 72

# --------------------------------------------------------------------------- #
# SCORING WEIGHTS
# --------------------------------------------------------------------------- #
SCORE_WEIGHTS = {
    "HIGH":   15,
    "MEDIUM":  7,
    "LOW":     3,
}

# --------------------------------------------------------------------------- #
# CTA DETECTION (SITE-AWARE)
# --------------------------------------------------------------------------- #
CTA_CLASS_SIGNALS_BY_TYPE = {
    "ecommerce": [
        "add-to-cart","addtocart","buy-now","buynow","checkout",
        "product-form__submit","shopify-payment-button",
        "btn-primary","button--add","cta","cta-button","atc-btn","product__submit",
    ],
    "saas": [
        "btn-primary","cta","cta-button","btn-cta","trial-btn",
        "demo-btn","signup-btn","get-started","hero-cta","primary-btn",
    ],
    "local_service": [
        "btn-primary","cta","cta-button","book-btn",
        "quote-btn","call-btn","contact-btn","appointment-btn",
    ],
    "agency_creative": ["btn-primary","cta","cta-button","hero-cta","proposal-btn","contact-btn","lets-talk"],
    "b2b_corporate": ["btn-primary","cta","cta-button","demo-btn","contact-sales","request-demo","download-btn"],
    "content_blog": ["subscribe-btn","newsletter-btn","cta","btn-primary","follow-btn"],
    "nonprofit": ["donate-btn","donation-btn","cta","btn-primary","volunteer-btn","give-btn"],
    "portfolio": ["hire-btn","contact-btn","cta","btn-primary","work-btn"],
}

CTA_CLASS_SIGNALS = [
    "add-to-cart","addtocart","buy-now","buynow","checkout",
    "product-form__submit","shopify-payment-button",
    "btn-primary","button--add","cta","cta-button",
]

CTA_TEXT_PATTERNS_BY_TYPE = {
    "ecommerce": [r"\badd to cart\b",r"\bbuy now\b",r"\bshop now\b",r"\bcheckout\b",r"\border now\b"],
    "saas": [r"\bstart\s+(free\s+)?trial\b",r"\bget started\b",r"\bbook\s+a?\s*(demo|call)\b",r"\bsign\s+up\b"],
    "local_service": [r"\bbook\s*(now|online)?\b",r"\bget\s+a\s+(free\s+)?(quote|estimate)\b",r"\bcall\s*now\b"],
    "agency_creative": [r"\bproposal\b", r"\blet['']?s\s+talk\b", r"\bwork\s+with\s+us\b"],
    "b2b_corporate": [r"\brequest\s+demo\b", r"\bcontact\s+sales\b", r"\bspeak\s+to\s+expert\b"],
    "content_blog": [r"\bsubscribe\b", r"\bnewsletter\b", r"\bread\s+more\b"],
    "nonprofit": [r"\bdonate\b", r"\bgive\s*now\b", r"\bvolunteer\b"],
    "portfolio": [r"\bhire\s+me\b", r"\bview\s+work\b", r"\bcontact\s+me\b"],
}

CTA_TEXT_PATTERNS = [
    r"\badd to cart\b",r"\bbuy now\b",r"\bshop now\b",r"\bcheckout\b",
    r"\border now\b",r"\bget started\b",r"\bbook\s*(a|now|free|call|demo)?\b",
    r"\bschedule\b",r"\bget\s+a\s+(quote|demo|proposal)\b",
]

CTA_THRESHOLDS_BY_SITE = {
    "ecommerce":       {"product": 3, "service": 3, "homepage": 2, "default": 2},
    "saas":            {"service": 3, "homepage": 3, "default": 2},
    "local_service":   {"homepage": 2, "contact": 2, "default": 2},
    "agency_creative": {"homepage": 2, "service": 2, "default": 2},
    "b2b_corporate":   {"homepage": 2, "service": 3, "default": 2},
    "content_blog":    {"homepage": 1, "default": 1},
    "nonprofit":       {"homepage": 2, "default": 1},
    "portfolio":       {"homepage": 1, "default": 1},
}

CTA_THRESHOLDS = {"product": 3, "service": 3, "default": 2}

# --------------------------------------------------------------------------- #
# TRUST & SOCIAL PROOF
# --------------------------------------------------------------------------- #
REVIEW_APP_SIGNATURES = [
    "judgeme","loox","yotpo","stamped","reviews.io",
    "shopify-product-reviews","trustpilot","g2.com",
    "capterra","clutch.co","birdeye","podium","grade.us",
]

RATING_PATTERNS = [
    r"\b\d(\.\d)?\s*/\s*5\b", r"\b\d(\.\d)?\s*stars?\b", r"★{3,5}",
    r"\b\d+\+?\s*reviews?\b", r"rated\s*\d(\.\d)?", r"\b\d+\+?\s*ratings?\b",
]

TRUST_PATTERNS = [
    r"\b\d{2,}\+?\s*(customers?|clients?|orders?|buyers?|businesses?|companies|users?|members?)\b",
    r"trusted by", r"best[\s-]?seller", r"join\s+\d{2,}\+",
    r"award[\s-]?winning", r"featured\s+in", r"as\s+seen\s+in",
]

SOCIAL_PROOF_THRESHOLDS_BY_SITE = {
    "ecommerce": 2, "saas": 2, "local_service": 1, "agency_creative": 2,
    "b2b_corporate": 2, "content_blog": 0, "nonprofit": 1, "portfolio": 1,
}

RESULTS_PROOF_PATTERNS = {
    "ecommerce": [r"\b\d+\+?\s*(reviews?|ratings?|customers?)\b", r"\bbest[\s-]?seller\b"],
    "saas": [r"\bg2\b", r"\bcapterra\b", r"\bproduct hunt\b", r"\b\d+%\s*(faster|more|better)\b"],
    "local_service": [r"\b\d+\+?\s*years\b", r"\bfully\s+(licensed|insured|certified)\b"],
    "agency_creative": [r"\bcase stud(y|ies)\b", r"\baward[\s-]?winning\b", r"\bfeatured\s+in\b"],
    "b2b_corporate": [r"\broi\b", r"\bsoc\s*2\b", r"\biso\s*\d+\b", r"\bcase stud(y|ies)\b"],
    "nonprofit": [r"\b\$[\d,]+\s+raised\b", r"\bimpact\s+report\b"],
    "portfolio": [r"\b\d+\+?\s*projects\b", r"testimonial"],
    "content_blog": [r"\b\d+\+?\s*readers\b", r"\bpress\b"],
}

RESULTS_PROOF_PATTERNS_DEFAULT = [
    r"\bcase stud(?:y|ies)\b", r"\bfeatured in\b", r"\baward[\s-]?winning\b", r"\bresult[s]?\b"
]

# --------------------------------------------------------------------------- #
# MISSED OPPORTUNITIES (PIXELS & BLOG)
# --------------------------------------------------------------------------- #
PIXEL_SIGNATURES = [
    "connect.facebook.net","fbevents.js",
    "googletagmanager.com","gtag(","ga('create","google-analytics.com",
    "snap.licdn.com","_linkedin_partner_id","analytics.tiktok.com",
    "static.ads-twitter.com","twq(","static.hotjar.com","clarity.ms",
]

PIXEL_REQUIRED_BY_SITE = {
    "ecommerce": True, "saas": True, "local_service": True,
    "agency_creative": True, "b2b_corporate": True,
    "content_blog": False, "nonprofit": True, "portfolio": False,
}

BLOG_REQUIRED_BY_SITE = {
    "ecommerce": True, "saas": True, "local_service": True,
    "agency_creative": True, "b2b_corporate": True,
    "content_blog": False, "nonprofit": True, "portfolio": False,
}

# --------------------------------------------------------------------------- #
# AI MODELS
# --------------------------------------------------------------------------- #
AI_MODEL        = "gpt-4o"
AI_TEXT_MODEL   = "gpt-4o-mini"
AI_MAX_TOKENS   = 1200

# --------------------------------------------------------------------------- #
# EXTERNAL APIS & REPORTS
# --------------------------------------------------------------------------- #
PSI_API_KEY = None  # Add your Google PageSpeed Insights key here
REPORTS_DIR = "reports"