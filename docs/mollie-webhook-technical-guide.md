# Mollie Webhook Technical Implementation Guide

## Overview

This document provides technical details on the Mollie webhook implementation for subscription payment processing. The webhook system has been developed with enterprise-grade security and reliability features.

## Architecture

### Webhook Flow

1. **Payment Completion**: Customer completes payment via Mollie checkout
2. **Webhook Trigger**: Mollie sends webhook notification to our endpoint
3. **Security Validation**: Multi-layer security validation of webhook payload
4. **Payment Processing**: Create Payment Entry and update Sales Invoice
5. **Subscription Activation**: If first payment, attempt subscription creation
6. **Error Recovery**: Built-in retry mechanism for failed operations

### Components

- **WebhookValidator**: Comprehensive webhook validation (`verenigingen_payments/core/security/webhook_validator.py`)
- **PaymentGatewayFactory**: Gateway management and processing
- **MollieGateway**: Mollie-specific payment processing
- **Subscription Activation**: Automated subscription creation after first payment

## Security Implementation

### Multi-Layer Validation

```python
def validate_webhook(payload, signature, headers):
    """
    1. Payload size validation (max 1MB)
    2. JSON structure validation
    3. Signature verification (HMAC-SHA256)
    4. Replay attack prevention (5-minute window)
    5. Required field validation
    """
```

### Security Features

- **HMAC-SHA256 Signature**: Validates webhook authenticity
- **Replay Protection**: Prevents duplicate webhook processing
- **Payload Size Limits**: Prevents DoS attacks via large payloads
- **Timestamp Validation**: Rejects old webhook notifications
- **IP Whitelisting**: Optional IP restriction (Mollie IP ranges)

### Configuration

```python
# Mollie Settings DocType
webhook_endpoint_key = "your-webhook-key-here"  # Set in Mollie Dashboard
signature_validation = True  # Always enabled in production
max_payload_size = 1048576  # 1MB limit
replay_window_seconds = 300  # 5-minute window
```

## Webhook Endpoint Implementation

### Primary Endpoint

**URL**: `/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook`
**Method**: POST
**Content-Type**: `application/json` or `application/x-www-form-urlencoded`

```python
@frappe.whitelist(allow_guest=True)
def mollie_subscription_webhook():
    """
    Main webhook handler for subscription payments
    - Authenticates webhook signature
    - Processes subscription payments
    - Creates Payment Entries
    - Activates subscriptions after first payment
    """
```

### Payload Processing

#### Mollie JSON Event Format (Production)
**Important**: Mollie sends webhooks as JSON event structures, not simple form data.

```json
{
    "resource": "event",
    "id": "event_abc123",
    "type": "payment.paid",
    "entityId": "tr_HWjAncEdZDCbf8ckhJ7EJ",
    "createdAt": "2025-09-12T12:39:00.0Z",
    "_embedded": {
        "entity": {
            "resource": "payment",
            "id": "tr_HWjAncEdZDCbf8ckhJ7EJ"
        }
    }
}
```

**Key Points**:
- Payment ID is in `entityId`, not `id`
- Event type (`payment.paid`, `payment.failed`, etc.) is in `type`
- Status must be fetched from Mollie API, not included in webhook
- Ping events have type `hook.ping` and should return success without processing

#### Legacy Form-Encoded Format (Manual Testing)
```
id=tr_xxxxx&status=paid
```

#### Processing Logic
```python
# Modern webhook handler must support both formats
if webhook_data.get("resource") == "event":
    # Mollie JSON event format
    event_type = webhook_data.get("type")
    if event_type.startswith("payment."):
        payment_id = webhook_data.get("entityId")
    elif event_type == "hook.ping":
        return {"status": "success", "message": "Webhook ping received"}
else:
    # Legacy form data format
    payment_id = webhook_data.get("id")
```

### Response Formats

#### Success Response
```json
{
    "status": "processed",
    "member": "MEMBER-001",
    "subscription_id": "sub_xxxxx",
    "actions": ["payment_entry_created", "subscription_activated"]
}
```

#### Error Response
```json
{
    "status": "error",
    "message": "Webhook authentication failed",
    "details": "Invalid signature"
}
```

## Payment Processing Logic

### Payment Entry Creation

```python
def _process_subscription_payment(gateway, member_name, customer_name, payment_id, subscription_id):
    """
    1. Verify payment is paid in Mollie
    2. Find unpaid Sales Invoice for member
    3. Create Payment Entry linking to invoice
    4. Use Bank account (not Cash) for electronic payments
    5. Update member subscription status if needed
    """
```

### Account Mapping

- **Source Account**: Sales Invoice `debit_to` (receivable account)
- **Target Account**: Bank account (for electronic Mollie payments)
- **Mode of Payment**: "Mollie"
- **Reference**: Mollie payment ID

### Data Flow

```
Mollie Payment (paid)
    ↓
Webhook Notification
    ↓
Payment Entry Creation
    ↓
Sales Invoice (marked as paid)
    ↓
Member Payment History (auto-updated via hooks)
```

## Subscription Activation

### First Payment Detection

```python
if payment.sequence_type == "first":
    # Attempt subscription activation
    activation_result = _activate_subscription_after_first_payment(
        gateway, member_name, customer_name, payment_id
    )
```

### Activation Logic

1. **Mandate Verification**: Confirm first payment established mandate
2. **Dues Schedule Lookup**: Find active Membership Dues Schedule
3. **Subscription Creation**: Call Mollie API to create subscription
4. **Member Update**: Set subscription ID and status on member record

### Frequency Mapping

```python
frequency_map = {
    "Monthly": "1 month",
    "Quarterly": "3 months",
    "Semi-Annual": "6 months",
    "Annual": "12 months"
}
```

## Error Recovery System

### Automatic Recovery

**Function**: `retry_failed_subscription_activations()`
**Schedule**: Daily via scheduled job
**Logic**:
- Find recent Mollie payments (last 30 days)
- Identify members without active subscriptions
- Retry subscription activation for completed first payments

### Manual Recovery

**Endpoint**: `/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.manual_subscription_retry`
**Access**: Requires appropriate user permissions
**Usage**: For troubleshooting and emergency recovery

## Logging and Monitoring

### Log Levels

- **INFO**: Normal webhook processing
- **WARNING**: Non-critical issues (amount mismatches, missing invoices)
- **ERROR**: Critical failures (webhook authentication, API errors)

### Key Log Messages

```python
# Success indicators
"Created Payment Entry {name} for Mollie subscription payment"
"Successfully activated subscription {id} for member {name}"

# Warning indicators
"No unpaid invoices found for member {name}"
"Payment amount mismatch: Mollie {amount1} vs Invoice {amount2}"

# Error indicators
"Webhook authentication failed"
"Error processing subscription payment {id}"
"Subscription activation failed for member {name}"
```

### Monitoring Queries

```sql
-- Recent webhook processing
SELECT * FROM tabError_Log
WHERE error LIKE '%Mollie%'
AND creation > DATE_SUB(NOW(), INTERVAL 24 HOUR);

-- Payment Entry creation
SELECT name, party, paid_amount, reference_no, posting_date
FROM `tabPayment Entry`
WHERE mode_of_payment = 'Mollie'
AND posting_date > DATE_SUB(CURDATE(), INTERVAL 7 DAY);

-- Member subscription status
SELECT name, first_name, last_name, subscription_status, next_payment_date
FROM tabMember
WHERE mollie_subscription_id IS NOT NULL;
```

## Testing Implementation

### Integration Tests

**File**: `verenigingen/tests/test_mollie_subscription_integration.py`
**Approach**: Genuine API integration (no mocks)
**Safety**: Built-in protection against live API key usage
**Coverage**:
- Real Mollie payment creation
- Webhook processing simulation
- Subscription activation testing
- Error recovery validation

### Test Scenarios

1. **Payment Creation**: Verify real Mollie checkout URLs generated
2. **Webhook Processing**: Test payment completion workflow
3. **Subscription Flow**: First payment → subscription activation
4. **Error Recovery**: Retry failed subscription activations

### Quality Assurance

- Phase 5.2 A+ Quality Testing standards
- Zero inappropriate mocks in integration tests
- **Built-in safety checks preventing live API key usage**
- Real API failure handling and validation
- Comprehensive business rule testing

### Test Safety Pattern

```python
def setUp(self):
    # CRITICAL SAFETY: Prevent live API key usage in tests
    settings = frappe.get_doc('Mollie Settings', 'Default')
    active_key = settings.get_active_api_key()

    if active_key and active_key.startswith('live_'):
        self.fail("CRITICAL SAFETY ERROR: Tests attempted to use LIVE API key")
```

## Performance Considerations

### Webhook Performance

- **Response Time**: < 5 seconds target
- **Concurrent Processing**: Thread-safe webhook handling
- **Database Optimization**: Indexed queries for member/customer lookup
- **API Rate Limits**: Mollie API call optimization

### Scalability

- **Webhook Queue**: Consider background job queue for high volume
- **Database Indexing**: Optimize member-customer relationship queries
- **Caching**: Cache frequent Mollie API settings lookups
- **Error Handling**: Graceful degradation under load

## Troubleshooting Guide

### Webhook Not Received

**Check List**:
1. Mollie Dashboard webhook URL configuration
2. Site URL accessibility from internet
3. Webhook endpoint security settings
4. Firewall and SSL certificate configuration

**Debugging**:
```bash
# Test webhook endpoint
curl -X POST https://yoursite.com/api/method/...mollie_subscription_webhook \
  -H "Content-Type: application/json" \
  -d '{"test": "payload"}'
```

### Payment Processing Failures

**Common Issues**:
- Bank account configuration missing
- Sales Invoice not found or already paid
- Member-Customer relationship not linked
- Account permission errors

**Debugging**:
```python
# Check recent Payment Entries
frappe.get_all("Payment Entry",
    filters={"mode_of_payment": "Mollie", "docstatus": 1},
    fields=["name", "party", "paid_amount", "posting_date"],
    order_by="posting_date desc", limit=10)
```

### Subscription Activation Issues

**Symptoms**: First payments complete but subscriptions not activated
**Root Causes**:
- Payment sequence_type != "first"
- Membership Dues Schedule not found
- Mollie mandate not established
- API rate limiting

**Resolution**:
```python
# Manual subscription retry
from verenigingen.verenigingen_payments.utils.payment_gateways import retry_failed_subscription_activations
result = retry_failed_subscription_activations()
print(result)
```

## Security Best Practices

### Production Deployment

1. **Always validate webhook signatures**
2. **Use HTTPS for all webhook endpoints**
3. **Implement IP whitelisting if required**
4. **Monitor for unusual webhook patterns**
5. **Regular API key rotation**

### Code Security

1. **No hardcoded secrets in source code**
2. **Proper error handling without data leakage**
3. **Input validation on all webhook data**
4. **Secure logging (no sensitive data in logs)**

### Infrastructure Security

1. **WAF protection for webhook endpoints**
2. **DDoS protection for high-volume webhooks**
3. **SSL/TLS termination at load balancer**
4. **Regular security updates and patches**

## Recent Updates (September 2025)

### JSON Event Format Implementation

**Critical Discovery**: Mollie sends webhooks as JSON event structures in production, not simple form data as used in testing.

**Production Format**:
```json
{
  "resource": "event",
  "type": "payment.paid",
  "entityId": "tr_HWjAncEdZDCbf8ckhJ7EJ",
  "createdAt": "2025-09-12T12:39:00.0Z"
}
```

**Key Implementation Updates**:
- ✅ **Unified Parser**: Created `mollie_webhook_parser.py` for consistent parsing across all handlers
- ✅ **JSON Event Support**: All webhook handlers now extract payment ID from `entityId` field
- ✅ **Ping Event Handling**: Proper response to Mollie's `hook.ping` connectivity tests
- ✅ **Backward Compatibility**: Legacy form data format still supported for manual testing
- ✅ **Quality Assurance**: QCE review completed with consistency improvements implemented

**Updated Webhook Handlers**:
- `mollie_payment_webhook.py` - Main donation webhook handler
- `payment_gateways.py::mollie_subscription_webhook()` - Subscription webhook handler
- `simple_donation_webhook.py` - Alternative donation webhook handler
- `secure_webhook_handler.py` - Enterprise webhook processor

**Testing Status**: ✅ Verified working with production Mollie webhook format

---

**Document Version**: 1.1
**Author**: Development Team
**Last Updated**: September 2025
**Classification**: Technical Implementation Guide
