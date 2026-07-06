"""
agents/orchestrator.py — Pipeline Orchestrator

Coordinates the sequential execution of the legal document review pipeline:
Parser -> Risk Analyst -> Protector.
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google.antigravity import types

from agents.api_gateway import AgentGateway, KeyPoolExhaustedError
from agents.parser_agent import run_parser_agent
from agents.risk_analyst_agent import run_risk_analyst_agent
from agents.protector_agent import run_protector_agent
from security.pii_redactor import PIIRedactor
from utils.reporter import generate_report
from utils.file_handler import validate_document_file

# Load environment variables from .env file.
# This must be called before any code that reads os.environ (e.g., API keys).
load_dotenv()

# Module-level logger
logger = logging.getLogger(__name__)


# ==============================================================================
# MCP SERVER CONFIGURATION
# ==============================================================================

def _build_mcp_server_config() -> types.McpStdioServer:
    """
    Builds the McpStdioServer configuration for the document server.
    """
    mcp_script_env = os.getenv("MCP_SERVER_SCRIPT", "mcp_server/document_server.py")
    mcp_script_path = Path(mcp_script_env).resolve()
    
    if not mcp_script_path.exists():
        raise RuntimeError(
            f"MCP server script not found at: {mcp_script_path}\n"
            "Ensure you are running from the project root directory."
        )
    
    logger.info("MCP server will be launched from: %s", mcp_script_path)
    
    return types.McpStdioServer(
        name="legalshield-document-server",
        command="python3",
        args=[str(mcp_script_path)],
    )


# ==============================================================================
# JSON VALIDATION HELPERS
# ==============================================================================

def _parse_json_safely(json_string: str, context: str) -> dict:
    """
    Parses JSON output, stripping potential markdown code blocks.
    """
    cleaned = json_string.strip()
    
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:]) if len(lines) > 1 else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse %s output as JSON. Error: %s\nRaw output (first 500 chars):\n%s",
            context, e, json_string[:500]
        )
        raise ValueError(
            f"The {context} returned invalid JSON. Parse error: {e}"
        )


# ==============================================================================
# MAIN ORCHESTRATION FUNCTION
# ==============================================================================

async def run_pipeline(document_path: str, verbose: bool = False) -> str:
    """
    Main orchestration function running the full reviewer pipeline.
    """
    logger.info("=" * 60)
    logger.info("🚀 LegalShield AI Pipeline Starting")
    logger.info("   Document: %s", document_path)
    logger.info("=" * 60)
    
    # ------------------------------------------------------------------
    # STAGE 0: Input Validation
    # ------------------------------------------------------------------
    logger.info("[Stage 0/5] Validating input document...")
    
    validated_path = validate_document_file(document_path)
    logger.info("✅ File validated: %s (%s)", validated_path.name, validated_path.suffix)
    
    # ------------------------------------------------------------------
    # STAGE 1: PII Redaction (Security Layer)
    # ------------------------------------------------------------------
    logger.info("[Stage 1/5] Running PII security redaction layer...")
    
    strict_mode = os.getenv("PII_STRICT_MODE", "false").lower() == "true"
    redactor = PIIRedactor(strict_mode=strict_mode)
    
    raw_text = validated_path.read_text(encoding="utf-8", errors="replace")
    redaction_result = redactor.redact(raw_text)
    
    logger.info(
        "✅ PII Redaction complete. Removed %d PII items.",
        redaction_result.redaction_count
    )
    if verbose:
        for entry in redaction_result.audit_log:
            logger.info("   Redacted [%s]: %s chars at position %d",
                       entry.pii_type, len(entry.original), entry.start)
    
    # ------------------------------------------------------------------
    # STAGE 2: Parser Agent (via AgentGateway)
    # ------------------------------------------------------------------
    logger.info("[Stage 2/5] Launching Parser Agent...")
    
    mcp_config = _build_mcp_server_config()
    gateway = AgentGateway()
    
    try:
        parser_output_raw = await gateway.execute_with_failover(
            role="parser",
            coro_factory=lambda: run_parser_agent(
                document_path=str(validated_path),
                mcp_server_config=mcp_config,
            ),
        )
    except KeyPoolExhaustedError:
        raise
    except Exception as e:
        raise RuntimeError(f"Parser Agent failed: {e}") from e
    
    if verbose:
        logger.info("Parser Agent raw output:\n%s", parser_output_raw[:1000])
    
    # Validate the Parser Agent's JSON output
    try:
        parsed_clauses = _parse_json_safely(parser_output_raw, "Parser Agent")
        logger.info(
            "✅ Parser Agent complete. Extracted %d clauses from document.",
            parsed_clauses.get("total_clauses", "?")
        )
    except ValueError as e:
        raise RuntimeError(str(e))
    
    # ------------------------------------------------------------------
    # STAGE 3: Risk Analyst Agent
    # ------------------------------------------------------------------
    logger.info("[Stage 3/5] Launching Risk Analyst Agent (Clause Risk Scoring)...")
    
    try:
        risk_output_raw = await gateway.execute_with_failover(
            role="analyst",
            coro_factory=lambda: run_risk_analyst_agent(
                parsed_clauses_json=parser_output_raw,
                mcp_server_config=mcp_config,
            ),
        )
    except KeyPoolExhaustedError:
        raise  # Propagate to main.py for user-friendly handling
    except Exception as e:
        raise RuntimeError(f"Risk Analyst Agent failed: {e}") from e
    
    if verbose:
        logger.info("Risk Analyst raw output:\n%s", risk_output_raw[:1000])
    
    # Validate the Risk Analyst's JSON output (graceful degradation if invalid)
    try:
        risk_analysis = _parse_json_safely(risk_output_raw, "Risk Analyst Agent")
        logger.info(
            "✅ Risk Analyst complete. Overall risk level: %s (score: %s/10)",
            risk_analysis.get("overall_risk_level", "?"),
            risk_analysis.get("overall_risk_score", "?")
        )
    except ValueError as e:
        # Graceful degradation: create a minimal risk structure and continue
        logger.warning(
            "Risk Analyst output was not valid JSON. Creating minimal risk structure. Error: %s", e
        )
        risk_analysis = {
            "overall_risk_level": "UNKNOWN",
            "overall_risk_score": 0,
            "risk_summary": "Risk analysis could not be parsed. See raw output.",
            "clause_analysis": [],
        }
        risk_output_raw = json.dumps(risk_analysis)
    
    # ------------------------------------------------------------------
    # STAGE 4: Protector Agent
    # ------------------------------------------------------------------
    logger.info("[Stage 4/5] Launching Protector Agent (Drafting Safer Alternatives)...")
    
    try:
        protective_report_md = await gateway.execute_with_failover(
            role="protector",
            coro_factory=lambda: run_protector_agent(
                parsed_clauses_json=parser_output_raw,
                risk_analysis_json=risk_output_raw,
                mcp_server_config=mcp_config,
            ),
        )
    except KeyPoolExhaustedError:
        raise  # Propagate to main.py for user-friendly handling
    except Exception as e:
        # Graceful degradation: generate a partial report
        logger.error("Protector Agent failed: %s. Generating partial report.", e)
        protective_report_md = (
            "## ⚠️ Protective Analysis Unavailable\n\n"
            f"The Protector Agent encountered an error: `{e}`\n\n"
            "Please re-run the analysis or review the Risk Analyst output manually.\n\n"
            "### Risk Analyst Output (Raw)\n"
            f"```json\n{risk_output_raw[:2000]}\n```"
        )
    
    logger.info("✅ Protector Agent complete. Protective report generated.")
    
    # ------------------------------------------------------------------
    # STAGE 5: Report Generation
    # ------------------------------------------------------------------
    logger.info("[Stage 5/5] Generating final risk report...")
    
    # Format the PII audit log for inclusion in the report
    audit_log_md = redactor.format_audit_log(redaction_result.audit_log)
    
    report_path = generate_report(
        document_name=validated_path.name,
        audit_log_markdown=audit_log_md,
        parser_result=parsed_clauses,
        risk_analysis=risk_analysis,
        protective_report_markdown=protective_report_md,
    )
    
    logger.info("=" * 60)
    logger.info("✅ LegalShield AI Pipeline Complete!")
    logger.info("   📊 Report saved to: %s", report_path)
    logger.info("=" * 60)
    
    return report_path
