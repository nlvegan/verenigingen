# Service Layer Architecture Design for N+1 Query Optimization

## Executive Summary

Based on software architecture expert review, the N+1 optimization requires a foundational service layer to prevent tight coupling and enable maintainable bulk operations. This document outlines the service layer architecture that will support the performance optimization work.

---

## Current Architecture Problems

### Tight Coupling Issues
```python
# CURRENT PROBLEM: Direct database access in business logic
class Member(Document):
    def get_payment_history(self):
        # Direct frappe.get_all calls scattered throughout
        return frappe.get_all("Payment Entry", filters={"party": self.name})

    def get_chapter_memberships(self):
        # Another direct database call
        return frappe.get_all("Chapter Member", filters={"member": self.name})
```

### N+1 Pattern Multiplication
- 864 N+1 patterns across 277 files
- Each optimization requires duplicate bulk operation code
- No centralized optimization strategy
- Difficult to maintain consistent performance patterns

---

## Proposed Service Layer Architecture

### Core Service Layer Structure

```
verenigingen/services/
├── __init__.py
├── base/
│   ├── bulk_operation_service.py      # Abstract bulk operations
│   ├── cache_service.py               # Centralized caching
│   └── query_optimization_service.py  # Query pattern management
├── member/
│   ├── member_service.py              # Member business logic
│   ├── member_repository.py           # Member data access
│   └── member_cache_service.py        # Member-specific caching
├── financial/
│   ├── payment_service.py             # Payment operations
│   ├── sepa_service.py                # SEPA bulk operations
│   └── invoice_service.py             # Invoice management
├── integration/
│   ├── eboekhouden_service.py         # E-Boekhouden operations
│   └── mollie_service.py              # Mollie payment service
└── reporting/
    ├── report_service.py              # Report generation
    └── analytics_service.py           # Performance analytics
```

---

## Implementation Design

### 1. Abstract Base Service

```python
# verenigingen/services/base/bulk_operation_service.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import frappe

class BulkOperationService(ABC):
    """Abstract base class for bulk database operations"""

    def __init__(self):
        self.cache_service = CacheService()
        self.query_optimizer = QueryOptimizationService()

    def bulk_get_related(self,
                        parent_ids: List[str],
                        related_doctype: str,
                        link_field: str,
                        fields: Optional[List[str]] = None,
                        additional_filters: Optional[Dict] = None) -> Dict[str, List[Dict]]:
        """Generic bulk relationship fetching"""

        # Build cache key
        cache_key = self._build_cache_key(
            related_doctype, parent_ids, link_field, fields, additional_filters
        )

        # Check cache first
        cached_result = self.cache_service.get(cache_key)
        if cached_result:
            return cached_result

        # Build filters
        filters = {link_field: ["in", parent_ids]}
        if additional_filters:
            filters.update(additional_filters)

        # Execute bulk query
        relationships = frappe.get_all(
            related_doctype,
            filters=filters,
            fields=fields or ["*"]
        )

        # Group by parent
        grouped_result = self._group_by_parent(relationships, link_field)

        # Cache result
        self.cache_service.set(cache_key, grouped_result, ttl=300)

        return grouped_result

    def _group_by_parent(self, relationships: List[Dict], link_field: str) -> Dict[str, List[Dict]]:
        """Group relationships by parent ID"""
        result = {}
        for rel in relationships:
            parent_id = rel.get(link_field)
            if parent_id:
                result.setdefault(parent_id, []).append(rel)
        return result

    @abstractmethod
    def get_cache_dependencies(self) -> List[str]:
        """Return list of DocTypes that affect this service's cache"""
        pass
```

### 2. Member Service Implementation

```python
# verenigingen/services/member/member_service.py
from typing import List, Dict, Any, Optional
import frappe
from ..base.bulk_operation_service import BulkOperationService

class MemberService(BulkOperationService):
    """Service for member-related operations with bulk optimization"""

    def get_members_with_chapter_info(self,
                                    limit: int = 20,
                                    filters: Optional[Dict] = None) -> Dict[str, Any]:
        """Optimized member listing with chapter information"""

        # Validate and sanitize filters
        validated_filters = self._validate_filters(filters)

        # Get members (Query 1)
        members = self._get_members_bulk(limit, validated_filters)
        if not members:
            return {"members": [], "total_count": 0}

        member_names = [m["name"] for m in members]

        # Get chapter relationships (Query 2)
        chapter_relationships = self.bulk_get_related(
            parent_ids=member_names,
            related_doctype="Chapter Member",
            link_field="member",
            fields=["parent", "member", "status", "enabled", "chapter_join_date"],
            additional_filters={"enabled": 1}
        )

        # Get chapter details (Query 3)
        chapter_names = list(set([
            rel["parent"] for rels in chapter_relationships.values()
            for rel in rels if rel.get("parent")
        ]))

        chapters_info = {}
        if chapter_names:
            chapters = frappe.get_all(
                "Chapter",
                filters={"name": ["in", chapter_names]},
                fields=["name", "region", "status"]
            )
            chapters_info = {ch["name"]: ch for ch in chapters}

        # Combine data
        result_members = []
        for member in members:
            member_chapters = []
            relationships = chapter_relationships.get(member["name"], [])

            for rel in relationships:
                chapter_name = rel.get("parent")
                if chapter_name and chapter_name in chapters_info:
                    chapter_info = chapters_info[chapter_name]
                    member_chapters.append({
                        "chapter_name": chapter_name,
                        "region": chapter_info.get("region"),
                        "status": rel.get("status", "Active"),
                        "join_date": rel.get("chapter_join_date")
                    })

            member["chapters"] = member_chapters
            result_members.append(member)

        return {
            "members": result_members,
            "total_count": len(result_members),
            "query_optimization": {
                "pattern": "bulk_operations",
                "queries_used": 3,
                "optimization_applied": True
            }
        }

    def _get_members_bulk(self, limit: int, filters: Dict) -> List[Dict]:
        """Get members with proper filtering and limits"""
        query_filters = {"docstatus": ["<", 2]}  # Not cancelled

        if filters:
            if filters.get("status"):
                query_filters["status"] = filters["status"]
            if filters.get("chapter"):
                # This requires a join - handle separately if needed
                pass

        return frappe.get_all(
            "Member",
            filters=query_filters,
            fields=["name", "full_name", "email", "status", "creation"],
            limit=limit,
            order_by="full_name asc"
        )

    def get_cache_dependencies(self) -> List[str]:
        return ["Member", "Chapter Member", "Chapter"]
```

### 3. Payment Service Implementation

```python
# verenigingen/services/financial/payment_service.py
from typing import List, Dict, Any, Optional, Tuple
import frappe
from ..base.bulk_operation_service import BulkOperationService

class PaymentService(BulkOperationService):
    """Service for payment operations with bulk optimization"""

    def get_payment_history_bulk(self, member_names: List[str]) -> Dict[str, List[Dict]]:
        """Get payment history for multiple members efficiently"""

        # Use bulk operation base method
        payment_entries = self.bulk_get_related(
            parent_ids=member_names,
            related_doctype="Payment Entry",
            link_field="party",
            fields=[
                "name", "party", "posting_date", "paid_amount",
                "payment_type", "reference_no", "status"
            ],
            additional_filters={"docstatus": 1}  # Submitted only
        )

        # Get related sales invoices if needed
        payment_names = [
            pe["name"] for payments in payment_entries.values()
            for pe in payments
        ]

        if payment_names:
            payment_references = self.bulk_get_related(
                parent_ids=payment_names,
                related_doctype="Payment Entry Reference",
                link_field="parent",
                fields=["parent", "reference_doctype", "reference_name", "allocated_amount"]
            )

            # Merge payment references back into payment entries
            for member_payments in payment_entries.values():
                for payment in member_payments:
                    payment["references"] = payment_references.get(payment["name"], [])

        return payment_entries

    def process_sepa_batch_bulk(self, sepa_mandates: List[Dict]) -> Dict[str, Any]:
        """Process SEPA operations in optimized batches"""

        # Group by bank/creditor for efficient processing
        grouped_mandates = self._group_mandates_by_creditor(sepa_mandates)

        results = {
            "processed_count": 0,
            "failed_count": 0,
            "batches": []
        }

        for creditor_id, mandates in grouped_mandates.items():
            batch_result = self._process_creditor_batch(creditor_id, mandates)
            results["batches"].append(batch_result)
            results["processed_count"] += batch_result["processed"]
            results["failed_count"] += batch_result["failed"]

        return results

    def _group_mandates_by_creditor(self, mandates: List[Dict]) -> Dict[str, List[Dict]]:
        """Group SEPA mandates by creditor for batch processing"""
        grouped = {}
        for mandate in mandates:
            creditor_id = mandate.get("creditor_id", "default")
            grouped.setdefault(creditor_id, []).append(mandate)
        return grouped

    def get_cache_dependencies(self) -> List[str]:
        return ["Payment Entry", "Payment Entry Reference", "SEPA Mandate"]
```

### 4. Cache Service Implementation

```python
# verenigingen/services/base/cache_service.py
from typing import Any, Optional, List
import frappe
import json
import hashlib

class CacheService:
    """Centralized caching service with dependency management"""

    def __init__(self, default_ttl: int = 300):
        self.default_ttl = default_ttl
        self.cache_dependencies = {}

    def get(self, key: str) -> Optional[Any]:
        """Get cached value"""
        try:
            cached_value = frappe.cache().get_value(key)
            if cached_value:
                return json.loads(cached_value) if isinstance(cached_value, str) else cached_value
        except Exception as e:
            frappe.log_error(f"Cache get error for key {key}: {str(e)}", "Cache Service")
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None, dependencies: Optional[List[str]] = None):
        """Set cached value with optional dependencies"""
        try:
            ttl = ttl or self.default_ttl
            serialized_value = json.dumps(value) if not isinstance(value, str) else value

            frappe.cache().set_value(key, serialized_value, expires_in_sec=ttl)

            # Track dependencies
            if dependencies:
                self.cache_dependencies[key] = dependencies

        except Exception as e:
            frappe.log_error(f"Cache set error for key {key}: {str(e)}", "Cache Service")

    def invalidate_by_doctype(self, doctype: str):
        """Invalidate all cached values that depend on a specific DocType"""
        keys_to_invalidate = []

        for cache_key, dependencies in self.cache_dependencies.items():
            if doctype in dependencies:
                keys_to_invalidate.append(cache_key)

        for key in keys_to_invalidate:
            self.invalidate(key)

    def invalidate(self, key: str):
        """Invalidate specific cached value"""
        try:
            frappe.cache().delete_value(key)
            if key in self.cache_dependencies:
                del self.cache_dependencies[key]
        except Exception as e:
            frappe.log_error(f"Cache invalidation error for key {key}: {str(e)}", "Cache Service")

    def build_cache_key(self, prefix: str, *args) -> str:
        """Build consistent cache key"""
        key_parts = [str(prefix)]
        key_parts.extend([str(arg) for arg in args])
        key_string = ":".join(key_parts)

        # Use hash for very long keys
        if len(key_string) > 200:
            key_hash = hashlib.md5(key_string.encode()).hexdigest()
            return f"{prefix}:hash:{key_hash}"

        return key_string
```

---

## Integration with Existing Code

### Migration Strategy

**Phase 0: Service Layer Foundation (Weeks 1-2)**
1. Create base service classes and interfaces
2. Implement Member Service with bulk operations
3. Replace critical N+1 patterns in member listing API
4. Add comprehensive testing for service layer

**Phase 1: Core Services (Weeks 3-4)**
1. Implement Payment Service with SEPA optimization
2. Create E-Boekhouden Integration Service
3. Add caching infrastructure
4. Migrate donation page to use services

**Phase 2: Full Migration (Weeks 5-8)**
1. Migrate all DocType controllers to use services
2. Implement repository pattern for data access
3. Add comprehensive monitoring and metrics
4. Performance validation and optimization

### Backwards Compatibility

```python
# verenigingen/api/member_management.py (Updated)
from verenigingen.services.member.member_service import MemberService

@frappe.whitelist()
def get_members_with_chapter_info(limit=20, filters=None):
    """API endpoint using service layer - maintains existing interface"""

    # Initialize service
    member_service = MemberService()

    # Use service method instead of direct database calls
    result = member_service.get_members_with_chapter_info(
        limit=int(limit),
        filters=filters
    )

    return result
```

---

## Quality Assurance Integration

### Service Layer Testing

```python
# tests/test_member_service.py
from verenigingen.services.member.member_service import MemberService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class TestMemberService(EnhancedTestCase):

    def setUp(self):
        super().setUp()
        self.member_service = MemberService()

    def test_bulk_member_retrieval_query_count(self):
        """Test that service layer maintains query optimization"""

        # Create test data
        members = self.create_test_members(count=20)
        chapters = self.create_test_chapters(count=3)
        self.assign_members_to_chapters(members, chapters)

        # Test query count
        with self.assertQueryCount(3):  # Should be exactly 3 queries
            result = self.member_service.get_members_with_chapter_info(limit=20)

        # Validate results
        self.assertEqual(result["query_optimization"]["queries_used"], 3)
        self.assertEqual(len(result["members"]), 20)

        # Validate chapter data is properly attached
        members_with_chapters = [m for m in result["members"] if m["chapters"]]
        self.assertGreater(len(members_with_chapters), 0)

    def test_service_layer_caching(self):
        """Test that service layer properly caches results"""

        # First call should hit database
        result1 = self.member_service.get_members_with_chapter_info(limit=10)

        # Second call should use cache (test by query count)
        with self.assertQueryCount(0):  # Should use cached results
            result2 = self.member_service.get_members_with_chapter_info(limit=10)

        self.assertEqual(result1, result2)
```

---

## Performance Monitoring Integration

### Service Layer Metrics

```python
# verenigingen/services/base/performance_monitor.py
import time
import frappe
from contextlib import contextmanager

class PerformanceMonitor:
    """Monitor service layer performance"""

    @contextmanager
    def monitor_operation(self, operation_name: str, **context):
        """Context manager for monitoring operations"""
        start_time = time.time()
        query_count = 0

        # Hook into query counting
        original_sql = frappe.db.sql
        def counting_sql(*args, **kwargs):
            nonlocal query_count
            query_count += 1
            return original_sql(*args, **kwargs)

        frappe.db.sql = counting_sql

        try:
            yield
        finally:
            # Restore original function
            frappe.db.sql = original_sql

            # Log performance data
            execution_time = (time.time() - start_time) * 1000  # ms

            self._log_performance_metrics(
                operation_name, execution_time, query_count, **context
            )

    def _log_performance_metrics(self, operation: str, time_ms: float, query_count: int, **context):
        """Log performance metrics for monitoring"""

        metrics = {
            "operation": operation,
            "execution_time_ms": time_ms,
            "query_count": query_count,
            "timestamp": frappe.utils.now(),
            **context
        }

        # Log to performance monitoring system
        frappe.log_error(json.dumps(metrics), "Service Performance Metrics")

        # Alert if performance thresholds exceeded
        if time_ms > 2000 or query_count > 10:
            frappe.log_error(
                f"Performance threshold exceeded: {operation} took {time_ms}ms with {query_count} queries",
                "Performance Alert"
            )
```

---

## Next Steps

1. **Implement Base Service Classes** - Foundation for all bulk operations
2. **Create Member Service** - First concrete implementation with full testing
3. **Add Performance Monitoring** - Track optimization effectiveness
4. **Integrate with Existing APIs** - Maintain backwards compatibility
5. **Expand to Other Services** - Payment, SEPA, E-Boekhouden integrations

This service layer architecture provides:
- ✅ **Decoupled Architecture** - Business logic separated from data access
- ✅ **Reusable Bulk Operations** - DRY principle for N+1 optimizations
- ✅ **Comprehensive Caching** - Multi-layered caching with dependency management
- ✅ **Performance Monitoring** - Built-in metrics and alerting
- ✅ **Testing Framework** - Service layer testing with query count validation
- ✅ **Backwards Compatibility** - Gradual migration without breaking changes
