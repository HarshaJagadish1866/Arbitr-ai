"""
agents/parser_agent.py — Document Parser Agent

Extracts the structure of a legal document (clauses and metadata)
and returns it as a formatted JSON object.
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
    Builds the Agent configuration for the Parser Agent.
    """
    logger.info("Building Parser Agent configuration...")
    
    config = LocalAgentConfig(
        system_instructions=PARSER_SYSTEM_INSTRUCTION,
        mcp_servers=[mcp_server_config],
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
    Runs the Parser Agent to extract structured clauses.
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
