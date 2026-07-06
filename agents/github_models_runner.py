"""
agents/github_models_runner.py — GitHub Models Agent Runner
=============================================================

PURPOSE:
    This module replaces the Google Antigravity SDK agent calls with direct
    calls to GitHub Models via the OpenAI-compatible API endpoint.

    GitHub Models provides access to powerful AI models (GPT-4o, Llama, etc.)
    using a GitHub Personal Access Token — no separate API key needed.

    API Endpoint: https://models.inference.ai.azure.com
    Auth:         GitHub PAT with `models:read` permission
    Protocol:     OpenAI-compatible (chat completions)

WHY THIS APPROACH:
    The google-antigravity SDK is coupled to Google's Gemini API and uses
    its own quota (20 req/day on free tier). GitHub Models offers higher
    free-tier limits using your existing GitHub account.

MODELS AVAILABLE (via GitHub Models):
    - openai/gpt-4o            — Best quality, our default
    - openai/gpt-4o-mini       — Faster, cheaper
    - meta/llama-3.3-70b-instruct — Open source alternative
    - mistral-ai/mistral-large — Good for legal text

HOW IT INTEGRATES:
    Each agent function (run_parser_agent, run_risk_analyst_agent, etc.)
    simply calls `run_github_agent()` with:
    - The agent's system instruction (same as before)
    - The user prompt (same as before)
    - Optional MCP tool results pre-embedded in the prompt
      (since GitHub Models API doesn't natively run MCP servers,
       we call MCP tools directly in Python and inject results)

MCP TOOL HANDLING:
    The MCP server tools (read_document, list_legal_references,
    get_clause_template) are called directly in Python here, and their
    results are embedded into the agent prompts. This is functionally
    equivalent to the agent calling the tools itself.
"""

import os
import logging
import sys
from pathlib import Path
from openai import OpenAI

logger = logging.getLogger(__name__)

# ==============================================================================
# GITHUB MODELS CONFIGURATION
# ==============================================================================

# GitHub Models endpoint — OpenAI-compatible
GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

# Default model — GPT-4o gives best results for legal analysis
# Change to "gpt-4o-mini" for faster/cheaper runs
DEFAULT_MODEL = "gpt-4o"


def _get_github_client() -> OpenAI:
    """
    Creates and returns an OpenAI client configured for GitHub Models.

    Reads GITHUB_TOKEN from the environment (loaded from .env by main.py).
    Falls back to GEMINI_API_KEY if GITHUB_TOKEN is not set (for compatibility).

    Returns:
        An OpenAI client pointed at the GitHub Models endpoint.

    Raises:
        RuntimeError: If no token is found in the environment.
    """
    token = os.getenv("GITHUB_TOKEN")

    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN not set in environment. "
            "Add GITHUB_TOKEN=your_github_pat to your .env file.\n"
            "Create a token at: https://github.com/settings/tokens\n"
            "Required scope: 'models:read' (under 'GitHub Models')"
        )

    return OpenAI(
        base_url=GITHUB_MODELS_ENDPOINT,
        api_key=token,
    )


def run_github_agent(
    system_instruction: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Calls GitHub Models API with a system instruction + user prompt.

    This is the core replacement for the google-antigravity Agent.chat() call.
    It uses the OpenAI chat completions API format, which GitHub Models supports.

    Args:
        system_instruction: The agent's system prompt (same as in *_agent.py files).
        user_prompt:        The user message / task prompt.
        model:              GitHub Models model identifier.

    Returns:
        The model's response text.

    Raises:
        Exception: If the API call fails (rate limit, auth error, etc.)
    """
    client = _get_github_client()

    logger.info("Calling GitHub Models API (model=%s)...", model)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.2,   # Low temperature for consistent, precise legal analysis
        max_tokens=4096,   # Enough for full clause analysis + alternatives
    )

    result = response.choices[0].message.content
    logger.info(
        "GitHub Models response received (%d chars, %d tokens used).",
        len(result),
        response.usage.total_tokens if response.usage else 0,
    )
    return result


# ==============================================================================
# DIRECT MCP TOOL CALLERS
# (Since GitHub Models doesn't run MCP servers natively, we call the tool
#  logic directly in Python and embed results in the prompt.)
# ==============================================================================

def _mcp_read_document(file_path: str) -> str:
    """Directly calls the MCP read_document logic without launching a subprocess."""
    # Import the MCP server module directly (it's just Python functions)
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from mcp_server.document_server import _read_txt, _read_pdf, _read_docx

    path = Path(file_path).resolve()
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _read_pdf(path)
    elif suffix == ".docx":
        return _read_docx(path)
    elif suffix == ".txt":
        return _read_txt(path)
    else:
        return f"ERROR: Unsupported file type '{suffix}'"


def _mcp_list_legal_references(category: str) -> str:
    """Directly calls the MCP list_legal_references logic."""
    legal_lib = Path(os.getenv("LEGAL_LIBRARY_PATH", "./legal_library")).resolve()
    ref_map = {
        "indemnification": "indemnification_standards.md",
        "ip_ownership":    "ip_ownership_standards.md",
        "liability":       "liability_limits_standards.md",
        "termination":     "termination_clause_standards.md",
    }
    filename = ref_map.get(category.lower())
    if not filename:
        return f"ERROR: Unknown category '{category}'"
    ref_file = legal_lib / filename
    return ref_file.read_text(encoding="utf-8") if ref_file.exists() else f"ERROR: File not found"


def _mcp_get_clause_template(clause_type: str) -> str:
    """Directly calls the MCP get_clause_template logic."""
    legal_lib = Path(os.getenv("LEGAL_LIBRARY_PATH", "./legal_library")).resolve()
    template_map = {
        "indemnification":         "templates/indemnification_template.md",
        "ip":                      "templates/ip_template.md",
        "limitation_of_liability": "templates/limitation_of_liability_template.md",
    }
    filename = template_map.get(clause_type.lower())
    if not filename:
        return f"ERROR: Unknown clause type '{clause_type}'"
    tmpl_file = legal_lib / filename
    return tmpl_file.read_text(encoding="utf-8") if tmpl_file.exists() else f"ERROR: File not found"


# ==============================================================================
# AGENT RUNNER FUNCTIONS (GitHub Models versions)
# ==============================================================================

async def run_parser_agent_github(document_path: str) -> str:
    """
    Runs the Parser Agent using GitHub Models.
    Reads the document directly and embeds it in the prompt.
    """
    from agents.parser_agent import PARSER_SYSTEM_INSTRUCTION

    logger.info("Parser Agent (GitHub Models): reading document...")
    doc_text = _mcp_read_document(document_path)

    prompt = (
        f"Please analyse this legal document and extract all clauses "
        f"as specified in your instructions.\n\n"
        f"DOCUMENT TEXT:\n{doc_text}\n\n"
        f"Return ONLY the JSON object. No markdown code fences."
    )

    return run_github_agent(PARSER_SYSTEM_INSTRUCTION, prompt)


async def run_risk_analyst_agent_github(parsed_clauses_json: str) -> str:
    """
    Runs the Risk Analyst Agent using GitHub Models.
    Pre-fetches all relevant legal reference standards and embeds them.
    """
    from agents.risk_analyst_agent import RISK_ANALYST_SYSTEM_INSTRUCTION

    logger.info("Risk Analyst Agent (GitHub Models): fetching legal references...")

    # Pre-fetch all four reference documents and embed in context
    refs = {
        "indemnification": _mcp_list_legal_references("indemnification"),
        "ip_ownership":    _mcp_list_legal_references("ip_ownership"),
        "liability":       _mcp_list_legal_references("liability"),
        "termination":     _mcp_list_legal_references("termination"),
    }

    ref_block = "\n\n".join(
        f"=== {k.upper()} STANDARDS ===\n{v}" for k, v in refs.items()
    )

    prompt = (
        "Below are the parsed clauses and the full legal reference standards.\n"
        "Analyse each clause against the relevant standards and return the risk JSON.\n\n"
        f"=== PARSED CLAUSES ===\n{parsed_clauses_json}\n\n"
        f"=== LEGAL REFERENCE STANDARDS ===\n{ref_block}\n\n"
        "Return ONLY the risk analysis JSON. No markdown code fences."
    )

    return run_github_agent(RISK_ANALYST_SYSTEM_INSTRUCTION, prompt)


async def run_protector_agent_github(
    parsed_clauses_json: str,
    risk_analysis_json: str,
) -> str:
    """
    Runs the Protector Agent using GitHub Models.
    Pre-fetches clause templates and embeds them in context.
    """
    from agents.protector_agent import PROTECTOR_SYSTEM_INSTRUCTION

    logger.info("Protector Agent (GitHub Models): fetching clause templates...")

    templates = {
        "indemnification":         _mcp_get_clause_template("indemnification"),
        "ip":                      _mcp_get_clause_template("ip"),
        "limitation_of_liability": _mcp_get_clause_template("limitation_of_liability"),
    }

    tmpl_block = "\n\n".join(
        f"=== {k.upper()} TEMPLATE ===\n{v}" for k, v in templates.items()
    )

    prompt = (
        "Below are the parsed clauses, risk analysis, and protective clause templates.\n"
        "Generate the full Protective Analysis Report in Markdown.\n\n"
        f"=== PARSED CLAUSES ===\n{parsed_clauses_json}\n\n"
        f"=== RISK ANALYSIS ===\n{risk_analysis_json}\n\n"
        f"=== PROTECTIVE CLAUSE TEMPLATES ===\n{tmpl_block}\n\n"
        "Generate the complete Markdown report now."
    )

    return run_github_agent(PROTECTOR_SYSTEM_INSTRUCTION, prompt)
