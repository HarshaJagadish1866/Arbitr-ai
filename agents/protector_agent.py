"""
agents/protector_agent.py — Protective Clause Drafter Agent

Generates explanations of risks in contract clauses and drafts
safer alternative legal language. Outputs Markdown.
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
    Builds the Agent configuration for the Protector Agent.
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
    Runs the Protector Agent to generate alternatives and explanations.
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
