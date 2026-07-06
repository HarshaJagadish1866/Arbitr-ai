"""
utils/file_handler.py — File Type Validation and Handling
==========================================================

PURPOSE & DESIGN:
    This utility module provides safe, validated file access for LegalShield AI.
    It is the gatekeeper that ensures only supported, valid document files
    enter the pipeline.

    SUPPORTED FILE TYPES:
    - .pdf  — Adobe Portable Document Format (most common for contracts)
    - .docx — Microsoft Word Open XML (common for editable agreements)
    - .txt  — Plain text (for simple contracts or extracted text)

    UNSUPPORTED (with helpful error messages):
    - .doc  — Legacy Word format (requires different library — suggest converting)
    - .odt  — OpenDocument Text (suggest converting to .docx)
    - Images (.jpg, .png, .tiff) — Scanned documents; suggest OCR pre-processing
    - .pdf with only images — Detected and warned; text extraction will be empty

ERROR HANDLING PHILOSOPHY:
    This module raises specific, descriptive exceptions rather than returning
    error codes. This follows the "fail fast" principle: if a file is invalid,
    we want to know immediately (before any expensive API calls) with a clear
    explanation of exactly what went wrong and how to fix it.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported file extensions and their human-readable names
SUPPORTED_EXTENSIONS = {
    ".pdf":  "Adobe PDF",
    ".docx": "Microsoft Word",
    ".txt":  "Plain Text",
}

# Common unsupported formats with helpful upgrade hints
UNSUPPORTED_HINTS = {
    ".doc": (
        "Legacy Microsoft Word (.doc) format is not supported. "
        "Please open it in Microsoft Word or LibreOffice and save as .docx."
    ),
    ".odt": (
        "OpenDocument Text (.odt) is not supported. "
        "Please open it in LibreOffice and export as .docx or .pdf."
    ),
    ".jpg": (
        "Image files (.jpg) are not supported directly. "
        "If this is a scanned contract, please use an OCR tool to convert it "
        "to a text-searchable PDF first."
    ),
    ".png": (
        "Image files (.png) are not supported directly. "
        "If this is a scanned contract, please use an OCR tool to convert it "
        "to a text-searchable PDF first."
    ),
    ".tiff": (
        "TIFF image files are not supported. "
        "Please OCR the document to a text-searchable PDF first."
    ),
    ".rtf": (
        "Rich Text Format (.rtf) is not supported. "
        "Please open it in a word processor and save as .docx or .pdf."
    ),
}

# Maximum file size: 10MB (to prevent memory issues and extremely long processing)
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def validate_document_file(file_path: str) -> Path:
    """
    Validates that a file path refers to a supported, readable document.
    
    Performs the following checks in order:
    1. Path is not empty or None
    2. File exists on the filesystem
    3. Path points to a file (not a directory)
    4. File extension is in the supported list
    5. File is not empty (0 bytes)
    6. File is within the maximum size limit (10MB)
    7. File appears readable (no permission errors)
    
    Args:
        file_path: String path to the document file (absolute or relative).
    
    Returns:
        A resolved, absolute Path object for the validated file.
    
    Raises:
        ValueError: If file_path is empty or None.
        FileNotFoundError: If the file does not exist at the given path.
        IsADirectoryError: If the path points to a directory, not a file.
        ValueError: If the file extension is not supported (with helpful hint).
        ValueError: If the file is empty (0 bytes).
        ValueError: If the file exceeds the maximum size limit.
        PermissionError: If the file cannot be read due to permissions.
    """
    # --- Check 1: Non-empty path ---
    if not file_path or not file_path.strip():
        raise ValueError(
            "No document path provided. "
            "Usage: python main.py --document path/to/contract.pdf"
        )
    
    path = Path(file_path).resolve()
    
    # --- Check 2: File exists ---
    if not path.exists():
        raise FileNotFoundError(
            f"Document not found: '{file_path}'\n"
            "Please verify the file path is correct and the file exists."
        )
    
    # --- Check 3: Is a file (not a directory) ---
    if not path.is_file():
        raise IsADirectoryError(
            f"The path '{file_path}' is a directory, not a file. "
            "Please provide a path to a specific document file."
        )
    
    # --- Check 4: Supported file extension ---
    suffix = path.suffix.lower()
    
    if suffix not in SUPPORTED_EXTENSIONS:
        # Provide a helpful message for common unsupported formats
        if suffix in UNSUPPORTED_HINTS:
            hint = UNSUPPORTED_HINTS[suffix]
        else:
            supported_str = ", ".join(f"'{ext}'" for ext in SUPPORTED_EXTENSIONS)
            hint = (
                f"File type '{suffix}' is not supported. "
                f"Supported formats are: {supported_str}"
            )
        raise ValueError(hint)
    
    # --- Check 5: File is not empty ---
    file_size = path.stat().st_size
    
    if file_size == 0:
        raise ValueError(
            f"The file '{path.name}' is empty (0 bytes). "
            "Please provide a document that contains contract text."
        )
    
    # --- Check 6: File size within limits ---
    if file_size > MAX_FILE_SIZE_BYTES:
        size_mb = file_size / 1024 / 1024
        raise ValueError(
            f"The file '{path.name}' is too large ({size_mb:.1f} MB). "
            f"Maximum supported file size is {MAX_FILE_SIZE_MB} MB. "
            "For large contracts, consider splitting them into separate files."
        )
    
    # --- Check 7: File is readable ---
    try:
        # Attempt to open the file in read mode to check permissions
        with open(path, 'rb') as f:
            f.read(1)  # Read 1 byte — minimal I/O, just verifies readability
    except PermissionError:
        raise PermissionError(
            f"Cannot read file '{path.name}' — permission denied. "
            "Please check file permissions: chmod 644 {path}"
        )
    
    file_type_name = SUPPORTED_EXTENSIONS[suffix]
    logger.info(
        "File validated: '%s' (%s, %.1f KB)",
        path.name, file_type_name, file_size / 1024
    )
    
    return path


def get_file_info(file_path: str) -> dict:
    """
    Returns a dictionary of metadata about a document file.
    
    Useful for including file metadata in the final report header.
    Does NOT validate the file — call validate_document_file() first.
    
    Args:
        file_path: Path to the document file.
    
    Returns:
        Dict with keys: name, size_kb, extension, type_name, absolute_path
    """
    path = Path(file_path).resolve()
    suffix = path.suffix.lower()
    size_bytes = path.stat().st_size
    
    return {
        "name":          path.name,
        "size_kb":       round(size_bytes / 1024, 1),
        "extension":     suffix,
        "type_name":     SUPPORTED_EXTENSIONS.get(suffix, "Unknown"),
        "absolute_path": str(path),
    }
