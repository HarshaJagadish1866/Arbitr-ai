"""
utils/reporter.py — Report Generation Utility
==============================================

PURPOSE & DESIGN:
    This module assembles the final LegalShield AI risk report from the outputs
    of all three agents and the security layer audit log.

    REPORT STRUCTURE:
    ┌─────────────────────────────────────────────┐
    │ Header: Title, timestamp, document metadata  │
    │ Executive Summary: Risk scores, counts       │
    │ PII Audit Log: What was redacted             │
    │ Document Overview: Type, clause count        │
    │ Protective Analysis: (from Protector Agent)  │
    │ Footer: Disclaimer                           │
    └─────────────────────────────────────────────┘

    The report is saved as a Markdown file in the `output/` directory with a
    timestamp in the filename for easy identification and archiving.

    DESIGN CHOICE — MARKDOWN FORMAT:
    Markdown was chosen over PDF or HTML for the output format because:
    1. It is human-readable as plain text (no renderer needed).
    2. It renders beautifully in GitHub, VS Code, Obsidian, and Notion.
    3. It can be easily converted to PDF (e.g., via `pandoc`).
    4. It is version-control friendly — diffs are readable.
    5. It requires no additional dependencies to generate.
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Risk level to emoji mapping for visual report headers
RISK_EMOJI = {
    "LOW":      "🟢",
    "MEDIUM":   "🟡",
    "HIGH":     "🟠",
    "CRITICAL": "🔴",
    "UNKNOWN":  "⚪",
}


def _get_output_dir() -> Path:
    """
    Resolves and creates the output directory for reports.
    
    Uses the OUTPUT_DIR environment variable if set, otherwise defaults
    to a './output' directory relative to the current working directory.
    Creates the directory (and any parent directories) if it doesn't exist.
    
    Returns:
        An absolute Path object to the output directory.
    """
    output_dir_str = os.getenv("OUTPUT_DIR", "./output")
    output_dir = Path(output_dir_str).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _format_overall_risk_badge(risk_level: str, risk_score: float) -> str:
    """
    Creates a visual risk badge string for the report header.
    
    Args:
        risk_level: The overall risk level string (e.g., "HIGH").
        risk_score: The numeric risk score (1.0–10.0).
    
    Returns:
        A formatted string like "🟠 HIGH (7.2/10)"
    """
    emoji = RISK_EMOJI.get(risk_level.upper(), "⚪")
    return f"{emoji} **{risk_level}** ({risk_score:.1f}/10)"


def _count_risks_by_level(risk_analysis: Dict) -> Dict[str, int]:
    """
    Counts the number of clauses at each risk level.
    
    Used to generate the Executive Summary statistics.
    
    Args:
        risk_analysis: The parsed risk analysis dict from the Risk Analyst Agent.
    
    Returns:
        Dict with keys: "CRITICAL", "HIGH", "MEDIUM", "LOW"
    """
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    
    for clause in risk_analysis.get("clause_analysis", []):
        level = clause.get("risk_level", "LOW").upper()
        if level in counts:
            counts[level] += 1
        else:
            counts["LOW"] += 1  # Default to LOW for unknown levels
    
    return counts


def generate_report(
    document_name: str,
    audit_log_markdown: str,
    parser_result: Dict[str, Any],
    risk_analysis: Dict[str, Any],
    protective_report_markdown: str,
) -> str:
    """
    Assembles and writes the final LegalShield AI risk report.
    
    Combines outputs from all pipeline stages into a single, comprehensive
    Markdown report file saved to the output directory.
    
    Args:
        document_name:             The filename of the analysed document.
        audit_log_markdown:        Formatted Markdown string from PIIRedactor.format_audit_log().
        parser_result:             Parsed dict from the Parser Agent's JSON output.
        risk_analysis:             Parsed dict from the Risk Analyst Agent's JSON output.
        protective_report_markdown: Markdown string from the Protector Agent.
    
    Returns:
        The absolute path to the written report file as a string.
    
    Raises:
        IOError: If the report file cannot be written (disk full, permissions, etc.)
    """
    # Generate timestamp for filename and header
    now = datetime.now()
    timestamp_file = now.strftime("%Y%m%d_%H%M%S")
    timestamp_display = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # Determine output path
    output_dir = _get_output_dir()
    # Sanitise document name for use in filename
    safe_doc_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in document_name.rsplit(".", 1)[0])
    report_filename = f"legalshield_report_{safe_doc_name}_{timestamp_file}.md"
    report_path = output_dir / report_filename
    
    # Extract key data from analysis results
    overall_risk_level = risk_analysis.get("overall_risk_level", "UNKNOWN")
    overall_risk_score = float(risk_analysis.get("overall_risk_score", 0))
    risk_summary = risk_analysis.get("risk_summary", "Risk summary not available.")
    
    doc_type = parser_result.get("document_type", "unknown")
    doc_summary = parser_result.get("document_summary", "")
    total_clauses = parser_result.get("total_clauses", 0)
    
    risk_counts = _count_risks_by_level(risk_analysis)
    total_flagged = risk_counts["CRITICAL"] + risk_counts["HIGH"] + risk_counts["MEDIUM"]
    
    risk_badge = _format_overall_risk_badge(overall_risk_level, overall_risk_score)
    
    # ==========================================================================
    # BUILD THE REPORT
    # ==========================================================================
    report_sections = []
    
    # --- HEADER ---
    report_sections.append(f"""# ⚖️ LegalShield AI — Contract Risk Report

| Field | Value |
|-------|-------|
| **Document Analysed** | `{document_name}` |
| **Report Generated** | {timestamp_display} |
| **Document Type** | {doc_type.replace("_", " ").title()} |
| **Overall Risk Level** | {risk_badge} |
| **Powered By** | LegalShield AI · Google Antigravity SDK |

---
""")
    
    # --- EXECUTIVE SUMMARY ---
    report_sections.append(f"""## 📊 Executive Summary

{risk_summary}

### Risk Overview

| Risk Level | Count |
|------------|-------|
| 🔴 CRITICAL | **{risk_counts['CRITICAL']}** clause(s) |
| 🟠 HIGH | **{risk_counts['HIGH']}** clause(s) |
| 🟡 MEDIUM | **{risk_counts['MEDIUM']}** clause(s) |
| 🟢 LOW | **{risk_counts['LOW']}** clause(s) |
| **Total Clauses Analysed** | **{total_clauses}** |
| **Clauses Requiring Attention** | **{total_flagged}** |

> ⚠️ **Important:** This report is generated by an AI system and is intended
> for informational purposes only. It does NOT constitute legal advice.
> For contracts involving significant financial commitments, always consult
> a qualified attorney before signing.

---
""")
    
    # --- DOCUMENT OVERVIEW ---
    if doc_summary:
        report_sections.append(f"""## 📄 Document Overview

{doc_summary}

---
""")
    
    # --- PII AUDIT LOG ---
    report_sections.append(f"""{audit_log_markdown}

---
""")
    
    # --- PROTECTIVE ANALYSIS (from Protector Agent) ---
    report_sections.append(protective_report_markdown)
    report_sections.append("\n---\n")
    
    # --- FOOTER / DISCLAIMER ---
    report_sections.append(f"""## ⚠️ Legal Disclaimer

This report was generated automatically by **LegalShield AI** using large language
model technology. The analysis, risk assessments, and suggested alternative clauses
are provided for informational and educational purposes only.

**This is not legal advice.** LegalShield AI:
- Is not a licensed attorney or law firm
- Cannot establish an attorney-client relationship
- May miss risks or incorrectly classify clauses
- Cannot account for jurisdiction-specific laws or your specific circumstances

**Always consult a qualified attorney** before signing, modifying, or rejecting
any legally binding contract.

---
*Report generated by LegalShield AI · Google Antigravity SDK · {timestamp_display}*
""")
    
    # --- WRITE TO FILE ---
    full_report = "\n".join(report_sections)
    
    try:
        report_path.write_text(full_report, encoding="utf-8")
        logger.info("Report written to: %s", report_path)
    except IOError as e:
        logger.error("Failed to write report to '%s': %s", report_path, e)
        raise
    
    return str(report_path)
