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

# A Direct Debit Batch Invoice row the XML generator left out of the pain.008 file
# (#2839: undeterminable SeqTp; also an invalid debtor IBAN). It is written as
# status "Failed" with this result_code, so it is told apart from a row that
# failed while being booked (also "Failed", but retryable) and from one a bank
# returned. Nothing was sent to the bank for such a row: it must never be booked
# as paid, and its invoice is collectable again.
ROW_NOT_IN_FILE_CODE = "NOT_IN_FILE"


def row_left_out_of_file(status, result_code) -> bool:
    """True for a batch row the generated SEPA file does not contain."""
    return status == "Failed" and result_code == ROW_NOT_IN_FILE_CODE


# =============================================================================
# Currency
# =============================================================================

SEPA_CURRENCY = "EUR"


# A Direct Debit Batch that can no longer collect: a DRAFT, carrying no generated
# SEPA file, whose collection date has passed. `DirectDebitBatch.before_submit`
# refuses a batch dated before today, so such a row can never be submitted through
# the real path and can never charge anyone -- yet a plain `docstatus != 2` test
# treats it as live and withholds its invoices from every future collection,
# permanently. Measured on veg11: 8 of them, over two months old.
#
# Kept deliberately narrow. Anything submitted is collecting; a draft dated today or
# later is what the monthly flow leaves behind while `auto_submit_sepa_batches` is 0
# (the default) for a human to submit; and a draft that already generated a file may
# have had that file taken to the bank by hand, which nothing here would know.
#
# Callers must bind `today` to the SITE's calendar day -- never the database's
# CURDATE(), which names a different day for hours of every day while before_submit
# judges on the site's (#628).
#
# A ROLLED BACK batch can no longer collect either (#3055). Its Payment Entries are
# cancelled and its rows reset to Pending (#3021), so it holds nothing -- yet it is
# submitted (docstatus 1), so without this clause every caller of this predicate keeps
# treating its invoices as "in a live batch" and never offers them for a new one.
# `Direct Debit Batch.status` is never "Rolled Back" for a batch still collecting.
#
# One definition, three call sites (payment_retry, sepa_mandate_service,
# dd_batch_optimizer): this predicate is the kind of thing that otherwise gets fixed
# in one place and missed in the others.
STRANDED_BATCH_EXCLUSION = """
    NOT (
        {alias}.docstatus = 0
        AND IFNULL({alias}.sepa_file_generated, 0) = 0
        AND {alias}.batch_date IS NOT NULL
        AND {alias}.batch_date < %(today)s
    )
    AND IFNULL({alias}.status, '') != 'Rolled Back'
"""


def stranded_batch_exclusion(alias="ddb"):
    """SQL fragment excluding batches that can no longer collect. See above."""
    return STRANDED_BATCH_EXCLUSION.format(alias=alias)


# Batch statuses under which a batch no longer "speaks for" its invoices: it collected
# nothing, so each invoice must stay collectable in a new batch (#1217, #3055). A
# Rolled Back batch belongs here: its Payment Entries are cancelled and its rows are
# back to Pending, and re-collection is only via a NEW batch.
NON_LOCKING_BATCH_STATUSES = ("Cancelled", "Failed", "Rolled Back")


def batch_status_locks_invoices(status) -> bool:
    """True when a batch in this status still holds its invoices out of new batches."""
    return status not in NON_LOCKING_BATCH_STATUSES


def non_locking_batch_status_sql_list() -> str:
    """The statuses above as a SQL list body, for `status NOT IN (...)`. Constants only."""
    return ", ".join(f"'{status}'" for status in NON_LOCKING_BATCH_STATUSES)
