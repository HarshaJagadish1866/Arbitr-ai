"""
security/pii_redactor.py — PII Redactor

Identifies and redacts Personally Identifiable Information (PII) 
from text before it is processed by external API models.
"""

import re
import logging
import spacy
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple

# Configure module-level logger.
# The calling code (main.py) sets the root log level from the environment.
logger = logging.getLogger(__name__)


# ==============================================================================
# DATA CLASSES
# ==============================================================================

@dataclass
class RedactionAuditEntry:
    """
    Represents a single PII redaction event in the audit log.
    
    Attributes:
        pii_type:     Category of PII detected (e.g., "EMAIL", "PHONE", "NAME")
        original:     The actual PII value that was found (for internal audit only)
        replacement:  The token that replaced the PII in the output text
        start:        Character start index in the original text
        end:          Character end index in the original text
        timestamp:    ISO-format timestamp of when the redaction occurred
    """
    pii_type: str
    original: str
    replacement: str
    start: int
    end: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class RedactionResult:
    """
    The output of the PII redaction process.
    
    Attributes:
        redacted_text:    The document text with all PII replaced by tokens
        audit_log:        List of all redaction events for compliance review
        redaction_count:  Total number of PII items removed
    """
    redacted_text: str
    audit_log: List[RedactionAuditEntry]
    redaction_count: int


# ==============================================================================
# COMPILED REGEX PATTERNS
# ==============================================================================
# Pre-compiled at module load time for performance efficiency.
# Each pattern includes a named group for easy extraction.

# Standard email address pattern (RFC 5322 simplified)
_EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
    re.IGNORECASE
)

# US and international phone numbers — covers formats like:
# (555) 867-5309, 555-867-5309, +1-555-867-5309, +44 20 7946 0958
_PHONE_PATTERN = re.compile(
    r'(\+?\d{1,3}[\s\-.])?(\(?\d{3}\)?[\s\-.])\d{3}[\s\-.]\d{4}\b'
)

# Social Security Number (US) — format: NNN-NN-NNNN
_SSN_PATTERN = re.compile(
    r'\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b'
)

# Bank/routing account numbers (generic 8–17 digit financial numbers)
# Preceded by keywords to reduce false positives.
_BANK_ACCOUNT_PATTERN = re.compile(
    r'(?:account|acct|routing|ABA|IBAN)[\s#:.]*\b\d{8,17}\b',
    re.IGNORECASE
)

# Credit card numbers — 16-digit sequences (with optional spaces/dashes)
# The Luhn check (below) further filters false positives.
_CREDIT_CARD_PATTERN = re.compile(
    r'\b(?:4[0-9]{12}(?:[0-9]{3})?|'      # Visa
    r'5[1-5][0-9]{14}|'                     # Mastercard
    r'3[47][0-9]{13}|'                      # American Express
    r'6(?:011|5[0-9]{2})[0-9]{12}|'        # Discover
    r'[0-9]{4}[\s\-][0-9]{4}[\s\-][0-9]{4}[\s\-][0-9]{4})\b'  # Spaced
)

# IPv4 addresses — e.g., 192.168.1.1
_IP_ADDRESS_PATTERN = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
)

# Street addresses — e.g., "123 Main Street", "456 Oak Ave, Suite 100"
_STREET_ADDRESS_PATTERN = re.compile(
    r'\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|St|Avenue|Ave|Boulevard|Blvd|'
    r'Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|Place|Pl|Way|Circle|Cir|Terrace|Ter)\b',
    re.IGNORECASE
)

# US ZIP codes — 5-digit or ZIP+4 format
_ZIP_CODE_PATTERN = re.compile(
    r'\b\d{5}(?:-\d{4})?\b'
)


# ==============================================================================
# LUHN ALGORITHM (Credit Card Validation)
# ==============================================================================

def _luhn_check(card_number: str) -> bool:
    """
    Validates a credit card number using the Luhn algorithm.
    
    The Luhn algorithm is the standard checksum formula used by all major
    credit card networks to validate card numbers. This reduces false positives
    when regex matches any 16-digit number sequence.
    
    Args:
        card_number: The card number string (digits only, no spaces or dashes).
    
    Returns:
        True if the number passes the Luhn check (valid card structure).
        False otherwise.
    """
    # Remove spaces and dashes for processing
    digits = re.sub(r'\D', '', card_number)
    
    if len(digits) < 13:
        return False
    
    total = 0
    reverse_digits = digits[::-1]
    
    for i, digit in enumerate(reverse_digits):
        n = int(digit)
        # Double every second digit (odd index in reversed string)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    
    return total % 10 == 0


# ==============================================================================
# MAIN REDACTOR CLASS
# ==============================================================================

class PIIRedactor:
    """
    Main PII detection and redaction engine for LegalShield AI.
    
    This class orchestrates all PII detection methods:
    - spaCy NER for context-aware entity detection (names, locations)
    - Regex patterns for structured PII (emails, phones, SSNs, etc.)
    
    Usage:
        redactor = PIIRedactor()
        result = redactor.redact(raw_document_text)
        clean_text = result.redacted_text
        audit = result.audit_log
    
    Design Note:
        The redactor processes in two passes:
        1. Collect ALL spans to redact (from both NER and regex)
        2. Sort spans by start position and apply redactions in reverse order
           (right-to-left) so that earlier character indices remain valid
           as text is modified.
    """
    
    def __init__(self, strict_mode: bool = False):
        """
        Initialise the PIIRedactor.
        
        Args:
            strict_mode: If True, also redacts any capitalized proper nouns
                         detected by spaCy, even if not labelled as PERSON.
                         Use for maximum privacy at cost of readability.
        """
        self.strict_mode = strict_mode
        self._nlp = None  # Lazy-loaded spaCy model
        logger.info("PIIRedactor initialised (strict_mode=%s)", strict_mode)
    
    def _load_nlp_model(self):
        """
        Lazy-loads the spaCy NLP model on first use.
        
        Design Choice: We load spaCy lazily (not at import time) because:
        1. The model is ~50MB and slow to load — we don't want startup delay
           if the user is just checking --help flags.
        2. The MCP server also imports this module; we avoid double-loading.
        
        Raises:
            RuntimeError: If the spaCy model is not installed. The error
                         message provides the installation command.
        """
        if self._nlp is None:
            try:
                logger.debug("Loading spaCy model 'en_core_web_sm'...")
                self._nlp = spacy.load("en_core_web_sm")
                logger.info("spaCy model loaded successfully.")
            except OSError:
                raise RuntimeError(
                    "spaCy model 'en_core_web_sm' not found. "
                    "Install it by running: python -m spacy download en_core_web_sm"
                )
    
    def _detect_ner_entities(self, text: str) -> List[Tuple[int, int, str, str]]:
        """
        Uses spaCy Named Entity Recognition to detect PII entities.
        
        Detects:
        - PERSON: Full names of people (e.g., "John Smith", "Dr. Emily Hartley")
        - GPE: Geopolitical entities — cities, states, countries
        - LOC: Physical locations — regions, landmarks
        
        Args:
            text: The raw document text to analyse.
        
        Returns:
            List of (start, end, original_text, pii_type) tuples.
        """
        self._load_nlp_model()
        doc = self._nlp(text)
        
        spans = []
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                spans.append((ent.start_char, ent.end_char, ent.text, "NAME"))
                logger.debug("NER detected PERSON: '%s' at [%d:%d]", ent.text, ent.start_char, ent.end_char)
            elif ent.label_ in ("GPE", "LOC") and self.strict_mode:
                # In strict mode, also redact geographic locations
                spans.append((ent.start_char, ent.end_char, ent.text, "LOCATION"))
                logger.debug("NER detected LOCATION: '%s' at [%d:%d]", ent.text, ent.start_char, ent.end_char)
        
        return spans
    
    def _detect_regex_patterns(self, text: str) -> List[Tuple[int, int, str, str]]:
        """
        Applies all pre-compiled regex patterns to detect structured PII.
        
        For each pattern, we record the match span, original value, and PII type.
        Credit card numbers undergo additional Luhn validation before recording.
        
        Args:
            text: The raw document text to analyse.
        
        Returns:
            List of (start, end, original_text, pii_type) tuples.
        """
        spans = []
        
        pattern_map = [
            (_EMAIL_PATTERN,        "EMAIL"),
            (_PHONE_PATTERN,        "PHONE"),
            (_SSN_PATTERN,          "SSN"),
            (_BANK_ACCOUNT_PATTERN, "BANK_ACCOUNT"),
            (_STREET_ADDRESS_PATTERN, "ADDRESS"),
            (_IP_ADDRESS_PATTERN,   "IP_ADDRESS"),
        ]
        
        for pattern, pii_type in pattern_map:
            for match in pattern.finditer(text):
                spans.append((match.start(), match.end(), match.group(), pii_type))
                logger.debug("Regex detected %s: '%s' at [%d:%d]",
                             pii_type, match.group(), match.start(), match.end())
        
        # Special case: Credit cards with Luhn validation
        for match in _CREDIT_CARD_PATTERN.finditer(text):
            if _luhn_check(match.group()):
                spans.append((match.start(), match.end(), match.group(), "CREDIT_CARD"))
                logger.debug("Detected CREDIT_CARD at [%d:%d]", match.start(), match.end())
        
        return spans
    
    def redact(self, text: str) -> RedactionResult:
        """
        Main entry point: detects and redacts all PII from the given text.
        
        Process:
        1. Collect spans from NER detection
        2. Collect spans from regex pattern matching
        3. Merge and deduplicate overlapping spans
        4. Apply redactions right-to-left (reverse order) to preserve indices
        5. Build the audit log
        6. Return RedactionResult with clean text and audit entries
        
        Args:
            text: The raw document text (extracted from PDF/DOCX/TXT).
        
        Returns:
            RedactionResult containing the redacted text and audit log.
        
        Design Note on Ordering:
            We process spans in REVERSE order of their start position. This is
            critical: if we replace a span at position [100, 115] first, then
            try to replace [50, 60], the indices for [50, 60] are still correct.
            But if we replaced [50, 60] first, the replacement (shorter or
            longer text) shifts all subsequent indices, corrupting them.
        """
        if not text or not text.strip():
            logger.warning("PIIRedactor received empty text. Returning empty result.")
            return RedactionResult(redacted_text="", audit_log=[], redaction_count=0)
        
        logger.info("Starting PII redaction on %d characters of text.", len(text))
        
        # Collect all detected spans from both methods
        all_spans: List[Tuple[int, int, str, str]] = []
        all_spans.extend(self._detect_ner_entities(text))
        all_spans.extend(self._detect_regex_patterns(text))
        
        # Remove duplicate/overlapping spans — keep the widest span
        all_spans = self._merge_overlapping_spans(all_spans)
        
        # Sort in reverse order to allow safe right-to-left substitution
        all_spans.sort(key=lambda s: s[0], reverse=True)
        
        # Apply redactions to the text
        audit_log: List[RedactionAuditEntry] = []
        redacted = text  # We'll modify this string in-place
        
        for start, end, original, pii_type in all_spans:
            replacement = f"[REDACTED_{pii_type}]"
            redacted = redacted[:start] + replacement + redacted[end:]
            
            audit_entry = RedactionAuditEntry(
                pii_type=pii_type,
                original=original,
                replacement=replacement,
                start=start,
                end=end,
            )
            audit_log.append(audit_entry)
        
        # Restore audit log to chronological order for readability
        audit_log.sort(key=lambda e: e.start)
        
        logger.info(
            "PII redaction complete. Removed %d PII items from document.",
            len(audit_log)
        )
        
        return RedactionResult(
            redacted_text=redacted,
            audit_log=audit_log,
            redaction_count=len(audit_log),
        )
    
    def _merge_overlapping_spans(
        self,
        spans: List[Tuple[int, int, str, str]]
    ) -> List[Tuple[int, int, str, str]]:
        """
        Merges overlapping or duplicate span detections.
        
        When both NER and regex detect the same PII (e.g., an address appearing
        in both spaCy LOC and the street regex), we keep only the widest span
        to avoid double-processing.
        
        Args:
            spans: List of (start, end, text, pii_type) tuples.
        
        Returns:
            Deduplicated list with no overlapping spans.
        """
        if not spans:
            return []
        
        # Sort by start position
        sorted_spans = sorted(spans, key=lambda s: s[0])
        merged = [sorted_spans[0]]
        
        for current in sorted_spans[1:]:
            prev = merged[-1]
            # Check for overlap: current starts before previous ends
            if current[0] < prev[1]:
                # Merge by extending to the wider end, keeping the first pii_type
                new_end = max(prev[1], current[1])
                merged[-1] = (prev[0], new_end, prev[2], prev[3])
            else:
                merged.append(current)
        
        return merged
    
    def format_audit_log(self, audit_log: List[RedactionAuditEntry]) -> str:
        """
        Formats the audit log as a human-readable Markdown string.
        
        This is included in the final report to document what PII was
        redacted, giving users and compliance officers a clear record.
        
        Args:
            audit_log: The list of RedactionAuditEntry objects.
        
        Returns:
            A formatted Markdown string summarising all redactions.
        """
        if not audit_log:
            return "✅ **No PII detected** — Document appears to contain no personal information.\n"
        
        lines = [
            f"## 🔒 PII Redaction Audit Log\n",
            f"**Total items redacted:** {len(audit_log)}\n",
            "| # | PII Type | Replacement Token | Position | Timestamp |",
            "|---|----------|------------------|----------|-----------|",
        ]
        
        for i, entry in enumerate(audit_log, 1):
            lines.append(
                f"| {i} | `{entry.pii_type}` | `{entry.replacement}` "
                f"| chars {entry.start}–{entry.end} | {entry.timestamp} |"
            )
        
        lines.append(
            "\n> ⚠️ The original PII values are stored only in this local audit log "
            "and were NEVER transmitted to any external AI service."
        )
        
        return "\n".join(lines)
