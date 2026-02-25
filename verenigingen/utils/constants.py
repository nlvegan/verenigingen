"""
Constants and configuration values for Verenigingen app

This module centralizes commonly used constants to eliminate magic strings
and provide a single source of truth for configuration values.
"""

from typing import FrozenSet, List, Set


# System roles and permissions
class Roles:
    """Standard role definitions used throughout the application"""

    SYSTEM_MANAGER = "System Manager"
    VERENIGINGEN_ADMIN = "Verenigingen Administrator"
    VERENIGINGEN_STAFF = "Verenigingen Staff"
    MEMBER = "Member"
    VOLUNTEER = "Verenigingen Volunteer"
    VOLUNTEER_MANAGER = "Volunteer Manager"
    AUDITOR = "Verenigingen Auditor"
    CHAPTER_ADMIN = "Chapter Administrator"
    HR_MANAGER = "HR Manager"

    # Role groups for common permission checks (frozenset prevents accidental mutation)
    ADMIN_ROLES: FrozenSet[str] = frozenset({SYSTEM_MANAGER, VERENIGINGEN_ADMIN, VERENIGINGEN_STAFF})
    ADMIN_PAIR: FrozenSet[str] = frozenset({SYSTEM_MANAGER, VERENIGINGEN_ADMIN})

    VOLUNTEER_ADMIN_ROLES: FrozenSet[str] = frozenset(
        {
            SYSTEM_MANAGER,
            VERENIGINGEN_ADMIN,
            VERENIGINGEN_STAFF,
            VOLUNTEER_MANAGER,
        }
    )

    HR_ADMIN_ROLES: FrozenSet[str] = frozenset(
        {
            SYSTEM_MANAGER,
            VERENIGINGEN_ADMIN,
            VERENIGINGEN_STAFF,
            HR_MANAGER,
        }
    )

    ALL_PRIVILEGED_ROLES: FrozenSet[str] = frozenset(
        {
            SYSTEM_MANAGER,
            VERENIGINGEN_ADMIN,
            VERENIGINGEN_STAFF,
            CHAPTER_ADMIN,
        }
    )


# Document statuses
class DocStatus:
    """Standard document status values"""

    DRAFT = 0
    SUBMITTED = 1
    CANCELLED = 2


# Common field limits and constraints
class Limits:
    """Field limits and performance constraints"""

    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 1000
    MAX_QUERY_LIMIT = 5000
    BATCH_SIZE_DEFAULT = 100
    BATCH_SIZE_LARGE = 500

    # String field limits
    EMAIL_MAX_LENGTH = 140
    NAME_MAX_LENGTH = 100
    DESCRIPTION_MAX_LENGTH = 500


# Netherlands-specific constants
class Netherlands:
    """Netherlands-specific constants for localization"""

    COUNTRY_IDENTIFIERS: Set[str] = {"netherlands", "nederland", "nl"}
    POSTAL_CODE_PATTERN = r"^\d{4}[A-Z]{2}$"
    DEFAULT_CURRENCY = "EUR"
    VAT_RATE_STANDARD = 21.0
    VAT_RATE_REDUCED = 9.0


# SEPA and banking constants
class Banking:
    """Banking and SEPA-related constants"""

    SEPA_MANDATE_VALID_DAYS = 36 * 30  # 36 months in days (approx)
    DIRECT_DEBIT_BATCH_TIMEOUT = 300  # 5 minutes
    PAYMENT_RETRY_MAX_ATTEMPTS = 3
    PAYMENT_RETRY_DELAY_DAYS = 7

    # Mock banks for testing
    TEST_BANKS: Set[str] = {"TEST", "MOCK", "DEMO"}


# eBoekhouden integration constants
class EBoekhouden:
    """Constants for eBoekhouden API integration"""

    # Transaction type mappings
    TRANSACTION_TYPE_INVOICE_RECEIVED = 1
    TRANSACTION_TYPE_INVOICE_SENT = 2
    TRANSACTION_TYPE_PAYMENT_RECEIVED = 3
    TRANSACTION_TYPE_PAYMENT_SENT = 4
    TRANSACTION_TYPE_MONEY_RECEIVED = 5
    TRANSACTION_TYPE_MONEY_SENT = 6
    TRANSACTION_TYPE_MEMORIAL = 7
    TRANSACTION_TYPE_OPENING_BALANCE = 0

    # API timeouts and limits
    API_TIMEOUT_SECONDS = 30
    BATCH_SIZE_REST = 100
    BATCH_SIZE_SOAP = 50
    MAX_RETRIES = 3


# Membership and contribution constants
class Membership:
    """Membership-related constants"""

    # Billing frequencies
    BILLING_MONTHLY = "Monthly"
    BILLING_QUARTERLY = "Quarterly"
    BILLING_SEMI_ANNUAL = "Semi-Annual"
    BILLING_ANNUAL = "Annual"

    BILLING_FREQUENCIES: List[str] = [BILLING_MONTHLY, BILLING_QUARTERLY, BILLING_SEMI_ANNUAL, BILLING_ANNUAL]

    # Billing frequency to months mapping
    BILLING_FREQUENCY_MONTHS = {
        BILLING_MONTHLY: 1,
        BILLING_QUARTERLY: 3,
        BILLING_SEMI_ANNUAL: 6,
        BILLING_ANNUAL: 12,
    }

    # Billing frequency to annual multiplier (periods per year)
    BILLING_FREQUENCY_ANNUAL_MULTIPLIER = {
        BILLING_MONTHLY: 12,
        BILLING_QUARTERLY: 4,
        BILLING_SEMI_ANNUAL: 2,
        BILLING_ANNUAL: 1,
    }

    # Member statuses
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_SUSPENDED = "Suspended"
    STATUS_TERMINATED = "Quit"


# Volunteer system constants
class Volunteer:
    """Volunteer-related constants"""

    MIN_AGE_REQUIREMENT = 16
    DEFAULT_ACTIVITY_HOURS = 0.0
    MAX_EXPENSE_AMOUNT = 1000.0  # Default limit for expense claims

    # Volunteer statuses
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_ON_LEAVE = "On Leave"


# Performance and caching constants
class Performance:
    """Performance tuning and caching constants"""

    CACHE_TTL_SHORT = 300  # 5 minutes
    CACHE_TTL_MEDIUM = 1800  # 30 minutes
    CACHE_TTL_LONG = 3600  # 1 hour
    CACHE_TTL_DAILY = 86400  # 24 hours

    # Query optimization
    QUERY_TIMEOUT_SECONDS = 30
    MAX_CONCURRENT_QUERIES = 10
    INDEX_SCAN_THRESHOLD = 10000


# Email and notification constants
class Notifications:
    """Email and notification settings"""

    DEFAULT_SENDER = "noreply@vereniging.example"
    MAX_EMAIL_RECIPIENTS = 100
    EMAIL_TEMPLATE_CACHE_TTL = 3600

    # Notification types
    TYPE_PAYMENT_REMINDER = "payment_reminder"
    TYPE_MANDATE_EXPIRY = "mandate_expiry"
    TYPE_MEMBERSHIP_RENEWAL = "membership_renewal"


# Development and testing constants
class Development:
    """Development and testing configuration"""

    TEST_USER_EMAIL = "test@example.com"
    TEST_COMPANY = "Test Company"
    DEBUG_SQL_QUERIES = False

    # Test data patterns
    TEST_MEMBER_PREFIX = "TEST-MEMBER-"
    TEST_VOLUNTEER_PREFIX = "TEST-VOLUNTEER-"
    TEST_CHAPTER_PREFIX = "TEST-CHAPTER-"


# Error handling and logging
class ErrorHandling:
    """Error handling configuration"""

    MAX_ERROR_MESSAGE_LENGTH = 1000
    LOG_SENSITIVE_DATA = False
    INCLUDE_STACK_TRACE = True
    CRITICAL_ERROR_THRESHOLD = 10

    # Error notification roles
    ERROR_NOTIFICATION_ROLES: List[str] = [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN]


# API and endpoint constants
class API:
    """API configuration and limits"""

    DEFAULT_API_VERSION = "v1"
    MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB
    RATE_LIMIT_PER_MINUTE = 100
    API_KEY_LENGTH = 32

    # Response formats
    FORMAT_JSON = "json"
    FORMAT_CSV = "csv"
    FORMAT_PDF = "pdf"


# Invoice and payment status constants
class PaymentStatus:
    """Payment and invoice status constants"""

    # Invoice statuses
    INVOICE_PAID = "Paid"
    INVOICE_CREDIT_NOTE_ISSUED = "Credit Note Issued"
    INVOICE_OVERDUE = "Overdue"
    INVOICE_UNPAID = "Unpaid"
    INVOICE_PARTIALLY_PAID = "Partially Paid"
    INVOICE_PARTLY_PAID = "Partly Paid"

    # Payment statuses for display
    STATUS_PAID = "Paid"
    STATUS_FAILED = "Failed"
    STATUS_PENDING = "Pending"

    # Status groups for filtering
    PAID_STATUSES: Set[str] = {INVOICE_PAID, INVOICE_CREDIT_NOTE_ISSUED}
    UNPAID_STATUSES: Set[str] = {INVOICE_UNPAID, INVOICE_OVERDUE, INVOICE_PARTIALLY_PAID}
    RECONCILED_STATUSES: Set[str] = {INVOICE_PAID, INVOICE_PARTLY_PAID}


def get_admin_roles() -> Set[str]:
    """Get set of administrative role names for permission checks"""
    return Roles.ADMIN_ROLES.copy()


def get_volunteer_admin_roles() -> Set[str]:
    """Get set of volunteer administrative role names for permission checks"""
    return Roles.VOLUNTEER_ADMIN_ROLES.copy()


def is_netherlands_country(country: str) -> bool:
    """Check if country string represents Netherlands"""
    if not country:
        return False
    return country.strip().lower() in Netherlands.COUNTRY_IDENTIFIERS


def get_billing_frequency_months(frequency: str) -> int:
    """Get number of months for billing frequency"""
    return Membership.BILLING_FREQUENCY_MONTHS.get(frequency, 1)


def get_billing_frequency_annual_multiplier(frequency: str) -> int:
    """Get annual multiplier for billing frequency (periods per year)"""
    return Membership.BILLING_FREQUENCY_ANNUAL_MULTIPLIER.get(frequency, 1)


def build_billing_frequency_multiplier_sql(
    frequency_column: str = "billing_frequency",
    amount_expression: str = "amount",
    include_custom: bool = True,
    custom_frequency_number_col: str = "custom_frequency_number",
    custom_frequency_unit_col: str = "custom_frequency_unit",
) -> str:
    """Build SQL CASE statement for annualizing amounts based on billing frequency.

    Args:
        frequency_column: Column name containing billing frequency
        amount_expression: SQL expression for the amount to multiply
        include_custom: Whether to include Custom frequency handling
        custom_frequency_number_col: Column for custom frequency number
        custom_frequency_unit_col: Column for custom frequency unit

    Returns:
        SQL CASE statement string for annual revenue calculation
    """
    sql = f"""CASE
        WHEN {frequency_column} = 'Monthly' THEN {amount_expression} * 12
        WHEN {frequency_column} = 'Quarterly' THEN {amount_expression} * 4
        WHEN {frequency_column} = 'Semi-Annual' THEN {amount_expression} * 2
        WHEN {frequency_column} = 'Yearly' OR {frequency_column} = 'Annual' THEN {amount_expression}"""

    if include_custom:
        sql += f"""
        WHEN {frequency_column} = 'Custom' THEN
            CASE
                WHEN {custom_frequency_unit_col} = 'Month' THEN
                    {amount_expression} * (12 / NULLIF({custom_frequency_number_col}, 0))
                WHEN {custom_frequency_unit_col} = 'Week' THEN
                    {amount_expression} * (52 / NULLIF({custom_frequency_number_col}, 0))
                WHEN {custom_frequency_unit_col} = 'Year' THEN
                    {amount_expression} / NULLIF({custom_frequency_number_col}, 0)
                ELSE {amount_expression}
            END"""

    sql += f"""
        ELSE {amount_expression}
    END"""

    return sql


def get_year_date_range(year: int) -> tuple:
    """Get start and end date strings for a calendar year.

    Args:
        year: The calendar year (e.g., 2025)

    Returns:
        Tuple of (year_start, year_end) as strings in 'YYYY-MM-DD' format
    """
    return f"{year}-01-01", f"{year}-12-31"


# SQL filter fragments for reuse across queries
class SQLFilters:
    """Reusable SQL filter fragments for common query patterns"""

    # Filter for identifying membership-related invoices
    # Used in revenue calculations and analytics queries
    MEMBERSHIP_INVOICE = "(si.is_membership_invoice = 1 OR si.member IS NOT NULL)"

    @staticmethod
    def membership_invoice_filter(table_alias: str = "si") -> str:
        """Get membership invoice filter with custom table alias.

        Args:
            table_alias: SQL table alias (default: 'si' for Sales Invoice)

        Returns:
            SQL WHERE clause fragment for membership invoices
        """
        return f"({table_alias}.is_membership_invoice = 1 OR {table_alias}.member IS NOT NULL)"
