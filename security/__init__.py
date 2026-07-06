"""
security/__init__.py — Security Package Initialiser
=====================================================

PURPOSE:
    Marks the `security/` directory as a Python package and provides a
    convenient top-level import for the PII redaction engine.

DESIGN:
    By exporting PIIRedactor and RedactionResult here, calling code can use:
        from security import PIIRedactor, RedactionResult
    instead of the longer:
        from security.pii_redactor import PIIRedactor, RedactionResult
"""

from security.pii_redactor import PIIRedactor, RedactionResult, RedactionAuditEntry

__all__ = ["PIIRedactor", "RedactionResult", "RedactionAuditEntry"]
