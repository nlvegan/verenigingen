"""
Cost Center Resolver

Centralized cost center resolution for all Mollie payment processing.
Consolidates logic previously split between payment_webhook.py and payment_entry_factory.py.

Uses consolidated cost center utilities from:
    verenigingen.e_boekhouden.utils.consolidated.cost_center_utils
"""

from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.e_boekhouden.utils.consolidated.cost_center_utils import (
    get_chapter_cost_center,
    get_default_cost_center,
    get_general_cost_center,
)

if TYPE_CHECKING:
    from ..payment_context_resolver import PaymentContext


class CostCenterResolver:
    """
    Resolves appropriate cost centers for payment processing.

    Cost center selection priority:
    1. Chapter-specific cost center (if donation is for a chapter)
    2. General/Main cost center
    3. Default non-group cost center (uses sophisticated fallback logic)

    Delegates to consolidated cost_center_utils for actual resolution.
    """

    def __init__(self):
        self.logger = frappe.logger()

    def resolve_for_context(self, context: "PaymentContext", company: str) -> str:
        """
        Resolve cost center based on PaymentContext.

        Args:
            context: PaymentContext with payment details
            company: Company name

        Returns:
            str: Cost center name
        """
        # Try to get donation from context if available
        donation = None
        if hasattr(context, "source_doc") and context.source_doc:
            if getattr(context.source_doc, "doctype", None) == "Donation":
                donation = context.source_doc

        return self.resolve_for_donation(donation, company)

    def resolve_for_donation(self, donation, company: str) -> str:
        """
        Resolve cost center based on donation document.

        Args:
            donation: Donation document (can be None)
            company: Company name

        Returns:
            str: Cost center name
        """
        default_cost_center = self._get_default_cost_center(company)

        if not donation:
            # No donation context - return general or default
            return self._get_general_cost_center(company) or default_cost_center

        # Check donation purpose type
        purpose_type = getattr(donation, "donation_purpose_type", None)

        if purpose_type == "Chapter" and hasattr(donation, "chapter_reference"):
            chapter_cost_center = self._get_chapter_cost_center(company, donation.chapter_reference)
            if chapter_cost_center:
                return chapter_cost_center

        # For General Fund or any other purpose, use general cost center
        return self._get_general_cost_center(company) or default_cost_center

    def _get_default_cost_center(self, company: str) -> Optional[str]:
        """
        Get default cost center for company using consolidated utility.

        Uses sophisticated fallback: company default -> Main -> company-named -> first eligible.
        """
        return get_default_cost_center(company)

    def _get_general_cost_center(self, company: str) -> Optional[str]:
        """Get a general/main cost center for company using consolidated utility."""
        return get_general_cost_center(company)

    def _get_chapter_cost_center(self, company: str, chapter_reference: str) -> Optional[str]:
        """Get chapter-specific cost center using consolidated utility."""
        return get_chapter_cost_center(company, chapter_reference)


# Module-level convenience functions for backward compatibility


def get_cost_center_for_donation(donation, company: str) -> str:
    """
    Get appropriate cost center based on donation purpose.

    This function provides backward compatibility with the original
    get_appropriate_cost_center() function from payment_webhook.py.

    Args:
        donation: Donation document (can be None)
        company: Company name

    Returns:
        str: Cost center name
    """
    resolver = CostCenterResolver()
    return resolver.resolve_for_donation(donation, company)


def get_cost_center_for_context(context: "PaymentContext", company: str) -> str:
    """
    Get appropriate cost center based on payment context.

    This function provides backward compatibility with the original
    get_appropriate_cost_center_for_context() function from payment_entry_factory.py.

    Args:
        context: PaymentContext with payment details
        company: Company name

    Returns:
        str: Cost center name
    """
    resolver = CostCenterResolver()
    return resolver.resolve_for_context(context, company)
