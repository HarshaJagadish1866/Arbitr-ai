"""
agents/__init__.py — Agents Package Initialiser
=================================================

PURPOSE:
    Marks the `agents/` directory as a Python package.
    Exposes the primary pipeline entry point for clean imports.

AGENT SUMMARY:
    Parser Agent       (parser_agent.py)       — Clause extraction
    Risk Analyst Agent (risk_analyst_agent.py) — Risk scoring
    Protector Agent    (protector_agent.py)    — Clause drafting
    Orchestrator       (orchestrator.py)       — Pipeline coordinator
"""

from agents.orchestrator import run_pipeline

__all__ = ["run_pipeline"]
