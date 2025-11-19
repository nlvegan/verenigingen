"""
Mollie API Test Data Factory

Provides realistic test data generation for Mollie Backend API integration tests.
Focuses on generating data that matches actual Mollie API response formats,
especially for testing timezone handling, date parsing, and API filtering issues.
"""

import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Union
from uuid import uuid4

import frappe
from faker import Faker
from frappe.utils import random_string


class MollieApiDataFactory:
    """
    Factory for generating realistic Mollie API response data
    
    This factory generates test data that matches the exact structure and
    formats returned by the Mollie API, including proper timezone information,
    status transitions, and edge cases that were causing bugs.
    """
    
    def __init__(self, seed: int = None):
        """Initialize factory with optional seed for reproducible data"""
        self.fake = Faker()
        if seed:
            Faker.seed(seed)
            random.seed(seed)
        
        # Common currencies and statuses for realistic data
        self.currencies = ["EUR", "USD", "GBP"]
        self.settlement_statuses = ["open", "pending", "paidout", "failed"]
        self.payment_statuses = ["open", "canceled", "pending", "authorized", "expired", "failed", "paid"]
        self.chargeback_statuses = ["queued", "pending", "resolved", "charged_back"]
        
    def generate_mollie_amount(self, min_value: float = 1.00, max_value: float = 1000.00, currency: str = "EUR") -> Dict:
        """Generate Mollie amount object with proper decimal formatting"""
        # Generate amount with 2 decimal places like Mollie API
        value = round(random.uniform(min_value, max_value), 2)
        return {
            "value": f"{value:.2f}",
            "currency": currency
        }
    
    def generate_mollie_datetime(
        self, 
        days_ago_min: int = 0, 
        days_ago_max: int = 30,
        include_timezone: bool = True
    ) -> str:
        """Generate Mollie-style datetime string with timezone info"""
        # Generate a datetime in the past
        days_ago = random.randint(days_ago_min, days_ago_max)
        hours_ago = random.randint(0, 23)
        minutes_ago = random.randint(0, 59)
        
        base_time = datetime.now() - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)
        
        if include_timezone:
            # Return in the format that was causing timezone comparison issues
            return base_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        else:
            return base_time.strftime("%Y-%m-%dT%H:%M:%S")
    
    def generate_settlement_data(
        self, 
        status: str = None,
        amount_range: tuple = (100.0, 2000.0),
        include_settled_date: bool = None,
        currency: str = "EUR"
    ) -> Dict:
        """Generate realistic settlement data matching Mollie API format"""
        if status is None:
            status = random.choice(self.settlement_statuses)
        
        # Only paidout settlements have settledAt dates
        if include_settled_date is None:
            include_settled_date = (status == "paidout")
        
        settlement_id = f"stl_{random_string(10).lower()}"
        
        settlement = {
            "resource": "settlement",
            "id": settlement_id,
            "reference": f"REF-{random.randint(1000, 9999)}-{datetime.now().strftime('%Y%m')}",
            "status": status,
            "amount": self.generate_mollie_amount(amount_range[0], amount_range[1], currency),
            "createdAt": self.generate_mollie_datetime(days_ago_max=60),
            "periods": {
                f"{datetime.now().year}-{datetime.now().month:02d}": {
                    "revenue": [
                        {
                            "description": f"Payment {random_string(8)}",
                            "method": random.choice(["creditcard", "ideal", "banktransfer", "paypal"]),
                            "count": random.randint(1, 50),
                            "amountNet": self.generate_mollie_amount(50.0, 500.0, currency),
                            "amountVat": self.generate_mollie_amount(10.0, 100.0, currency),
                            "amountGross": self.generate_mollie_amount(60.0, 600.0, currency),
                        }
                    ],
                    "costs": [
                        {
                            "description": "Transaction fees",
                            "method": "creditcard",
                            "count": random.randint(1, 20),
                            "rate": {
                                "fixed": self.generate_mollie_amount(0.25, 0.35, currency),
                                "percentage": f"{random.uniform(1.8, 2.9):.1f}"
                            },
                            "amountNet": self.generate_mollie_amount(5.0, 50.0, currency),
                            "amountVat": self.generate_mollie_amount(1.0, 10.0, currency),
                            "amountGross": self.generate_mollie_amount(6.0, 60.0, currency),
                        }
                    ]
                }
            },
            "_links": {
                "self": {
                    "href": f"https://api.mollie.com/v2/settlements/{settlement_id}",
                    "type": "application/hal+json"
                },
                "payments": {
                    "href": f"https://api.mollie.com/v2/settlements/{settlement_id}/payments",
                    "type": "application/hal+json"
                }
            }
        }
        
        # Add settledAt only if settlement is paidout (this was causing filtering bugs)
        if include_settled_date and status == "paidout":
            settlement["settledAt"] = self.generate_mollie_datetime(days_ago_max=30)
        
        return settlement
    
    def generate_settlement_list(
        self, 
        count: int = 10,
        status_distribution: Dict[str, float] = None,
        date_range_days: int = 90
    ) -> List[Dict]:
        """Generate a list of settlements with realistic status distribution"""
        if status_distribution is None:
            status_distribution = {
                "paidout": 0.7,  # 70% of settlements are paid out
                "pending": 0.2,  # 20% are pending
                "open": 0.08,    # 8% are open
                "failed": 0.02   # 2% failed
            }
        
        settlements = []
        
        for _ in range(count):
            # Choose status based on distribution
            rand = random.random()
            cumulative = 0
            chosen_status = "paidout"  # default
            
            for status, probability in status_distribution.items():
                cumulative += probability
                if rand <= cumulative:
                    chosen_status = status
                    break
            
            settlement = self.generate_settlement_data(
                status=chosen_status,
                amount_range=(50.0, 5000.0)
            )
            settlements.append(settlement)
        
        # Sort by createdAt date (most recent first, like Mollie API)
        settlements.sort(key=lambda x: x["createdAt"], reverse=True)
        
        return settlements
    
    def generate_balance_data(self, currency: str = "EUR", status: str = "active") -> Dict:
        """Generate realistic balance data"""
        return {
            "resource": "balance",
            "id": f"bal_{random_string(10).lower()}",
            "currency": currency,
            "status": status,
            "availableAmount": self.generate_mollie_amount(0.0, 10000.0, currency),
            "pendingAmount": self.generate_mollie_amount(0.0, 1000.0, currency),
            "transferFrequency": random.choice(["daily", "weekly", "monthly"]),
            "transferThreshold": self.generate_mollie_amount(100.0, 1000.0, currency),
            "transferDestination": {
                "type": "bank-account",
                "bankAccount": f"NL{random.randint(10, 99)}BANK{random.randint(1000000000, 9999999999)}"
            },
            "createdAt": self.generate_mollie_datetime(days_ago_max=365),
            "_links": {
                "self": {
                    "href": f"https://api.mollie.com/v2/balances/bal_{random_string(10).lower()}",
                    "type": "application/hal+json"
                }
            }
        }
    
    def generate_chargeback_data(
        self, 
        payment_id: str = None,
        status: str = None,
        amount_range: tuple = (50.0, 500.0)
    ) -> Dict:
        """Generate realistic chargeback data"""
        if status is None:
            status = random.choice(self.chargeback_statuses)
        
        if payment_id is None:
            payment_id = f"tr_{random_string(10).lower()}"
        
        chargeback_id = f"chb_{random_string(10).lower()}"
        
        return {
            "resource": "chargeback",
            "id": chargeback_id,
            "amount": self.generate_mollie_amount(amount_range[0], amount_range[1]),
            "settlementAmount": self.generate_mollie_amount(amount_range[0] * -1, amount_range[1] * -1),  # Negative for chargebacks
            "reason": random.choice([
                "duplicate",
                "fraud", 
                "subscription_canceled",
                "product_unacceptable",
                "product_not_received",
                "unrecognized",
                "credit_not_processed"
            ]),
            "reasonCode": random.choice(["4853", "4855", "4840", "4837", "4834"]),
            "status": status,
            "createdAt": self.generate_mollie_datetime(days_ago_max=60),
            "reversedAt": self.generate_mollie_datetime(days_ago_max=30) if status == "resolved" else None,
            "paymentId": payment_id,
            "_links": {
                "self": {
                    "href": f"https://api.mollie.com/v2/payments/{payment_id}/chargebacks/{chargeback_id}",
                    "type": "application/hal+json"
                },
                "payment": {
                    "href": f"https://api.mollie.com/v2/payments/{payment_id}",
                    "type": "application/hal+json"
                }
            }
        }
    
    def generate_invoice_data(
        self, 
        status: str = None,
        is_overdue: bool = False
    ) -> Dict:
        """Generate realistic invoice data"""
        if status is None:
            status = random.choice(["open", "paid", "overdue", "canceled"])
        
        if is_overdue:
            status = "overdue"
        
        invoice_id = f"inv_{random_string(10).lower()}"
        
        # Generate due date based on status
        if status == "overdue":
            due_date = self.generate_mollie_datetime(days_ago_min=1, days_ago_max=60)
        else:
            due_date = self.generate_mollie_datetime(days_ago_min=-30, days_ago_max=30)
        
        return {
            "resource": "invoice",
            "id": invoice_id,
            "reference": f"INV-{random.randint(1000, 9999)}-{datetime.now().strftime('%Y')}",
            "status": status,
            "issuedAt": self.generate_mollie_datetime(days_ago_max=90),
            "dueAt": due_date,
            "paidAt": self.generate_mollie_datetime(days_ago_max=30) if status == "paid" else None,
            "netAmount": self.generate_mollie_amount(100.0, 2000.0),
            "vatAmount": self.generate_mollie_amount(20.0, 400.0),
            "grossAmount": self.generate_mollie_amount(120.0, 2400.0),
            "lines": [
                {
                    "period": f"{datetime.now().year}-{random.randint(1, 12):02d}",
                    "description": f"Transaction fees for {self.fake.month_name()}",
                    "count": random.randint(10, 1000),
                    "vatPercentage": 21.0,
                    "amount": self.generate_mollie_amount(50.0, 1000.0)
                }
            ],
            "_links": {
                "self": {
                    "href": f"https://api.mollie.com/v2/invoices/{invoice_id}",
                    "type": "application/hal+json"
                },
                "pdf": {
                    "href": f"https://api.mollie.com/v2/invoices/{invoice_id}.pdf",
                    "type": "application/pdf"
                }
            }
        }
    
    def generate_webhook_payload(
        self, 
        resource_type: str = "payment",
        resource_id: str = None,
        include_signature_data: bool = True
    ) -> Dict:
        """Generate realistic webhook payload for testing signature validation"""
        if resource_id is None:
            prefixes = {
                "payment": "tr_",
                "settlement": "stl_",
                "chargeback": "chb_",
                "refund": "re_"
            }
            prefix = prefixes.get(resource_type, "tr_")
            resource_id = f"{prefix}{random_string(10).lower()}"
        
        payload = {
            "resource": resource_type,
            "id": resource_id,
            "_links": {
                "self": {
                    "href": f"https://api.mollie.com/v2/{resource_type}s/{resource_id}",
                    "type": "application/hal+json"
                }
            }
        }
        
        result = {
            "payload": json.dumps(payload),
            "timestamp": datetime.now().isoformat(),
        }
        
        if include_signature_data:
            # Generate mock signature for testing
            result["signature"] = f"sha256={random_string(64).lower()}"
            result["webhook_secret"] = f"whsec_{random_string(32)}"
        
        return result

    def generate_edge_case_settlements(self) -> List[Dict]:
        """Generate edge case settlement data that was causing bugs"""
        edge_cases = []
        
        # Case 1: Settlement with only createdAt, no settledAt (was causing date filtering issues)
        edge_cases.append(self.generate_settlement_data(
            status="pending",
            include_settled_date=False
        ))
        
        # Case 2: Settlement with both dates but different timezones (timezone comparison bug)
        settlement_with_tz = self.generate_settlement_data(status="paidout")
        # Modify to have timezone info that was causing comparison failures
        settlement_with_tz["settledAt"] = "2025-08-01T13:00:00+02:00"  # Different timezone format
        edge_cases.append(settlement_with_tz)
        
        # Case 3: Very old settlement (edge case for date ranges)
        old_settlement = self.generate_settlement_data(
            status="paidout",
            amount_range=(1.0, 10.0)  # Very small amount
        )
        old_settlement["createdAt"] = "2020-01-01T00:00:00Z"
        old_settlement["settledAt"] = "2020-01-01T12:00:00Z"
        edge_cases.append(old_settlement)
        
        # Case 4: Settlement with zero amount (edge case for calculations)
        zero_settlement = self.generate_settlement_data()
        zero_settlement["amount"] = {"value": "0.00", "currency": "EUR"}
        edge_cases.append(zero_settlement)
        
        # Case 5: Settlement with very large amount (edge case for decimal handling)
        large_settlement = self.generate_settlement_data(
            amount_range=(99999.99, 99999.99)
        )
        edge_cases.append(large_settlement)
        
        # Case 6: Settlement with invalid/missing periods (was causing calculation errors)
        invalid_periods = self.generate_settlement_data()
        invalid_periods["periods"] = {}  # Empty periods
        edge_cases.append(invalid_periods)
        
        return edge_cases

    def generate_timezone_test_data(self) -> Dict:
        """Generate specific data for testing timezone handling fixes"""
        now = datetime.now()
        
        return {
            "settlements_mixed_timezones": [
                # Settlement with Z suffix (UTC)
                {
                    **self.generate_settlement_data(status="paidout"),
                    "settledAt": "2025-08-01T13:00:00Z",
                    "createdAt": "2025-07-15T10:00:00Z"
                },
                # Settlement with +00:00 (explicit UTC)
                {
                    **self.generate_settlement_data(status="paidout"),
                    "settledAt": "2025-08-01T13:00:00+00:00",
                    "createdAt": "2025-07-15T10:00:00+00:00"
                },
                # Settlement with different timezone
                {
                    **self.generate_settlement_data(status="paidout"),
                    "settledAt": "2025-08-01T15:00:00+02:00",  # Same time as first, different format
                    "createdAt": "2025-07-15T12:00:00+02:00"
                },
                # Settlement with only createdAt (no timezone issues)
                {
                    **self.generate_settlement_data(status="pending"),
                    "createdAt": "2025-08-10T09:00:00Z"
                    # No settledAt field
                }
            ],
            "current_period_boundaries": {
                "now": now.isoformat(),
                "month_start": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(),
                "week_start": (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                "quarter_start": now.replace(month=((now.month - 1) // 3) * 3 + 1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
            }
        }

    def generate_api_error_responses(self) -> Dict[str, Dict]:
        """Generate realistic API error responses for testing error handling"""
        return {
            "bad_request_unsupported_params": {
                "status": 400,
                "title": "Bad Request",
                "detail": "The from parameter is not supported for this endpoint",
                "field": "from",
                "_links": {
                    "documentation": {
                        "href": "https://docs.mollie.com/api/settlements#list-settlements",
                        "type": "text/html"
                    }
                }
            },
            "rate_limit_exceeded": {
                "status": 429,
                "title": "Too Many Requests",
                "detail": "You have exceeded the API rate limit. Please retry after some time.",
                "_links": {
                    "documentation": {
                        "href": "https://docs.mollie.com/api/rate-limiting",
                        "type": "text/html"
                    }
                }
            },
            "unauthorized": {
                "status": 401,
                "title": "Unauthorized",
                "detail": "Missing authentication, or failed to authenticate",
                "_links": {
                    "documentation": {
                        "href": "https://docs.mollie.com/api/authentication",
                        "type": "text/html"
                    }
                }
            },
            "not_found": {
                "status": 404,
                "title": "Not Found",
                "detail": "The settlement could not be found",
                "_links": {
                    "documentation": {
                        "href": "https://docs.mollie.com/api/settlements",
                        "type": "text/html"
                    }
                }
            }
        }


# Convenience functions for common test scenarios
def create_test_settlements_for_revenue_analysis(month_count: int = 3) -> List[Dict]:
    """Create settlements specifically for testing revenue analysis with timezone issues"""
    factory = MollieApiDataFactory(seed=42)  # Deterministic for testing
    
    settlements = []
    base_date = datetime.now()
    
    for month_offset in range(month_count):
        # Create settlements for each month with proper dates
        month_date = base_date - timedelta(days=30 * month_offset)
        
        # Create 3-5 settlements per month
        for i in range(random.randint(3, 5)):
            settlement = factory.generate_settlement_data(
                status="paidout",
                amount_range=(200.0, 2000.0)
            )
            
            # Set specific dates within the month
            day = random.randint(1, 28)
            settlement_date = month_date.replace(day=day)
            
            settlement["settledAt"] = settlement_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            settlement["createdAt"] = (settlement_date - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            settlements.append(settlement)
    
    return settlements


def create_test_data_for_caching_validation() -> Dict:
    """Create test data specifically for validating caching mechanisms"""
    factory = MollieApiDataFactory(seed=123)
    
    # Create a realistic set of settlements that should be cached
    settlements = factory.generate_settlement_list(count=15)
    
    return {
        "settlements": settlements,
        "balances": [factory.generate_balance_data() for _ in range(3)],
        "api_call_metadata": {
            "first_call_time": datetime.now().isoformat(),
            "expected_cache_hit": True,
            "cache_key_pattern": "settlements_list_*"
        }
    }
