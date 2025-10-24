# Mollie API Response Caching - Usage Examples

**Purpose**: Practical examples of using the response caching system in production code

---

## Example 1: Dashboard Loading with Cache

**Scenario**: Loading a financial dashboard that displays balance and settlement data

### Without Caching (Original)

```python
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient

def load_financial_dashboard():
    """Load dashboard data (slow - multiple API calls every time)"""
    balances_client = BalancesClient()
    settlements_client = SettlementsClient()

    # API call 1: Get primary balance
    primary_balance = balances_client.get_primary_balance()

    # API call 2: Get all balances
    all_balances = balances_client.list_balances()

    # API call 3: Get recent settlements
    recent_settlements = settlements_client.list_settlements(limit=10)

    # API call 4: Get balance summary
    balance_summary = balances_client.get_all_balances_summary()

    return {
        "primary_balance": primary_balance,
        "all_balances": all_balances,
        "recent_settlements": recent_settlements,
        "summary": balance_summary
    }
```

**Performance**: 4 API calls × 150ms average = ~600ms

### With Caching (Optimized)

```python
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient

def load_financial_dashboard():
    """Load dashboard data (fast - cached after first load)"""
    balances_client = BalancesClient()
    settlements_client = SettlementsClient()

    # First load: 4 API calls
    # Subsequent loads within TTL: 0 API calls
    primary_balance = balances_client.get_cached(
        "balances/primary",
        cache_ttl=300  # Cache for 5 minutes
    )

    all_balances = balances_client.get_cached(
        "balances",
        params=None,
        cache_ttl=300
    )

    recent_settlements = settlements_client.get_cached(
        "settlements",
        params={"limit": 10},
        cache_ttl=180  # Cache for 3 minutes (more volatile data)
    )

    # This makes multiple API calls internally, so use shorter TTL
    balance_summary = balances_client.get_all_balances_summary()  # Uses get_cached internally

    return {
        "primary_balance": primary_balance,
        "all_balances": all_balances,
        "recent_settlements": recent_settlements,
        "summary": balance_summary
    }
```

**Performance**:
- First load: ~600ms (4 API calls)
- Cached loads: ~5ms (0 API calls, 120x faster)

---

## Example 2: Real-Time Balance Monitoring

**Scenario**: Monitoring balance for threshold alerts with appropriate cache balance

### Implementation

```python
from datetime import datetime
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient

class BalanceMonitor:
    """Monitor balance levels with smart caching"""

    def __init__(self):
        self.client = BalancesClient()
        self.alert_threshold = 1000.0  # EUR

    def check_balance_level(self, balance_id: str, real_time: bool = False):
        """
        Check if balance is below threshold

        Args:
            balance_id: Balance to monitor
            real_time: If True, bypass cache for fresh data
        """
        if real_time:
            # Critical check - bypass cache
            balance = self.client.get(f"balances/{balance_id}")
        else:
            # Routine check - use cache (30 second TTL)
            balance = self.client.get_cached(
                f"balances/{balance_id}",
                cache_ttl=30
            )

        balance_obj = self.client._parse_response(balance, Balance)
        current_amount = balance_obj.available_amount.value

        if float(current_amount) < self.alert_threshold:
            self._trigger_alert(balance_id, current_amount)
            # Invalidate cache to ensure next check gets fresh data
            self.client.invalidate_cache(f"balances/{balance_id}")

        return current_amount

    def _trigger_alert(self, balance_id: str, amount: float):
        """Trigger low balance alert"""
        import frappe
        frappe.publish_realtime(
            "balance_alert",
            {
                "message": f"Balance {balance_id} is low: EUR {amount}",
                "balance_id": balance_id,
                "amount": amount,
                "threshold": self.alert_threshold
            },
            user=frappe.session.user
        )
```

**Usage**:
```python
monitor = BalanceMonitor()

# Routine checks (use cache)
monitor.check_balance_level("bal_primary", real_time=False)  # May hit cache

# Critical alerts (bypass cache)
monitor.check_balance_level("bal_primary", real_time=True)  # Always fresh
```

---

## Example 3: Report Generation with Cache Warming

**Scenario**: Generating monthly financial reports that fetch large datasets

### Implementation

```python
from datetime import datetime, timedelta
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient

class MonthlyReportGenerator:
    """Generate monthly financial reports with cache optimization"""

    def __init__(self):
        self.balances_client = BalancesClient()
        self.settlements_client = SettlementsClient()

    def warm_cache(self, year: int, month: int):
        """
        Pre-fetch and cache data before report generation

        Call this in background job before users access reports
        """
        start_date = datetime(year, month, 1)
        end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        # Warm balance cache (1 hour TTL for reports)
        self.balances_client.get_cached(
            "balances",
            params=None,
            cache_ttl=3600
        )

        # Warm settlement cache
        self.settlements_client.get_cached(
            "settlements",
            params={
                "from": start_date.strftime("%Y-%m-%d"),
                "until": end_date.strftime("%Y-%m-%d")
            },
            cache_ttl=3600
        )

    def generate_report(self, year: int, month: int):
        """Generate monthly report (uses cached data if available)"""
        start_date = datetime(year, month, 1)
        end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        # These will hit cache if warm_cache() was called
        all_balances = self.balances_client.get_cached(
            "balances",
            params=None,
            cache_ttl=3600
        )

        settlements = self.settlements_client.get_cached(
            "settlements",
            params={
                "from": start_date.strftime("%Y-%m-%d"),
                "until": end_date.strftime("%Y-%m-%d")
            },
            cache_ttl=3600
        )

        return self._compile_report(all_balances, settlements, year, month)

    def _compile_report(self, balances, settlements, year, month):
        """Compile report data"""
        return {
            "period": f"{year}-{month:02d}",
            "balance_count": len(balances),
            "settlement_count": len(settlements),
            "generated_at": datetime.now().isoformat()
        }
```

**Usage**:
```python
# Background job (runs hourly)
def background_cache_warmer():
    generator = MonthlyReportGenerator()
    now = datetime.now()
    generator.warm_cache(now.year, now.month)

# User request (instant response from cache)
def get_monthly_report(year, month):
    generator = MonthlyReportGenerator()
    return generator.generate_report(year, month)  # Fast - cached
```

---

## Example 4: Cache Invalidation After Mutations

**Scenario**: Keeping cache fresh after creating/updating data

### Implementation

```python
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient

class SettlementManager:
    """Manage settlements with proper cache invalidation"""

    def __init__(self):
        self.client = SettlementsClient()

    def capture_settlement(self, settlement_id: str):
        """
        Capture a settlement and invalidate related caches
        """
        # Make mutation (no caching for mutations)
        settlement = self.client.capture_settlement(settlement_id)

        # Invalidate affected caches
        self.client.invalidate_cache("settlements")  # List cache
        self.client.invalidate_cache(f"settlements/{settlement_id}")  # Specific settlement

        # Note: Next read will fetch fresh data from API
        return settlement

    def get_settlement_with_cache(self, settlement_id: str):
        """Get settlement with caching"""
        return self.client.get_cached(
            f"settlements/{settlement_id}",
            cache_ttl=300  # 5 minute cache
        )

    def list_settlements_with_cache(self, limit: int = 10):
        """List settlements with caching"""
        return self.client.get_cached(
            "settlements",
            params={"limit": limit},
            cache_ttl=180  # 3 minute cache (more volatile)
        )
```

**Usage**:
```python
manager = SettlementManager()

# Read operations (use cache)
settlements = manager.list_settlements_with_cache(limit=20)
settlement = manager.get_settlement_with_cache("stl_123")

# Mutation (invalidates cache)
captured = manager.capture_settlement("stl_123")

# Next read gets fresh data (cache was invalidated)
fresh_settlement = manager.get_settlement_with_cache("stl_123")  # API call
```

---

## Example 5: Cache Statistics Monitoring

**Scenario**: Monitoring cache performance and adjusting configuration

### Implementation

```python
from verenigingen.verenigingen_payments.core.mollie_base_client import MollieBaseClient
import frappe

class CacheHealthMonitor:
    """Monitor cache health and performance"""

    def __init__(self):
        self.client = MollieBaseClient()

    def check_cache_health(self):
        """Check cache statistics and log warnings"""
        if not self.client.enable_cache:
            return {"status": "disabled"}

        stats = self.client.cache.get_stats()

        health = {
            "status": "healthy",
            "stats": stats,
            "issues": []
        }

        # Check hit rate
        if stats["hit_rate_percent"] < 50:
            health["status"] = "degraded"
            health["issues"].append(
                f"Low hit rate: {stats['hit_rate_percent']}%. "
                "Consider increasing TTL or cache size."
            )

        # Check cache utilization
        utilization = (stats["size"] / stats["max_size"]) * 100
        if utilization > 90:
            health["status"] = "degraded"
            health["issues"].append(
                f"Cache nearly full: {utilization:.1f}% utilization. "
                "Consider increasing max_size."
            )

        # Check eviction rate
        eviction_rate = (stats["evictions"] / stats["total_requests"] * 100) if stats["total_requests"] > 0 else 0
        if eviction_rate > 20:
            health["status"] = "degraded"
            health["issues"].append(
                f"High eviction rate: {eviction_rate:.1f}%. "
                "Cache size may be too small."
            )

        # Log issues
        if health["issues"]:
            frappe.logger().warning(f"Cache health issues: {health['issues']}")

        return health

    def cleanup_expired_entries(self):
        """Clean up expired cache entries"""
        removed = self.client.cleanup_expired_cache()
        if removed > 0:
            frappe.logger().info(f"Removed {removed} expired cache entries")
        return removed
```

**Usage**:
```python
# Scheduled job (runs every hour)
def hourly_cache_maintenance():
    monitor = CacheHealthMonitor()

    # Check health
    health = monitor.check_cache_health()
    if health["status"] == "degraded":
        frappe.log_error(
            f"Cache performance degraded: {health['issues']}",
            "Mollie Cache Health Alert"
        )

    # Cleanup expired entries
    monitor.cleanup_expired_entries()
```

---

## Example 6: Adaptive TTL Based on Data Volatility

**Scenario**: Using different TTL values based on how frequently data changes

### Implementation

```python
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient

class AdaptiveCacheClient:
    """Client with adaptive TTL based on data type"""

    # TTL configuration by endpoint type
    TTL_CONFIG = {
        "static": 3600,      # 1 hour - rarely changing data
        "semi_static": 600,  # 10 minutes - occasionally changing
        "dynamic": 180,      # 3 minutes - frequently changing
        "volatile": 30       # 30 seconds - very frequently changing
    }

    def __init__(self):
        self.client = BalancesClient()

    def get_organization_info(self):
        """Get organization info (static - rarely changes)"""
        return self.client.get_cached(
            "organizations/me",
            cache_ttl=self.TTL_CONFIG["static"]
        )

    def get_balance_report(self, balance_id: str, from_date: str, until_date: str):
        """Get balance report (semi-static - changes daily)"""
        return self.client.get_cached(
            f"balances/{balance_id}/report",
            params={"from": from_date, "until": until_date},
            cache_ttl=self.TTL_CONFIG["semi_static"]
        )

    def get_balance_transactions(self, balance_id: str):
        """Get balance transactions (dynamic - changes hourly)"""
        return self.client.get_cached(
            f"balances/{balance_id}/transactions",
            params={"limit": 50},
            cache_ttl=self.TTL_CONFIG["dynamic"]
        )

    def get_primary_balance(self):
        """Get primary balance (volatile - changes frequently)"""
        return self.client.get_cached(
            "balances/primary",
            cache_ttl=self.TTL_CONFIG["volatile"]
        )
```

---

## Best Practices Summary

### ✅ Do's

1. **Use longer TTL for static data**
   ```python
   # Organization info rarely changes
   client.get_cached("organizations/me", cache_ttl=3600)
   ```

2. **Use shorter TTL for volatile data**
   ```python
   # Balance changes frequently
   client.get_cached("balances/primary", cache_ttl=30)
   ```

3. **Invalidate cache after mutations**
   ```python
   client.capture_settlement(settlement_id)
   client.invalidate_cache("settlements")  # Refresh list
   ```

4. **Use force_refresh for critical operations**
   ```python
   # Financial audit requires fresh data
   balance = client.get_cached("balances/primary", force_refresh=True)
   ```

5. **Monitor cache health**
   ```python
   stats = client.cache.get_stats()
   if stats["hit_rate_percent"] < 50:
       logger.warning("Consider tuning cache configuration")
   ```

### ❌ Don'ts

1. **Don't cache mutation operations**
   ```python
   # WRONG - mutations should not be cached
   client.get_cached("settlements/stl_123/capture", ...)
   ```

2. **Don't use excessive TTL**
   ```python
   # WRONG - 24 hour TTL for frequently changing data
   client.get_cached("balances/primary", cache_ttl=86400)
   ```

3. **Don't forget to invalidate after updates**
   ```python
   # WRONG - cache becomes stale
   client.update_settlement(settlement_id)
   # Missing: client.invalidate_cache("settlements")
   ```

4. **Don't bypass cache unnecessarily**
   ```python
   # WRONG - always using force_refresh defeats the purpose
   client.get_cached("balances", force_refresh=True)  # Why use cache?
   ```

5. **Don't ignore cache statistics**
   ```python
   # WRONG - never monitoring performance
   # Missing: regular stats checks
   ```

---

## Configuration Recommendations

### Development Environment
```python
client = MollieBaseClient(
    enable_cache=True,
    cache_max_size=50,
    cache_default_ttl=60  # 1 minute - faster iteration
)
```

### Production Environment
```python
client = MollieBaseClient(
    enable_cache=True,
    cache_max_size=200,
    cache_default_ttl=300  # 5 minutes - balance freshness vs performance
)
```

### High-Traffic Production
```python
client = MollieBaseClient(
    enable_cache=True,
    cache_max_size=500,
    cache_default_ttl=600  # 10 minutes - maximize cache hits
)
```

---

## Troubleshooting

### Problem: Low Hit Rate

**Symptoms**: `hit_rate_percent` < 50%

**Possible Causes**:
1. TTL too short - data expires before being reused
2. Cache size too small - frequent evictions
3. Unique query parameters - each request has different params

**Solutions**:
```python
# Increase TTL
client.get_cached("endpoint", cache_ttl=600)  # 10 minutes instead of 5

# Increase cache size
client = MollieBaseClient(cache_max_size=500)

# Normalize query parameters
params = {"limit": 10}  # Use consistent values
```

### Problem: Stale Data

**Symptoms**: UI shows outdated information

**Possible Causes**:
1. TTL too long
2. Missing cache invalidation after mutations
3. Force refresh not used for critical operations

**Solutions**:
```python
# Reduce TTL for volatile data
client.get_cached("balances/primary", cache_ttl=30)

# Invalidate after mutations
client.update_data()
client.invalidate_cache("endpoint")

# Force refresh for critical checks
client.get_cached("endpoint", force_refresh=True)
```

### Problem: High Memory Usage

**Symptoms**: Server memory consumption increasing

**Possible Causes**:
1. Cache size too large
2. Large responses being cached
3. No periodic cleanup

**Solutions**:
```python
# Reduce cache size
client = MollieBaseClient(cache_max_size=100)

# Add periodic cleanup
def hourly_cleanup():
    client.cleanup_expired_cache()

# Avoid caching large responses
# Use direct get() instead of get_cached() for large datasets
```
