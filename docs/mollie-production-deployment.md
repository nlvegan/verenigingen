# Mollie Integration Production Deployment Guide

## Overview

This guide covers the deployment of Mollie payment integration and subscription functionality to production environment. The integration has been developed following Phase 5.2 A+ Quality Testing standards with genuine API integration testing.

## Pre-Deployment Checklist

### 1. API Configuration

- [ ] **Production API Keys**: Replace test API keys with live Mollie API keys
  - Navigate to: Vereinigingen Payments → Mollie Settings
  - Update `api_key` field with live key (starts with `live_`)
  - Verify webhook endpoint URL is accessible from internet

- [ ] **Webhook Security**: Configure webhook signature validation
  - Set webhook endpoint key in Mollie Dashboard
  - Verify webhook validator is using production security settings
  - Test webhook authentication with real Mollie webhooks

### 2. Account Configuration

- [ ] **Bank Accounts**: Configure proper bank accounts for Mollie payments
  - Mollie payments are electronic transfers, not cash
  - Update company default bank account settings
  - Verify account mapping in Payment Entry creation

- [ ] **Customer Fields**: Ensure Mollie-specific fields are available
  - `custom_mollie_customer_id` on Customer doctype
  - `custom_mollie_subscription_id` on Customer doctype
  - Fields should be created automatically during app installation

### 3. Subscription Workflow Setup

- [ ] **Membership Dues Schedules**: Configure automatic dues generation
  - Verify Membership Dues Schedule DocType has all required fields
  - Test membership creation triggers dues schedule creation
  - Ensure `auto_generate` flag is properly set

- [ ] **Member Fields**: Verify subscription tracking fields on Member doctype
  - `mollie_customer_id`
  - `mollie_subscription_id`
  - `subscription_status`
  - `next_payment_date`

### 4. Error Recovery Setup

- [ ] **Scheduled Jobs**: Configure subscription retry scheduled task
  ```python
  # Add to hooks.py or scheduler_events
  scheduler_events = {
      "daily": [
          "verenigingen.verenigingen_payments.utils.payment_gateways.retry_failed_subscription_activations"
      ]
  }
  ```

- [ ] **Manual Recovery**: Document manual recovery procedure
  - Access: `/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.manual_subscription_retry`
  - Requires appropriate user permissions

## Deployment Steps

### 1. Database Migration

```bash
# Run database migration to ensure all fields are created
bench --site [site-name] migrate

# Import any custom fields or fixtures
bench --site [site-name] import-doc /path/to/fixtures/

# Clear cache after field updates
bench --site [site-name] clear-cache
```

### 2. Configuration Updates

```bash
# Update Mollie Settings with production values
# Navigate to: Verenigingen Payments → Mollie Settings
# Update:
# - API Key (live_xxxxx)
# - Webhook URL (https://yourdomain.com/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook)
# - Enable subscriptions
# - Set webhook endpoint key for signature validation
```

### 3. Webhook Setup

#### 3.1 Mollie Dashboard Configuration

1. Login to Mollie Dashboard
2. Navigate to Developers → Webhooks
3. Add webhook URL: `https://yourdomain.com/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook`
4. Enable events:
   - `payment.paid`
   - `payment.failed`
   - `subscription.created`
   - `subscription.cancelled`
5. Set webhook endpoint key for signature validation

#### 3.2 Webhook Security Verification

```bash
# Test webhook endpoint accessibility
curl -X POST https://yourdomain.com/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook \
  -H "Content-Type: application/json" \
  -d '{"test": "ping"}'

# Should return webhook authentication error (expected for test payload)
```

### 4. Production Testing

#### 4.1 Test Payment Flow

**CRITICAL SAFETY**: Verify test environment is using test API keys:
```bash
# Verify test mode in Frappe console
bench --site [site-name] console
>>> settings = frappe.get_doc('Mollie Settings', 'Default')
>>> key = settings.get_active_api_key()
>>> print(f"Using API key: {key[:10]}...")  # Should show "test_xxxxx"
>>> assert key.startswith('test_'), "CRITICAL: Live API key detected!"
```

1. Create test donation with small amount (€0.01)
2. Complete payment via Mollie checkout
3. Verify Payment Entry creation
4. Check Sales Invoice marked as paid

#### 4.2 Test Subscription Flow

1. Create member with Membership Dues Schedule
2. Process first payment with `sequenceType: "first"`
3. Complete payment via Mollie checkout
4. Verify webhook triggers subscription activation
5. Check member has `mollie_subscription_id` and `subscription_status: "Active"`

#### 4.3 Test Error Recovery

```bash
# Run manual subscription retry
curl -X POST https://yourdomain.com/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.manual_subscription_retry \
  -H "Authorization: token [api-key]:[api-secret]"
```

## Monitoring and Maintenance

### 1. Log Monitoring

- **Webhook Processing**: Monitor `/logs` for webhook processing errors
- **Subscription Activation**: Check for subscription activation failures
- **Payment Entry Creation**: Verify Payment Entries are created correctly

Key log patterns to monitor:
```
- "Mollie subscription webhook received and authenticated"
- "Created Payment Entry .* for Mollie subscription payment"
- "Successfully activated subscription .* for member"
- "Subscription activation failed for member"
```

### 2. Data Integrity Checks

#### Daily Checks
- Verify all paid Mollie payments have corresponding Payment Entries
- Check members with completed first payments have active subscriptions
- Monitor failed subscription activation attempts

#### Weekly Checks
- Reconcile Mollie dashboard subscriptions with system subscriptions
- Verify subscription payment amounts match Membership Dues Schedules
- Check for orphaned customers without linked members

### 3. Performance Monitoring

- **Webhook Response Time**: Should be < 5 seconds
- **API Call Frequency**: Monitor Mollie API rate limits
- **Database Performance**: Check Payment Entry creation performance

## Security Considerations

### 1. Webhook Security

- **Signature Validation**: Always enabled in production
- **HTTPS Only**: Webhook endpoint must use HTTPS
- **Replay Protection**: Built-in replay attack prevention
- **Payload Size Limits**: 1MB maximum payload size

### 2. API Key Security

- **Environment Variables**: Store API keys securely
- **Access Control**: Limit who can view/modify Mollie Settings
- **Key Rotation**: Regular API key rotation (quarterly recommended)

### 3. Data Protection

- **PII Handling**: Customer data handled according to GDPR
- **Payment Data**: No payment card data stored locally
- **Audit Trail**: All payment operations logged

## Troubleshooting

### Common Issues

#### 1. Webhook Not Receiving Events

**Symptoms**: No webhook calls in logs, payments not processed
**Solutions**:
- Check Mollie Dashboard webhook URL configuration
- Verify webhook endpoint is publicly accessible
- Test with `curl` or webhook testing tools
- Check Frappe site configuration for webhook URL

#### 2. Subscription Creation Fails

**Symptoms**: First payments complete but subscriptions not activated
**Solutions**:
- Verify customer has valid mandate (completed first payment)
- Check Membership Dues Schedule exists and is active
- Run manual subscription retry function
- Verify sequenceType in payment creation

#### 3. Payment Entry Creation Errors

**Symptoms**: Webhooks received but Payment Entries not created
**Solutions**:
- Check bank account configuration
- Verify Sales Invoice exists and is unpaid
- Check account mapping for receivable accounts
- Review Payment Entry validation errors

#### 4. Member-Customer Linking Issues

**Symptoms**: Webhooks processed but member data not updated
**Solutions**:
- Verify Customer has `custom_mollie_subscription_id` field
- Check Member-Customer relationship is properly linked
- Ensure customer sync hooks are enabled

## Rollback Procedure

If issues arise post-deployment:

### 1. Immediate Actions
- Disable webhook in Mollie Dashboard
- Switch Mollie Settings back to test mode
- Stop scheduled subscription retry jobs

### 2. Data Recovery
- Review Payment Entries created since deployment
- Check member subscription status updates
- Verify no duplicate charges occurred

### 3. System Restore
```bash
# Restore from pre-deployment backup if necessary
bench --site [site-name] restore [backup-file]

# Rollback specific changes
bench --site [site-name] migrate --reset-to [commit-hash]
```

## Support and Maintenance

### Contact Information
- **Technical Issues**: Development team
- **Mollie API Issues**: Mollie Support
- **Financial Discrepancies**: Finance team

### Documentation Updates
This document should be updated when:
- API endpoints change
- New webhook events are added
- Security requirements are updated
- Troubleshooting procedures are modified

## Appendices

### A. API Endpoints

- **Mollie Webhook**: `/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook`
- **Manual Retry**: `/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.manual_subscription_retry`

### B. Database Fields

**Customer DocType**:
- `custom_mollie_customer_id` (Data)
- `custom_mollie_subscription_id` (Data)

**Member DocType**:
- `mollie_customer_id` (Data)
- `mollie_subscription_id` (Data)
- `subscription_status` (Select)
- `next_payment_date` (Date)

### C. Test Scenarios

Comprehensive test scenarios are available in:
- `verenigingen/tests/test_mollie_subscription_integration.py`
- All tests use genuine Mollie API integration (no mocks)
- Tests validate complete payment and subscription workflows

---

**Document Version**: 1.0
**Last Updated**: September 2025
**Next Review**: December 2025
