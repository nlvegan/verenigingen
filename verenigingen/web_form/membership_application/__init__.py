"""
Compatibility shim for old membership_application imports.

This module provides backwards compatibility for code that imports from
verenigingen.verenigingen.web_form.membership_application.

The actual implementations have been moved to the API modules.
"""

# Re-export the actual implementation
from verenigingen.api.membership_application_review import approve_membership_application


# Stub implementations for functions that may have been removed/refactored
def submit_membership_application(*args, **kwargs):
    """Stub - this function has been deprecated or refactored."""
    raise NotImplementedError(
        "submit_membership_application has been deprecated. "
        "Use the Member DocType directly or the API modules instead."
    )


def create_volunteer_application_data(*args, **kwargs):
    """Stub - this function has been deprecated or refactored."""
    raise NotImplementedError(
        "create_volunteer_application_data has been deprecated. "
        "Handle volunteer data through the Volunteer DocType instead."
    )


def create_volunteer_from_approved_member(*args, **kwargs):
    """Stub - this function has been deprecated or refactored."""
    raise NotImplementedError(
        "create_volunteer_from_approved_member has been deprecated. "
        "Use the Volunteer DocType or service layer instead."
    )


def parse_volunteer_data_from_notes(*args, **kwargs):
    """Stub - this function has been deprecated or refactored."""
    raise NotImplementedError("parse_volunteer_data_from_notes has been deprecated.")


def add_skills_to_volunteer(*args, **kwargs):
    """Stub - this function has been deprecated or refactored."""
    raise NotImplementedError(
        "add_skills_to_volunteer has been deprecated. " "Use the volunteer_skills API module instead."
    )


def get_proficiency_label(*args, **kwargs):
    """Stub - this function has been deprecated or refactored."""
    raise NotImplementedError("get_proficiency_label has been deprecated.")


__all__ = [
    "approve_membership_application",
    "submit_membership_application",
    "create_volunteer_application_data",
    "create_volunteer_from_approved_member",
    "parse_volunteer_data_from_notes",
    "add_skills_to_volunteer",
    "get_proficiency_label",
]
