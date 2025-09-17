# Mollie Webhook Security Implementation

## Overview

This document summarizes the webhook security implementation completed to address QCE security review findings. The implementation adds HMAC-SHA256 signature verification to prevent malicious webhook attacks.

## Security Issue Addressed

**Problem**: Mollie webhooks were unprotected with `@frappe.whitelist(allow_guest=True)` but no signature verification, allowing potential malicious requests.

**Solution**: Implemented webhook signature verification using the secret key provided by Mollie: `g4BK7FuzA5tGQxfmPUpefWDb8A7c8bKc`

## Implementation Details

### 1. Mollie Settings Configuration

**File**: `verenigingen/verenigingen_payments/doctype/mollie_settings/mollie_settings.json`

Added new field to store webhook secret securely:
```json
{
  "fieldname": "webhook_secret_key",
  "fieldtype": "Password",
  "label": "Webhook Secret Key",
  "description": "Secret key from Mollie for webhook signature verification (obtained when configuring webhook endpoint)"
}
```

**File**: `verenigingen/verenigingen_payments/doctype/mollie_settings/mollie_settings.py`

Updated `get_webhook_secret()` method to retrieve the encrypted secret:
```python
def get_webhook_secret(self):
    """Get webhook secret key for signature verification"""
    return self.get_password(fieldname="webhook_secret_key", raise_exception=False)
```

### 2. Webhook Security Utilities

**File**: `verenigingen/utils/webhook_security.py` (NEW)

Created security utilities including:

- `verify_mollie_webhook_signature()`: Core HMAC-SHA256 signature verification
- `authenticate_mollie_webhook()`: Complete request authentication with error handling
- `log_webhook_security_event()`: Security event logging for monitoring
- `WebhookAuthenticationError`: Custom exception for webhook authentication failures

Key security features:
- Constant-time signature comparison to prevent timing attacks
- Proper error handling and logging
- Support for Mollie's `sha256=` signature format
- security event logging

### 3. Webhook Endpoint Security

**File**: `verenigingen/verenigingen_payments/utils/payment_gateways.py`

Updated both webhook endpoints to use authentication:

- `mollie_webhook()`: Regular payment webhook with signature verification
- `mollie_subscription_webhook()`: Subscription webhook with signature verification

Both endpoints now:
1. Authenticate webhook using signature verification
2. Log security events (success/failure)
3. Return proper error responses for authentication failures
4. Process webhook data only after successful authentication

## Security Testing

Comprehensive testing confirmed:

✅ **Valid Signature**: Properly accepts webhooks with correct HMAC-SHA256 signatures
✅ **Invalid Signature**: Correctly rejects webhooks with invalid signatures
✅ **Missing Signature**: Properly rejects webhooks without signature headers
✅ **Empty Payload**: Handles empty webhook payloads appropriately
✅ **Security Logging**: Events logged for monitoring and debugging

## Usage Instructions

### 1. Configure Webhook Secret

1. Navigate to **Verenigingen Payments → Mollie Settings**
2. In the **Webhook Security** section, enter the webhook secret key: `g4BK7FuzA5tGQxfmPUpefWDb8A7c8bKc`
3. Save the settings

### 2. Update Mollie Dashboard

Configure your webhook endpoints in the Mollie Dashboard:
- Payment webhook: `https://your-domain/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_webhook`
- Subscription webhook: `https://your-domain/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook`

### 3. Monitor Security Events

Check Frappe error logs for webhook security events:
- ✅ Successful authentications logged as INFO
- ⚠️ Security warnings logged as WARNINGS
- ❌ Authentication failures logged as ERRORS

## Security Benefits

1. **Prevents Malicious Attacks**: Only webhooks from Mollie with valid signatures are processed
2. **Timing Attack Protection**: Uses constant-time comparison for signature verification
3. **Comprehensive Logging**: All security events logged for monitoring and debugging
4. **Error Handling**: Proper error responses prevent information leakage
5. **Industry Standard**: Implements HMAC-SHA256 as recommended by Mollie

## Testing Commands

Test the webhook authentication:
```bash
# Run webhook signature verification test (development mode only)
bench --site dev.veganisme.net execute "verenigingen.utils.webhook_security.test_webhook_signature_verification"
```

## Files Modified

1. `mollie_settings.json` - Added webhook secret field
2. `mollie_settings.py` - Updated webhook secret retrieval method
3. `webhook_security.py` - NEW: Core security utilities
4. `payment_gateways.py` - Updated webhook endpoints with authentication

## Compliance

This implementation addresses the QCE security review findings and implements industry-standard webhook security practices as recommended by Mollie documentation.

---
**Status**: ✅ COMPLETED
**Date**: 2025-08-30
**Security Rating**: 🔒 HIGH - Webhook endpoints now properly secured with signature verification
