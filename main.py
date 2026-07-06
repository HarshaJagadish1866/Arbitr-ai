"""
main.py — LegalShield AI Entry Point

Provides a CLI interface for the legal document review pipeline.
"""

import asyncio
import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

# --- Fault-tolerant dotenv import ---
# If python-dotenv is not on the current Python's sys.path (e.g. VS Code
# integrated terminal using a different PATH), install it automatically.
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-dotenv", "-q"])
    from dotenv import load_dotenv

# --- Fault-tolerant rich import ---
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich import print as rprint
except ModuleNotFoundError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich", "-q"])
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich import print as rprint

# =============================================================================
# ENVIRONMENT SETUP
# =============================================================================

# Load environment variables BEFORE anything else imports os.environ.
# This ensures GEMINI_API_KEY and other settings are available to the
# Google Antigravity SDK when it is imported.
load_dotenv()

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

def _configure_logging(verbose: bool) -> None:
    """
    Configures the root logger for the application.
    
    In normal mode: INFO level, clean format (no module names).
    In verbose mode: DEBUG level, full format (includes module and line number).
    
    The log level can also be controlled via the LOG_LEVEL environment variable.
    The --verbose flag overrides LOG_LEVEL to DEBUG.
    
    Args:
        verbose: If True, enables DEBUG logging with full format.
    """
    if verbose:
        log_level = logging.DEBUG
        log_format = "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d — %(message)s"
    else:
        env_level = os.getenv("LOG_LEVEL", "INFO").upper()
        log_level = getattr(logging, env_level, logging.INFO)
        log_format = "%(asctime)s [%(levelname)s] %(message)s"
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    
    # Suppress overly verbose logs from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)


# =============================================================================
# CLI ARGUMENT PARSER
# =============================================================================

def _build_argument_parser() -> argparse.ArgumentParser:
    """
    Builds and returns the CLI argument parser.
    
    Design Note:
        We use argparse (stdlib) rather than third-party libraries like Click
        or Typer to keep dependencies minimal. The interface is simple enough
        that argparse is perfectly sufficient.
    
    Returns:
        A configured ArgumentParser ready to parse sys.argv.
    """
    parser = argparse.ArgumentParser(
        prog="legalshield",
        description=(
            "⚖️  LegalShield AI — Intelligent Legal Document Reviewer\n\n"
            "Analyses contracts and legal agreements using a multi-agent AI system\n"
            "to identify risks, loopholes, and dangerous clauses, then generates\n"
            "safer alternative language to protect you."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py --document contract.pdf\n"
            "  python main.py --document agreement.docx --verbose\n"
            "  python main.py --document sample_contracts/sample_freelance_agreement.txt\n\n"
            "Supported file types: .pdf, .docx, .txt\n\n"
            "IMPORTANT: Set your Gemini API keys in .env before running.\n"
            "           See .env.example for all configuration options."
        )
    )
    
    parser.add_argument(
        "--document",
        "-d",
        required=True,
        metavar="PATH",
        help=(
            "Path to the legal document to analyse. "
            "Supported formats: .pdf, .docx, .txt"
        )
    )
    
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help=(
            "Enable verbose output: shows agent responses and detailed logs. "
            "Useful for debugging or understanding agent reasoning."
        )
    )
    
    parser.add_argument(
        "--output-dir",
        "-o",
        metavar="DIR",
        default=None,
        help=(
            "Directory where the risk report will be saved. "
            "Defaults to ./output (or OUTPUT_DIR environment variable)."
        )
    )
    
    return parser


# =============================================================================
# PREREQUISITE CHECKS
# =============================================================================

def _check_prerequisites() -> None:
    """
    Validates that all required configuration is present before starting.
    
    Checks:
    1. At least one API key exists for each pool (parser and analyst),
       either via the dedicated multi-key variables or the legacy fallback.
    2. No keys are still set to placeholder values.
    
    Raises:
        SystemExit: If a critical prerequisite is not met.
    """
    console = Console()
    
    # Check for multi-key configuration
    parser_keys = [
        os.getenv("GEMINI_KEY_PARSER_1", "").strip(),
        os.getenv("GEMINI_KEY_PARSER_2", "").strip(),
    ]
    analyst_keys = [
        os.getenv("GEMINI_KEY_ANALYST_1", "").strip(),
        os.getenv("GEMINI_KEY_ANALYST_2", "").strip(),
    ]
    legacy_key = os.getenv("GEMINI_API_KEY", "").strip()
    
    # Filter out empty strings and placeholder values
    placeholders = {"your_key_here", "your_gemini_api_key_here", ""}
    parser_valid = [k for k in parser_keys if k not in placeholders]
    analyst_valid = [k for k in analyst_keys if k not in placeholders]
    legacy_valid = legacy_key not in placeholders
    
    # A pool is satisfied if it has dedicated keys OR the legacy fallback exists
    parser_ok = bool(parser_valid) or legacy_valid
    analyst_ok = bool(analyst_valid) or legacy_valid
    
    if not parser_ok or not analyst_ok:
        missing_pools = []
        if not parser_ok:
            missing_pools.append("Parser (GEMINI_KEY_PARSER_1 / _2)")
        if not analyst_ok:
            missing_pools.append("Analyst (GEMINI_KEY_ANALYST_1 / _2)")
        
        console.print(Panel(
            "[bold red]❌ API keys not found![/bold red]\n\n"
            "LegalShield AI requires at least one Gemini API key per agent pool.\n\n"
            f"[bold]Missing pools:[/bold] {', '.join(missing_pools)}\n\n"
            "[bold]Setup steps:[/bold]\n"
            "1. Get your free API key at: [link]https://aistudio.google.com/app/api-keys[/link]\n"
            "2. Copy the .env.example file: [code]cp .env.example .env[/code]\n"
            "3. Edit .env and set your keys for each pool\n\n"
            "[dim]Tip: You can also set GEMINI_API_KEY as a single fallback for all pools.[/dim]",
            title="Configuration Error",
            border_style="red"
        ))
        sys.exit(1)


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def _print_banner(console: Console) -> None:
    """Prints the LegalShield AI welcome banner to the console."""
    banner_text = Text()
    banner_text.append("⚖️  LegalShield AI\n", style="bold cyan")
    banner_text.append("Intelligent Legal Document Reviewer\n", style="dim")
    banner_text.append("Powered by Google Antigravity SDK", style="dim italic")
    
    console.print(Panel(
        banner_text,
        border_style="cyan",
        padding=(1, 4),
    ))


def _print_pipeline_start(console: Console, document_path: str) -> None:
    """Prints a summary of what the pipeline is about to do."""
    doc_name = Path(document_path).name
    console.print(f"\n📄 Document: [bold]{doc_name}[/bold]")
    console.print("\n🔄 Starting analysis pipeline:\n")
    console.print("   [dim]Stage 1/5:[/dim] 🔒 Security scan & PII redaction")
    console.print("   [dim]Stage 2/5:[/dim] 🤖 Agent 1: Parsing document structure")
    console.print("   [dim]Stage 3/5:[/dim] 🔍 Agent 2: Risk analysis & clause scoring")
    console.print("   [dim]Stage 4/5:[/dim] ✍️  Agent 3: Drafting safer alternatives")
    console.print("   [dim]Stage 5/5:[/dim] 📊 Generating risk report")
    console.print()


def _print_success(console: Console, report_path: str) -> None:
    """Prints a success message with the report location."""
    console.print(Panel(
        f"[bold green]✅ Analysis Complete![/bold green]\n\n"
        f"Your risk report has been saved to:\n\n"
        f"[bold white]{report_path}[/bold white]\n\n"
        f"Open it in any Markdown viewer, VS Code, or GitHub to read the full analysis.",
        title="LegalShield AI — Done",
        border_style="green",
        padding=(1, 2),
    ))


# =============================================================================
# MAIN ASYNC FUNCTION
# =============================================================================

async def _async_main(args: argparse.Namespace) -> int:
    """
    The main async execution function.
    
    Separated from main() to allow clean async/await usage throughout.
    Returns an exit code (0 for success, non-zero for failure).
    
    Args:
        args: Parsed command-line arguments from argparse.
    
    Returns:
        Integer exit code (0 = success, 1 = error).
    """
    console = Console()
    
    _print_banner(console)
    _check_prerequisites()
    
    # Override OUTPUT_DIR if --output-dir was specified
    if args.output_dir:
        os.environ["OUTPUT_DIR"] = args.output_dir
    
    _print_pipeline_start(console, args.document)
    
    # Import here (not at module top) so prerequisite checks run first
    # and environment variables are loaded before SDK imports occur.
    from agents.orchestrator import run_pipeline
    
    try:
        with console.status("[bold cyan]Running LegalShield AI pipeline...[/bold cyan]",
                           spinner="dots"):
            report_path = await run_pipeline(
                document_path=args.document,
                verbose=args.verbose,
            )
        
        _print_success(console, report_path)
        return 0
    
    except FileNotFoundError as e:
        console.print(f"\n[bold red]❌ File not found:[/bold red] {e}")
        return 1
    
    except ValueError as e:
        console.print(f"\n[bold red]❌ Invalid input:[/bold red] {e}")
        return 1
    
    except PermissionError as e:
        console.print(f"\n[bold red]❌ Permission denied:[/bold red] {e}")
        return 1
    
    except RuntimeError as e:
        # Check if this is a KeyPoolExhaustedError (subclass of RuntimeError)
        from agents.api_gateway import KeyPoolExhaustedError
        if isinstance(e, KeyPoolExhaustedError):
            console.print(Panel(
                f"[bold red]❌ All API keys rate-limited![/bold red]\n\n"
                f"The [bold]{e.role}[/bold] agent pool exhausted all {e.attempts} "
                f"retry attempts due to rate limiting (HTTP 429).\n\n"
                "[bold]What you can do:[/bold]\n"
                "1. Wait a few minutes for rate limits to reset\n"
                "2. Add more API keys to the pool in your .env file\n"
                "3. Spread keys across different Google Cloud projects",
                title="Rate Limit Exhaustion",
                border_style="red"
            ))
        else:
            console.print(f"\n[bold red]❌ Pipeline error:[/bold red] {e}")
        if args.verbose:
            traceback.print_exc()
        else:
            console.print("[dim]Run with --verbose for full traceback.[/dim]")
        return 1
    
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Analysis interrupted by user.[/yellow]")
        return 130  # Standard Unix exit code for Ctrl-C
    
    except Exception as e:
        console.print(
            f"\n[bold red]❌ Unexpected error:[/bold red] {type(e).__name__}: {e}"
        )
        if args.verbose:
            traceback.print_exc()
        else:
            console.print(
                "[dim]This may indicate a problem with the Gemini API or the SDK.\n"
                "Run with --verbose for full traceback.[/dim]"
            )
        return 1


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    """
    Synchronous entry point that bootstraps the async pipeline.
    
    This function:
    1. Parses CLI arguments
    2. Configures logging
    3. Runs the async pipeline via asyncio.run()
    4. Exits with the appropriate exit code
    """
    parser = _build_argument_parser()
    args = parser.parse_args()
    
    _configure_logging(verbose=args.verbose)
    
    # asyncio.run() is the standard way to run async code from a sync context.
    # It creates a new event loop, runs the coroutine, and cleans up.
    exit_code = asyncio.run(_async_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
