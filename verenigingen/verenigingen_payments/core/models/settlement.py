"""
Settlement Models for Mollie API
Data structures for settlement-related operations
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

import frappe

from .base import Amount, BaseModel, Links


class SettlementStatus(Enum):
    """Settlement status types"""

    OPEN = "open"
    PENDING = "pending"
    PAIDOUT = "paidout"
    FAILED = "failed"


class SettlementPeriod(BaseModel):
    """
    Settlement period information
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize settlement period"""
        self.revenue: Optional[List[Dict[str, Any]]] = None
        self.costs: Optional[List[Dict[str, Any]]] = None
        self.invoice_id: Optional[str] = None
        super().__init__(data)

    def calculate_net_amount(self) -> Decimal:
        """Calculate net amount for period"""
        total_revenue = Decimal("0")
        total_costs = Decimal("0")

        # Sum revenue
        if self.revenue:
            for item in self.revenue:
                if "amountNet" in item and "value" in item["amountNet"]:
                    try:
                        total_revenue += Decimal(item["amountNet"]["value"])
                    except:
                        pass

        # Sum costs
        if self.costs:
            for item in self.costs:
                if "amountNet" in item and "value" in item["amountNet"]:
                    try:
                        total_costs += Decimal(item["amountNet"]["value"])
                    except:
                        pass

        return total_revenue - total_costs


class Settlement(BaseModel):
    """
    Mollie Settlement resource

    Represents a settlement of funds from Mollie to merchant account
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize settlement"""
        self.resource: str = "settlement"
        self.id: Optional[str] = None
        self.reference: Optional[str] = None
        self.created_at: Optional[str] = None
        self.settled_at: Optional[str] = None
        self.status: Optional[str] = None
        self.amount: Optional[Amount] = None
        self.periods: Optional[Dict[str, SettlementPeriod]] = None
        self.invoice_id: Optional[str] = None
        self._links: Optional[Links] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name == "amount":
            return Amount
        elif attr_name == "_links":
            return Links
        return None

    def _post_init(self):
        """Parse dates and periods with consistent timezone handling"""
        # Parse dates with proper timezone handling
        if self.created_at and isinstance(self.created_at, str):
            try:
                dt = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
                self.created_at_datetime = dt.replace(
                    tzinfo=None
                )  # Convert to naive for consistent comparison
            except (ValueError, TypeError) as e:
                frappe.logger().warning(f"Failed to parse settlement created_at date: {e}")
                self.created_at_datetime = None

        if self.settled_at and isinstance(self.settled_at, str):
            try:
                dt = datetime.fromisoformat(self.settled_at.replace("Z", "+00:00"))
                self.settled_at_datetime = dt.replace(
                    tzinfo=None
                )  # Convert to naive for consistent comparison
            except (ValueError, TypeError) as e:
                frappe.logger().warning(f"Failed to parse settlement settled_at date: {e}")
                self.settled_at_datetime = None

        # Parse periods
        if self.periods and isinstance(self.periods, dict):
            parsed_periods = {}
            for year_month, period_data in self.periods.items():
                if isinstance(period_data, dict):
                    parsed_periods[year_month] = SettlementPeriod(period_data)
                else:
                    parsed_periods[year_month] = period_data
            self.periods = parsed_periods

    def is_settled(self) -> bool:
        """Check if settlement is paid out"""
        return self.status == SettlementStatus.PAIDOUT.value

    def is_failed(self) -> bool:
        """Check if settlement failed"""
        return self.status == SettlementStatus.FAILED.value

    def get_total_revenue(self) -> Decimal:
        """Calculate total revenue across all periods"""
        total = Decimal("0")

        if self.periods:
            for period in self.periods.values():
                if isinstance(period, SettlementPeriod) and period.revenue:
                    for item in period.revenue:
                        if "amountNet" in item and "value" in item["amountNet"]:
                            try:
                                total += Decimal(item["amountNet"]["value"])
                            except:
                                pass

        return total

    def get_total_costs(self) -> Decimal:
        """Calculate total costs across all periods"""
        total = Decimal("0")

        if self.periods:
            for period in self.periods.values():
                if isinstance(period, SettlementPeriod) and period.costs:
                    for item in period.costs:
                        if "amountNet" in item and "value" in item["amountNet"]:
                            try:
                                total += Decimal(item["amountNet"]["value"])
                            except:
                                pass

        return total


class SettlementLine(BaseModel):
    """
    Individual line item in a settlement
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize settlement line"""
        self.id: Optional[str] = None
        self.type: Optional[str] = None
        self.amount: Optional[Amount] = None
        self.description: Optional[str] = None
        self.created_at: Optional[str] = None
        self.metadata: Optional[Dict[str, Any]] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name == "amount":
            return Amount
        return None

    def _post_init(self):
        """Parse dates"""
        if self.created_at and isinstance(self.created_at, str):
            try:
                self.created_at_datetime = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            except:
                self.created_at_datetime = None


class SettlementCapture(BaseModel):
    """
    Settlement capture details
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize settlement capture"""
        self.resource: str = "capture"
        self.id: Optional[str] = None
        self.mode: Optional[str] = None
        self.amount: Optional[Amount] = None
        self.settlement_amount: Optional[Amount] = None
        self.payment_id: Optional[str] = None
        self.shipment_id: Optional[str] = None
        self.settlement_id: Optional[str] = None
        self.created_at: Optional[str] = None
        self._links: Optional[Links] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name in ["amount", "settlement_amount"]:
            return Amount
        elif attr_name == "_links":
            return Links
        return None

    def _post_init(self):
        """Parse dates"""
        if self.created_at and isinstance(self.created_at, str):
            try:
                self.created_at_datetime = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            except:
                self.created_at_datetime = None
