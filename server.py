# server.py — Flask web server bridging the HTML UI to the audit pipeline
import asyncio
import os
from datetime import datetime
from urllib.parse import urlparse
from dataclasses import asdict

from flask import Flask, request, jsonify, send_from_directory

# Import your existing pipeline exactly as main.py does
from main import _run_audit
from pdf_report import generate_pdf, TWENTY_ONE_CHECKS, _issue_affects_check
from config import REPORTS_DIR

app = Flask(__name__, static_folder=".")


# ── Serve the HTML page ──────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "audit_report_viewer.html")


# ── Main audit endpoint ──────────────────────────────────────────────────────
@app.route("/api/audit", methods=["POST"])
def run_audit():
    body         = request.get_json()
    url          = body.get("url", "").strip()
    prospect     = body.get("prospect", "").strip()
    agency       = body.get("agency", "Your Agency").strip()

    if not url:
        return jsonify({"error": "URL is required"}), 400
    if not url.startswith("http"):
        url = "https://" + url

    domain = urlparse(url).netloc

    # Run your existing async pipeline (unchanged)
    result = asyncio.run(_run_audit(url))
    if result is None:
        return jsonify({"error": "Could not fetch the website. Check the URL."}), 400

    all_issues, scores, quick_wins, narrative, tech_report = result

    # Build the checklist (same logic as pdf_report.py's _build_checklist_table)
    failing_checks = set()
    for issue in all_issues:
        for _, num, label, _ in TWENTY_ONE_CHECKS:
            if _issue_affects_check(issue, label):
                failing_checks.add(num)

    checklist = [
        {
            "num":    num,
            "cat":    cat,
            "label":  label,
            "method": method,
            "status": "fail" if num in failing_checks else "pass",
        }
        for cat, num, label, method in TWENTY_ONE_CHECKS
    ]

    # Serialise AuditIssue dataclasses to plain dicts
    issues_list = [
        {
            "severity":    i.severity,
            "category":    i.category,
            "title":       i.title,
            "description": i.description,
        }
        for i in all_issues
    ]

    # Optionally generate and save the PDF
    os.makedirs(REPORTS_DIR, exist_ok=True)
    safe_domain = domain.replace(".", "_").replace(":", "")
    pdf_path    = os.path.join(REPORTS_DIR, f"audit_{safe_domain}.pdf")
    try:
        generate_pdf(
            all_issues    = all_issues,
            scores        = scores,
            quick_wins    = quick_wins,
            narrative     = narrative,
            prospect_name = prospect or domain,
            website_url   = domain,
            agency_name   = agency,
            output_path   = pdf_path,
            cwv           = tech_report.cwv,
            lighthouse    = tech_report.lighthouse,
        )
        pdf_filename = f"audit_{safe_domain}.pdf"
    except Exception:
        pdf_filename = None

    return jsonify({
        "prospect":   prospect or domain,
        "url":        domain,
        "date":       datetime.now().strftime("%-d %B %Y"),
        "scores":     scores,
        "issues":     issues_list,
        "checklist":  checklist,
        "quick_wins": quick_wins,
        "narrative":  narrative,
        "pdf_file":   pdf_filename,
    })


# ── PDF download endpoint ────────────────────────────────────────────────────
@app.route("/download/<filename>")
def download_pdf(filename):
    return send_from_directory(REPORTS_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5000)