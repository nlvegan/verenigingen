# Mollie API Pagination Patterns

**Version**: 1.0
**Date**: 2025-10-23
**Status**: Production

---

## Overview

The Verenigingen system uses **centralized pagination** in `MollieBaseClient` to handle Mollie's cursor-based pagination automatically. All client methods use the same pagination implementation for consistency and maintainability.

---

## Quick Start

### Basic Usage

```python
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient

client = SettlementsClient()

# Fetch all settlements (automatically paginated)
settlements = client.list_settlements()

# Behind the scenes:
# - Fetches up to 250 items per page (Mollie's max)
# - Automatically follows _links.next
# - Returns complete list
```

### When to Use Pagination

**Use `paginated=True` when**:
- Listing resources (settlements, payments, transactions)
- Expecting multiple items in response
- Response includes `_embedded` or `data` array

**Use `paginated=False` when**:
- Fetching a single resource by ID
- Creating/updating resources
- Response is a single object (not a list)

---

## How It Works

### Mollie's Cursor-Based Pagination

Mollie uses **cursor-based pagination** (not offset-based):

1. **First Request**:
   ```http
   GET /v2/settlements?limit=250
   ```

2. **First Response**:
   ```json
   {
     "_embedded": {
       "settlements": [... 250 items ...]
     },
     "_links": {
       "next": {
         "href": "https://api.mollie.com/v2/settlements?from=stl_abc123&limit=250"
       }
     },
     "count": 250
   }
   ```

3. **Second Request**:
   ```http
   GET /v2/settlements?from=stl_abc123&limit=250
   ```

4. **Continues until `_links.next` is null**

### MollieBaseClient Implementation

**Location**: `core/mollie_base_client.py:231-346`

```python
def _request_paginated(self, method, endpoint, params, data) -> List[Dict]:
    """
    Automatic pagination with safety limits and logging

    Features:
    - Sets limit=250 (Mollie's maximum)
    - Follows _links.next automatically
    - MAX_PAGES=100 safety limit
    - Debug/info logging for monitoring
    """
    all_items = []
    page_count = 0
    MAX_PAGES = 100

    while True:
        page_count += 1

        # Safety check
        if page_count > MAX_PAGES:
            frappe.logger().warning(...)
            break

        response, status_code = self.http_client.request(...)

        # Extract items from _embedded or data
        if "_embedded" in response:
            for key in response["_embedded"]:
                all_items.extend(response["_embedded"][key])
        elif "data" in response:
            all_items.extend(response["data"])

        # Follow next link
        if "_links" in response and "next" in response["_links"]:
            next_url = response["_links"]["next"]["href"]
            # Extract cursor parameter
            match = re.search(r"from=([^&]+)", next_url)
            if match:
                params["from"] = match.group(1)
            else:
                break
        else:
            break

    return all_items
```

---

## Usage Patterns

### Pattern 1: Simple List Retrieval

```python
# settlements_client.py
def list_settlements(self):
    """List all settlements with automatic pagination"""
    response = self.get("settlements", paginated=True)
    return [Settlement(item) for item in response]
```

**When to use**: Listing all items without filters

**Pros**:
- Simple and clean
- Automatic pagination
- No manual page management

**Cons**:
- May fetch many items (memory)
- No progress feedback

### Pattern 2: Filtered List with Parameters

```python
# payments_client.py
def list_payments(self, status=None, limit=250):
    """List payments with optional status filter"""
    params = {"limit": limit}
    if status:
        params["status"] = status

    response = self.get("/payments", params=params, paginated=True)
    return response
```

**When to use**: Listing with API-side filters

**Pros**:
- Reduces items fetched
- API does filtering (efficient)

**Cons**:
- Still fetches all matching items

### Pattern 3: Date Filtering After Pagination

```python
# balances_client.py
def list_balance_transactions(self, balance_id, from_date=None, until_date=None):
    """
    List transactions with date filtering

    Note: Mollie API doesn't support date params, so we:
    1. Fetch all transactions (paginated)
    2. Filter in memory
    """
    response = self.get(
        f"balances/{balance_id}/transactions",
        paginated=True
    )

    # Convert to model objects
    transactions = [BalanceTransaction(item) for item in response]

    # Apply memory-based date filtering
    return self._filter_by_date(transactions, from_date, until_date)
```

**When to use**: API doesn't support filter parameters

**Pros**:
- Works when API lacks filter support
- Reusable `_filter_by_date()` helper

**Cons**:
- Fetches all items then filters (inefficient)
- Memory usage for large datasets

**Memory consideration**: For balance_id with 10,000 transactions, this fetches all 10,000 before filtering.

### Pattern 4: Wrapped with Error Handling

```python
# settlements_client.py (Phase 4.1 pattern)
def get_settlements_by_date_range(self, from_date, to_date):
    """Get settlements with error handling"""

    def _fetch_and_filter():
        all_settlements = self.get("settlements", paginated=True)
        # ... date filtering ...
        return filtered_settlements

    return self.error_handler.wrap_operation(
        operation_name="get_settlements_by_date_range",
        operation_callable=_fetch_and_filter,
        error_type="settlement_processing",
        fallback_value=[],
        suppress_errors=True
    )
```

**When to use**: Operations that should fail gracefully

**Pros**:
- Consistent error handling
- Audit trail logging
- User-friendly error messages

---

## Memory Considerations

### Pagination Memory Usage

Each page fetches up to 250 items. With MAX_PAGES=100:

**Maximum items per call**: 100 pages × 250 items = 25,000 items

**Typical item size**:
- Settlement: ~2KB per item
- Payment: ~1-2KB per item
- Transaction: ~500 bytes per item

**Maximum memory per call**:
- Settlements: 25,000 × 2KB = ~50MB
- Payments: 25,000 × 1.5KB = ~37MB
- Transactions: 25,000 × 500B = ~12MB

### When to Worry About Memory

✅ **Safe** (typical usage):
- Fetching last month's transactions (~1,000 items)
- Listing settlements for the year (~365 items)
- Getting payments with status filter (~few hundred items)

⚠️ **Caution** (large datasets):
- Fetching all historical transactions (10,000+ items)
- Listing all payments without filters (thousands of items)
- Long-running accounts with years of history

🚨 **Danger** (runaway pagination):
- Hitting MAX_PAGES limit (25,000 items)
- Check logs for warning message
- Consider adding date filters or API-side filtering

### Mitigation Strategies

**1. Use API-Side Filters**:
```python
# GOOD: Filter on API side
params = {"status": "paid", "from": "2025-01-01"}
payments = self.get("/payments", params=params, paginated=True)

# BAD: Fetch everything then filter
all_payments = self.get("/payments", paginated=True)
paid_payments = [p for p in all_payments if p["status"] == "paid"]
```

**2. Limit Date Ranges**:
```python
# GOOD: Specific date range
transactions = client.list_balance_transactions(
    balance_id,
    from_date=last_month_start,
    until_date=last_month_end
)

# BAD: All history
transactions = client.list_balance_transactions(balance_id)
```

**3. Process in Batches**:
```python
# For very large datasets, process incrementally
for month in date_ranges:
    settlements = client.list_settlements(
        from_date=month.start,
        until_date=month.end
    )
    process_batch(settlements)
```

---

## Monitoring and Debugging

### Log Levels

**DEBUG**: Page-by-page progress
```
Pagination settlements: Page 1, items this page: 250, total: 250
Pagination settlements: Following next page cursor=stl_abc123
Pagination settlements: Page 2, items this page: 250, total: 500
...
```

**INFO**: Pagination completion summary
```
Pagination complete for settlements: 3 pages, 650 total items
```

**WARNING**: Safety limit reached
```
Pagination safety limit reached (100 pages) for settlements. Fetched 25000 items total.
```

### Checking Logs

```python
# In Frappe console
frappe.db.sql("""
    SELECT error, creation
    FROM `tabError Log`
    WHERE error LIKE '%Pagination%'
    ORDER BY creation DESC
    LIMIT 10
""")
```

### Performance Monitoring

Typical pagination performance:
- **1 page (250 items)**: ~500ms
- **3 pages (750 items)**: ~1.5s
- **10 pages (2,500 items)**: ~5s
- **100 pages (25,000 items)**: ~50s (hits safety limit)

If pagination is slow:
1. Check network latency to Mollie API
2. Consider reducing date range
3. Add API-side filters if available

---

## Safety Features

### 1. MAX_PAGES Limit

**Purpose**: Prevent runaway pagination consuming memory/time

**Value**: 100 pages (25,000 items max)

**Behavior**:
- Logs warning when limit reached
- Stops fetching additional pages
- Returns items fetched so far

**Override**: Not currently configurable (hardcoded for safety)

### 2. Request Timeout

**Purpose**: Prevent hanging on network issues

**Value**: 30 seconds per request (set in ResilientHTTPClient)

**Behavior**:
- Times out if single page fetch takes > 30s
- Error handler catches timeout exception
- Returns graceful error to user

### 3. Circuit Breaker

**Purpose**: Stop making requests after repeated failures

**Value**: 5 failures threshold (set in ResilientHTTPClient)

**Behavior**:
- Opens circuit after 5 consecutive failures
- Blocks further requests temporarily
- Resets after cooldown period

---

## Best Practices

### DO ✅

1. **Use `paginated=True` for list operations**:
   ```python
   settlements = self.get("settlements", paginated=True)
   ```

2. **Add API-side filters when available**:
   ```python
   payments = self.get("/payments", params={"status": "paid"}, paginated=True)
   ```

3. **Log completion for long-running operations**:
   ```python
   frappe.logger().info(f"Fetched {len(items)} items")
   ```

4. **Use date filtering to limit dataset size**:
   ```python
   transactions = client.list_balance_transactions(
       balance_id,
       from_date=start,
       until_date=end
   )
   ```

### DON'T ❌

1. **Don't manage pagination manually**:
   ```python
   # BAD: Manual pagination
   cursor = None
   while cursor:
       response = self.get(f"settlements?from={cursor}")
       cursor = response["_links"]["next"]
   ```

2. **Don't fetch everything when you need a subset**:
   ```python
   # BAD: Fetch all then filter
   all_payments = self.get("/payments", paginated=True)
   recent = [p for p in all_payments if p["createdAt"] > yesterday]

   # GOOD: Filter first
   recent = self.get("/payments", params={"from": yesterday}, paginated=True)
   ```

3. **Don't ignore safety warnings**:
   ```python
   # If you see "Pagination safety limit reached", investigate:
   # - Is the date range too broad?
   # - Can you add more filters?
   # - Do you really need all items?
   ```

---

## Troubleshooting

### Problem: "Pagination safety limit reached"

**Cause**: Query returned more than 25,000 items

**Solutions**:
1. Add date range filters to reduce dataset
2. Use API-side status/type filters
3. Process data in batches (by month/week)
4. Consider if you really need all items

### Problem: Pagination is slow

**Cause**: Large dataset or network latency

**Solutions**:
1. Reduce date range
2. Add filters to reduce items
3. Check network connection to Mollie API
4. Monitor ResilientHTTPClient performance

### Problem: Out of memory

**Cause**: Too many items fetched at once

**Solutions**:
1. Process in smaller batches
2. Stream processing instead of bulk loading
3. Add filters to reduce dataset size
4. Consider background job for large operations

---

## Examples

### Example 1: List Recent Settlements

```python
from datetime import datetime, timedelta

# Efficient: Only fetch last 30 days
thirty_days_ago = datetime.now() - timedelta(days=30)

settlements = client.list_settlements(
    from_date=thirty_days_ago,
    until_date=datetime.now()
)

print(f"Found {len(settlements)} settlements in last 30 days")
```

### Example 2: Process Large Dataset in Batches

```python
# Process yearly data in monthly batches
for month in range(1, 13):
    start = datetime(2024, month, 1)
    end = start + timedelta(days=32)  # Next month

    settlements = client.list_settlements(
        from_date=start,
        until_date=end
    )

    # Process this month's data
    process_settlements(settlements)

    print(f"Processed {len(settlements)} settlements for {start.strftime('%Y-%m')}")
```

### Example 3: Filtered Payment Listing

```python
# Fetch only paid payments (API-side filter)
paid_payments = client.list_payments(status="paid")

# Further filter by date (memory-based)
recent_paid = [
    p for p in paid_payments
    if datetime.fromisoformat(p["createdAt"]) > thirty_days_ago
]
```

---

## Future Enhancements

Potential improvements (not currently implemented):

1. **Configurable MAX_PAGES**: Allow override via config
2. **Progress Callbacks**: UI progress bars for long operations
3. **Streaming API**: Process items as they're fetched
4. **Pagination Metrics**: Export to monitoring system
5. **Adaptive Page Size**: Start with 250, reduce if slow

---

## Related Documentation

- **Error Handling**: See `PHASE_4_1_COMPLETION_SUMMARY.md`
- **Mollie API Reference**: https://docs.mollie.com/overview/pagination
- **Client Architecture**: See `PHASE_3_COMPLETION_SUMMARY.md`

---

**Last Updated**: 2025-10-23
**Maintained By**: Mollie Integration Team
