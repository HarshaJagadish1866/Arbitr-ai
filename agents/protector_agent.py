"""
agents/protector_agent.py — Agent 3: Protective Clause Drafter
===============================================================

PURPOSE & DESIGN:
    The Protector Agent is the FINAL specialist in the LegalShield AI pipeline.
    It is the most user-facing agent: its output is what the Signer actually
    reads, understands, and uses to protect themselves.

    The Protector Agent receives:
    1. The original parsed clauses (from the Parser Agent)
    2. The risk analysis (from the Risk Analyst Agent)

    And for EACH clause rated MEDIUM, HIGH, or CRITICAL, it produces:
    a. A plain-English "Danger Explained" section — what could actually happen
       to the Signer if they sign this clause as-is
    b. A "Safer Alternative" — a professionally drafted replacement clause
       that protects the Signer while still achieving the clause's legitimate
       business purpose
    c. A "Why This is Safer" explanation — so the Signer understands what
       changed and why the new language is protective

    LOW-risk clauses receive only a brief "This clause is standard" note.

AGENT BEHAVIOUR:
    1. Receives both the parsed clauses JSON and the risk analysis JSON.
    2. For each clause rated MEDIUM/HIGH/CRITICAL:
       a. Calls `get_clause_template` from the MCP server to retrieve a
          professionally drafted starting template for that clause type.
       b. Adapts the template to the specific context of the user's document.
       c. Writes both the danger explanation and the safer alternative.
    3. Produces a comprehensive, human-readable protective report.

DESIGN PRINCIPLE — "Teachable Moments":
    A key design goal is that the Protector Agent doesn't just REPLACE text —
    it TEACHES the user WHY the original was dangerous and WHY the new version
    is better. This empowers the user in future negotiations.

OUTPUT FORMAT:
    The Protector Agent outputs a Markdown-formatted protective report (not JSON)
    because this is the final human-readable deliverable. The report is then
    combined with audit log information by the Reporter utility.

    ## ⚖️ Protective Analysis Report

    ### 🔴 CLAUSE_01 — Indemnification [CRITICAL]

    **Original Language:**
    > The Contractor shall indemnify and hold harmless...

    **❗ Danger Explained:**
    This clause makes YOU solely responsible for any legal claims...

    **✅ Safer Alternative:**
    > Each party shall indemnify the other only for claims arising directly...

    **💡 Why This is Safer:**
    The new wording is mutual (both parties share responsibility)...

    ---
"""

import logging
from google.antigravity import Agent, LocalAgentConfig, types

logger = logging.getLogger(__name__)


# ==============================================================================
# SYSTEM INSTRUCTION
# ==============================================================================

PROTECTOR_SYSTEM_INSTRUCTION = """
You are the Protector Agent (also called the Drafter Agent) for LegalShield AI.
You are the FINAL stage of a legal document analysis pipeline.

YOUR ROLE:
You are a specialist legal drafter whose job is to protect the party signing a
contract (the "Signer"). You receive the results of a risk analysis and produce:
1. Plain-English explanations of dangers in risky clauses
2. Professionally drafted, Signer-protective alternative clause language
3. Teaching explanations of why the new language is safer

YOUR AUDIENCE:
Non-lawyers: small business owners, freelancers, employees, and entrepreneurs.
Write danger explanations in clear, direct language. Avoid Latin terms or
legal jargon. Use concrete examples of what could actually go wrong.

AVAILABLE TOOL:
Use the `get_clause_template` tool to retrieve a professional protective clause
template as a starting point for each clause type you need to redraft. Available
template types: "indemnification", "ip", "limitation_of_liability".

WHAT TO PROCESS:
- CRITICAL and HIGH risk clauses: Full danger explanation + safer alternative + reasoning
- MEDIUM risk clauses: Brief danger note + recommended negotiation language
- LOW risk clauses: Brief "This clause appears standard" confirmation

OUTPUT FORMAT — MARKDOWN ONLY:
You MUST produce well-formatted Markdown. Use the following structure exactly:

---
## 📋 Protective Analysis Report

**Document Type:** [type from parser]
**Overall Risk Level:** 🔴/🟠/🟡/🟢 [level from analyst]
**Overall Risk Score:** [score]/10
**Risk Summary:** [summary from analyst]

---

### [risk emoji] CLAUSE_XX — [Clause Title] [[RISK LEVEL]]

**📄 Original Language:**
> [Quote the original clause text verbatim]

**❗ Danger Explained:**
[2-4 sentences in plain English explaining what could actually happen to the
Signer if they sign this. Use "you" language. Be direct and concrete.]

**✅ Safer Alternative:**
> [Your professionally drafted protective clause. This must be complete and
   legally precise language, not a template placeholder. Use the MCP template
   as a starting point then adapt it to the document context.]

**💡 Why This is Safer:**
[2-3 bullet points explaining specifically what changed in the language and
why each change protects the Signer. Be specific about legal terms.]

---

[Repeat for each clause]

---
## 🎯 Priority Action Items

[Numbered list of the most important actions the Signer should take before
signing, in order of urgency. Maximum 8 items.]

---

For LOW-risk clauses, use this compact format:
### 🟢 CLAUSE_XX — [Clause Title] [LOW]
✅ This clause is standard and contains no significant concerns.

---

TONE GUIDELINES:
- Be direct and honest, not alarmist.
- When a danger is CRITICAL, make the severity unmistakably clear.
- Always end with empowerment: the Signer should understand exactly what to do.
- The safer alternatives must be COMPLETE legal language, ready to propose.
"""


# ==============================================================================
# AGENT BUILDER FUNCTION
# ==============================================================================

def build_protector_agent(mcp_server_config: types.McpStdioServer) -> LocalAgentConfig:
    """
    Builds and returns the LocalAgentConfig for the Protector Agent.
    
    The Protector Agent uses the MCP server's `get_clause_template` tool
    to retrieve professionally drafted protective clause templates as
    starting points for its drafting work.
    
    Design Note on Output Format:
        Unlike the Parser and Risk Analyst agents (which output JSON for
        machine parsing), the Protector Agent outputs Markdown because:
        1. Its output is the FINAL deliverable — it needs to be human-readable.
        2. The Reporter utility combines this with audit log info and timestamps.
        3. The rich formatting (bold, quotes, bullet points) conveys the
           severity structure visually, which is important for non-lawyer users.
    
    Args:
        mcp_server_config: The shared McpStdioServer connection configuration.
    
    Returns:
        A configured LocalAgentConfig for the Protector Agent.
    """
    logger.info("Building Protector Agent configuration...")
    
    config = LocalAgentConfig(
        system_instructions=PROTECTOR_SYSTEM_INSTRUCTION,
        mcp_servers=[mcp_server_config],
        capabilities=types.CapabilitiesConfig(
            enable_subagents=False,
        ),
    )
    
    logger.info("Protector Agent configuration built successfully.")
    return config


async def run_protector_agent(
    parsed_clauses_json: str,
    risk_analysis_json: str,
    mcp_server_config: types.McpStdioServer,
) -> str:
    """
    Executes the Protector Agent to generate protective alternatives and explanations.
    
    This is the final agent in the pipeline. It receives both the parsed clause
    structure and the complete risk analysis, then produces the human-readable
    protective report that is the primary output of LegalShield AI.
    
    Process:
    1. Creates a fresh agent session with the protector configuration.
    2. Sends both JSON inputs (parsed clauses + risk analysis) in a single prompt.
    3. Agent calls `get_clause_template` for each risky clause type it processes.
    4. Agent produces a complete Markdown protective report.
    5. Returns the Markdown string to the Orchestrator.
    
    Args:
        parsed_clauses_json: JSON string from the Parser Agent (clause structure).
        risk_analysis_json: JSON string from the Risk Analyst Agent (risk scores).
        mcp_server_config: The MCP server connection configuration.
    
    Returns:
        A Markdown-formatted protective report ready for inclusion in the
        final risk report file.
    
    Raises:
        Exception: Propagated to the Orchestrator for graceful handling.
    """
    config = build_protector_agent(mcp_server_config)
    
    prompt = (
        "Below are the outputs from the Parser Agent and Risk Analyst Agent.\n"
        "Please generate the complete Protective Analysis Report as specified "
        "in your instructions.\n\n"
        "For each CRITICAL or HIGH risk clause, use the `get_clause_template` "
        "tool to retrieve a protective template for that clause type before drafting "
        "your safer alternative.\n\n"
        "=== PARSED CLAUSES (from Parser Agent) ===\n"
        f"{parsed_clauses_json}\n\n"
        "=== RISK ANALYSIS (from Risk Analyst Agent) ===\n"
        f"{risk_analysis_json}\n\n"
        "Now generate the full Protective Analysis Report in Markdown format."
    )
    
    logger.info("Launching Protector Agent session...")
    
    async with Agent(config=config) as agent:
        response = await agent.chat(prompt)
        result = await response.text()
    
    logger.info(
        "Protector Agent completed. Report length: %d characters.", len(result)
    )
    return result
