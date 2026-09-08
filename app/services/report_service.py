import io
import logging
import time
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.core.config import settings
from app.prompts import analysis_prompts
from app.services.analysis_service import _parse_llm_json
from app.services.vllm_service import call_vllm_api_streamed

logger = logging.getLogger(__name__)

SUMMARY_MAX_TOKENS = 2048
# Per-issue char budget in the findings digest sent to the LLM, so a huge
# issue list still fits comfortably alongside the prompt template.
DIGEST_DESCRIPTION_CHARS = 400

VALID_GRADES = ("Critical Risk", "High Risk", "Moderate Risk", "Low Risk")

GRADE_COLORS = {
    "Critical Risk": colors.HexColor("#b91c1c"),
    "High Risk": colors.HexColor("#dc2626"),
    "Moderate Risk": colors.HexColor("#ea580c"),
    "Low Risk": colors.HexColor("#16a34a"),
}

SEVERITY_COLORS = {
    "High": colors.HexColor("#dc2626"),
    "Medium": colors.HexColor("#ea580c"),
    "Low": colors.HexColor("#16a34a"),
}


def _hex(color) -> str:
    """reportlab Color -> '#rrggbb' for inline <font color=...> markup."""
    return "#" + color.hexval()[2:]


def _severity_counts(issues: list) -> dict:
    counts = {"High": 0, "Medium": 0, "Low": 0}
    for issue in issues:
        severity = issue.get("severity")
        if severity in counts:
            counts[severity] += 1
    return counts


def _findings_digest(issues: list) -> str:
    """Compact plain-text rendering of the findings for the summary prompt."""
    if not issues:
        return "No security issues were found."
    lines = []
    for idx, issue in enumerate(issues, start=1):
        description = (issue.get("description") or "")[:DIGEST_DESCRIPTION_CHARS]
        strategy = (issue.get("strategy") or "")[:DIGEST_DESCRIPTION_CHARS]
        lines.append(
            f"{idx}. [{issue.get('severity', 'Medium')}] {issue.get('title', 'Security Finding')} "
            f"(file: {issue.get('file', 'unknown')})\n"
            f"   Description: {description}\n"
            f"   Remediation: {strategy}"
        )
    return "\n".join(lines)


def _fallback_summary(issues: list) -> dict:
    """Deterministic summary derived from severity counts, used when the LLM
    call fails or returns an unparseable reply — the PDF must still download."""
    counts = _severity_counts(issues)
    total = len(issues)

    if counts["High"] >= 3:
        grade, score = "Critical Risk", 25
    elif counts["High"] >= 1:
        grade, score = "High Risk", 45
    elif counts["Medium"] >= 1:
        grade, score = "Moderate Risk", 70
    else:
        grade, score = "Low Risk", 95

    if total == 0:
        summary = ("The audit did not identify any security issues in the analyzed "
                   "configurations. The reviewed rule sets appear consistent with the "
                   "selected policy framework.")
    else:
        summary = (
            f"The audit identified {total} finding(s) across the analyzed configurations: "
            f"{counts['High']} high, {counts['Medium']} medium, and {counts['Low']} low "
            f"severity. Detailed context and remediation guidance for each finding are "
            f"listed in the sections below. (An AI-generated executive summary was not "
            f"available for this report.)"
        )

    actions = []
    for severity in ("High", "Medium", "Low"):
        for issue in issues:
            if issue.get("severity") == severity and issue.get("strategy"):
                actions.append(issue["strategy"])
            if len(actions) >= 10:
                break
        if len(actions) >= 10:
            break

    return {
        "executive_summary": summary,
        "overall_rating": {
            "grade": grade,
            "score": score,
            "justification": f"Derived from the severity distribution of the {total} finding(s).",
        },
        "recommended_actions": actions or ["Maintain the current configuration baseline."],
    }


def _sanitize_summary(parsed: dict, issues: list) -> dict:
    """Validates the LLM reply, patching any invalid field from the fallback."""
    fallback = _fallback_summary(issues)

    if not isinstance(parsed.get("executive_summary"), str) or not parsed["executive_summary"].strip():
        parsed["executive_summary"] = fallback["executive_summary"]

    rating = parsed.get("overall_rating")
    if not isinstance(rating, dict):
        rating = fallback["overall_rating"]
    if rating.get("grade") not in VALID_GRADES:
        rating["grade"] = fallback["overall_rating"]["grade"]
    try:
        rating["score"] = max(0, min(100, int(rating.get("score"))))
    except (TypeError, ValueError):
        rating["score"] = fallback["overall_rating"]["score"]
    if not isinstance(rating.get("justification"), str):
        rating["justification"] = ""
    parsed["overall_rating"] = rating

    actions = parsed.get("recommended_actions")
    if not isinstance(actions, list) or not actions:
        actions = fallback["recommended_actions"]
    parsed["recommended_actions"] = [str(a) for a in actions if str(a).strip()][:10]

    return parsed


async def _generate_summary(issues: list, framework: str) -> dict:
    """One LLM call producing executive_summary / overall_rating /
    recommended_actions; falls back to a deterministic summary on failure."""
    prompt = analysis_prompts.REPORT_SUMMARY_PROMPT.format(
        framework=framework, findings=_findings_digest(issues))
    payload = {
        "model": settings.VLLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": SUMMARY_MAX_TOKENS,
    }
    try:
        response_json = await call_vllm_api_streamed(payload)
        parsed = _parse_llm_json(response_json["choices"][0]["message"]["content"])
        if parsed is None:
            logger.warning("Report summary reply was not valid JSON; using fallback summary")
            return _fallback_summary(issues)
        return _sanitize_summary(parsed, issues)
    except Exception as e:
        logger.error(f"Report summary LLM call failed: {e}; using fallback summary")
        return _fallback_summary(issues)


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=base["Title"], fontSize=22, leading=26,
            textColor=colors.HexColor("#111827"), spaceAfter=4),
        "meta": ParagraphStyle(
            "Meta", parent=base["Normal"], fontSize=9, leading=12,
            textColor=colors.HexColor("#6b7280")),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontSize=14, leading=18,
            textColor=colors.HexColor("#111827"), spaceBefore=18, spaceAfter=8),
        "h3": ParagraphStyle(
            "H3", parent=base["Heading3"], fontSize=11, leading=14,
            textColor=colors.HexColor("#111827"), spaceBefore=12, spaceAfter=4),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=10, leading=15,
            textColor=colors.HexColor("#1f2937"), spaceAfter=8),
        "small": ParagraphStyle(
            "Small", parent=base["Normal"], fontSize=8.5, leading=12,
            textColor=colors.HexColor("#4b5563")),
        "grade": ParagraphStyle(
            "Grade", parent=base["Normal"], fontSize=16, leading=20,
            alignment=TA_CENTER, textColor=colors.white, fontName="Helvetica-Bold"),
        "score": ParagraphStyle(
            "Score", parent=base["Normal"], fontSize=10, leading=14,
            alignment=TA_CENTER, textColor=colors.white),
    }


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#9ca3af"))
    canvas.drawString(0.75 * inch, 0.5 * inch, "Defense Halo — Security Audit Report")
    canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _rating_block(rating: dict, styles: dict):
    grade = rating["grade"]
    color = GRADE_COLORS.get(grade, GRADE_COLORS["Moderate Risk"])
    cell = [
        Paragraph(escape(grade).upper(), styles["grade"]),
        Spacer(1, 2),
        Paragraph(f"Score: {rating['score']} / 100", styles["score"]),
    ]
    table = Table([[cell]], colWidths=[3.2 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    return table


def _overview_table(issues: list, styles: dict):
    counts = _severity_counts(issues)
    header = [Paragraph(f"<b>{h}</b>", styles["small"])
              for h in ("High Severity", "Medium Severity", "Low Severity", "Total Findings")]
    row = []
    for severity in ("High", "Medium", "Low"):
        row.append(Paragraph(
            f'<font color="{_hex(SEVERITY_COLORS[severity])}"><b>{counts[severity]}</b></font>',
            styles["body"]))
    row.append(Paragraph(f"<b>{len(issues)}</b>", styles["body"]))
    table = Table([header, row], colWidths=[1.7 * inch] * 4)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _files_table(file_metadata: list, styles: dict):
    header = [Paragraph(f"<b>{h}</b>", styles["small"])
              for h in ("File", "Vendor", "OS", "Version")]
    rows = [header]
    for meta in file_metadata:
        rows.append([
            Paragraph(escape(str(meta.get("file", "—"))), styles["small"]),
            Paragraph(escape(str(meta.get("vendor", "—"))), styles["small"]),
            Paragraph(escape(str(meta.get("os", "—"))), styles["small"]),
            Paragraph(escape(str(meta.get("version", "—"))), styles["small"]),
        ])
    table = Table(rows, colWidths=[3.1 * inch, 1.3 * inch, 1.3 * inch, 1.1 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _build_pdf(summary: dict, issues: list, file_metadata: list, framework: str) -> bytes:
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.9 * inch,
        title="Security Audit Report", author="Defense Halo Config Analyzer")

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story = [
        Paragraph("Security Audit Report", styles["title"]),
        Paragraph(f"Framework: {escape(framework)} &nbsp;|&nbsp; Generated: {generated} "
                  f"&nbsp;|&nbsp; Findings: {len(issues)}", styles["meta"]),
        Spacer(1, 10),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb")),

        Paragraph("Overall Rating", styles["h2"]),
        _rating_block(summary["overall_rating"], styles),
    ]
    justification = summary["overall_rating"].get("justification")
    if justification:
        story.append(Spacer(1, 6))
        story.append(Paragraph(escape(justification), styles["body"]))

    story.append(Paragraph("Executive Summary", styles["h2"]))
    for paragraph in summary["executive_summary"].split("\n\n"):
        if paragraph.strip():
            story.append(Paragraph(escape(paragraph.strip()), styles["body"]))

    story.append(Paragraph("Findings Overview", styles["h2"]))
    story.append(_overview_table(issues, styles))
    if file_metadata:
        story.append(Paragraph("Analyzed Configurations", styles["h3"]))
        story.append(_files_table(file_metadata, styles))

    story.append(Paragraph("Recommended Actions", styles["h2"]))
    story.append(ListFlowable(
        [ListItem(Paragraph(escape(action), styles["body"]), leftIndent=6)
         for action in summary["recommended_actions"]],
        bulletType="1", bulletFontSize=10, leftIndent=18))

    if issues:
        story.append(Paragraph("Detailed Findings", styles["h2"]))
        for idx, issue in enumerate(issues, start=1):
            severity = issue.get("severity", "Medium")
            color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["Medium"])
            story.append(Paragraph(
                f'{idx}. {escape(issue.get("title", "Security Finding"))} '
                f'<font color="{_hex(color)}">[{escape(severity)}]</font>',
                styles["h3"]))
            story.append(Paragraph(
                f'File: {escape(str(issue.get("file", "multiple")))}', styles["small"]))
            if issue.get("description"):
                story.append(Paragraph(escape(issue["description"]), styles["body"]))
            if issue.get("strategy"):
                story.append(Paragraph(
                    f'<b>Remediation:</b> {escape(issue["strategy"])}', styles["body"]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


async def generate_report(issues: list, file_metadata: list, framework: str) -> bytes:
    """Builds the full audit report PDF: one LLM call for the executive
    section, then reportlab rendering. Never raises for LLM problems — the
    deterministic fallback keeps the download working."""
    start = time.time()
    logger.info(f"Generating PDF report: framework={framework} issues={len(issues)}")
    summary = await _generate_summary(issues, framework)
    pdf = _build_pdf(summary, issues, file_metadata, framework)
    logger.info(f"PDF report generated: {len(pdf)} bytes in {time.time() - start:.2f}s")
    return pdf
