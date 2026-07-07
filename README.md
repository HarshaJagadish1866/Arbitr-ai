
# ⚖️ Arbitr-ai — Intelligent Legal Document Reviewer

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Google Antigravity SDK](https://img.shields.io/badge/ADK-Google%20Antigravity-orange.svg)](https://aistudio.google.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 📋 Table of Contents

- [Problem Statement](#-problem-statement)
- [Solution Overview](#-solution-overview)
- [Architecture](#-architecture)
- [Course Concepts Implemented](#-course-concepts-implemented)
- [Project Structure](#-project-structure)
- [Prerequisites](#-prerequisites)
- [Setup & Installation](#-setup--installation)
- [Usage](#-usage)
- [Security & Privacy](#-security--privacy)
- [Troubleshooting](#-troubleshooting)

---

## 🚨 Problem Statement

Every year, thousands of businesses and individuals sign contracts they don't
fully understand. Legal agreements are deliberately complex — filled with
industry jargon, buried liability clauses, and loopholes that favour the
drafting party. Hiring a contract attorney for a routine document review costs
$500–$800/hour and is out of reach for most small businesses and freelancers.

The consequences are severe:
- **Unfair termination clauses** that allow one-sided cancellation without cause
- **Unlimited liability exposure** hidden in indemnification language
- **IP ownership traps** that strip creators of their work permanently
- **Non-compete agreements** with overbroad scope and geography
- **Auto-renewal clauses** that lock users into undesirable long-term commitments

---

## ✅ Solution Overview

**Arbitr-ai** is a multi-agent AI system that acts as a tireless, expert
contract analyst available 24/7. It automatically:

1. **Parses** uploaded PDF, DOCX, or TXT contracts into structured, clause-by-clause units
2. **Scrubs** all Personally Identifiable Information (PII) before any data
   reaches the AI model — privacy by design
3. **Analyses** each clause against a library of business protection standards,
   flagging dangerous language with a risk severity score (LOW / MEDIUM / HIGH / CRITICAL)
4. **Drafts** plain-English explanations of every risk AND generates safer
   alternative clause phrasing that protects the user
5. **Reports** all findings in a clean, structured Markdown report

The system is powered by the **Google Antigravity SDK**, orchestrating three
specialised AI sub-agents working in sequence, integrated with a local **MCP
(Model Context Protocol) server** that handles all file I/O and legal reference
lookups.

---

## 🏛️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER / CLI Interface                         │
│                          (main.py entrypoint)                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  1. Ingest document path
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  SECURITY LAYER  (security/pii_redactor.py)          │
│  • Regex + spaCy NLP to detect: Names, Emails, Phone Numbers,        │
│    Addresses, SSNs, Bank Account numbers, Credit Card numbers        │
│  • Redacts PII before text is passed to any AI agent                 │
│  • Produces a redaction audit log                                    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  2. Clean, redacted text
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              MCP SERVER  (mcp_server/document_server.py)             │
│  • FastMCP-based stdio server                                        │
│  • Tools: read_document, list_legal_references, get_clause_template  │
│  • Serves document text and a local legal reference library          │
└──────────┬─────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────┐
│  ORCHESTRATOR AGENT  │  ← Google Antigravity SDK
│  (agents/            │     LocalAgentConfig + McpStdioServer
│  orchestrator.py)    │     CapabilitiesConfig(subagents=True)
└──────────┬───────────┘
           │ delegates to sub-agents in sequence
     ┌─────┴──────────────────────────┐
     ▼                                ▼
┌──────────┐  structured clause JSON  ┌──────────────────┐
│ AGENT 1  │ ─────────────────────── ▶│    AGENT 2        │
│  Parser  │                          │  Risk Analyst     │
│  Agent   │                          │                   │
└──────────┘                          └────────┬──────────┘
                                               │ risk report
                                               ▼
                                    ┌──────────────────────┐
                                    │      AGENT 3          │
                                    │  Protector (Drafter)  │
                                    └──────────┬────────────┘
                                               │ final report
                                               ▼
                                    ┌──────────────────────┐
                                    │   REPORT GENERATOR   │
                                    │  output/report_*.md  │
                                    └──────────────────────┘
```

---

## 📚 Course Concepts Implemented

### ✅ Concept 1: Multi-Agent System (ADK)

**Files:** `agents/orchestrator.py`, `agents/parser_agent.py`,
`agents/risk_analyst_agent.py`, `agents/protector_agent.py`

Three distinct, specialised AI agents powered by the **Google Antigravity SDK**:

| Agent | Role | Key Behaviour |
|-------|------|---------------|
| **Parser Agent** | Document Intelligence | Extracts clauses, headings, and structural components from raw legal text |
| **Risk Analyst Agent** | Legal Risk Assessment | Evaluates clauses against business protection standards; assigns severity scores |
| **Protector Agent** | Protective Drafting | Generates safer alternative clause language with plain-English explanations |

### ✅ Concept 2: MCP Server Integration

**File:** `mcp_server/document_server.py`

A **FastMCP-based Model Context Protocol server** launched via stdio transport
and connected to all sub-agents. It exposes three tools:

- `read_document(file_path)` — Reads and returns text from PDF, DOCX, or TXT files
- `list_legal_references(category)` — Returns references from the local `legal_library/`
- `get_clause_template(clause_type)` — Retrieves protective clause templates

### ✅ Concept 3: Security / PII Redaction Layer

**File:** `security/pii_redactor.py`

A pre-processing security layer that detects and redacts all PII before any
document text reaches the AI models. Detects:
names, emails, phone numbers, addresses, SSNs, bank details, credit cards.

---

## 📁 Project Structure

```
Arbitr-ai/
│
├── README.md
├── .env.example
├── requirements.txt
├── main.py                                    # 🚀 Entry point
│
├── agents/                                    # 🤖 Multi-Agent System
│   ├── __init__.py
│   ├── orchestrator.py                        # Orchestrates the pipeline
│   ├── parser_agent.py                        # Agent 1: Clause extractor
│   ├── risk_analyst_agent.py                  # Agent 2: Risk scorer
│   └── protector_agent.py                     # Agent 3: Clause drafter
│
├── mcp_server/                                # 🔌 MCP Server
│   ├── __init__.py
│   └── document_server.py                     # FastMCP stdio server
│
├── security/                                  # 🔒 PII Redaction
│   ├── __init__.py
│   └── pii_redactor.py                        # PII detection & redaction
│
├── legal_library/                             # 📚 Legal References
│   ├── indemnification_standards.md
│   ├── ip_ownership_standards.md
│   ├── liability_limits_standards.md
│   ├── termination_clause_standards.md
│   └── templates/
│       ├── indemnification_template.md
│       ├── ip_template.md
│       └── limitation_of_liability_template.md
│
├── utils/                                     # 🛠️ Utilities
│   ├── __init__.py
│   ├── reporter.py                            # Report generator
│   └── file_handler.py                        # File type validation
│
├── sample_contracts/
│   └── sample_freelance_agreement.txt
│
└── output/                                    # 📊 Generated reports
    └── .gitkeep
```

---

## 🔧 Prerequisites

- **Python 3.10 or higher**
- **pip** package manager
- A **Gemini API Key** from [Google AI Studio](https://aistudio.google.com/app/api-keys)
- **poppler** for PDF parsing: `brew install poppler` (macOS)

---

## ⚙️ Setup & Installation

### Step 1: Clone the Repository

```bash
git clone <your-repo-url>
cd Arbitr-ai
```

### Step 2: Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Download the spaCy Language Model

```bash
python -m spacy download en_core_web_sm
```

### Step 5: Configure Environment Variables

```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

---

## 🚀 Usage

```bash
# Analyse a contract
python main.py --document path/to/contract.pdf

# Verbose output (shows agent reasoning)
python main.py --document path/to/contract.pdf --verbose

# Test with sample contract
python main.py --document sample_contracts/sample_freelance_agreement.txt
```

The system writes a structured Markdown report to `output/report_<timestamp>.md`.

---

## 🔒 Security & Privacy

- **No PII reaches the AI model.** All personal identifiers are redacted first.
- **Local MCP server.** Files are read locally via stdio — no third-party storage.
- **API key safety.** Credentials are managed via environment variables only.
- **Audit trail.** Every redaction is logged with a timestamp.

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| `GEMINI_API_KEY not set` | Ensure `.env` file exists and contains the key |
| `spacy model not found` | Run `python -m spacy download en_core_web_sm` |
| `poppler not found` | Run `brew install poppler` on macOS |
| `File type not supported` | Only PDF, DOCX, and TXT files are supported |

---
