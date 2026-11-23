"""
Payment Context Resolver

Determines the payment context (donation, membership, etc.) from Mollie payment data
without being tied to any specific payment type.
"""

from typing import Any, Dict


class PaymentContext:
    """Container for payment context information"""

    def __init__(
        self, payment_type: str, target_doctype: str, target_name: str, metadata: Dict[str, Any] = None
    ):
        # A PaymentContext is only meaningful if it identifies a concrete target
        # document to attribute the payment to. Reject empty/blank fields at
        # construction so a partially-resolved context can never masquerade as a
        # real one downstream (payment attribution, reconciliation).
        for field_name, value in (
            ("payment_type", payment_type),
            ("target_doctype", target_doctype),
            ("target_name", target_name),
        ):
            if not value or not str(value).strip():
                raise ValueError(f"PaymentContext.{field_name} is required (got {value!r})")

        self.payment_type = payment_type  # 'donation', 'membership', etc.
        self.target_doctype = target_doctype  # 'Donation', 'Member', etc.
        self.target_name = target_name  # The document name
        self.metadata = metadata or {}

    def __str__(self):
        return f"PaymentContext(type={self.payment_type}, target={self.target_doctype}:{self.target_name})"
