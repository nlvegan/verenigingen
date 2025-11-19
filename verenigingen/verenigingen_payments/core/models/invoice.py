"""
Invoice Models for Mollie API
Data structures for invoice-related operations
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from .base import Amount, BaseModel, Links


class InvoiceStatus(Enum):
    """Invoice status types"""

    OPEN = "open"
    PAID = "paid"
    OVERDUE = "overdue"


class InvoiceLine(BaseModel):
    """
    Line item on an invoice
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize invoice line"""
        self.period: Optional[str] = None
        self.description: Optional[str] = None
        self.count: Optional[int] = None
        self.vat_percentage: Optional[float] = None
        self.amount: Optional[Amount] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name == "amount":
            return Amount
        return None

    def calculate_total(self) -> Decimal:
        """Calculate total amount for line"""
        if self.amount and hasattr(self.amount, "decimal_value") and self.count:
            return self.amount.decimal_value * self.count
        return Decimal("0")


class Invoice(BaseModel):
    """
    Mollie Invoice resource

    Represents an invoice from Mollie for fees and services
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize invoice"""
        self.resource: str = "invoice"
        self.id: Optional[str] = None
        self.reference: Optional[str] = None
        self.vat_number: Optional[str] = None
        self.status: Optional[str] = None
        self.issued_at: Optional[str] = None
        self.paid_at: Optional[str] = None
        self.due_at: Optional[str] = None
        self.lines: Optional[List[InvoiceLine]] = None
        self.net_amount: Optional[Amount] = None
        self.vat_amount: Optional[Amount] = None
        self.gross_amount: Optional[Amount] = None
        self.settlements: Optional[List[str]] = None
        self._links: Optional[Links] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name in ["net_amount", "vat_amount", "gross_amount"]:
            return Amount
        elif attr_name == "_links":
            return Links
        return None

    def _post_init(self):
        """Parse dates and lines"""
        # Parse dates
        if self.issued_at and isinstance(self.issued_at, str):
            try:
                # Handle date-only format
                if "T" not in self.issued_at:
                    self.issued_at_date = datetime.strptime(self.issued_at, "%Y-%m-%d").date()
                else:
                    self.issued_at_datetime = datetime.fromisoformat(self.issued_at.replace("Z", "+00:00"))
            except:
                self.issued_at_date = None
                self.issued_at_datetime = None

        if self.paid_at and isinstance(self.paid_at, str):
            try:
                if "T" not in self.paid_at:
                    self.paid_at_date = datetime.strptime(self.paid_at, "%Y-%m-%d").date()
                else:
                    self.paid_at_datetime = datetime.fromisoformat(self.paid_at.replace("Z", "+00:00"))
            except:
                self.paid_at_date = None
                self.paid_at_datetime = None

        if self.due_at and isinstance(self.due_at, str):
            try:
                if "T" not in self.due_at:
                    self.due_at_date = datetime.strptime(self.due_at, "%Y-%m-%d").date()
                else:
                    self.due_at_datetime = datetime.fromisoformat(self.due_at.replace("Z", "+00:00"))
            except:
                self.due_at_date = None
                self.due_at_datetime = None

        # Parse lines
        if self.lines and isinstance(self.lines, list):
            parsed_lines = []
            for line in self.lines:
                if isinstance(line, dict):
                    parsed_lines.append(InvoiceLine(line))
                else:
                    parsed_lines.append(line)
            self.lines = parsed_lines

    def is_paid(self) -> bool:
        """Check if invoice is paid"""
        return self.status == InvoiceStatus.PAID.value

    def is_overdue(self) -> bool:
        """Check if invoice is overdue"""
        return self.status == InvoiceStatus.OVERDUE.value

    def calculate_total_lines(self) -> Decimal:
        """Calculate total from invoice lines"""
        total = Decimal("0")

        if self.lines:
            for line in self.lines:
                if isinstance(line, InvoiceLine):
                    total += line.calculate_total()

        return total

    def get_vat_rate(self) -> float:
        """Calculate effective VAT rate"""
        if (
            self.net_amount
            and hasattr(self.net_amount, "decimal_value")
            and self.vat_amount
            and hasattr(self.vat_amount, "decimal_value")
        ):
            net = self.net_amount.decimal_value
            vat = self.vat_amount.decimal_value

            if net > 0:
                return float((vat / net) * 100)

        return 0.0
