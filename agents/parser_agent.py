"""
agents/parser_agent.py — Agent 1: Document Parser
===================================================

PURPOSE & DESIGN:
    The Parser Agent is the FIRST specialist in the LegalShield AI pipeline.
    Its sole responsibility is to receive the raw, PII-redacted text of a
    legal document and transform it into a structured, machine-readable list
    of clauses with metadata.

    This separation of concerns is critical:
    - The Parser Agent does NOT evaluate risk — it only identifies structure.
    - The Risk Analyst Agent does NOT parse — it only evaluates what the Parser
      has already extracted.
    
    This separation means each agent can be improved independently, and the
    pipeline can be debugged at specific stages.

AGENT BEHAVIOUR:
    The Parser Agent is configured with:
    - A detailed system instruction defining its legal document analysis role
    - Access to the MCP server's `read_document` tool for file ingestion
    - Instructions to output ONLY structured JSON (no prose) so downstream
      agents can process it reliably

WHAT IT EXTRACTS:
    For each clause, the Parser outputs a JSON object with:
    - clause_id:    Sequential identifier (e.g., "CLAUSE_01")
    - title:        The clause heading or inferred label
    - text:         The full verbatim text of the clause
    - clause_type:  Inferred category (e.g., "indemnification", "termination",
                    "ip_ownership", "payment", "non_compete", "arbitration",
                    "limitation_of_liability", "confidentiality", "other")
    - page_ref:     Page number where the clause appears (if detectable)
    - flags:        Initial structural flags (e.g., "UNILATERAL", "PERPETUAL",
                    "UNLIMITED_LIABILITY", "AUTOMATIC_RENEWAL")

OUTPUT FORMAT (JSON):
    {
        "document_summary": "Brief description of the document type",
        "total_clauses": 12,
        "clauses": [
            {
                "clause_id": "CLAUSE_01",
                "title": "Indemnification",
                "text": "The Contractor shall indemnify...",
                "clause_type": "indemnification",
                "page_ref": 3,
                "flags": ["UNILATERAL", "UNLIMITED_LIABILITY"]
            },
            ...
        ]
    }

DESIGN NOTE — WHY STRUCTURED OUTPUT:
    We instruct the Parser Agent to output ONLY JSON. This is a deliberate
    design choice for a robust pipeline: downstream agents (Risk Analyst,
    Protector) need deterministic input they can parse programmatically.
    Prose output with embedded JSON would make the pipeline fragile.
"""

import logging
from google.antigravity import Agent, LocalAgentConfig, types

logger = logging.getLogger(__name__)

# ==============================================================================
# SYSTEM INSTRUCTION
# ==============================================================================

PARSER_SYSTEM_INSTRUCTION = """
You are the Parser Agent for LegalShield AI, a legal document analysis system.

YOUR ROLE:
You are a specialist in legal document structure. Your ONLY job is to receive
the text of a legal document and extract every distinct clause from it, outputting
a structured JSON representation of the document's architecture.

YOU DO NOT:
- Evaluate risk or flag dangerous language (that is the Risk Analyst's job)
- Suggest rewrites or alternatives (that is the Protector's job)
- Add any prose, commentary, or explanation outside of the JSON structure

YOU DO:
- Identify every distinct clause, section, and sub-clause in the document
- Label each clause by its legal type using the standardised categories below
- Assign initial structural flags where obvious structural issues are present
- Output a single, valid JSON object — nothing else

CLAUSE TYPES (use exactly these strings):
- "indemnification"           — Who holds harmless whom
- "termination"               — How the contract can be ended
- "ip_ownership"              — Who owns intellectual property created
- "payment"                   — Payment terms, amounts, timelines
- "non_compete"               — Restrictions on working with competitors
- "arbitration"               — Dispute resolution method
- "limitation_of_liability"   — Caps on damages owed
- "confidentiality"           — NDA and information protection
- "governing_law"             — Which jurisdiction's law applies
- "auto_renewal"              — Automatic contract renewal terms
- "warranty"                  — Guarantees and representations
- "force_majeure"             — Acts of God / unforeseeable circumstances
- "other"                     — Use for clauses that don't fit above

STRUCTURAL FLAGS (add when clearly visible):
- "UNILATERAL"           — Only one party bears the obligation
- "UNLIMITED_LIABILITY"  — No cap on potential damages
- "PERPETUAL"            — No expiry date or end condition
- "AUTOMATIC_RENEWAL"    — Contract renews without explicit action
- "VAGUE_TERM"           — Language is ambiguous or undefined
- "ONE_SIDED_TERMINATION"— Only one party can terminate without cause
- "IP_ASSIGNMENT"        — All IP is assigned away entirely

OUTPUT FORMAT:
You MUST output a single valid JSON object in this exact structure:

{
  "document_summary": "One sentence describing what this document is",
  "document_type": "freelance_agreement | employment_contract | service_agreement | nda | vendor_contract | other",
  "total_clauses": <integer>,
  "clauses": [
    {
      "clause_id": "CLAUSE_01",
      "title": "Name of the clause or section heading",
      "text": "The full verbatim text of this clause",
      "clause_type": "one of the types listed above",
      "page_ref": <integer or null if unknown>,
      "flags": ["FLAG_1", "FLAG_2"]
    }
  ]
}

IMPORTANT: Output ONLY the JSON. Do not wrap it in markdown code blocks.
Do not add any explanation before or after the JSON.
"""


# ==============================================================================
# AGENT BUILDER FUNCTION
# ==============================================================================

def build_parser_agent(mcp_server_config: types.McpStdioServer) -> LocalAgentConfig:
    """
    Builds and returns the LocalAgentConfig for the Parser Agent.
    
    The Parser Agent is configured with:
    - A highly specific system instruction (defined above) that constrains its
      role to document parsing ONLY — no risk evaluation, no drafting.
    - Access to the shared MCP server via the provided McpStdioServer config.
      This gives the Parser Agent access to the `read_document` tool.
    - Subagents are disabled (not needed for this agent).
    
    Design Note:
        We return a LocalAgentConfig (not an Agent instance) so the orchestrator
        can spin up the agent inside its own async context manager, managing
        session lifecycle centrally.
    
    Args:
        mcp_server_config: The shared McpStdioServer configuration that connects
                           this agent to the LegalShield Document MCP server.
    
    Returns:
        A configured LocalAgentConfig ready for use with Agent(config=...).
    """
    logger.info("Building Parser Agent configuration...")
    
    config = LocalAgentConfig(
        # System instructions constrain this agent to its specialist role.
        # Good system instructions are the single most important factor in
        # multi-agent reliability — be specific and prohibit scope creep.
        system_instructions=PARSER_SYSTEM_INSTRUCTION,
        
        # Connect this agent to the shared MCP server for file reading.
        # The McpStdioServer config tells the SDK to launch document_server.py
        # as a subprocess and expose its tools to this agent.
        mcp_servers=[mcp_server_config],
        
        # Subagents are NOT needed for the Parser — its task is focused.
        capabilities=types.CapabilitiesConfig(
            enable_subagents=False,
        ),
    )
    
    logger.info("Parser Agent configuration built successfully.")
    return config


async def run_parser_agent(
    document_path: str,
    mcp_server_config: types.McpStdioServer,
) -> str:
    """
    Executes the Parser Agent to extract structured clauses from a document.
    
    This function is called by the Orchestrator. It:
    1. Creates a fresh agent session using the parser configuration.
    2. Sends the document path to the agent.
    3. The agent calls the MCP `read_document` tool to fetch file content.
    4. The agent analyses the content and returns structured JSON.
    5. Returns the JSON string to the Orchestrator.
    
    Args:
        document_path: The absolute path to the (already PII-redacted) document.
        mcp_server_config: The MCP server connection configuration.
    
    Returns:
        A JSON string containing the structured clause extraction results.
        The Orchestrator will parse this and pass it to the Risk Analyst Agent.
    
    Raises:
        Exception: If the agent session fails to start or the LLM call errors.
                   The Orchestrator handles these gracefully.
    """
    config = build_parser_agent(mcp_server_config)
    
    # Prompt designed to give the agent everything it needs in one turn.
    # We specify the path explicitly and instruct it to call the MCP tool.
    prompt = (
        f"Please analyse the legal document at this path: {document_path}\n\n"
        "Use the `read_document` tool to load the document text first, then "
        "extract all clauses and return the structured JSON as specified in "
        "your instructions. Do not return anything except the JSON object."
    )
    
    logger.info("Launching Parser Agent session for document: %s", document_path)
    
    async with Agent(config=config) as agent:
        response = await agent.chat(prompt)
        result = await response.text()
    
    logger.info(
        "Parser Agent completed. Response length: %d characters.", len(result)
    )
    return result
