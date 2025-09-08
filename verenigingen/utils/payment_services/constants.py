"""
Payment Services Constants

Centralized constants for payment processing business rules and configuration.
"""

# Mollie Payment ID Prefixes
MOLLIE_LIVE_PAYMENT_PREFIX = "tr_"
MOLLIE_TEST_PAYMENT_PREFIX = "test_"
MOLLIE_VALID_PREFIXES = (MOLLIE_LIVE_PAYMENT_PREFIX, MOLLIE_TEST_PAYMENT_PREFIX)

# Mollie Customer ID Prefixes
MOLLIE_LIVE_CUSTOMER_PREFIX = "cst_"
MOLLIE_TEST_CUSTOMER_PREFIX = "test_"
MOLLIE_VALID_CUSTOMER_PREFIXES = (MOLLIE_LIVE_CUSTOMER_PREFIX, MOLLIE_TEST_CUSTOMER_PREFIX)

# Mollie Refund ID Prefixes
MOLLIE_LIVE_REFUND_PREFIX = "re_"
MOLLIE_TEST_REFUND_PREFIX = "test_"
MOLLIE_VALID_REFUND_PREFIXES = (MOLLIE_LIVE_REFUND_PREFIX, MOLLIE_TEST_REFUND_PREFIX)

# Payment Status Constants
MOLLIE_PAYMENT_STATUS_PAID = "paid"
MOLLIE_PAYMENT_STATUS_CANCELED = "canceled"
MOLLIE_PAYMENT_STATUS_EXPIRED = "expired"
MOLLIE_PAYMENT_STATUS_FAILED = "failed"
MOLLIE_PAYMENT_STATUS_PENDING = "pending"

# Refund Status Constants
MOLLIE_REFUND_STATUS_REFUNDED = "refunded"
MOLLIE_REFUND_STATUS_PENDING = "pending"
MOLLIE_REFUND_STATUS_FAILED = "failed"

# Webhook Types
WEBHOOK_TYPE_PAYMENT = "payment"
WEBHOOK_TYPE_REFUND = "refund"
WEBHOOK_TYPE_CHARGEBACK = "chargeback"
WEBHOOK_TYPE_SUBSCRIPTION = "subscription"

# Standard Error Response Format
STANDARD_ERROR_RESPONSE = {
    "status": "error",
    "message": "",
    "error_code": None,
    "details": None,
    "timestamp": None,
}

STANDARD_SUCCESS_RESPONSE = {"status": "success", "message": "", "data": None, "timestamp": None}

# Query Limits and Timeouts
DEFAULT_QUERY_LIMIT = 1000
WEBHOOK_PROCESSING_TIMEOUT_MINUTES = 10
REFUND_QUERY_BATCH_SIZE = 100

# Validation Constants
MAX_REFUND_DESCRIPTION_LENGTH = 255
MIN_REFUND_AMOUNT = 0.01
MAX_CONCURRENT_WEBHOOK_PROCESSING = 5

# Logging Categories
LOG_CATEGORY_PAYMENT = "Payment Processing"
LOG_CATEGORY_REFUND = "Refund Processing"
LOG_CATEGORY_WEBHOOK = "Webhook Processing"
LOG_CATEGORY_VALIDATION = "Input Validation"
LOG_CATEGORY_SECURITY = "Security"
