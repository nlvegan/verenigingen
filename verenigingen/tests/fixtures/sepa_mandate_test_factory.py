#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEPA Mandate Test Factory Extension
==================================

Specialized test factory extension for Enhanced Test Factory that provides
comprehensive SEPA mandate test data generation with Dutch banking compliance.

This module extends the Enhanced Test Factory with SEPA-specific functionality
while maintaining the same business logic validation and field safety principles.

Key Features:
- Realistic Dutch banking test data (IBAN, BIC, bank names)
- SEPA mandate lifecycle scenario generation
- European banking regulation compliance testing
- Integration with Mollie payment gateway testing
- PSD2 compliance validation scenarios

Usage:
```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_mandate_test_factory import SEPAMandateTestMixin

class TestSEPAFeature(EnhancedTestCase, SEPAMandateTestMixin):
    def test_mandate_creation(self):
        member = self.create_test_member(birth_date="1990-01-01")
        mandate = self.create_test_sepa_mandate(member=member, status="Active")
        self.assertEqual(mandate.status, "Active")
```

Compliance Focus:
- Dutch banking standards (DNB regulations)
- SEPA mandate lifecycle rules
- PSD2 payment services directive
- GDPR data protection requirements
"""

import random
from datetime import datetime, date
from typing import Dict, Any, Optional, List, Union

import frappe
from frappe import _
from frappe.utils import (
    add_days, 
    today, 
    getdate,
    random_string,
    flt,
    cstr
)

# Import Enhanced Test Factory for integration
try:
    from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory
    HAS_ENHANCED_FACTORY = True
except ImportError:
    HAS_ENHANCED_FACTORY = False

# Import validation utilities
try:
    from verenigingen.utils.validation.iban_validator import (
        validate_iban,
        format_iban,
        derive_bic_from_iban
    )
    HAS_IBAN_VALIDATOR = True
except ImportError:
    HAS_IBAN_VALIDATOR = False


class SEPAMandateTestDataFactory:
    """
    Comprehensive SEPA mandate test data factory with realistic European banking data.
    
    This factory generates test data that complies with:
    - Dutch banking regulations (DNB)
    - SEPA mandate requirements
    - PSD2 payment services directive
    - European banking standards
    """
    
    # Comprehensive Dutch banking data for realistic testing
    DUTCH_BANKS = {
        "ABNA": {
            "bic": "ABNANL2A",
            "name": "ABN AMRO Bank N.V.",
            "test_ibans": [
                "NL91ABNA0417164300",
                "NL39ABNA0123456789",
                "NL17ABNA9876543210"
            ]
        },
        "INGB": {
            "bic": "INGBNL2A", 
            "name": "ING Bank N.V.",
            "test_ibans": [
                "NL27INGB0001234567",
                "NL53INGB0987654321",
                "NL89INGB0555666777"
            ]
        },
        "RABO": {
            "bic": "RABONL2U",
            "name": "Rabobank Nederland", 
            "test_ibans": [
                "NL13RABO0123456789",
                "NL46RABO0987654321",
                "NL72RABO0111222333"
            ]
        },
        "SNSB": {
            "bic": "SNSBNL2A",
            "name": "SNS Bank N.V.",
            "test_ibans": [
                "NL98SNSB0123456789",
                "NL54SNSB0987654321"
            ]
        },
        "TRIO": {
            "bic": "TRIONL2U", 
            "name": "Triodos Bank N.V.",
            "test_ibans": [
                "NL25TRIO0123456789",
                "NL81TRIO0987654321"
            ]
        },
        "ASNB": {
            "bic": "ASNBNL21",
            "name": "ASN Bank N.V.",
            "test_ibans": [
                "NL69ASNB0123456789"
            ]
        }
    }
    
    # European test IBANs for cross-border testing
    EUROPEAN_TEST_IBANS = {
        "DE": [
            "DE89370400440532013000",  # Deutsche Bank
            "DE12500105170648489890",  # DZ Bank
            "DE75500105179972073000"   # Commerzbank
        ],
        "FR": [
            "FR1420041010050500013M02606",  # BNP Paribas
            "FR7630001007941234567890185",  # Crédit Agricole
            "FR1420076020004321234567890"   # La Banque Postale
        ],
        "BE": [
            "BE68539007547034",  # KBC Bank
            "BE71096123456769"   # ING Belgium
        ],
        "AT": [
            "AT611904300234573201",  # Erste Bank
            "AT023200000012345864"   # Raiffeisen
        ]
    }
    
    # SEPA mandate types with business context
    MANDATE_TYPES = {
        "CORE": {
            "description": "SEPA Core Direct Debit",
            "usage": "Standard consumer payments",
            "pre_notification_days": 14
        },
        "RCUR": {
            "description": "Recurring payments", 
            "usage": "Subscription and membership fees",
            "pre_notification_days": 14
        },
        "FNAL": {
            "description": "Final payment",
            "usage": "Last payment in series",
            "pre_notification_days": 14
        },
        "OOFF": {
            "description": "One-off payment",
            "usage": "Single direct debit",
            "pre_notification_days": 14
        }
    }
    
    # Realistic frequency patterns for Dutch associations
    FREQUENCY_PATTERNS = {
        "Monthly": {
            "interval_days": 30,
            "common_usage": "Regular membership fees"
        },
        "Quarterly": {
            "interval_days": 90, 
            "common_usage": "Quarterly membership fees"
        },
        "Biannual": {
            "interval_days": 180,
            "common_usage": "Half-yearly contributions"
        },
        "Annual": {
            "interval_days": 365,
            "common_usage": "Annual membership fees"
        },
        "Variable": {
            "interval_days": None,
            "common_usage": "Irregular donations"
        }
    }
    
    def __init__(self, seed: Optional[int] = None, locale: str = "nl_NL"):
        """
        Initialize SEPA mandate test factory.
        
        Args:
            seed: Random seed for deterministic test data
            locale: Locale for data generation (default: Dutch)
        """
        if seed:
            random.seed(seed)
            
        self.locale = locale
        self._initialize_faker()
        
    def _initialize_faker(self):
        """Initialize Faker with Dutch locale if available."""
        try:
            from faker import Faker
            self.faker = Faker(self.locale)
        except ImportError:
            self.faker = None
            
    def get_random_dutch_iban(self, bank_code: Optional[str] = None) -> str:
        """
        Get a random valid Dutch test IBAN.
        
        Args:
            bank_code: Specific Dutch bank code (ABNA, INGB, RABO, etc.)
            
        Returns:
            Valid Dutch test IBAN
        """
        if bank_code and bank_code in self.DUTCH_BANKS:
            return random.choice(self.DUTCH_BANKS[bank_code]["test_ibans"])
            
        # Get random bank and random IBAN from that bank
        random_bank = random.choice(list(self.DUTCH_BANKS.keys()))
        return random.choice(self.DUTCH_BANKS[random_bank]["test_ibans"])
        
    def get_random_european_iban(self, country: Optional[str] = None) -> str:
        """
        Get a random European test IBAN for cross-border testing.
        
        Args:
            country: ISO country code (DE, FR, BE, AT)
            
        Returns:
            Valid European test IBAN
        """
        if country and country in self.EUROPEAN_TEST_IBANS:
            return random.choice(self.EUROPEAN_TEST_IBANS[country])
            
        # Get random country and random IBAN
        random_country = random.choice(list(self.EUROPEAN_TEST_IBANS.keys()))
        return random.choice(self.EUROPEAN_TEST_IBANS[random_country])
        
    def get_bank_info_for_iban(self, iban: str) -> Dict[str, str]:
        """
        Get bank information for a given IBAN.
        
        Args:
            iban: IBAN string (formatted or unformatted)
            
        Returns:
            Dictionary with bank information
        """
        # Clean IBAN
        clean_iban = iban.replace(" ", "").upper()
        
        # Check Dutch banks
        if clean_iban.startswith("NL") and len(clean_iban) >= 8:
            bank_code = clean_iban[4:8]
            if bank_code in self.DUTCH_BANKS:
                bank_info = self.DUTCH_BANKS[bank_code]
                return {
                    "bank_code": bank_code,
                    "bic": bank_info["bic"],
                    "bank_name": bank_info["name"],
                    "country": "NL"
                }
                
        # Default bank info for unknown IBANs
        return {
            "bank_code": "UNKN",
            "bic": "UNKNNL2A",
            "bank_name": "Unknown Bank",
            "country": clean_iban[:2] if len(clean_iban) >= 2 else "XX"
        }
        
    def generate_realistic_account_holder_name(self, member_name: str = None) -> str:
        """
        Generate realistic Dutch account holder name.
        
        Args:
            member_name: Base name from member record
            
        Returns:
            Realistic Dutch name with proper formatting
        """
        if member_name:
            return member_name
            
        if self.faker:
            # Generate Dutch name with tussenvoegsel (name particles)
            first_name = self.faker.first_name()
            
            # Add Dutch name particles occasionally
            particles = ["van", "de", "der", "van de", "van der", "te", "ten"]
            if random.random() < 0.3:  # 30% chance of particle
                particle = random.choice(particles)
                last_name = f"{particle} {self.faker.last_name()}"
            else:
                last_name = self.faker.last_name()
                
            return f"{first_name} {last_name}"
        else:
            # Fallback without Faker
            return f"Test User {random_string(6)}"
            
    def create_mandate_test_data(
        self,
        member_name: str,
        status: str = "Active",
        iban: str = None,
        mandate_type: str = "RCUR",
        frequency: str = "Monthly",
        maximum_amount: float = None,
        sign_date: Union[str, date] = None,
        expiry_date: Union[str, date] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create comprehensive SEPA mandate test data.
        
        Args:
            member_name: Member document name
            status: Mandate status (Draft, Active, Suspended, Cancelled, Expired)
            iban: Custom IBAN (generates Dutch IBAN if None)
            mandate_type: SEPA mandate type (CORE, RCUR, FNAL, OOFF)
            frequency: Collection frequency
            maximum_amount: Maximum collection amount
            sign_date: Mandate sign date
            expiry_date: Mandate expiry date
            **kwargs: Additional mandate fields
            
        Returns:
            Dictionary with complete mandate data
        """
        # Generate or validate IBAN
        if not iban:
            iban = self.get_random_dutch_iban()
            
        # Get bank information
        bank_info = self.get_bank_info_for_iban(iban)
        
        # Get member information for account holder name
        account_holder_name = kwargs.get("account_holder_name")
        if not account_holder_name:
            try:
                member_doc = frappe.get_doc("Member", member_name)
                account_holder_name = member_doc.full_name or self.generate_realistic_account_holder_name()
            except:
                account_holder_name = self.generate_realistic_account_holder_name()
                
        # Set dates
        sign_date = sign_date or today()
        if isinstance(sign_date, str):
            sign_date = getdate(sign_date)
            
        # Generate expiry date if not provided and status suggests it
        if not expiry_date and status not in ["Cancelled", "Expired"]:
            if random.random() < 0.3:  # 30% chance of having expiry date
                expiry_date = add_days(sign_date, random.randint(365, 1095))  # 1-3 years
                
        # Set maximum amount based on frequency if not provided
        if not maximum_amount:
            if frequency == "Monthly":
                maximum_amount = random.uniform(10.0, 100.0)
            elif frequency == "Quarterly":
                maximum_amount = random.uniform(25.0, 300.0)
            elif frequency == "Annual":
                maximum_amount = random.uniform(100.0, 500.0)
            else:
                maximum_amount = random.uniform(50.0, 200.0)
                
        # Build mandate data
        mandate_data = {
            "doctype": "SEPA Mandate",
            "member": member_name,
            "account_holder_name": account_holder_name,
            "iban": iban,
            "bic": bank_info["bic"],
            "bank_name": bank_info["bank_name"],
            "sign_date": sign_date,
            "expiry_date": expiry_date,
            "status": status,
            "mandate_type": mandate_type,
            "scheme": "SEPA",
            "is_active": 1 if status == "Active" else 0,
            "frequency": frequency,
            "maximum_amount": maximum_amount,
            "used_for_memberships": 1,
            "used_for_donations": kwargs.get("used_for_donations", 0),
            "used_for_other": kwargs.get("used_for_other", 0),
            **kwargs  # Allow override of any field
        }
        
        # Handle cancelled status specific fields
        if status == "Cancelled":
            mandate_data["cancelled_date"] = kwargs.get("cancelled_date", today())
            mandate_data["cancellation_reason"] = kwargs.get(
                "cancellation_reason", 
                "Test cancellation scenario"
            )
            
        return mandate_data
        
    def create_mandate_usage_scenario(self, mandate_name: str, scenario: str = "regular") -> List[Dict[str, Any]]:
        """
        Create realistic mandate usage history for testing.
        
        Args:
            mandate_name: SEPA Mandate document name
            scenario: Usage scenario (regular, irregular, failed, mixed)
            
        Returns:
            List of usage history records
        """
        usage_records = []
        
        if scenario == "regular":
            # Regular monthly payments for 6 months
            for i in range(6):
                usage_date = add_days(today(), -150 + (i * 30))
                usage_records.append({
                    "usage_date": usage_date,
                    "reference_doctype": "Sales Invoice",
                    "reference_name": f"INV-{usage_date.strftime('%Y%m')}-{i+1:03d}",
                    "amount": 25.00,
                    "sequence_type": "FRST" if i == 0 else "RCUR",
                    "status": "Collected",
                    "processing_date": add_days(usage_date, 2)
                })
                
        elif scenario == "irregular":
            # Irregular payments with varying amounts
            usage_dates = [add_days(today(), -120), add_days(today(), -80), add_days(today(), -30)]
            amounts = [15.00, 35.00, 25.00]
            
            for i, (usage_date, amount) in enumerate(zip(usage_dates, amounts)):
                usage_records.append({
                    "usage_date": usage_date,
                    "reference_doctype": "Sales Invoice",
                    "reference_name": f"INV-IRR-{i+1:03d}",
                    "amount": amount,
                    "sequence_type": "FRST" if i == 0 else "RCUR",
                    "status": "Collected",
                    "processing_date": add_days(usage_date, random.randint(1, 3))
                })
                
        elif scenario == "failed":
            # Some failed payments
            for i in range(4):
                usage_date = add_days(today(), -90 + (i * 20))
                status = "Failed" if i in [1, 2] else "Collected"
                
                usage_records.append({
                    "usage_date": usage_date,
                    "reference_doctype": "Sales Invoice",
                    "reference_name": f"INV-FAIL-{i+1:03d}",
                    "amount": 25.00,
                    "sequence_type": "FRST" if i == 0 else "RCUR",
                    "status": status,
                    "processing_date": add_days(usage_date, 2),
                    "failure_reason": "Insufficient funds" if status == "Failed" else None
                })
                
        return usage_records
        
    def create_compliance_test_scenarios(self) -> Dict[str, Dict[str, Any]]:
        """
        Create test scenarios for regulatory compliance testing.
        
        Returns:
            Dictionary of compliance test scenarios
        """
        scenarios = {
            "psd2_sca_compliance": {
                "description": "Strong Customer Authentication compliance",
                "mandate_data": {
                    "status": "Active",
                    "mandate_type": "RCUR",
                    "maximum_amount": 100.00,
                    "frequency": "Monthly"
                },
                "validation_rules": [
                    "mandate_requires_explicit_consent",
                    "maximum_amount_enforced",
                    "pre_notification_sent"
                ]
            },
            "gdpr_data_protection": {
                "description": "GDPR data protection compliance",
                "mandate_data": {
                    "status": "Active",
                    "data_processing_consent": True,
                    "retention_period_days": 1825  # 5 years
                },
                "validation_rules": [
                    "explicit_consent_recorded",
                    "data_minimization_applied",
                    "retention_period_enforced"
                ]
            },
            "dnb_dutch_banking": {
                "description": "Dutch central bank (DNB) compliance",
                "mandate_data": {
                    "status": "Active",
                    "iban": self.get_random_dutch_iban(),
                    "mandate_type": "RCUR",
                    "scheme": "SEPA"
                },
                "validation_rules": [
                    "dutch_iban_required",
                    "bic_validation_passed",
                    "sepa_scheme_compliance"
                ]
            },
            "sepa_mandate_lifecycle": {
                "description": "SEPA mandate lifecycle compliance",
                "mandate_data": {
                    "status": "Active",
                    "sign_date": today(),
                    "first_collection_date": add_days(today(), 14),
                    "pre_notification_days": 14
                },
                "validation_rules": [
                    "sign_date_validation",
                    "first_collection_date_compliance",
                    "pre_notification_period_enforced"
                ]
            }
        }
        
        return scenarios


class SEPAMandateTestMixin:
    """
    Mixin class for SEPA mandate testing capabilities.
    
    This mixin can be combined with EnhancedTestCase to provide
    comprehensive SEPA mandate testing functionality.
    
    Usage:
    ```python
    class TestSEPAFeature(EnhancedTestCase, SEPAMandateTestMixin):
        def test_mandate_creation(self):
            member = self.create_test_member(birth_date="1990-01-01")
            mandate = self.create_test_sepa_mandate(member=member)
            self.assertEqual(mandate.status, "Active")
    ```
    """
    
    def setUp(self):
        """Initialize SEPA test factory."""
        super().setUp()
        self.sepa_factory = SEPAMandateTestDataFactory(seed=12345)
        
    def create_test_sepa_mandate(
        self,
        member=None,
        status: str = "Active",
        **kwargs
    ):
        """
        Create a test SEPA mandate with business logic validation.
        
        Args:
            member: Member document (creates one if None)
            status: Mandate status
            **kwargs: Additional mandate fields
            
        Returns:
            SEPA Mandate document
            
        Raises:
            FieldValidationError: If field names don't exist in DocType
            ValidationError: If business rules are violated
        """
        # Create member if not provided
        if not member:
            if hasattr(self, 'create_test_member'):
                member = self.create_test_member(birth_date="1990-01-01")
            else:
                # Fallback member creation
                member = frappe.get_doc({
                    "doctype": "Member",
                    "first_name": "SEPA",
                    "last_name": "TestUser",
                    "email": f"sepa_test_{random_string(8)}@example.com",
                    "birth_date": "1990-01-01"
                })
                member.insert()
                
        # Generate mandate data
        mandate_data = self.sepa_factory.create_mandate_test_data(
            member_name=member.name,
            status=status,
            **kwargs
        )
        
        # Validate fields if Enhanced Test Factory available
        if HAS_ENHANCED_FACTORY and hasattr(self, '_validate_fields'):
            self._validate_fields("SEPA Mandate", list(mandate_data.keys()))
            
        # Create and return mandate
        mandate = frappe.get_doc(mandate_data)
        mandate.insert()
        return mandate
        
    def create_test_sepa_mandate_with_usage(
        self,
        member = None,
        usage_scenario: str = "regular",
        **kwargs
    ):
        """
        Create a test SEPA mandate with realistic usage history.
        
        Args:
            member: Member document
            usage_scenario: Usage scenario (regular, irregular, failed, mixed)
            **kwargs: Additional mandate fields
            
        Returns:
            SEPA Mandate document with usage history
        """
        mandate = self.create_test_sepa_mandate(member=member, **kwargs)
        
        # Add usage history
        usage_records = self.sepa_factory.create_mandate_usage_scenario(
            mandate.name, 
            usage_scenario
        )
        
        for usage_record in usage_records:
            mandate.append("usage_history", usage_record)
            
        mandate.save()
        return mandate
        
    def create_compliance_test_mandate(
        self, 
        scenario: str,
        member = None
    ):
        """
        Create a SEPA mandate for specific compliance testing scenarios.
        
        Args:
            scenario: Compliance scenario name
            member: Member document
            
        Returns:
            SEPA Mandate configured for compliance testing
        """
        scenarios = self.sepa_factory.create_compliance_test_scenarios()
        
        if scenario not in scenarios:
            raise ValueError(f"Unknown compliance scenario: {scenario}")
            
        scenario_data = scenarios[scenario]
        mandate_data = scenario_data["mandate_data"]
        
        return self.create_test_sepa_mandate(member=member, **mandate_data)
        
    def assert_sepa_mandate_valid(self, mandate):
        """
        Assert that a SEPA mandate meets all validation requirements.
        
        Args:
            mandate: SEPA Mandate document to validate
            
        Raises:
            AssertionError: If mandate fails validation
        """
        # Basic field validation
        self.assertIsNotNone(mandate.mandate_id, "Mandate ID should be generated")
        self.assertIsNotNone(mandate.iban, "IBAN is required")
        self.assertIsNotNone(mandate.account_holder_name, "Account holder name is required")
        self.assertIsNotNone(mandate.sign_date, "Sign date is required")
        
        # IBAN format validation
        if HAS_IBAN_VALIDATOR:
            iban_result = validate_iban(mandate.iban)
            self.assertTrue(iban_result["valid"], f"IBAN validation failed: {iban_result['message']}")
            
        # Date validation
        if mandate.expiry_date:
            self.assertGreaterEqual(
                getdate(mandate.expiry_date),
                getdate(mandate.sign_date),
                "Expiry date must be after sign date"
            )
            
        # Status consistency validation
        if mandate.status == "Active":
            self.assertEqual(mandate.is_active, 1, "Active mandates should have is_active=1")
        elif mandate.status in ["Cancelled", "Expired", "Suspended"]:
            self.assertEqual(mandate.is_active, 0, "Inactive mandates should have is_active=0")
            
    def assert_mandate_compliance(self, mandate, scenario: str):
        """
        Assert that a mandate meets specific compliance requirements.
        
        Args:
            mandate: SEPA Mandate document
            scenario: Compliance scenario to validate against
        """
        scenarios = self.sepa_factory.create_compliance_test_scenarios()
        
        if scenario not in scenarios:
            raise ValueError(f"Unknown compliance scenario: {scenario}")
            
        scenario_data = scenarios[scenario]
        validation_rules = scenario_data["validation_rules"]
        
        # Apply validation rules
        for rule in validation_rules:
            if rule == "dutch_iban_required" and mandate.iban:
                self.assertTrue(
                    mandate.iban.startswith("NL"),
                    "Dutch compliance requires NL IBAN"
                )
            elif rule == "bic_validation_passed":
                self.assertIsNotNone(mandate.bic, "BIC is required for compliance")
            elif rule == "sepa_scheme_compliance":
                self.assertEqual(mandate.scheme, "SEPA", "SEPA scheme required")
            # Add more validation rules as needed