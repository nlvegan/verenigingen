# API Optimization Quick Win Guide

## Current Status

- **Total API Endpoints**: 338
- **Optimized Endpoints**: 0
- **Optimization Coverage**: 0%
- **Potential Performance Gain**: 50-90% response time reduction

## Quick Win Optimizations

### Phase 1: High-Impact Endpoints (Week 1)

These endpoints handle the most traffic and would benefit most from optimization:

#### 1. Payment Dashboard (`payment_dashboard.py`)
- `get_dashboard_data()` - Heavy queries, no caching
- `get_payment_history()` - Complex JOINs
- `get_payment_schedule()` - Calculations

**Optimizations needed**:
```python
@cache_with_ttl(ttl=300)  # 5 min cache
@handle_api_errors
@monitor_performance
@frappe.whitelist()
def get_dashboard_data(**kwargs):
    # Add pagination
    limit = int(kwargs.get('limit', 100))
    offset = int(kwargs.get('offset', 0))
```

#### 2. Chapter Dashboard (`chapter_dashboard_api.py`)
- `get_chapter_member_emails()` - Currently 5 min cache, increase to 30 min
- `get_chapter_analytics()` - No caching

#### 3. SEPA Batch UI (`sepa_batch_ui.py`)
- `load_unpaid_invoices()` - N+1 query problem
- `get_batch_analytics()` - Heavy aggregations

#### 4. Member Management (`member_management.py`)
- `get_members_without_chapter()` - Full table scan
- `search_members()` - No pagination

### Implementation Steps

#### Step 1: Add Required Imports

```python
from verenigingen.utils.error_handling import cache_with_ttl, handle_api_errors, validate_request
from verenigingen.utils.performance_monitoring import monitor_performance
from verenigingen.utils.batch_processor import BatchProcessor
```

#### Step 2: Apply Decorators

For **GET/List endpoints**:
```python
@cache_with_ttl(ttl=300)  # 5-30 minutes depending on data volatility
@handle_api_errors
@monitor_performance
@frappe.whitelist()
def get_something():
    pass
```

For **Create/Update endpoints**:
```python
@validate_request
@handle_api_errors
@monitor_performance
@frappe.whitelist()
def create_something():
    pass
```

#### Step 3: Add Pagination

```python
def get_list(**kwargs):
    # Pagination parameters
    limit = int(kwargs.get('limit', 100))
    offset = int(kwargs.get('offset', 0))

    # Apply limits
    if limit > 1000:
        limit = 1000

    # Query with pagination
    data = frappe.get_all(
        "DocType",
        filters=filters,
        limit=limit,
        start=offset,
        order_by="creation desc"
    )

    # Return with metadata
    return {
        "data": data,
        "total": frappe.db.count("DocType", filters),
        "limit": limit,
        "offset": offset
    }
```

#### Step 4: Optimize Queries

Replace multiple queries with JOINs:
```python
# Before (N+1 problem)
members = frappe.get_all("Member")
for member in members:
    member["chapter"] = frappe.get_value("Chapter Member", {"member": member.name}, "chapter")

# After (Single query)
members = frappe.db.sql("""
    SELECT m.*, cm.chapter
    FROM `tabMember` m
    LEFT JOIN `tabChapter Member` cm ON cm.member = m.name
""", as_dict=True)
```

### Cache TTL Guidelines

| Data Type | Suggested TTL | Example |
|-----------|--------------|---------|
| Dashboard data | 5-15 minutes | `@cache_with_ttl(ttl=300)` |
| User lists | 5-10 minutes | `@cache_with_ttl(ttl=600)` |
| Reports | 15-60 minutes | `@cache_with_ttl(ttl=1800)` |
| Static data | 1-24 hours | `@cache_with_ttl(ttl=3600)` |
| Real-time data | No cache | Don't add decorator |

### Testing Optimizations

#### 1. Performance Test
```bash
# Before optimization
time curl https://site.com/api/method/endpoint

# After optimization (should be 5-10x faster on second call)
time curl https://site.com/api/method/endpoint
time curl https://site.com/api/method/endpoint  # Cached
```

#### 2. Load Test
```python
import concurrent.futures
import requests

def test_endpoint():
    return requests.get("https://site.com/api/method/endpoint")

# Test with 50 concurrent users
with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
    futures = [executor.submit(test_endpoint) for _ in range(100)]
    results = [f.result() for f in futures]
```

#### 3. Cache Verification
Check Redis for cached values:
```python
frappe.cache().get_value("cache_key")
```

### Monitoring After Optimization

1. **Performance Dashboard** (`/performance_dashboard`)
   - Response time trends
   - Slow query identification
   - Error rates

2. **Cache Hit Rates**
   ```python
   # Add to your monitoring
   cache_hits = frappe.cache().hget("stats", "hits")
   cache_misses = frappe.cache().hget("stats", "misses")
   hit_rate = cache_hits / (cache_hits + cache_misses) * 100
   ```

3. **Database Load**
   - Monitor query count reduction
   - Check for N+1 query elimination

### Common Pitfalls to Avoid

1. **Over-caching**: Don't cache user-specific or frequently changing data
2. **Cache invalidation**: Remember to clear cache when data changes
3. **Large cache values**: Don't cache huge datasets (>1MB)
4. **Missing error handling**: Always include @handle_api_errors

### Expected Results

After implementing these quick wins:

- **Response times**: 50-90% reduction for cached endpoints
- **Database load**: 60-80% reduction in queries
- **User experience**: Noticeably faster page loads
- **Error handling**: Consistent error responses
- **Monitoring**: Automatic performance tracking

### Rollout Plan

1. **Day 1-2**: Optimize top 5 dashboard endpoints
2. **Day 3-4**: Add pagination to all list endpoints
3. **Day 5**: Optimize search and filter endpoints
4. **Week 2**: Apply to remaining CRUD operations
5. **Week 3**: Monitor and adjust cache TTLs

### Scripts Available

1. **Preview optimizations**: `python scripts/optimization/preview_optimizations.py`
2. **Apply to single file**: `python scripts/optimization/optimize_payment_dashboard.py`
3. **Bulk optimizer**: `python scripts/optimization/quick_win_optimizer.py`
4. **Analysis tool**: `python scripts/optimization/analyze_api_optimization_status.py`

### Success Metrics

Track these KPIs after optimization:
- Average response time < 200ms
- Cache hit rate > 80%
- Database queries per request < 5
- Error rate < 0.1%
- User satisfaction score improvement

## Next Steps

1. Review this guide with the team
2. Start with payment dashboard optimization
3. Test thoroughly in staging
4. Deploy to production
5. Monitor improvements
6. Apply to all 338 endpoints systematically

The optimization framework is excellent and ready to use - it just needs to be applied!
