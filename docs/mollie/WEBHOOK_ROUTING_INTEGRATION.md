# Webhook Payment Type Routing Integration

**Date**: 2025-10-21
**Status**: ✅ Completed
**Impact**: High - Enables membership dues webhook processing

## Problem Statement

The unified webhook handler (`handle_payment_webhook`) was hardcoded to process **donations only**. When testing webhook processing for membership dues payments (e.g., from balance transactions), the system would return:

```json
{
  "status": "error",
  "message": "No donation found for payment tr_XXXXXXXXX"
}
```

This occurred because the webhook service only used `find_donation_for_payment_by_id()` and had no logic to handle membership dues payments, even though a separate `DuesPaymentProcessor` existed.

## Solution Architecture

### 1. Payment Type Router Service

Created a new service (`payment_type_router.py`) that acts as a dispatcher:

```python
class PaymentTypeRouter:
    """
    Routes payments to appropriate processors based on classification.

    Flow:
    1. Fetch payment data from Mollie API
    2. Classify payment type (dues, donation, unknown)
    3. Route to appropriate processor
    4. Return unified result format
    """
```

**Key Features**:
- Uses existing `PaymentClassifier` for type detection
- Integrates both `DuesPaymentProcessor` and donation webhook service
- Provides unified result format across all payment types
- Includes classification metadata (confidence, matched_by) for debugging

### 2. Classification Strategy

The router leverages the existing `PaymentClassifier` with multiple classification rules:

1. **Subscription-based** (High Confidence)
   - Checks `subscription_id` against Member/Donor records
   - Highest confidence level

2. **Customer-based** (Medium Confidence)
   - Checks `customer_id` against Member/Donor records
   - Good confidence for direct customer links

3. **Metadata-based** (Low Confidence)
   - Parses payment description for member/donor IDs
   - Fallback method for legacy data

### 3. Webhook Integration

Modified `UnifiedWebhookWrapperService.process_payment_webhook()` to:

```python
# STEP 0: PAYMENT TYPE CLASSIFICATION & ROUTING
router = get_payment_router()
payment = router.fetch_payment(payment_id)
classification = router.classify_payment(payment)

# If it's membership dues, route to DuesPaymentProcessor
if classification['payment_type'] == PaymentType.DUES:
    result = router.route_payment(payment_id, payment)
    return result

# Otherwise, continue with existing donation processor
```

**Benefits**:
- Non-breaking change - donation processing unchanged
- Graceful fallback if classification fails
- Comprehensive logging for debugging

### 4. Debug Page Enhancement

Updated `MollieDebugService.test_webhook_processing()` to:
- Classify payment before processing
- Show payment type in results
- Display classification confidence and method
- Provide clear indication of which processor handled it

## Files Modified

1. **Created**: `verenigingen/integrations/mollie/services/payment_type_router.py`
   - New service for payment routing logic

2. **Modified**: `verenigingen/integrations/mollie/services/webhook_wrapper_service_unified.py`
   - Added payment classification and routing (lines 269-311)
   - Maintains backward compatibility with donation processing

3. **Modified**: `verenigingen/services/mollie_debug_service.py`
   - Enhanced `test_webhook_processing()` to show payment type (lines 999-1058)

4. **Modified**: `verenigingen/templates/pages/mollie_payments_debug.py`
   - Fixed `debug_payment` response wrapping (lines 203-213)

5. **Created**: `docs/mollie/WEBHOOK_ROUTING_INTEGRATION.md`
   - This documentation

## Processing Flow

### Membership Dues Payment

```
Payment ID: tr_XXXXX (from subscription)
     ↓
Webhook Handler (unified_payment_api.py)
     ↓
UnifiedWebhookWrapperService.process_payment_webhook()
     ↓
PaymentTypeRouter.classify_payment()
     ↓ (subscription_id matches Member record)
Classification: type=DUES, confidence=HIGH
     ↓
PaymentTypeRouter.route_payment()
     ↓
DuesPaymentProcessor.process_dues_payment()
     ↓
Creates Payment Entry or Bank Transaction (based on settings)
     ↓
Returns: {status: "success", payment_type: "dues", ...}
```

### Donation Payment

```
Payment ID: tr_YYYYY (no subscription)
     ↓
Webhook Handler (unified_payment_api.py)
     ↓
UnifiedWebhookWrapperService.process_payment_webhook()
     ↓
PaymentTypeRouter.classify_payment()
     ↓ (payment_id matches Donation record)
Classification: type=DONATION, confidence=HIGH
     ↓
Continues with existing donation processor
     ↓
UnifiedIdempotencyManager checks state
     ↓
Creates Payment Entry for donation
     ↓
Returns: {status: "success", payment_type: "donation", ...}
```

## Response Format

### Successful Dues Processing

```json
{
  "payment_id": "tr_8Y85zADQFW",
  "status": "success",
  "payment_type": "dues",
  "confidence": "high",
  "matched_by": "subscription_id_member_match",
  "processor": "DuesPaymentProcessor",
  "member": "Assoc-Member-2024-01-0001",
  "payment_entry": "ACC-PAY-2025-00123",
  "amount": "25.00 EUR",
  "duration_seconds": 0.45
}
```

### Test Webhook Results (Enhanced)

```json
{
  "payment_id": "tr_8Y85zADQFW",
  "test_mode": false,
  "timestamp": "2025-10-21 12:30:00",
  "payment_type": "dues",
  "classification_confidence": "high",
  "classification_method": "subscription_id_member_match",
  "webhook_called": true,
  "status": "success",
  "message": "Webhook processed successfully for payment tr_8Y85zADQFW (type: dues)",
  "http_status": 200,
  "webhook_status": "success"
}
```

## Testing

### Via Debug Page

1. Navigate to `/mollie_payments_debug`
2. Enter a membership dues payment ID (e.g., `tr_8Y85zADQFW`)
3. Click "Test Webhook Processing"
4. Verify results show:
   - ✅ `payment_type: "dues"`
   - ✅ `classification_confidence: "high"`
   - ✅ `status: "success"`
   - ✅ Member name displayed
   - ✅ Payment Entry created

### Via Console

```python
from verenigingen.integrations.mollie.services.payment_type_router import get_payment_router

router = get_payment_router()

# Test classification
payment = router.fetch_payment("tr_8Y85zADQFW")
classification = router.classify_payment(payment)
print(classification)

# Test full routing
result = router.route_payment("tr_8Y85zADQFW")
print(result)
```

### Via API

```bash
# Test webhook endpoint directly
curl -X POST https://dev.veganisme.net/api/method/verenigingen.integrations.mollie.api.unified_payment_api.handle_payment_webhook \
  -H "Content-Type: application/json" \
  -d '{"payment_id": "tr_8Y85zADQFW"}'
```

## Backward Compatibility

✅ **Fully backward compatible**:
- Existing donation webhooks continue to work unchanged
- Classification failure gracefully falls back to donation processor
- No changes to database schema or DocTypes required
- All existing tests should pass

## Error Handling

### Unknown Payment Type

If a payment cannot be classified (no matching member or donor):

```json
{
  "payment_id": "tr_UNKNOWN",
  "status": "error",
  "processor": "none",
  "payment_type": "unknown",
  "message": "Cannot determine payment type - no matching member/donor found"
}
```

### Classification Failure

If the PaymentClassifier encounters an error:

```
⚠️ Payment classification failed for tr_XXXXX: [error details]
Falling back to donation processor
```

The system continues with the donation processor to maintain service availability.

## Performance Considerations

- **Additional API Call**: Fetches payment from Mollie for classification
- **Impact**: ~100-200ms overhead per webhook
- **Mitigation**: Payment data is reused by downstream processors
- **Benefit**: Accurate routing prevents failed processing attempts

## Future Enhancements

1. **Caching**: Cache classification results for frequently accessed payments
2. **Batch Processing**: Optimize for bulk webhook processing
3. **Analytics**: Track payment type distribution and classification accuracy
4. **Configuration**: Make routing logic configurable via Mollie Settings
5. **Unknown Type Handling**: Add admin interface for manual payment classification

## Related Documentation

- `docs/mollie/BALANCE_TRANSACTION_PROCESSING.md` - Balance transaction details
- `docs/mollie/DUES_PAYMENT_PROCESSOR.md` - Membership dues processing
- `docs/mollie/PAYMENT_CLASSIFICATION.md` - Classification strategy details
- `verenigingen/integrations/mollie/domain/payment_classification.py` - Classifier implementation

## Monitoring

### Key Metrics to Track

- Payment type distribution (dues vs donation vs unknown)
- Classification confidence levels
- Processing success rates by payment type
- Average processing time by payment type
- Fallback rate (classification failures)

### Logging

All routing decisions are logged with emoji indicators:
- 🔀 Payment routing decision
- 📊 Classification result
- 📋 Dues processor route
- 💝 Donation processor route
- ⚠️ Classification failure/fallback

## Conclusion

The webhook routing integration successfully unifies donation and membership dues payment processing through a single webhook endpoint. The architecture maintains backward compatibility while providing clear separation of concerns and comprehensive debugging capabilities.

**Status**: ✅ Ready for production use
**Testing**: Manual testing successful
**Next Steps**: Monitor webhook processing in production environment
