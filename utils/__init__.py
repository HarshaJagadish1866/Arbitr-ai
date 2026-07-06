"""
utils/__init__.py — Utilities Package Initialiser
===================================================
Marks the utils/ directory as a Python package.
"""
from utils.reporter import generate_report
from utils.file_handler import validate_document_file, get_file_info

__all__ = ["generate_report", "validate_document_file", "get_file_info"]
