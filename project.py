from openai import OpenAI
from dotenv import load_dotenv
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import time

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

url = input("Enter website URL: ")
domain = urlparse(url).netloc

# --- STEP 1: FETCH HOMEPAGE ---
try:
    headers = {
    "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, headers=headers, timeout=8)
    soup = BeautifulSoup(response.text, "html.parser")
except:
    print("Failed to fetch website")
    exit()

# --- STEP 2: EXTRACT INTERNAL LINKS ---
links = set()

for a_tag in soup.find_all("a", href=True):
    full_url = urljoin(url, a_tag["href"])
    parsed = urlparse(full_url)

    clean_url = full_url.split("?")[0]

    if (
        parsed.netloc == domain
        and not parsed.fragment
        and not clean_url.startswith("mailto:")
        and not clean_url.startswith("tel:")
    ):
        links.add(clean_url)

links = list(links)[:5]

print(f"\nFound {len(links)} internal pages to analyze...\n")

# --- EXTRACT STRUCTURED DATA ---
def extract_data(page_url):
    try:
        res = requests.get(page_url, headers=headers, timeout=8)
        soup = BeautifulSoup(res.text, "html.parser")

        title = soup.title.string.strip() if soup.title else ""

        meta = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag:
            meta = meta_tag.get("content", "").strip()

        h1 = [h.text.strip() for h in soup.find_all("h1")]
        text = soup.get_text().lower()

        links = []
        for a in soup.find_all("a", href=True):
            links.append(urljoin(page_url, a["href"]))

        return {
            "url": page_url,
            "title": title,
            "meta": meta,
            "h1": h1,
            "text": text,
            "soup": soup,
            "links": links
        }

    except:
        return None

# --- PAGE TYPE DETECTION ---
def get_page_type(url):
    if "/product" in url:
        return "product"
    elif "/collection" in url:
        return "collection"
    elif "/pages/" in url:
        return "policy"
    else:
        return "general"
    
# --- CTA DETECTION (HYBRID) ---
def check_cta(data):
    soup = data["soup"]
    text = data["text"]
    html = str(data["soup"]).lower()

    import re

    score = 0

    # -----------------------------
    # 1. CLASS-BASED CTA DETECTION (REAL WORLD)
    # -----------------------------
    cta_class_signals = [
        "add-to-cart",
        "addtocart",
        "buy-now",
        "buynow",
        "checkout",
        "product-form__submit",
        "shopify-payment-button",
        "btn-primary",
        "button--add",
        "product__cart"
    ]

    for tag in soup.find_all(["a", "button"]):
        classes = " ".join(tag.get("class", [])).lower()

        if any(sig in classes for sig in cta_class_signals):
            score += 3
            break

    # -----------------------------
    # 2. FORM-BASED CTA DETECTION (IMPORTANT FOR SHOPIFY)
    # -----------------------------
    forms = soup.find_all("form")
    if forms:
        for form in forms:
            action = form.get("action", "").lower()
            if "cart" in action or "checkout" in action:
                score += 2
                break

    # -----------------------------
    # 3. BUTTON TEXT INTENT DETECTION
    # -----------------------------
    cta_text_patterns = [
        r"\badd to cart\b",
        r"\bbuy now\b",
        r"\bshop now\b",
        r"\bcheckout\b",
        r"\border now\b",
        r"\bget yours\b",
        r"\bbuy\b"
    ]

    button_texts = " ".join([b.get_text(" ", strip=True).lower() for b in soup.find_all(["button", "a"])])

    if any(re.search(p, button_texts) for p in cta_text_patterns):
        score += 2

    # -----------------------------
    # 4. VISUAL CTA SIGNALS (GENERIC BUTTON CLASSES)
    # -----------------------------
    for tag in soup.find_all(["a", "button"]):
        classes = " ".join(tag.get("class", [])).lower()

        if "btn" in classes or "button" in classes:
            score += 1
            break

    # -----------------------------
    # 5. PAGE TYPE ADJUSTMENT (IMPORTANT)
    # -----------------------------
    page_type = get_page_type(data["url"])

    # stricter expectations for product pages
    if page_type == "product":
        threshold = 3
    else:
        threshold = 2

    # -----------------------------
    # FINAL DECISION
    # -----------------------------
    if score < threshold:
        return f"[HIGH] Weak or missing CTA on {data['url']}"

    return None

# --- SOCIAL PROOF DETECTION (HYBRID) ---
def check_social_proof(data):
    soup = data["soup"]
    text = data["text"]
    html = str(data["soup"]).lower()

    import re

    score = 0

    # -----------------------------
    # 1. REVIEW APP DETECTION (SHOPIFY REAL WORLD)
    # -----------------------------
    review_apps = [
        "judgeme",
        "loox",
        "yotpo",
        "stamped",
        "reviews.io",
        "shopify-product-reviews"
    ]

    if any(app in html for app in review_apps):
        score += 2

    # -----------------------------
    # 2. SCHEMA.ORG REVIEW DETECTION
    # -----------------------------
    if "aggregateRating" in html or "reviewcount" in html:
        score += 2

    # -----------------------------
    # 3. RATING PATTERNS (VISIBLE OR TEXT)
    # -----------------------------
    rating_patterns = [
        r"\b\d(\.\d)?\s*/\s*5\b",
        r"\b\d(\.\d)?\s*stars?\b",
        r"★{3,5}",
        r"\b\d+\+?\s*reviews?\b",
        r"rated\s*\d(\.\d)?"
    ]

    if any(re.search(p, text.lower()) for p in rating_patterns):
        score += 1

    # -----------------------------
    # 4. TRUST SIGNALS
    # -----------------------------
    trust_patterns = [
        r"\b\d{2,}\+?\s*(customers|orders|buyers|people)\b",
        r"trusted by",
        r"best\s*seller",
        r"bestselling",
        r"join\s+\d{2,}\+"
    ]

    if any(re.search(p, text.lower()) for p in trust_patterns):
        score += 1

    # -----------------------------
    # 5. TESTIMONIAL STRUCTURE (WEAK BUT USEFUL)
    # -----------------------------
    for tag in soup.find_all(["p", "div", "span"]):
        txt = tag.get_text(" ", strip=True)

        if len(txt.split()) > 15 and txt.count('"') >= 2:
            score += 1
            break

    # -----------------------------
    # FINAL DECISION (SMART THRESHOLD)
    # -----------------------------
    page_type = get_page_type(data["url"])

    # IMPORTANT: LOWER FALSE POSITIVES FOR SHOPIFY PRODUCT PAGES
    if page_type == "product":
        threshold = 2
    else:
        threshold = 1

    if score < threshold:
        return f"[HIGH] No detectable social proof on {data['url']}"

    return None

def check_broken_links(links):
    broken = []

    for link in links[:15]:
        if link.startswith("mailto:") or link.startswith("tel:"):
            continue
        if "#" in link:
            continue
        if urlparse(link).netloc != domain:
            continue

        try:
            r = requests.get(link, headers=headers, timeout=5)
            if r.status_code >= 400:
                broken.append(link)
        except:
            broken.append(link)

    return broken

# --- BASIC SEO ---
def check_basic_seo(data):
    issues = []

    if not data["title"]:
        issues.append(f"[LOW] Missing title on {data['url']}")

    if not data["meta"]:
        issues.append(f"[LOW] Missing meta description on {data['url']}")

    if len(data["h1"]) == 0:
        issues.append(f"[MEDIUM] No H1 tag on {data['url']}")

    return issues

# --- STEP 3: RUN ANALYSIS ---
#all issues
seo_issues = []
ux_issues = []
conversion_issues = []

for link in links:
    print(f"Analyzing: {link}")
    time.sleep(1)

    data = extract_data(link)

    if not data:
        continue

    page_type = get_page_type(data["url"])

    # --- RUN DETECTORS ---
    cta_issue = check_cta(data)
    social_issue = check_social_proof(data)
    broken_links = check_broken_links(data["links"])

    # --- SEO ISSUES ---
    seo_issues.extend(check_basic_seo(data))

    # --- UX ISSUES ---
    if broken_links:
        ux_issues.append(f"[MEDIUM] {len(broken_links)} broken links on {data['url']}")

    # --- CONVERSION ISSUES ---
    if cta_issue:
        conversion_issues.append(cta_issue)

    if social_issue:
        conversion_issues.append(social_issue)


def calculate_score(issues, base=100):
    score = base

    high_count = 0
    medium_count = 0
    low_count = 0

    for issue in issues:
        if "[HIGH]" in issue:
            high_count += 1
        elif "[MEDIUM]" in issue:
            medium_count += 1
        elif "[LOW]" in issue:
            low_count += 1

    # weighted scoring
    score -= high_count * 15
    score -= medium_count * 7
    score -= low_count * 3

    return max(0, min(100, score))

seo_score = calculate_score(seo_issues)
ux_score = calculate_score(ux_issues)
conversion_score = calculate_score(conversion_issues)


# --- STEP 4: AI EXPLANATION ---

issues_text = f"""
SEO ISSUES:
{chr(10).join(seo_issues)}

UX ISSUES:
{chr(10).join(ux_issues)}

CONVERSION ISSUES:
{chr(10).join(conversion_issues)}

SCORES:
SEO: {seo_score}/100
UX: {ux_score}/100
Conversion: {conversion_score}/100
"""

prompt = f"""
You are a senior website auditing expert.

You are given structured audit data.

Your job:
1. Explain issues in simple non-technical language
2. Group related problems together
3. Focus MOST on conversion issues (CTA + social proof)
4. Prioritize HIGH impact problems first
5. Keep it concise and actionable (like a SaaS audit tool)

DATA:
{issues_text}
"""
try:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    # --- OUTPUT ---
    print("\n--- RAW ISSUES ---\n")

    print("\nSEO ISSUES:")
    for issue in seo_issues:
        print("-", issue)

    print("\nUX ISSUES:")
    for issue in ux_issues:
        print("-", issue)

    print("\nCONVERSION ISSUES:")
    for issue in conversion_issues:
        print("-", issue)

    print("\n--- SCORES ---")
    print("SEO:", seo_score)
    print("UX:", ux_score)
    print("Conversion:", conversion_score)

    print("\n--- AI AUDIT REPORT ---\n")
    print(response.choices[0].message.content)

except Exception as e:
    print("\n⚠️ AI analysis failed (network issue)")
    print("Error:", e)
    print("\nBut your raw audit still works perfectly 👇")