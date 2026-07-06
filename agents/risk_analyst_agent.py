"""
agents/risk_analyst_agent.py — Agent 2: Legal Risk Analyst
===========================================================

PURPOSE & DESIGN:
    The Risk Analyst Agent is the SECOND specialist in the LegalShield AI
    pipeline. It receives the structured clause JSON produced by the Parser
    Agent and evaluates each clause for legal risk from the perspective of
    the PARTY SIGNING the contract (typically the weaker party — a freelancer,
    small business owner, or employee).

    This agent embodies the core legal intelligence of the system:
    - It knows what standard, fair, and protective language looks like.
    - It recognises patterns of unfair, one-sided, or exploitative clauses.
    - It can call the MCP server to retrieve legal reference standards for
      specific clause categories, grounding its analysis in documented criteria.

RISK SCORING SYSTEM:
    Each clause is assigned one of four severity levels:

    🟢 LOW      — Standard boilerplate; no significant concerns. The clause is
                  fair or weighted only slightly toward the other party.
                  Action: Acknowledge and proceed.

    🟡 MEDIUM   — Potentially unfavourable terms. May be acceptable depending
                  on negotiation leverage, but warrants review.
                  Action: Negotiate if possible.

    🟠 HIGH     — Significant unfair advantage to the other party. Clause
                  creates meaningful legal or financial exposure.
                  Action: Strongly request modification before signing.

    🔴 CRITICAL — Extremely dangerous clause. Creates unlimited liability,
                  strips core rights (IP, pay), or enables predatory behaviour.
                  Action: DO NOT SIGN without legal counsel and modification.

AGENT BEHAVIOUR:
    1. Receives the structured clause JSON from the Parser Agent.
    2. For each clause, optionally calls `list_legal_references` to compare
       the clause against documented standards.
    3. Evaluates each clause along five dimensions:
       a. Liability exposure — what the signer could be held responsible for
       b. Rights retention   — does the signer keep their core rights?
       c. Fairness & balance — is the obligation mutual or one-sided?
       d. Ambiguity risk     — are undefined terms used that could be exploited?
       e. Scope creep        — does the clause extend beyond its stated purpose?
    4. Outputs annotated JSON with risk scores, reasoning, and key concerns.

OUTPUT FORMAT (JSON):
    {
        "overall_risk_level": "HIGH",
        "overall_risk_score": 7.2,
        "risk_summary": "Brief paragraph summarising the overall risk profile",
        "clause_analysis": [
            {
                "clause_id": "CLAUSE_01",
                "title": "Indemnification",
                "risk_level": "CRITICAL",
                "risk_score": 9.5,
                "risk_reasons": ["Unilateral obligation", "No liability cap", ...],
                "key_concerns": "Plain English description of what could go wrong",
                "dimensions": {
                    "liability_exposure": "CRITICAL",
                    "rights_retention": "LOW",
                    "fairness_balance": "HIGH",
                    "ambiguity_risk": "MEDIUM",
                    "scope_creep": "LOW"
                }
            }
        ]
    }
"""

import logging
from google.antigravity import Agent, LocalAgentConfig, types

logger = logging.getLogger(__name__)


# ==============================================================================
# SYSTEM INSTRUCTION
# ==============================================================================

RISK_ANALYST_SYSTEM_INSTRUCTION = """
You are the Risk Analyst Agent for LegalShield AI, a legal document analysis
system built to protect individuals and small businesses from unfair contracts.

YOUR ROLE:
You are an expert legal risk analyst with deep knowledge of commercial contract
law across common law jurisdictions (US, UK, Australia, Canada). Your job is to
analyse each clause in a parsed legal document and assign a precise risk rating
to protect the PARTY SIGNING the document (hereafter: "the Signer").

PERSPECTIVE: You ALWAYS advocate for the Signer — the weaker party. You are
looking for clauses that could be used against them, even if currently benign.

AVAILABLE TOOL:
You have access to `list_legal_references` tool. Use it to fetch the legal
standards document for a clause's category before evaluating it. This grounds
your analysis in documented criteria rather than general knowledge.

RISK LEVELS:
- LOW (score 1-3):      Standard, fair boilerplate. Proceed with awareness.
- MEDIUM (score 4-5):   Unfavourable but negotiable. Flag for discussion.
- HIGH (score 6-8):     Significant risk. Request modification before signing.
- CRITICAL (score 9-10): Dangerous clause. DO NOT SIGN without legal counsel.

EVALUATION DIMENSIONS (score each 1-10):
1. liability_exposure:  Could this create unlimited or large financial liability?
2. rights_retention:    Does the Signer keep their core rights (IP, payment, exit)?
3. fairness_balance:    Is the obligation mutual or entirely one-sided?
4. ambiguity_risk:      Are there undefined terms that could be exploited?
5. scope_creep:         Does the clause extend beyond its ostensible purpose?

AUTOMATIC CRITICAL FLAGS — always assign CRITICAL if:
- The clause allows unlimited, uncapped financial liability for the Signer
- All IP is assigned to the other party with no exceptions or carve-outs
- The other party can terminate without cause but the Signer cannot
- Indemnification is unilateral and covers the other party's own negligence
- Arbitration terms are one-sided (e.g., the other party's chosen venue only)

AUTOMATIC HIGH FLAGS — always assign HIGH if:
- Indemnification is unilateral but does NOT cover the other party's negligence
- IP assignment carves out pre-existing IP but is otherwise total
- Non-compete is overly broad (more than 12 months, multi-state/country)
- Automatic renewal with no notice period for cancellation
- The governing law favours the other party in their home jurisdiction

INPUT:
You will receive a JSON object from the Parser Agent containing extracted clauses.

OUTPUT FORMAT:
You MUST output ONLY a valid JSON object in this exact structure:

{
  "overall_risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "overall_risk_score": <float 1.0-10.0>,
  "risk_summary": "2-3 sentence plain English summary of the overall contract risk",
  "clause_analysis": [
    {
      "clause_id": "CLAUSE_01",
      "title": "Clause name",
      "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
      "risk_score": <float 1.0-10.0>,
      "risk_reasons": ["Short reason 1", "Short reason 2"],
      "key_concerns": "Plain English explanation of what could go wrong for the Signer",
      "dimensions": {
        "liability_exposure": "LOW | MEDIUM | HIGH | CRITICAL",
        "rights_retention": "LOW | MEDIUM | HIGH | CRITICAL",
        "fairness_balance": "LOW | MEDIUM | HIGH | CRITICAL",
        "ambiguity_risk": "LOW | MEDIUM | HIGH | CRITICAL",
        "scope_creep": "LOW | MEDIUM | HIGH | CRITICAL"
      }
    }
  ]
}

IMPORTANT: Output ONLY the JSON. No markdown code blocks. No prose before or after.
"""


# ==============================================================================
# AGENT BUILDER FUNCTION
# ==============================================================================

def build_risk_analyst_agent(mcp_server_config: types.McpStdioServer) -> LocalAgentConfig:
    """
    Builds and returns the LocalAgentConfig for the Risk Analyst Agent.
    
    The Risk Analyst Agent has access to the MCP server's `list_legal_references`
    tool, allowing it to compare clauses against documented legal standards.
    
    Design Note on Tool Access:
        The Risk Analyst Agent intentionally has access to ALL MCP tools
        (read_document, list_legal_references, get_clause_template), but its
        system instruction only directs it to use `list_legal_references`.
        This is simpler than configuring fine-grained tool permissions for
        each agent individually. In production, you would use MCP permissions
        to enforce this separation strictly.
    
    Args:
        mcp_server_config: The shared McpStdioServer connection configuration.
    
    Returns:
        A configured LocalAgentConfig for the Risk Analyst Agent.
    """
    logger.info("Building Risk Analyst Agent configuration...")
    
    config = LocalAgentConfig(
        system_instructions=RISK_ANALYST_SYSTEM_INSTRUCTION,
        mcp_servers=[mcp_server_config],
        capabilities=types.CapabilitiesConfig(
            enable_subagents=False,
        ),
    )
    
    logger.info("Risk Analyst Agent configuration built successfully.")
    return config


async def run_risk_analyst_agent(
    parsed_clauses_json: str,
    mcp_server_config: types.McpStdioServer,
) -> str:
    """
    Executes the Risk Analyst Agent to evaluate legal risk for each clause.
    
    This function is called by the Orchestrator after the Parser Agent has
    completed its work. It:
    1. Creates a fresh agent session with the risk analyst configuration.
    2. Sends the structured clause JSON from the Parser Agent.
    3. The agent evaluates each clause (optionally calling `list_legal_references`).
    4. Returns a risk-annotated JSON string.
    
    Args:
        parsed_clauses_json: The JSON string output from the Parser Agent,
                             containing all extracted clauses.
        mcp_server_config: The MCP server connection configuration.
    
    Returns:
        A JSON string containing the risk analysis for every clause.
        The Orchestrator will pass this to the Protector Agent.
    
    Raises:
        Exception: Propagated to the Orchestrator for graceful handling.
    """
    config = build_risk_analyst_agent(mcp_server_config)
    
    prompt = (
        "Below is the structured clause extraction from a legal document.\n"
        "Please analyse each clause for risk as specified in your instructions.\n"
        "For each clause category (e.g., 'indemnification', 'ip_ownership'), "
        "use the `list_legal_references` tool to fetch the relevant legal standard "
        "before evaluating that clause.\n\n"
        "PARSED DOCUMENT (JSON):\n"
        f"{parsed_clauses_json}\n\n"
        "Return ONLY the risk analysis JSON. No markdown. No prose."
    )
    
    logger.info("Launching Risk Analyst Agent session...")
    
    async with Agent(config=config) as agent:
        response = await agent.chat(prompt)
        result = await response.text()
    
    logger.info(
        "Risk Analyst Agent completed. Response length: %d characters.", len(result)
    )
    return result
