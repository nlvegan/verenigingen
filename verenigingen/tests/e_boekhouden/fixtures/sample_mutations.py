"""
Sample eBoekhouden Mutations for Testing

This module provides sample mutation data representing various transaction types,
edge cases, and error scenarios from the eBoekhouden API.

Mutation Types (REST API numeric codes):
- 0: Opening Balance (BeginBalans)
- 1: Purchase Invoice (Factuur ontvangen)
- 2: Sales Invoice (Factuur verstuurd)
- 3: Customer Payment (Factuurbetaling ontvangen)
- 4: Supplier Payment (Factuurbetaling verstuurd)
- 5: Money Received (Geld ontvangen)
- 6: Money Sent (Geld verstuurd)
- 7: Memorial Booking (Memoriaal)
"""

from decimal import Decimal
from typing import Any, Dict, List

# =============================================================================
# TRANSACTION TYPE SAMPLES (Numeric - REST API)
# =============================================================================

MUTATION_TYPE_0_OPENING_BALANCE: Dict[str, Any] = {
    "id": 1001,
    "type": 0,
    "date": "2025-01-01",
    "description": "Opening balance 2025",
    "amount": 10000.00,
    "ledgerId": 1100,
    "rows": [
        {"ledgerId": 1100, "amount": 10000.00, "description": "Bank opening balance"}
    ],
}

MUTATION_TYPE_1_PURCHASE_INVOICE: Dict[str, Any] = {
    "id": 1002,
    "type": 1,
    "date": "2025-01-15",
    "description": "Office supplies from Staples",
    "invoiceNumber": "INV-2025-001",
    "amount": 121.00,
    "relationId": 5001,
    "ledgerId": 1400,
    "rows": [
        {
            "ledgerId": 4600,
            "amount": 100.00,
            "description": "Office supplies",
            "btwCode": "HOOG_INK_21",
        }
    ],
}

MUTATION_TYPE_2_SALES_INVOICE: Dict[str, Any] = {
    "id": 1003,
    "type": 2,
    "date": "2025-01-20",
    "description": "Membership fee Q1 2025",
    "invoiceNumber": "2025-0001",
    "amount": 60.50,
    "relationId": 3001,
    "ledgerId": 1300,
    "rows": [
        {
            "ledgerId": 8000,
            "amount": 50.00,
            "description": "Membership contribution",
            "btwCode": "HOOG_VERK_21",
        }
    ],
}

MUTATION_TYPE_3_CUSTOMER_PAYMENT: Dict[str, Any] = {
    "id": 1004,
    "type": 3,
    "date": "2025-01-25",
    "description": "Payment received for invoice 2025-0001",
    "invoiceNumber": "2025-0001",
    "amount": 60.50,
    "relationId": 3001,
    "ledgerId": 1100,
    "rows": [{"ledgerId": 1300, "amount": 60.50, "description": "Invoice payment"}],
}

MUTATION_TYPE_4_SUPPLIER_PAYMENT: Dict[str, Any] = {
    "id": 1005,
    "type": 4,
    "date": "2025-01-28",
    "description": "Payment to Staples for INV-2025-001",
    "invoiceNumber": "INV-2025-001",
    "amount": 121.00,
    "relationId": 5001,
    "ledgerId": 1100,
    "rows": [{"ledgerId": 1400, "amount": 121.00, "description": "Supplier payment"}],
}

MUTATION_TYPE_5_MONEY_RECEIVED: Dict[str, Any] = {
    "id": 1006,
    "type": 5,
    "date": "2025-01-30",
    "description": "Donation received from J. de Vries",
    "amount": 50.00,
    "ledgerId": 1100,
    "rows": [{"ledgerId": 8500, "amount": 50.00, "description": "Donation income"}],
}

MUTATION_TYPE_6_MONEY_SENT: Dict[str, Any] = {
    "id": 1007,
    "type": 6,
    "date": "2025-01-31",
    "description": "Bank charges January 2025",
    "amount": 12.50,
    "ledgerId": 1100,
    "rows": [{"ledgerId": 4800, "amount": 12.50, "description": "Bank fees"}],
}

MUTATION_TYPE_7_MEMORIAL: Dict[str, Any] = {
    "id": 1008,
    "type": 7,
    "date": "2025-01-31",
    "description": "Year-end adjustment entry",
    "amount": 0.00,
    "ledgerId": None,
    "rows": [
        {"ledgerId": 4000, "amount": 100.00, "description": "Expense adjustment"},
        {"ledgerId": 8000, "amount": -100.00, "description": "Income adjustment"},
    ],
}

# =============================================================================
# TRANSACTION TYPE SAMPLES (Text - SOAP API)
# =============================================================================

MUTATION_SOAP_FACTUUR_ONTVANGEN: Dict[str, Any] = {
    "MutatieNr": "2001",
    "Soort": "Factuur ontvangen",
    "Datum": "20250115",
    "Omschrijving": "Purchase invoice from supplier",
    "Bedrag": 242.00,
}

MUTATION_SOAP_FACTUUR_VERSTUURD: Dict[str, Any] = {
    "MutatieNr": "2002",
    "Soort": "Factuur verstuurd",
    "Datum": "20250120",
    "Omschrijving": "Sales invoice to customer",
    "Bedrag": 121.00,
}

MUTATION_SOAP_FACTUURBETALING_ONTVANGEN: Dict[str, Any] = {
    "MutatieNr": "2003",
    "Soort": "Factuurbetaling ontvangen",
    "Datum": "20250125",
    "Omschrijving": "Payment received for invoice",
    "Bedrag": 121.00,
}

MUTATION_SOAP_FACTUURBETALING_VERSTUURD: Dict[str, Any] = {
    "MutatieNr": "2004",
    "Soort": "Factuurbetaling verstuurd",
    "Datum": "20250128",
    "Omschrijving": "Payment sent to supplier",
    "Bedrag": 242.00,
}

MUTATION_SOAP_GELD_ONTVANGEN: Dict[str, Any] = {
    "MutatieNr": "2005",
    "Soort": "Geld ontvangen",
    "Datum": "20250130",
    "Omschrijving": "Cash received",
    "Bedrag": 50.00,
}

MUTATION_SOAP_MEMORIAAL: Dict[str, Any] = {
    "MutatieNr": "2006",
    "Soort": "Memoriaal",
    "Datum": "20250131",
    "Omschrijving": "Adjustment entry",
    "Bedrag": 0.00,
}

# CamelCase variants (normalized SOAP types)
MUTATION_SOAP_CAMELCASE_FACTUUR_ONTVANGEN: Dict[str, Any] = {
    "MutatieNr": "2007",
    "MutatieType": "FactuurOntvangen",
    "Datum": "20250115",
    "Omschrijving": "CamelCase purchase invoice",
    "Bedrag": 100.00,
}

MUTATION_SOAP_CAMELCASE_FACTUUR_VERSTUURD: Dict[str, Any] = {
    "MutatieNr": "2008",
    "MutatieType": "FactuurVerstuurd",
    "Datum": "20250120",
    "Omschrijving": "CamelCase sales invoice",
    "Bedrag": 100.00,
}

# =============================================================================
# EDGE CASES - PAYMENT REFUNDS
# =============================================================================

MUTATION_TYPE_3_NEGATIVE_NO_INVOICE: Dict[str, Any] = {
    "id": 3001,
    "type": 3,
    "date": "2025-02-01",
    "description": "Generic customer refund",
    "invoiceNumber": "",  # No invoice reference
    "amount": -50.00,  # Negative = refund
    "relationId": 3001,
    "ledgerId": 1100,
    "rows": [{"ledgerId": 1300, "amount": -50.00, "description": "Customer refund"}],
}

MUTATION_TYPE_3_NEGATIVE_WITH_INVOICE: Dict[str, Any] = {
    "id": 3002,
    "type": 3,
    "date": "2025-02-02",
    "description": "Credit note payment for invoice 2025-0002",
    "invoiceNumber": "2025-0002",  # Has invoice reference
    "amount": -25.00,  # Negative = credit note payment
    "relationId": 3001,
    "ledgerId": 1100,
    "rows": [{"ledgerId": 1300, "amount": -25.00, "description": "Credit note payment"}],
}

MUTATION_TYPE_4_POSITIVE_NORMAL: Dict[str, Any] = {
    "id": 3003,
    "type": 4,
    "date": "2025-02-03",
    "description": "Normal supplier payment",
    "invoiceNumber": "SUP-2025-001",
    "amount": 500.00,  # Positive = normal outgoing payment
    "relationId": 5001,
    "ledgerId": 1100,
    "rows": [{"ledgerId": 1400, "amount": 500.00, "description": "Supplier payment"}],
}

MUTATION_TYPE_4_NEGATIVE_REFUND: Dict[str, Any] = {
    "id": 3004,
    "type": 4,
    "date": "2025-02-04",
    "description": "Supplier refund received",
    "invoiceNumber": "SUP-2025-002",
    "amount": -75.00,  # Negative = refund from supplier (money IN)
    "relationId": 5002,
    "ledgerId": 1100,
    "rows": [{"ledgerId": 1400, "amount": -75.00, "description": "Supplier refund"}],
}

# Edge case: Negative row amount (violates unsigned assumption)
MUTATION_TYPE_3_NEGATIVE_ROW_AMOUNT: Dict[str, Any] = {
    "id": 3005,
    "type": 3,
    "date": "2025-02-05",
    "description": "Payment with negative row (unexpected)",
    "invoiceNumber": "2025-0003",
    "amount": 100.00,  # Main amount positive
    "relationId": 3001,
    "ledgerId": 1100,
    "rows": [
        {"ledgerId": 1300, "amount": -100.00, "description": "Negative row amount"}
    ],  # Row is negative (unusual)
}

# =============================================================================
# EDGE CASES - PAYMENT GATEWAY (MOLLIE)
# =============================================================================

MUTATION_MOLLIE_FIRST_PAYMENT: Dict[str, Any] = {
    "id": 4001,
    "type": 4,
    "date": "2025-02-10",
    "description": "Mollie settlement payment",
    "invoiceNumber": "MOLLIE-2025-001",  # Gateway prefix
    "amount": 95.50,  # After fees
    "relationId": 9001,  # Mollie relation
    "ledgerId": 1150,  # Gateway virtual account ledger
    "rows": [{"ledgerId": 1400, "amount": 95.50, "description": "Mollie payment"}],
}

MUTATION_MOLLIE_ADJUSTMENT: Dict[str, Any] = {
    "id": 4002,
    "type": 4,
    "date": "2025-02-10",
    "description": "Mollie fee adjustment",
    "invoiceNumber": "MOLLIE-2025-001",  # Same invoice (already paid)
    "amount": 4.50,  # Fee portion
    "relationId": 9001,
    "ledgerId": 1150,
    "rows": [{"ledgerId": 4850, "amount": 4.50, "description": "Transaction fee"}],
}

# =============================================================================
# EDGE CASES - DATE FORMATS
# =============================================================================

DATE_FORMAT_SAMPLES: List[Dict[str, Any]] = [
    {"input": "20250110", "expected": "2025-01-10", "description": "YYYYMMDD"},
    {"input": "2025-01-10", "expected": "2025-01-10", "description": "Already correct"},
    {
        "input": "2025-01-10T00:00:00",
        "expected": "2025-01-10",
        "description": "ISO datetime",
    },
    {
        "input": "2025-01-10T12:30:45",
        "expected": "2025-01-10",
        "description": "ISO with time",
    },
    {
        "input": "2025-01-10T00:00:00+01:00",
        "expected": "2025-01-10",
        "description": "ISO with timezone",
    },
    {"input": "2025-01-10T00:00:00Z", "expected": "2025-01-10", "description": "ISO Zulu"},
    {"input": "10-01-2025", "expected": "2025-01-10", "description": "European dash"},
    {"input": "10/01/2025", "expected": "2025-01-10", "description": "European slash"},
    {"input": "1-1-2024", "expected": "2024-01-01", "description": "Single digit day/month"},
    {"input": 20250110, "expected": "2025-01-10", "description": "Integer date"},
    {"input": None, "expected": None, "description": "None value"},
    {"input": "", "expected": None, "description": "Empty string"},
    {"input": "   ", "expected": None, "description": "Whitespace only"},
]

# =============================================================================
# EDGE CASES - AMOUNT HANDLING
# =============================================================================

MUTATION_ZERO_MAIN_WITH_ROWS: Dict[str, Any] = {
    "id": 5001,
    "type": 5,
    "date": "2025-03-01",
    "description": "Zero main amount, calculate from rows",
    "amount": 0,  # Main amount is zero
    "ledgerId": 1100,
    "rows": [
        {"ledgerId": 8000, "amount": 75.00, "description": "Row 1"},
        {"ledgerId": 8100, "amount": 25.00, "description": "Row 2"},
    ],  # Total: 100.00
}

MUTATION_ROW_SUM_MISMATCH: Dict[str, Any] = {
    "id": 5002,
    "type": 5,
    "date": "2025-03-02",
    "description": "Row sum does not match main amount",
    "amount": 100.00,  # Main says 100
    "ledgerId": 1100,
    "rows": [
        {"ledgerId": 8000, "amount": 60.00, "description": "Row 1"},
        {"ledgerId": 8100, "amount": 35.00, "description": "Row 2"},
    ],  # Total: 95.00 (5.00 difference)
}

MUTATION_ROW_SUM_WITHIN_TOLERANCE: Dict[str, Any] = {
    "id": 5003,
    "type": 5,
    "date": "2025-03-03",
    "description": "Row sum within rounding tolerance",
    "amount": 100.005,  # Slightly off from row sum to test tolerance
    "ledgerId": 1100,
    "rows": [
        {"ledgerId": 8000, "amount": 50.00, "description": "Row 1"},
        {"ledgerId": 8100, "amount": 50.00, "description": "Row 2"},
    ],  # Total: 100.00 (within 0.005 of 100.005, clearly under 0.01 tolerance)
}

MUTATION_NEAR_ZERO_ROWS: Dict[str, Any] = {
    "id": 5004,
    "type": 5,
    "date": "2025-03-04",
    "description": "Has near-zero rows that should be skipped",
    "amount": 100.00,
    "ledgerId": 1100,
    "rows": [
        {"ledgerId": 8000, "amount": 100.00, "description": "Main row"},
        {"ledgerId": 8100, "amount": 0.001, "description": "Near-zero row"},  # Rounds to 0.00
        {"ledgerId": 8200, "amount": 0.00, "description": "Zero row"},
    ],
}

# =============================================================================
# EDGE CASES - MALFORMED DATA
# =============================================================================

MUTATION_MISSING_ID: Dict[str, Any] = {
    "type": 2,
    "date": "2025-04-01",
    "description": "Missing ID field",
    "amount": 100.00,
}

MUTATION_MISSING_DATE: Dict[str, Any] = {
    "id": 6002,
    "type": 2,
    "description": "Missing date field",
    "amount": 100.00,
}

MUTATION_MISSING_TYPE: Dict[str, Any] = {
    "id": 6003,
    "date": "2025-04-03",
    "description": "Missing type field",
    "amount": 100.00,
}

MUTATION_EMPTY_ROWS: Dict[str, Any] = {
    "id": 6004,
    "type": 5,
    "date": "2025-04-04",
    "description": "Empty rows array",
    "amount": 100.00,
    "rows": [],
}

MUTATION_ROW_MISSING_LEDGER: Dict[str, Any] = {
    "id": 6005,
    "type": 5,
    "date": "2025-04-05",
    "description": "Row missing ledgerId",
    "amount": 100.00,
    "ledgerId": 1100,
    "rows": [
        {"amount": 100.00, "description": "Row without ledgerId"}  # Missing ledgerId
    ],
}

MUTATION_INVALID_AMOUNT: Dict[str, Any] = {
    "id": 6006,
    "type": 2,
    "date": "2025-04-06",
    "description": "Non-numeric amount",
    "amount": "not-a-number",
}

MUTATION_NULL_ROWS: Dict[str, Any] = {
    "id": 6007,
    "type": 5,
    "date": "2025-04-07",
    "description": "Null rows field",
    "amount": 100.00,
    "rows": None,
}

# =============================================================================
# PII MASKING TEST DATA
# =============================================================================

MUTATION_WITH_PII: Dict[str, Any] = {
    "id": 7001,
    "type": 2,
    "date": "2025-05-01",
    "description": "Transaction with PII",
    "amount": 100.00,
    "email": "john.doe@example.com",
    "phone": "0612345678",
    "mobile": "0687654321",
    "iban": "NL91ABNA0417164300",
    "address": "Hoofdstraat 123, Amsterdam",
    "city": "Amsterdam",
    "postcode": "1012AB",
    "relation": {
        "name": "Jan de Vries",
        "email": "jan@company.nl",
        "phone": "0201234567",
        "address": "Kerkstraat 45",
    },
}

MUTATION_WITH_DUTCH_PII_FIELDS: Dict[str, Any] = {
    "id": 7002,
    "type": 2,
    "date": "2025-05-02",
    "description": "Dutch field names with PII",
    "amount": 100.00,
    "emailadres": "test@test.nl",
    "telefoon": "0301234567",
    "telefoonnummer": "0401234567",
    "adres": "Dorpsstraat 78",
    "straat": "Nieuwstraat",
    "woonplaats": "Rotterdam",
    "voornaam": "Pieter",
    "achternaam": "Jansen",
    "bankrekeningnummer": "NL02RABO0123456789",
    "btwnummer": "NL123456789B01",
    "kvknummer": "12345678",
    "bsn": "123456789",
}

# =============================================================================
# VAT/BTW CODE TEST DATA
# =============================================================================

BTW_CODE_TEST_CASES: List[Dict[str, Any]] = [
    {
        "code": "HOOG_VERK_21",
        "expected_rate": 21,
        "expected_type": "Output VAT",
        "description": "High VAT sales 21%",
    },
    {
        "code": "LAAG_VERK_9",
        "expected_rate": 9,
        "expected_type": "Output VAT",
        "description": "Low VAT sales 9%",
    },
    {
        "code": "HOOG_INK_21",
        "expected_rate": 21,
        "expected_type": "Input VAT",
        "description": "High VAT purchase 21%",
    },
    {
        "code": "LAAG_INK_9",
        "expected_rate": 9,
        "expected_type": "Input VAT",
        "description": "Low VAT purchase 9%",
    },
    {
        "code": "HOOG_VERK_6",
        "expected_rate": 6,
        "expected_type": "Output VAT",
        "description": "VAT sales 6%",
    },
    {
        "code": "LAAG_INK_6",
        "expected_rate": 6,
        "expected_type": "Input VAT",
        "description": "VAT purchase 6%",
    },
    {
        "code": "VERLEGDE_BTW",
        "expected_rate": 21,
        "expected_type": "Reverse Charge",
        "description": "Reverse charge VAT",
    },
    {
        "code": "GEEN",
        "expected_rate": 0,
        "expected_type": None,
        "description": "No VAT",
    },
    {
        "code": "VRIJ",
        "expected_rate": 0,
        "expected_type": None,
        "description": "VAT exempt",
    },
]

# =============================================================================
# UOM MAPPING TEST DATA
# =============================================================================

UOM_TEST_CASES: List[Dict[str, Any]] = [
    {"dutch": "Stk", "expected": "Nos"},
    {"dutch": "Stuks", "expected": "Nos"},
    {"dutch": "St", "expected": "Nos"},
    {"dutch": "Uur", "expected": "Hour"},
    {"dutch": "Uren", "expected": "Hour"},
    {"dutch": "Dag", "expected": "Day"},
    {"dutch": "Dagen", "expected": "Day"},
    {"dutch": "Maand", "expected": "Month"},
    {"dutch": "Maanden", "expected": "Month"},
    {"dutch": "Jaar", "expected": "Year"},
    {"dutch": "kg", "expected": "Kg"},
    {"dutch": "gram", "expected": "Gram"},
    {"dutch": "liter", "expected": "Litre"},
    {"dutch": "m", "expected": "Meter"},
    {"dutch": "m2", "expected": "Sq Meter"},
    {"dutch": "m3", "expected": "Cubic Meter"},
    {"dutch": "%", "expected": "Percent"},
]

# =============================================================================
# ITEM GROUP CLASSIFICATION TEST DATA
# =============================================================================

ITEM_GROUP_TEST_CASES: List[Dict[str, Any]] = [
    # Service keywords
    {"description": "Advies en consultancy diensten", "expected_group": "Services"},
    {"description": "IT ondersteuning maandelijks", "expected_group": "Services"},
    {"description": "Training workshop medewerkers", "expected_group": "Services"},
    # Product keywords
    {"description": "Laptop Dell XPS 15", "expected_group": "Products"},
    {"description": "Kantoor meubilair bureau", "expected_group": "Products"},
    {"description": "Software licentie Microsoft 365", "expected_group": "Products"},
    # Travel keywords
    {"description": "Reiskosten trein Amsterdam-Utrecht", "expected_group": "Expense Items"},
    {"description": "Hotel verblijf conferentie", "expected_group": "Expense Items"},
    {"description": "Parkeerkosten vergadering", "expected_group": "Expense Items"},
    # Office supplies
    {"description": "Kantoorartikelen papier en pennen", "expected_group": "Office Supplies"},
    {"description": "Printer cartridge toner", "expected_group": "Office Supplies"},
    # Finance
    {"description": "Bankkosten transactiekosten", "expected_group": "Services"},
    {"description": "Mollie betalingskosten", "expected_group": "Services"},
]

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_all_numeric_type_mutations() -> List[Dict[str, Any]]:
    """Return all numeric type mutation samples."""
    return [
        MUTATION_TYPE_0_OPENING_BALANCE,
        MUTATION_TYPE_1_PURCHASE_INVOICE,
        MUTATION_TYPE_2_SALES_INVOICE,
        MUTATION_TYPE_3_CUSTOMER_PAYMENT,
        MUTATION_TYPE_4_SUPPLIER_PAYMENT,
        MUTATION_TYPE_5_MONEY_RECEIVED,
        MUTATION_TYPE_6_MONEY_SENT,
        MUTATION_TYPE_7_MEMORIAL,
    ]


def get_all_soap_type_mutations() -> List[Dict[str, Any]]:
    """Return all SOAP text type mutation samples."""
    return [
        MUTATION_SOAP_FACTUUR_ONTVANGEN,
        MUTATION_SOAP_FACTUUR_VERSTUURD,
        MUTATION_SOAP_FACTUURBETALING_ONTVANGEN,
        MUTATION_SOAP_FACTUURBETALING_VERSTUURD,
        MUTATION_SOAP_GELD_ONTVANGEN,
        MUTATION_SOAP_MEMORIAAL,
        MUTATION_SOAP_CAMELCASE_FACTUUR_ONTVANGEN,
        MUTATION_SOAP_CAMELCASE_FACTUUR_VERSTUURD,
    ]


def get_all_refund_edge_cases() -> List[Dict[str, Any]]:
    """Return all refund-related edge case mutations."""
    return [
        MUTATION_TYPE_3_NEGATIVE_NO_INVOICE,
        MUTATION_TYPE_3_NEGATIVE_WITH_INVOICE,
        MUTATION_TYPE_4_POSITIVE_NORMAL,
        MUTATION_TYPE_4_NEGATIVE_REFUND,
        MUTATION_TYPE_3_NEGATIVE_ROW_AMOUNT,
    ]


def get_all_malformed_mutations() -> List[Dict[str, Any]]:
    """Return all malformed mutation samples."""
    return [
        MUTATION_MISSING_ID,
        MUTATION_MISSING_DATE,
        MUTATION_MISSING_TYPE,
        MUTATION_EMPTY_ROWS,
        MUTATION_ROW_MISSING_LEDGER,
        MUTATION_INVALID_AMOUNT,
        MUTATION_NULL_ROWS,
    ]
