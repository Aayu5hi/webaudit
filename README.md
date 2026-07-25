# Website Audit Agent

This is an AI-powered website auditing tool that analyses websites across conversion, UX, trust, SEO, and marketing best practices, then generates professional client-ready reports in both PDF and interactive web formats.

Unlike generic website analysers, this project first classifies the website (e-commerce, SaaS, agency, local business, blog, etc.) then adapts its evaluation criteria accordingly. For example, missing product CTAs matter for an online store but not for a blog, while lead-generation expectations differ between service businesses and portfolios.

The project combines traditional rule-based analysis, technical SEO metrics, and multimodal LLM evaluation to produce a comprehensive website audit suitable for agency sales, client onboarding, and website reviews.

---

## Features

- Automatic website crawling with asynchronous page fetching
- Site-type-aware auditing across 21 checks in 8 categories
- AI evaluation of messaging, first impression, and visual design
- Technical SEO analysis using Lighthouse/PageSpeed Insights
- Rule-based detection for UX, trust, lead generation, mobile, and SEO issues
- Weighted scoring engine with category and overall scores
- Executive summary generated using an LLM
- Professional PDF report generation
- Interactive browser interface powered by Flask

---

## Architecture

```
URL
 │
 ▼
Async crawler
 │
 ▼
HTML extraction
 │
 ▼
Website classification
 │
 ├── Rule-based analysis
 ├── Technical SEO
 ├── Screenshot capture
 └── AI qualitative analysis
          │
          ▼
   Scoring engine
          │
          ▼
Narrative summary
          │
          ▼
 PDF + Web report
```

---

## Project Structure

| File | Responsibility |
|------|----------------|
| `main.py` | Audit pipeline orchestrator |
| `server.py` | Flask web interface |
| `fetcher.py` | Asynchronous crawler |
| `extractors.py` | HTML parsing and structured extraction |
| `site_classifier.py` | Website type classification |
| `detectors.py` | Rule-based audit checks |
| `seo_technical.py` | Lighthouse and technical SEO analysis |
| `ai_analysis.py` | LLM-powered qualitative analysis |
| `scoring.py` | Category and overall scoring |
| `pdf_report.py` | PDF generation |
| `screenshot.py` | Homepage screenshot capture |
| `config.py` | Configuration and scoring rules |

---

## Running the Project

Clone the repository & Install dependencies:

```bash
git clone https://github.com/<username>/...
pip install -r requirements.txt
```

Create a `.env` file:

```env
OPENAI_API_KEY=your_api_key
```

### CLI

```bash
python main.py
```

### Web Interface

```bash
python server.py
```

Then open:

```
http://127.0.0.1:5000
```

---

## Optional Dependencies

Some functionality is optional and degrades gracefully when unavailable.

| Dependency | Purpose |
|-----------|---------|
| Playwright | Homepage screenshot capture for visual AI analysis |
| PageSpeed Insights API | Lighthouse metrics |
| advertools | `robots.txt` and sitemap analysis |
| extruct | Structured data extraction |

---

## Tech Stack

- Python
- Asyncio & aiohttp
- Flask
- BeautifulSoup
- OpenAI API
- Playwright
- Google PageSpeed Insights
- ReportLab

---

## Notes

- AI analysis requires an OpenAI API key.
- Technical SEO analysis benefits from a PageSpeed Insights API key but can run without one.
- The included Flask server is intended for local development and demonstration purposes.
- It does not include production features such as authentication or rate limiting and should not be used as-is in a production deployment.

---

## Licence

This project is provided for educational and portfolio purposes.