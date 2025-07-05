# verenigingen/verenigingen/doctype/chapter/validators/init.py
"""
Chapter Validators Package
This package contains all validation logic for the Chapter doctype, organized into
focused, testable, and reusable validator classes.
Validators:
- BaseValidator: Base class with common validation utilities
- ChapterInfoValidator: Validates basic chapter information
- BoardMemberValidator: Validates board member data and constraints
- PostalCodeValidator: Validates postal code patterns
- ChapterValidator: Main coordinator that orchestrates all validation
Usage:
    from .validators import ChapterValidator

    validator = ChapterValidator(chapter_doc)
    result = validator.validate_all()

    if not result.is_valid:
        frappe.throw("Validation failed: " + ", ".join(result.errors))
"""
from .board_member_validator import BoardMemberValidator
from .chapter_validator import ChapterValidator
from .postal_code_validator import PostalCodeValidator

all = [
    "BaseValidator",
    "ValidationResult",
    "ChapterInfoValidator",
    "BoardMemberValidator",
    "PostalCodeValidator",
    "ChapterValidator",
]
# Version info
version = "1.0.0"
author = "Verenigingen Development Team"


# Convenience functions for common validation scenarios
def validate_chapter(chapter_doc):
    """
    Convenience function to validate a chapter document

    Args:
        chapter_doc: Chapter document instance

    Returns:
        ValidationResult: Validation result with errors and warnings
    """
    validator = ChapterValidator(chapter_doc)
    return validator.validate_all()


def validate_board_members(board_members_list):
    """
    Convenience function to validate board members list

    Args:
        board_members_list: List of board member dictionaries

    Returns:
        ValidationResult: Validation result
    """
    validator = BoardMemberValidator()
    return validator.validate_all_board_members(board_members_list)


def validate_postal_codes(postal_codes_string):
    """
    Convenience function to validate postal code patterns

    Args:
        postal_codes_string: Comma-separated postal code patterns

    Returns:
        ValidationResult: Validation result
    """
    validator = PostalCodeValidator()
    return validator.validate_postal_codes(postal_codes_string)


def check_publication_readiness(chapter_doc):
    """
    Check if a chapter is ready for publication

    Args:
        chapter_doc: Chapter document instance

    Returns:
        dict: Publication readiness status with issues and score
    """
    validator = ChapterValidator(chapter_doc)
    summary = validator.get_validation_summary()
    return summary.get("ready_for_publication", {})
