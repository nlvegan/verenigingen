"""
Constants and configuration values for Verenigingen app

This module centralizes commonly used constants to eliminate magic strings
and provide a single source of truth for configuration values.
"""

from typing import List, Set


# System roles and permissions
class Roles:
    """Standard role definitions used throughout the application"""

    SYSTEM_MANAGER = "System Manager"
    VERENIGINGEN_ADMIN = "Verenigingen Administrator"
    VERENIGINGEN_MANAGER = "Verenigingen Manager"
    VOLUNTEER_MANAGER = "Volunteer Manager"
    MEMBER = "Member"
    VOLUNTEER = "Volunteer"
    CHAPTER_ADMIN = "Chapter Administrator"

    # Role groups for common permission checks
    ADMIN_ROLES: Set[str] = {SYSTEM_MANAGER, VERENIGINGEN_ADMIN, VERENIGINGEN_MANAGER}

    VOLUNTEER_ADMIN_ROLES: Set[str] = {
        SYSTEM_MANAGER,
        VERENIGINGEN_ADMIN,
        VERENIGINGEN_MANAGER,
        VOLUNTEER_MANAGER,
    }

    ALL_PRIVILEGED_ROLES: Set[str] = {
        SYSTEM_MANAGER,
        VERENIGINGEN_ADMIN,
        VERENIGINGEN_MANAGER,
        VOLUNTEER_MANAGER,
        CHAPTER_ADMIN,
    }


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

    # Member statuses
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_SUSPENDED = "Suspended"
    STATUS_TERMINATED = "Terminated"


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
