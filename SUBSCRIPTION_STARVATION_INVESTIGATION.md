# Subscription Starvation Investigation Report

## Summary
Investigation into why member "Assoc-Member-2025-07-0030" and potentially other members are not receiving invoices despite having active subscriptions, and why Zabbix monitoring shows "0 processed" subscriptions.

## Key Findings

### 1. Root Cause Analysis

**Primary Issue**: The subscription processing system appears to have multiple potential failure points:

1. **Zabbix Monitoring Issue**: The metric `frappe.subscriptions.processed_today` checks the `tabSubscription Invoice` table, but this table may not exist or may not be properly populated by the subscription processing logic.

2. **Subscription Processing Logic**: The custom `SubscriptionHandler` in `verenigingen/utils/subscription_processing.py` bypasses the standard ERPNext subscription processing to handle long-term subscriptions, but may have issues with invoice generation tracking.

3. **Scheduler Integration**: The subscription processing is scheduled daily via `hooks.py`, but there may be issues with:
   - Scheduler execution
   - Error handling in the processing logic
   - Tracking of processed subscriptions

### 2. Technical Analysis

**Subscription Processing Flow**:
```
Daily Scheduler → process_all_subscriptions() → SubscriptionHandler.process_subscription() → Invoice Generation
```

**Monitoring Flow**:
```
Zabbix Query → COUNT(DISTINCT subscription) FROM `tabSubscription Invoice` WHERE creation >= today → "0 processed" result
```

### 3. Identified Issues

#### A. Monitoring Logic Issue
The Zabbix monitoring checks `tabSubscription Invoice` table:
```sql
SELECT COUNT(DISTINCT subscription)
FROM `tabSubscription Invoice`
WHERE creation >= %s
```

However, the custom `SubscriptionHandler` may not properly update this table when creating invoices.

#### B. Invoice Tracking Issue
In `subscription_processing.py` line 247-250, invoices are added to the subscription's invoice list:
```python
self.subscription.append(
    "invoices",
    {"invoice": invoice.name, "posting_date": invoice.posting_date, "document_type": "Sales Invoice"},
)
```

But this doesn't create entries in the `tabSubscription Invoice` table that monitoring depends on.

#### C. Date Handling Issue
The custom handler directly updates subscription dates via `frappe.db.set_value()` (lines 275-284) which may bypass some ERPNext validation or tracking mechanisms.

#### D. Error Handling
The processing logic has try-catch blocks but may silently fail without proper logging or notification.

### 4. Member-Specific Investigation

For member "Assoc-Member-2025-07-0030":
- Need to verify if member exists in database
- Check if member has active subscriptions
- Verify subscription dates and billing intervals
- Check if invoices should be generated based on current dates

### 5. System-Wide Impact

**Potential Scope**:
- All members with active subscriptions may be affected
- Billing cycles may be disrupted
- Revenue tracking may be inaccurate
- Member satisfaction issues due to lack of invoices

## Recommended Action Plan

### Phase 1: Immediate Investigation (1-2 hours)
1. **Verify Member Data**: Check if member exists and has active subscriptions
2. **Test Subscription Processing**: Manually run subscription processing for the specific member
3. **Check Table Structure**: Verify `tabSubscription Invoice` table exists and has correct structure
4. **Review Scheduler Logs**: Check for recent subscription processing attempts and errors

### Phase 2: System Analysis (2-4 hours)
1. **Audit All Active Subscriptions**: Check how many subscriptions should be processed
2. **Test Custom Handler**: Verify the `SubscriptionHandler` logic works correctly
3. **Check Monitoring Accuracy**: Ensure Zabbix metrics reflect actual system state
4. **Review Error Logs**: Look for subscription-related errors in the past week

### Phase 3: Fix Implementation (4-8 hours)
1. **Fix Monitoring Logic**: Ensure proper tracking of processed subscriptions
2. **Improve Error Handling**: Add better logging and error notification
3. **Test Invoice Generation**: Verify invoices are created correctly
4. **Update Documentation**: Document the subscription processing flow

### Phase 4: Validation (1-2 hours)
1. **End-to-End Testing**: Test complete subscription workflow
2. **Monitor Metrics**: Verify Zabbix shows correct processed count
3. **Member Verification**: Confirm member receives expected invoices

## Technical Fixes Needed

### 1. Fix Monitoring Logic
Update the Zabbix monitoring to check actual invoice generation:
```python
# Instead of checking tabSubscription Invoice, check Sales Invoice directly
processed_today = frappe.db.sql("""
    SELECT COUNT(DISTINCT subscription)
    FROM `tabSales Invoice`
    WHERE subscription IS NOT NULL
    AND subscription != ''
    AND creation >= %s
""", (today_start,))[0][0] or 0
```

### 2. Improve Subscription Processing
Ensure the custom handler properly tracks processed subscriptions:
```python
# Add proper tracking to subscription processing
def _generate_invoice_directly(self):
    # ... existing code ...

    # Ensure Subscription Invoice table is updated
    subscription_invoice = frappe.new_doc("Subscription Invoice")
    subscription_invoice.subscription = self.subscription.name
    subscription_invoice.document_type = "Sales Invoice"
    subscription_invoice.insert()
```

### 3. Add Better Error Handling
Implement comprehensive error logging:
```python
def process_all_subscriptions():
    # ... existing code ...

    # Add detailed logging
    frappe.logger().info(f"Processing {len(subscriptions)} active subscriptions")

    # Track success/failure rates
    success_count = 0
    failure_count = 0

    # ... processing logic ...

    # Log summary
    frappe.logger().info(f"Subscription processing complete: {success_count} successful, {failure_count} failed")
```

## Next Steps

1. **Execute Phase 1 investigation scripts** to gather current system state
2. **Run manual subscription processing** for the specific member to test functionality
3. **Review and fix monitoring logic** to ensure accurate metrics
4. **Implement improved error handling** and logging
5. **Test end-to-end workflow** to ensure proper invoice generation
6. **Update monitoring and alerting** to prevent future issues

## Files for Investigation

### Debug Scripts Created:
- `scripts/debug/subscription_starvation_analysis.py` - Comprehensive analysis
- `scripts/debug/simple_subscription_check.py` - Basic database queries
- `scripts/debug/check_subscription_invoice_table.py` - Table structure check
- `scripts/debug/check_scheduler_status.py` - Scheduler status check

### Key System Files:
- `verenigingen/utils/subscription_processing.py` - Custom subscription handler
- `verenigingen/hooks.py` - Scheduler configuration
- `scripts/monitoring/zabbix_integration.py` - Monitoring logic
- `verenigingen/verenigingen/doctype/membership/membership.py` - Membership integration

## Risk Assessment

**High Risk**: Revenue impact if subscriptions are not processed
**Medium Risk**: Member satisfaction if invoices are missing
**Low Risk**: System stability (monitoring issue, not core functionality)

**Mitigation**: Immediate investigation and fix of subscription processing logic, with improved monitoring and alerting for future issues.
