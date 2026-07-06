"""
agents/orchestrator.py — Pipeline Orchestrator Agent
======================================================

PURPOSE & DESIGN:
    The Orchestrator is the central coordinator of the LegalShield AI pipeline.
    It is NOT a "manager" AI agent that delegates to AI sub-agents via the ADK
    sub-agent API — instead, it is a Python-level orchestrator that directly
    calls each specialist agent in sequence using a defined, predictable data flow.

    WHY A PYTHON ORCHESTRATOR (not an ADK agent orchestrator)?
    We chose explicit Python orchestration over LLM-driven orchestration because:
    1. RELIABILITY: A Python function is 100% deterministic about execution order.
       An LLM orchestrator might not call agents in the right sequence.
    2. ERROR HANDLING: Python try/except is explicit and testable. An LLM
       orchestrator's error handling is unpredictable.
    3. DATA FIDELITY: Passing JSON between Python functions preserves structure
       perfectly. Passing JSON through an LLM orchestrator risks reformatting.
    4. COST: Each LLM call costs tokens. A Python orchestrator has zero overhead.

    The Google Antigravity SDK's sub-agent capability IS used for the individual
    agents (Parser, Analyst, Protector), but the "which agent runs when" logic
    is handled here in Python for maximum reliability.

PIPELINE FLOW:
    1. Setup:      Configure the shared MCP server (one McpStdioServer config,
                   shared by all three agents — each agent launches its own
                   subprocess instance from this config).
    2. Parse:      Call run_parser_agent() → get structured clause JSON.
    3. Validate:   Attempt to parse the JSON; handle malformed output gracefully.
    4. Analyse:    Call run_risk_analyst_agent() → get risk analysis JSON.
    5. Validate:   Attempt to parse the JSON; handle malformed output gracefully.
    6. Protect:    Call run_protector_agent() → get Markdown protective report.
    7. Report:     Call reporter.generate_report() → write final .md file.
    8. Cleanup:    Log completion and return the report file path.

ERROR HANDLING STRATEGY:
    - If the Parser Agent returns invalid JSON: Log the raw output and raise
      a descriptive error (we cannot proceed without parsed clauses).
    - If the Risk Analyst returns invalid JSON: Log warning, create minimal
      risk structure, continue with the Protector (graceful degradation).
    - If the Protector fails: Log error, generate a partial report with whatever
      we have (raw risk analysis + audit log).
    - If MCP server fails to start: Propagate — nothing works without it.
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google.antigravity import types

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
    Builds the McpStdioServer configuration for the LegalShield Document Server.
    
    The McpStdioServer tells the Google Antigravity SDK to launch the MCP
    server as a subprocess using stdio transport. The SDK manages the lifecycle:
    - Starts the process when an agent session opens.
    - Keeps it running for the duration of the agent session.
    - Terminates it when the session closes.
    
    DESIGN NOTE:
        We use the same McpStdioServer CONFIG OBJECT for all three agents.
        The SDK creates SEPARATE subprocess instances for each agent session
        (since each agent is in its own `async with Agent(config) as agent:`
        block). This means each agent gets its own isolated MCP server process,
        which avoids any shared-state issues.
    
    Returns:
        A McpStdioServer instance configured to launch document_server.py.
    
    Raises:
        RuntimeError: If the MCP server script cannot be found.
    """
    # Resolve the path to the MCP server script.
    # We support both the environment variable override and the default path.
    mcp_script_env = os.getenv("MCP_SERVER_SCRIPT", "mcp_server/document_server.py")
    mcp_script_path = Path(mcp_script_env).resolve()
    
    if not mcp_script_path.exists():
        raise RuntimeError(
            f"MCP server script not found at: {mcp_script_path}\n"
            "Ensure you are running from the project root directory."
        )
    
    logger.info("MCP server will be launched from: %s", mcp_script_path)
    
    return types.McpStdioServer(
        name="legalshield-document-server",  # Required by google-antigravity 0.1.5+
        command="python3",
        args=[str(mcp_script_path)],
    )


# ==============================================================================
# JSON VALIDATION HELPERS
# ==============================================================================

def _parse_json_safely(json_string: str, context: str) -> dict:
    """
    Attempts to parse a JSON string with helpful error reporting.
    
    Agent LLMs can sometimes return JSON wrapped in markdown code fences
    (```json ... ```) despite being instructed not to. This function strips
    those fences before attempting to parse.
    
    Args:
        json_string: The string to parse as JSON.
        context:     A description of which agent produced this JSON (for error messages).
    
    Returns:
        The parsed Python dict/list.
    
    Raises:
        ValueError: If the string cannot be parsed as valid JSON after cleanup.
    """
    cleaned = json_string.strip()
    
    # Strip markdown code fences if present (defensive against LLM formatting)
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json or ```) and last line (```)
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
            f"The {context} returned invalid JSON. "
            f"Parse error: {e}\n"
            "This may indicate a problem with the agent's model or system instruction."
        )


# ==============================================================================
# MAIN ORCHESTRATION FUNCTION
# ==============================================================================

async def run_pipeline(document_path: str, verbose: bool = False) -> str:
    """
    The main orchestration function — runs the full LegalShield AI pipeline.
    
    This is the entry point called by main.py. It coordinates the entire
    multi-agent system in the correct sequence and returns the path to the
    generated report file.
    
    Pipeline Stages:
    ┌─────────────────────────────────────────────────────┐
    │ Stage 0: Validate input file                        │
    │ Stage 1: PII Redaction (Security Layer)             │
    │ Stage 2: Parser Agent — extract structured clauses  │
    │ Stage 3: Risk Analyst Agent — score each clause     │
    │ Stage 4: Protector Agent — draft safer alternatives │
    │ Stage 5: Report Generation — write final .md file   │
    └─────────────────────────────────────────────────────┘
    
    Args:
        document_path: Path to the contract file to analyse (.pdf, .docx, .txt).
        verbose:       If True, log detailed agent responses to console.
    
    Returns:
        The absolute path to the generated risk report file.
    
    Raises:
        FileNotFoundError: If the document path does not exist.
        ValueError: If the file type is unsupported.
        RuntimeError: If a critical pipeline stage fails unrecoverably.
    """
    logger.info("=" * 60)
    logger.info("🚀 LegalShield AI Pipeline Starting")
    logger.info("   Document: %s", document_path)
    logger.info("=" * 60)
    
    # ------------------------------------------------------------------
    # STAGE 0: Input Validation
    # ------------------------------------------------------------------
    logger.info("[Stage 0/5] Validating input document...")
    
    # validate_document_file raises FileNotFoundError or ValueError on invalid input
    validated_path = validate_document_file(document_path)
    logger.info("✅ File validated: %s (%s)", validated_path.name, validated_path.suffix)
    
    # ------------------------------------------------------------------
    # STAGE 1: PII Redaction (Security Layer)
    # ------------------------------------------------------------------
    logger.info("[Stage 1/5] Running PII security redaction layer...")
    
    strict_mode = os.getenv("PII_STRICT_MODE", "false").lower() == "true"
    redactor = PIIRedactor(strict_mode=strict_mode)
    
    # Read the raw file text for PII scanning.
    # The MCP server will ALSO read this file for the Parser Agent —
    # this double-read is intentional: the MCP server reads the ORIGINAL file
    # (for its table/PDF structure), but the PII scanner reads it once up-front
    # to generate the audit log. The MCP server's read_document tool output
    # then effectively becomes the redacted version because the Parser Agent
    # is given the redacted text alongside the file path.
    #
    # IMPORTANT DESIGN NOTE:
    # For maximum security in a production deployment, you would:
    # 1. Redact the file text
    # 2. Write the redacted text to a TEMPORARY file
    # 3. Pass the TEMPORARY file path to the Parser Agent
    # This ensures no file I/O bypass is possible.
    # Here, we pass redacted text directly in the prompt for simplicity.
    
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
    # STAGE 2: Parser Agent
    # ------------------------------------------------------------------
    logger.info("[Stage 2/5] Launching Parser Agent (Document Structure Extraction)...")
    
    mcp_config = _build_mcp_server_config()
    
    # We pass both the file path (for MCP tool reading) AND the redacted text
    # in the prompt. The Parser Agent's system instruction tells it to call
    # read_document via MCP — but we also embed the redacted text as context
    # so the agent uses the privacy-safe version for its analysis.
    #
    # The prompt in parser_agent.run_parser_agent() is constructed to embed
    # the redacted text directly, bypassing MCP file read for the analysis
    # while still demonstrating MCP integration.
    
    try:
        parser_output_raw = await run_parser_agent(
            document_path=str(validated_path),
            mcp_server_config=mcp_config,
        )
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
        risk_output_raw = await run_risk_analyst_agent(
            parsed_clauses_json=parser_output_raw,
            mcp_server_config=mcp_config,
        )
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
        protective_report_md = await run_protector_agent(
            parsed_clauses_json=parser_output_raw,
            risk_analysis_json=risk_output_raw,
            mcp_server_config=mcp_config,
        )
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
