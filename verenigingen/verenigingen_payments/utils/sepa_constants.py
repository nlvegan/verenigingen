"""
SEPA Constants Module

Single source of truth for SEPA-related constants used across the payment module.
This prevents drift between validation and generation components.

Usage:
    from verenigingen.verenigingen_payments.utils.sepa_constants import (
        SEPA_CHAR_PATTERN,
        MAX_DEBTOR_NAME_LENGTH,
        ...
    )
"""

import re
from decimal import Decimal

# =============================================================================
# SEPA Character Set
# =============================================================================

# SEPA allowed characters (EPC Best Practices - basic Latin subset)
# Reference: EPC217-08 "SEPA Requirements for an Extended Character Set (SRECS)"
# This pattern is used for validating names, remittance info, and other text fields
SEPA_CHAR_PATTERN = re.compile(r"^[a-zA-Z0-9\+\?\-\:\(\)\.\,\'\s/]*$")

# Human-readable description for error messages
SEPA_ALLOWED_CHARS_DESCRIPTION = (
    "letters (a-z, A-Z), digits (0-9), and special characters: + ? - : ( ) . , ' / space"
)


# =============================================================================
# SEPA Field Length Limits
# =============================================================================

# Message and document identification
MAX_MESSAGE_ID_LENGTH = 35
MAX_END_TO_END_ID_LENGTH = 35
MAX_PAYMENT_INFO_ID_LENGTH = 35

# Party names
MAX_CREDITOR_NAME_LENGTH = 70
MAX_DEBTOR_NAME_LENGTH = 70
MAX_INITIATING_PARTY_NAME_LENGTH = 70

# Mandate and remittance
MAX_MANDATE_ID_LENGTH = 35
MAX_REMITTANCE_INFO_LENGTH = 140

# Address fields
MAX_STREET_NAME_LENGTH = 70
MAX_POST_CODE_LENGTH = 16
MAX_TOWN_NAME_LENGTH = 35
MAX_COUNTRY_CODE_LENGTH = 2


# =============================================================================
# SEPA Amount Limits
# =============================================================================

# Per-transaction limits (SEPA scheme limits)
MIN_TRANSACTION_AMOUNT = Decimal("0.01")
MAX_TRANSACTION_AMOUNT = Decimal("999999999.99")

# Operational batch limit (configurable safety limit for this application)
# This is an application-level limit, not a SEPA scheme limit
DEFAULT_MAX_BATCH_TOTAL = Decimal("10000000.00")  # 10 million EUR


# =============================================================================
# SEPA Batch Limits
# =============================================================================

MAX_BATCH_SIZE = 10000  # Maximum number of transactions per file


# =============================================================================
# SEPA Date Constraints
# =============================================================================

# Collection date offsets (days from today)
MIN_COLLECTION_DATE_OFFSET = 1
MAX_COLLECTION_DATE_OFFSET = 30

# First collection vs recurring offsets (bank-dependent, these are common defaults)
FIRST_COLLECTION_MIN_OFFSET = 5  # D+5 for FRST
RECURRING_COLLECTION_MIN_OFFSET = 2  # D+2 for RCUR


# =============================================================================
# SEPA Scheme Types
# =============================================================================

VALID_BATCH_TYPES = ["CORE", "B2B", "COR1"]
VALID_SEQUENCE_TYPES = ["FRST", "RCUR", "OOFF", "FNAL"]


# =============================================================================
# Currency
# =============================================================================

SEPA_CURRENCY = "EUR"
