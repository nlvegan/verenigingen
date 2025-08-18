# Mollie Backend API Integration - Documentation

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [API Endpoints](#api-endpoints)
4. [Configuration](#configuration)
5. [Security](#security)
6. [Error Handling](#error-handling)
7. [Monitoring](#monitoring)
8. [Troubleshooting](#troubleshooting)

## Overview

The Mollie Backend API Integration provides comprehensive financial operations management for the Verenigingen association management system. This integration enables automated payment processing, settlement reconciliation, dispute resolution, and financial reporting through Mollie's backend APIs.

### Key Features
- **Real-time Balance Monitoring**: Track account balances and receive alerts
- **Automated Settlement Reconciliation**: Match settlements with invoices automatically
- **Subscription Management**: Handle recurring payments and subscription lifecycle
- **Dispute Resolution**: Manage chargebacks and payment disputes
- **Financial Dashboard**: Real-time metrics and reporting

### System Requirements
- Frappe Framework v15+
- Python 3.10+
- Redis for background jobs
- MySQL 8.0+ or MariaDB 10.6+
- Mollie API credentials (live or test)

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Frappe Application Layer                 │
├─────────────────────────────────────────────────────────────┤
│                   Mollie Backend Integration                 │
├──────────────┬────────────┬────────────┬──────────────────┤
│   Security   │  Resilience │ Compliance │    Monitoring    │
├──────────────┴────────────┴────────────┴──────────────────┤
│                      API Clients Layer                       │
├────────┬──────────┬───────────┬──────────┬────────────────┤
│Balance │Settlement│  Invoice  │  Org     │  Chargeback    │
│ Client │  Client  │  Client   │  Client  │    Client      │
├────────┴──────────┴───────────┴──────────┴────────────────┤
│                    Mollie Backend APIs                       │
└─────────────────────────────────────────────────────────────┘
```

### Core Components

#### 1. Security Framework
- **Location**: `verenigingen_payments/core/security/`
- **Components**:
  - `mollie_security_manager.py`: API key management and rotation
  - `webhook_validator.py`: Webhook signature validation
  - `encryption_handler.py`: Sensitive data encryption

#### 2. Resilience Infrastructure
- **Location**: `verenigingen_payments/core/resilience/`
- **Components**:
  - `circuit_breaker.py`: Fault tolerance with circuit breaker pattern
  - `rate_limiter.py`: API rate limiting
  - `retry_policy.py`: Exponential backoff retry logic

#### 3. API Clients
- **Location**: `verenigingen_payments/clients/`
- **Components**:
  - `balances_client.py`: Balance monitoring and alerts
  - `settlements_client.py`: Settlement reconciliation
  - `invoices_client.py`: Invoice management
  - `organizations_client.py`: Organization settings
  - `chargebacks_client.py`: Dispute handling

#### 4. Business Workflows
- **Location**: `verenigingen_payments/workflows/`
- **Components**:
  - `reconciliation_engine.py`: Automated reconciliation
  - `subscription_manager.py`: Subscription lifecycle
  - `dispute_resolution.py`: Chargeback workflows
  - `financial_dashboard.py`: Reporting and metrics

## API Endpoints

### Whitelisted Methods

All API endpoints are secured with Frappe's permission system and require authentication.

#### Balance Operations

```python
@frappe.whitelist()
def get_account_balance():
    """
    Get current account balance

    Returns:
        dict: {
            "available": decimal,
            "pending": decimal,
            "currency": str
        }
    """
```

```python
@frappe.whitelist()
def set_balance_alert(threshold: float, alert_type: str):
    """
    Set balance alert threshold

    Args:
        threshold: Amount threshold
        alert_type: "low_balance" | "high_balance"

    Returns:
        dict: Alert configuration
    """
```

#### Settlement Operations

```python
@frappe.whitelist()
def reconcile_settlements(date_from: str = None, date_to: str = None):
    """
    Reconcile settlements for date range

    Args:
        date_from: Start date (YYYY-MM-DD)
        date_to: End date (YYYY-MM-DD)

    Returns:
        dict: {
            "reconciled": int,
            "unmatched": int,
            "errors": list
        }
    """
```

```python
@frappe.whitelist()
def get_settlement_details(settlement_id: str):
    """
    Get detailed settlement information

    Args:
        settlement_id: Mollie settlement ID

    Returns:
        dict: Settlement details with transactions
    """
```

#### Subscription Management

```python
@frappe.whitelist()
def create_subscription(member_name: str, amount: float, interval: str):
    """
    Create Mollie subscription

    Args:
        member_name: Member document name
        amount: Subscription amount
        interval: "1 month" | "3 months" | "1 year"

    Returns:
        dict: {
            "subscription_id": str,
            "status": str,
            "next_payment": date
        }
    """
```

```python
@frappe.whitelist()
def cancel_subscription(member_name: str, reason: str = None):
    """
    Cancel member subscription

    Args:
        member_name: Member document name
        reason: Cancellation reason

    Returns:
        dict: Cancellation confirmation
    """
```

#### Dispute Resolution

```python
@frappe.whitelist()
def create_dispute_case(payment_id: str, chargeback_id: str):
    """
    Create dispute case from chargeback

    Args:
        payment_id: Mollie payment ID
        chargeback_id: Mollie chargeback ID

    Returns:
        dict: Dispute case details
    """
```

```python
@frappe.whitelist()
def submit_dispute_evidence(case_id: str, evidence_ids: list, response: str):
    """
    Submit dispute response with evidence

    Args:
        case_id: Dispute case ID
        evidence_ids: List of evidence document IDs
        response: Dispute response text

    Returns:
        dict: Submission result
    """
```

#### Dashboard & Reporting

```python
@frappe.whitelist()
def get_dashboard_metrics():
    """
    Get real-time financial metrics

    Returns:
        dict: {
            "balance": dict,
            "settlements": dict,
            "subscriptions": dict,
            "disputes": dict,
            "revenue": dict
        }
    """
```

## Configuration

### Mollie Settings DocType

Configure the integration through the Mollie Settings DocType:

```python
{
    "gateway_name": "Production",  # or "Test"
    "secret_key": "live_xxx",      # Encrypted
    "profile_id": "pfl_xxx",
    "webhook_secret": "xxx",       # For webhook validation

    # Security Settings
    "enable_encryption": true,
    "enable_audit_trail": true,
    "api_key_rotation_days": 90,

    # Resilience Settings
    "circuit_breaker_failure_threshold": 5,
    "circuit_breaker_timeout": 60,
    "rate_limit_requests_per_second": 25,
    "retry_max_attempts": 3,
    "retry_backoff_base": 2,

    # Reconciliation Settings
    "auto_reconcile": true,
    "reconciliation_hour": 2,  # 2 AM
    "reconciliation_tolerance": 0.01,  # 1 cent

    # Alert Settings
    "low_balance_threshold": 1000.00,
    "enable_balance_alerts": true,
    "alert_recipients": "finance@example.com"
}
```

### Environment Variables

Set these environment variables for production:

```bash
# Required
MOLLIE_API_KEY=live_xxx
MOLLIE_PROFILE_ID=pfl_xxx
MOLLIE_WEBHOOK_SECRET=xxx

# Optional
MOLLIE_API_TIMEOUT=30
MOLLIE_MAX_RETRIES=3
MOLLIE_RATE_LIMIT=25
```

### Webhook Configuration

Configure webhook endpoint in Mollie Dashboard:

```
URL: https://your-domain.com/api/method/verenigingen.utils.payment_gateways.mollie_webhook
Method: POST
Events: All payment and subscription events
```

## Security

### API Key Management

```python
# Rotate API keys programmatically
from verenigingen.verenigingen_payments.core.security import MollieSecurityManager

manager = MollieSecurityManager("Production")
new_key = manager.rotate_api_key()
```

### Webhook Validation

All webhooks are validated using HMAC-SHA256:

```python
from verenigingen.verenigingen_payments.core.security import WebhookValidator

validator = WebhookValidator("Production")
is_valid = validator.validate_webhook(body, signature)
```

### Data Encryption

Sensitive data is encrypted using AES-256-GCM:

```python
from verenigingen.verenigingen_payments.core.security import EncryptionHandler

handler = EncryptionHandler()
encrypted = handler.encrypt_data(sensitive_data)
decrypted = handler.decrypt_data(encrypted)
```

### Permission Model

| Role | Permissions |
|------|------------|
| Verenigingen Administrator | Full access to all features |
| Verenigingen Manager | Create/read subscriptions, view reports |
| Verenigingen Finance | Reconciliation, reports, disputes |
| Verenigingen Staff | View reports only |

## Error Handling

### Error Types

#### 1. API Errors
```python
try:
    result = client.get_balance()
except MollieAPIError as e:
    # Handle API-specific errors
    if e.status_code == 404:
        # Resource not found
    elif e.status_code == 422:
        # Validation error
```

#### 2. Network Errors
```python
try:
    result = client.make_request()
except (ConnectionError, TimeoutError) as e:
    # Handled by retry policy and circuit breaker
```

#### 3. Business Logic Errors
```python
try:
    reconcile_settlement(settlement_id)
except ReconciliationError as e:
    # Log to audit trail
    # Create manual reconciliation task
```

### Error Recovery

The system implements automatic recovery for transient failures:

1. **Retry with Exponential Backoff**: Up to 3 attempts
2. **Circuit Breaker**: Prevents cascading failures
3. **Fallback Mechanisms**: Degraded service when possible
4. **Manual Recovery Queue**: For persistent failures

## Monitoring

### Metrics Collection

Key metrics tracked:

- **API Performance**:
  - Response times (p50, p95, p99)
  - Error rates by endpoint
  - Rate limit utilization

- **Business Metrics**:
  - Successful payment rate
  - Settlement reconciliation rate
  - Dispute win rate
  - Subscription churn rate

- **System Health**:
  - Circuit breaker state
  - Queue depth
  - Memory usage
  - Database query performance

### Alerting Rules

Configure alerts in `Mollie Alert Configuration`:

```python
{
    "alert_rules": [
        {
            "name": "Low Balance",
            "condition": "balance < 1000",
            "severity": "warning",
            "recipients": ["finance@example.com"]
        },
        {
            "name": "High Failure Rate",
            "condition": "error_rate > 0.05",
            "severity": "critical",
            "recipients": ["tech@example.com"]
        },
        {
            "name": "Reconciliation Failed",
            "condition": "reconciliation_status == 'failed'",
            "severity": "high",
            "recipients": ["finance@example.com"]
        }
    ]
}
```

### Dashboard Access

Access the financial dashboard at:
```
/app/mollie-financial-dashboard
```

Features:
- Real-time balance display
- Settlement status overview
- Subscription metrics
- Dispute tracking
- Revenue trends

## Troubleshooting

### Common Issues

#### 1. Webhook Not Received

**Symptoms**: Payments not updating automatically

**Diagnosis**:
```bash
# Check webhook logs
bench --site your-site mariadb
SELECT * FROM `tabMollie Webhook Log`
WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)
ORDER BY creation DESC;
```

**Solutions**:
- Verify webhook URL in Mollie Dashboard
- Check webhook secret configuration
- Ensure firewall allows Mollie IPs
- Validate SSL certificate

#### 2. Reconciliation Failures

**Symptoms**: Settlements not matching invoices

**Diagnosis**:
```python
# Check reconciliation logs
frappe.get_all("Mollie Reconciliation Log",
    filters={"status": "Failed"},
    fields=["settlement_id", "error_message"])
```

**Solutions**:
- Adjust reconciliation tolerance
- Check for duplicate invoices
- Verify payment references
- Run manual reconciliation

#### 3. API Rate Limiting

**Symptoms**: 429 errors from Mollie API

**Diagnosis**:
```python
# Check rate limit metrics
from verenigingen.verenigingen_payments.core.resilience import RateLimiter
limiter = RateLimiter()
print(f"Current rate: {limiter.get_current_rate()}")
```

**Solutions**:
- Reduce request frequency
- Implement request batching
- Use webhook updates instead of polling
- Contact Mollie for rate limit increase

#### 4. Circuit Breaker Open

**Symptoms**: All API calls failing immediately

**Diagnosis**:
```python
# Check circuit breaker state
from verenigingen.verenigingen_payments.core.resilience import CircuitBreaker
breaker = CircuitBreaker.get_instance("mollie_api")
print(f"State: {breaker.state}")
print(f"Failure count: {breaker.failure_count}")
```

**Solutions**:
- Wait for timeout period
- Check API health status
- Manually reset if API recovered
- Investigate root cause of failures

### Debug Mode

Enable debug logging:

```python
# In frappe-bench/sites/your-site/site_config.json
{
    "developer_mode": 1,
    "logging": 2,
    "mollie_debug": true
}
```

View debug logs:
```bash
tail -f frappe-bench/logs/frappe.log | grep MOLLIE
```

### Support Resources

- **Mollie API Documentation**: https://docs.mollie.com/
- **Frappe Framework Docs**: https://frappeframework.com/
- **Issue Tracker**: https://github.com/your-org/verenigingen/issues
- **Support Email**: support@your-org.com

## Appendix

### A. API Response Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process response |
| 201 | Created | Process new resource |
| 204 | No Content | Success, no response body |
| 400 | Bad Request | Check request parameters |
| 401 | Unauthorized | Check API key |
| 403 | Forbidden | Check permissions |
| 404 | Not Found | Resource doesn't exist |
| 422 | Unprocessable | Validation error |
| 429 | Rate Limited | Implement backoff |
| 500 | Server Error | Retry with backoff |
| 503 | Unavailable | Circuit breaker activates |

### B. Webhook Event Types

| Event | Description | Handler |
|-------|-------------|---------|
| payment.paid | Payment successful | Update invoice, create payment entry |
| payment.failed | Payment failed | Log failure, notify member |
| payment.expired | Payment expired | Cancel pending invoice |
| subscription.created | New subscription | Update member record |
| subscription.updated | Subscription changed | Update subscription details |
| subscription.cancelled | Subscription ended | Update status, stop billing |
| settlement.settled | Settlement completed | Trigger reconciliation |
| chargeback.received | Dispute initiated | Create dispute case |

### C. Database Schema

Key tables created by the integration:

```sql
-- Mollie Settings
CREATE TABLE `tabMollie Settings` (
    `name` varchar(140),
    `gateway_name` varchar(140),
    `secret_key` text,  -- Encrypted
    `profile_id` varchar(140),
    ...
);

-- Mollie Audit Log
CREATE TABLE `tabMollie Audit Log` (
    `name` varchar(140),
    `event_type` varchar(140),
    `severity` varchar(20),
    `message` text,
    `details` longtext,  -- JSON
    `user` varchar(140),
    `ip_address` varchar(45),
    ...
);

-- Dispute Case
CREATE TABLE `tabDispute Case` (
    `name` varchar(140),
    `case_id` varchar(140),
    `payment_id` varchar(140),
    `chargeback_id` varchar(140),
    `amount` decimal(18,6),
    `status` varchar(20),
    `priority` varchar(20),
    ...
);
```

---

*Last Updated: August 2024*
*Version: 1.0.0*
