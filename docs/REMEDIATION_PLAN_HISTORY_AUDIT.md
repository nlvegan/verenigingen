# Remediation Plan: Member & Volunteer History Management Audit

**Date:** 2026-01-17
**Audit Source:** External Code Audit
**Status:** IMPLEMENTED

## Implementation Summary

| Item | Status | Notes |
|------|--------|-------|
| P0.1 (Cleanup Audit DocType) | SKIPPED | User determined unnecessary |
| P0.2 (Error codes & monitoring) | COMPLETED | Added to OperationResult, error_codes.py created |
| P1.3 (Donor-member mapping) | COMPLETED | donor_member_reconciliation.py created |
| P1.4 (DB indexes) | COMPLETED | Patch created for composite indexes |
| P2.5 (Caching) | COMPLETED | Request-level caching added to query builder |
| P2.6 (Configurable grace period) | SKIPPED | User determined low-value |
| P2.7 (Tests) | COMPLETED | test_history_audit_improvements.py created |
| P2.8 (Remove dead code) | COMPLETED | Volunteer expense methods deprecated |

---

---

## Executive Summary

This plan addresses findings from the code audit of the member & volunteer history management code. The audit identified strengths in architecture (service/util separation, OperationResult pattern, batching, defensive coding) but raised concerns around:

1. **Risky auto-cleanup behavior** - Automated deletion without sufficient undo path
2. **Fragile data mappings** - Donor→member by email, volunteer↔employee lookups
3. **Hard-coded grace periods** - 7-day grace period not configurable
4. **Broad exception handling** - May obscure root causes
5. **UNION SQL maintenance** - Schema changes could break queries
6. **Dead/archived code** - Volunteer expense handling still present

---

## P0: Critical Priority (Address First)

### 1. Make Cleanup Safe & Auditable

**Current State:**
- `HistoryIntegrityManager` removes child table rows automatically
- `cleanup_child_table_broken_links()` in `history_manager_utils.py` removes rows when broken links detected
- Audit log created via `_create_audit_log()` as Comment, but only shows first 5 entries
- No backup/quarantine of deleted data
- No undo capability

**Risk:** Unintended data loss if cleanup misfires

**Remediation Tasks:**

#### 1.1 Create History Cleanup Audit DocType
```
File: verenigingen/member_history_management/doctype/history_cleanup_audit/
Purpose: Store full details of all cleanup operations for reversibility
Fields:
  - member/volunteer (Link)
  - cleanup_type (Select: payment_history, fee_history, volunteer_expenses, assignment_history)
  - removed_entries (JSON) - Full serialized data of removed rows
  - removal_reason (Text)
  - cleanup_timestamp (Datetime)
  - performed_by (Link: User)
  - can_restore (Check) - Whether restore is possible
  - restored (Check) - Whether data was restored
  - restored_by (Link: User)
  - restored_timestamp (Datetime)
```

#### 1.2 Add Soft-Delete/Quarantine Mode
```python
# In history_manager_utils.py
def cleanup_child_table_broken_links(
    doc: Any,
    child_table_name: str,
    remove_broken_rows: bool = True,
    quarantine_mode: bool = True,  # NEW: Default to quarantine instead of delete
) -> HistoryOperationResult:
```

#### 1.3 Make auto_cleanup Opt-In via Site Config
```python
# In site_config.json or Verenigingen Settings DocType
{
    "history_cleanup": {
        "auto_cleanup_enabled": false,  # Default OFF
        "require_admin_approval": true,
        "quarantine_before_delete": true,
        "quarantine_retention_days": 30
    }
}
```

#### 1.4 Add Restore Capability
```python
# New function in member_history_integrity.py
def restore_cleanup_entries(audit_record_name: str) -> OperationResult[Dict[str, Any]]:
    """Restore previously cleaned up entries from audit record."""
```

**Files to Modify:**
- `verenigingen/utils/member_history_integrity.py`
- `verenigingen/utils/history_manager_utils.py`
- Create new DocType: `History Cleanup Audit`
- Create new util: `verenigingen/utils/history_cleanup_restore.py`

**Estimated Effort:** 2-3 days

---

### 2. Full Trace Capture & Monitoring for OperationResult.fail()

**Current State:**
- `MemberHistoryUpdateService` catches exceptions and converts to `OperationResult.fail()`
- Error messages truncated (line 1273: `str(e)[:100]`)
- Logging via `self.logger.error()` but no structured error codes
- No alerting integration

**Risk:** Root cause analysis difficult when errors occur

**Remediation Tasks:**

#### 2.1 Add Error Codes to OperationResult
```python
# In operation_result.py - extend OperationResult class
class OperationResult:
    error_code: Optional[str] = None  # e.g., "HIST_001", "CLEANUP_ERR_002"

    @classmethod
    def fail(cls, message: str, error_code: str = None, **metadata):
        result = cls(success=False, message=message, **metadata)
        result.error_code = error_code
        return result
```

#### 2.2 Create Error Code Registry
```python
# New file: verenigingen/utils/error_codes.py
HISTORY_ERROR_CODES = {
    "HIST_001": "Donation history sync failed",
    "HIST_002": "Payment reference prefetch failed",
    "HIST_003": "Dues payment history update failed",
    "HIST_004": "Invoice payment history update failed",
    "HIST_005": "Volunteer expense history update failed",
    "HIST_006": "Fee change history refresh failed",
    "CLEANUP_001": "Permission denied for cleanup",
    "CLEANUP_002": "Broken link cleanup failed",
    "CLEANUP_003": "Duplicate detection conflict - manual review required",
}
```

#### 2.3 Integrate with frappe.log_error() for Full Tracebacks
```python
# In member_history_update_service.py, replace:
except Exception as e:
    self.logger.error(f"Error updating donation history for {member_doc.name}: {str(e)}")

# With:
except Exception as e:
    full_traceback = frappe.get_traceback()
    self.logger.error(f"Error updating donation history for {member_doc.name}: {str(e)}")
    frappe.log_error(
        title=f"HIST_001: Donation history sync failed for {member_doc.name}",
        message=full_traceback
    )
    results["donations"]["error_code"] = "HIST_001"
```

#### 2.4 Add Monitoring Hook for Alert Integration
```python
# New file: verenigingen/utils/error_monitoring.py
def report_operation_failure(
    operation_result: OperationResult,
    context: Dict[str, Any]
) -> None:
    """Hook for external monitoring integration (Sentry, etc.)"""
    if not operation_result.success and operation_result.error_code:
        # This can be extended to push to Sentry/Datadog/etc.
        frappe.publish_realtime(
            event="history_operation_failed",
            message={
                "error_code": operation_result.error_code,
                "message": operation_result.message,
                "context": context
            }
        )
```

**Files to Modify:**
- `verenigingen/utils/operation_result.py`
- `verenigingen/services/member/history/member_history_update_service.py`
- Create: `verenigingen/utils/error_codes.py`
- Create: `verenigingen/utils/error_monitoring.py`

**Estimated Effort:** 1-2 days

---

## P1: Medium Priority

### 3. Harden Donor & Volunteer Mapping

**Current State:**
```python
# In member_history_update_service.py line 164:
donor_name = frappe.db.get_value("Donor", {"donor_email": member_doc.email}, "name")
```
- Single lookup by email - fails silently on duplicates
- No logging when multiple donors match
- Volunteer→employee mapping has similar fragility

**Risk:** Incorrect donation/expense attribution

**Remediation Tasks:**

#### 3.1 Add Explicit Donor-Member Link Field
```
# On Member DocType - add field:
donor (Link: Donor) - Explicit link to canonical donor record

# On Donor DocType - add field:
member (Link: Member) - Backlink to member if applicable
```

#### 3.2 Create Mapping Reconciliation Utility
```python
# New file: verenigingen/utils/donor_member_reconciliation.py

def get_donor_for_member(member_doc) -> Optional[str]:
    """
    Get canonical donor for a member with proper handling of duplicates.

    Priority:
    1. Explicit donor field on member (if set)
    2. Single donor matching by email
    3. Log warning and return None if multiple matches
    """
    # Check explicit link first
    if member_doc.donor:
        if frappe.db.exists("Donor", member_doc.donor):
            return member_doc.donor
        else:
            frappe.logger().warning(
                f"Member {member_doc.name} has invalid donor link: {member_doc.donor}"
            )

    # Fallback to email lookup with duplicate detection
    donors = frappe.get_all(
        "Donor",
        filters={"donor_email": member_doc.email},
        fields=["name", "creation"],
        order_by="creation desc"
    )

    if len(donors) == 0:
        return None
    elif len(donors) == 1:
        return donors[0].name
    else:
        # Multiple donors - log warning and return most recent
        frappe.logger().warning(
            f"Multiple donors ({len(donors)}) found for member {member_doc.name} "
            f"with email {member_doc.email}. Using most recent: {donors[0].name}. "
            f"Consider reconciling: {[d.name for d in donors]}"
        )
        # Track for admin review
        _log_mapping_ambiguity("Donor", member_doc.name, member_doc.email, donors)
        return donors[0].name

def _log_mapping_ambiguity(mapping_type: str, member: str, email: str, matches: list):
    """Log ambiguous mappings for admin review."""
    frappe.log_error(
        title=f"Ambiguous {mapping_type} mapping for {member}",
        message=f"Email: {email}\nMatches: {[m.name for m in matches]}"
    )
```

#### 3.3 Update MemberHistoryUpdateService to Use New Utility
```python
# Replace line 164-169 with:
from verenigingen.utils.donor_member_reconciliation import get_donor_for_member

donor_name = get_donor_for_member(member_doc)
if donor_name:
    # ... existing sync logic
```

#### 3.4 Similar Fix for Volunteer-Employee Mapping
```python
# In _build_expense_entries_batched and _build_lightweight_expense_entry
# Add similar reconciliation logic for employee_id → Volunteer mapping
```

**Files to Modify:**
- `verenigingen/services/member/history/member_history_update_service.py`
- Create: `verenigingen/utils/donor_member_reconciliation.py`
- Member DocType JSON (add donor field)
- Donor DocType JSON (add member field)

**Estimated Effort:** 2 days

---

### 4. Add DB Indexes for Volunteer Assignment Lookups

**Current State:**
- UNION queries rely on default indexes
- `ARCHITECTURE.md` recommends indexes but they're not enforced
- Performance may degrade at scale

**Recommended Indexes (from audit):**
```sql
CREATE INDEX idx_board_member_volunteer ON `tabChapter Board Member`(volunteer, is_active);
CREATE INDEX idx_team_member_volunteer ON `tabTeam Member`(volunteer, status);
CREATE INDEX idx_activity_volunteer ON `tabVolunteer Activity`(volunteer, status);
```

**Remediation Tasks:**

#### 4.1 Create Database Migration Patch
```python
# New file: verenigingen/patches/v1_0/add_volunteer_assignment_indexes.py

import frappe

def execute():
    """Add indexes for volunteer assignment queries."""

    indexes = [
        {
            "table": "tabChapter Board Member",
            "name": "idx_board_member_volunteer",
            "columns": ["volunteer", "is_active"]
        },
        {
            "table": "tabTeam Member",
            "name": "idx_team_member_volunteer",
            "columns": ["volunteer", "status"]
        },
        {
            "table": "tabVolunteer Activity",
            "name": "idx_activity_volunteer",
            "columns": ["volunteer", "status"]
        }
    ]

    for idx in indexes:
        try:
            # Check if index exists
            existing = frappe.db.sql(f"""
                SHOW INDEX FROM `{idx['table']}` WHERE Key_name = %s
            """, idx['name'])

            if not existing:
                columns = ", ".join(f"`{c}`" for c in idx['columns'])
                frappe.db.sql(f"""
                    CREATE INDEX `{idx['name']}` ON `{idx['table']}` ({columns})
                """)
                frappe.logger().info(f"Created index {idx['name']} on {idx['table']}")
        except Exception as e:
            frappe.logger().error(f"Failed to create index {idx['name']}: {str(e)}")
```

#### 4.2 Add to patches.txt
```
verenigingen.patches.v1_0.add_volunteer_assignment_indexes
```

#### 4.3 Add Index Verification to CI
```yaml
# In .github/workflows/tests.yml or similar
- name: Verify required indexes exist
  run: |
    cd ~/frappe-bench
    bench --site test_site execute verenigingen.utils.db_health.verify_required_indexes
```

**Files to Create/Modify:**
- Create: `verenigingen/patches/v1_0/add_volunteer_assignment_indexes.py`
- Modify: `verenigingen/patches.txt`
- Create: `verenigingen/utils/db_health.py` (index verification utility)

**Estimated Effort:** 0.5 days

---

## P2: Lower Priority (Valuable Improvements)

### 5. Add Short-Term Cache for get_aggregated_assignments()

**Current State:**
- No caching for dashboard queries
- UNION query runs on every request

**Remediation Tasks:**

#### 5.1 Add Request-Level Cache
```python
# In assignment_query_builder.py

def get_all_active_assignments(self) -> List[Dict]:
    """Get all active assignments with request-level caching."""
    cache_key = f"volunteer_assignments_{self.volunteer_name}"

    # Check request cache first
    if hasattr(frappe.local, 'volunteer_assignment_cache'):
        cached = frappe.local.volunteer_assignment_cache.get(cache_key)
        if cached is not None:
            return cached

    # Execute query
    assignments_data = frappe.db.sql(...)
    result = self._format_assignments(assignments_data)

    # Store in request cache
    if not hasattr(frappe.local, 'volunteer_assignment_cache'):
        frappe.local.volunteer_assignment_cache = {}
    frappe.local.volunteer_assignment_cache[cache_key] = result

    return result
```

#### 5.2 Add Redis-Based Cache with TTL (Optional Enhancement)
```python
# For dashboard pages with high traffic
@frappe.whitelist()
def get_volunteer_assignments_cached(volunteer_name: str) -> List[Dict]:
    """Get assignments with 5-minute Redis cache."""
    cache_key = f"volunteer_asgn:{volunteer_name}"

    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    service = VolunteerAssignmentService(volunteer_name)
    result = service.get_aggregated_assignments()

    frappe.cache().set_value(cache_key, result, expires_in_sec=300)
    return result
```

#### 5.3 Add Cache Invalidation on Assignment Changes
```python
# In chapter_board_member.py, team_member.py, volunteer_activity.py hooks
def invalidate_volunteer_assignment_cache(volunteer_name: str):
    """Clear cache when assignments change."""
    cache_key = f"volunteer_asgn:{volunteer_name}"
    frappe.cache().delete_value(cache_key)
```

**Estimated Effort:** 1 day

---

### 6. Make Grace Period & Cleanup Policy Configurable

**Current State:**
- Hard-coded 7-day grace period in `_is_within_grace_period()` (line 434)
- No site-level configuration

**Remediation Tasks:**

#### 6.1 Add to Verenigingen Settings DocType
```
# Fields to add:
history_cleanup_grace_days (Int, default: 7)
history_cleanup_enabled (Check, default: 0)
history_cleanup_require_confirmation (Check, default: 1)
```

#### 6.2 Update HistoryIntegrityManager to Read Config
```python
def _is_within_grace_period(self, entry, date_field: str, grace_days: int = None) -> bool:
    """Check if entry is recent enough to skip cleanup."""
    if grace_days is None:
        # Read from site config
        grace_days = frappe.db.get_single_value(
            "Verenigingen Settings",
            "history_cleanup_grace_days"
        ) or 7

    # ... existing logic
```

**Estimated Effort:** 0.5 days

---

### 7. Enhance Test Coverage

**Current State:**
- Manual testing documented for duplicate fixes
- No automated query-count assertions
- No concurrency tests

**Remediation Tasks:**

#### 7.1 Add Query Count Tests
```python
# tests/test_assignment_query_performance.py

def test_get_all_active_assignments_single_query():
    """Verify aggregation uses single UNION query."""
    volunteer = create_test_volunteer()

    with assert_query_count(max_queries=1):
        builder = AssignmentQueryBuilder(volunteer.name)
        builder.get_all_active_assignments()
```

#### 7.2 Add Concurrency Tests
```python
# tests/test_history_concurrency.py

def test_concurrent_history_updates_no_duplicates():
    """Verify concurrent updates don't create duplicates."""
    volunteer = create_test_volunteer()

    # Simulate concurrent updates
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(
                AssignmentHistoryManager.add_assignment_history,
                volunteer.name, "Board Position", "Chapter", "CH-001", "Chair", "2024-01-01"
            )
            for _ in range(5)
        ]

    # Wait for all
    [f.result() for f in futures]

    # Verify only one entry
    volunteer.reload()
    matching = [h for h in volunteer.assignment_history
                if h.reference_name == "CH-001" and h.role == "Chair"]
    assert len(matching) == 1, f"Expected 1 entry, got {len(matching)}"
```

#### 7.3 Add Cleanup Dry-Run Tests
```python
# tests/test_history_cleanup.py

def test_cleanup_dry_run_mode():
    """Verify dry-run doesn't delete data."""
    member = create_test_member_with_broken_history()
    original_count = len(member.payment_history)

    manager = HistoryIntegrityManager(member)
    result = manager.cleanup_payment_history(dry_run=True)

    assert result["would_remove"] > 0
    member.reload()
    assert len(member.payment_history) == original_count  # No actual deletion
```

**Estimated Effort:** 2 days

---

### 8. Remove/Deprecate Archived Volunteer Expense Code

**Current State:**
- `_update_volunteer_expense_history()` returns 0 immediately if child table doesn't exist
- Code kept for "backward compatibility" but is dead code

**Remediation Tasks:**

#### 8.1 Add Deprecation Warning
```python
def _update_volunteer_expense_history(self, member_doc: "Document") -> int:
    """
    DEPRECATED: Volunteer expense history feature has been archived.
    This method is retained for backward compatibility but performs no operations.
    Scheduled for removal in v2.0.
    """
    import warnings
    warnings.warn(
        "_update_volunteer_expense_history is deprecated and will be removed in v2.0",
        DeprecationWarning,
        stacklevel=2
    )

    if not hasattr(member_doc, "volunteer_expenses"):
        return 0
    # ... rest of code
```

#### 8.2 Track Removal in CHANGELOG
```markdown
# CHANGELOG.md
## [Unreleased]
### Deprecated
- `MemberHistoryUpdateService._update_volunteer_expense_history()` - volunteer expense
  tracking has been archived. Method retained for compatibility but scheduled for
  removal in v2.0.
```

**Estimated Effort:** 0.5 days

---

## Implementation Order

| Phase | Items | Est. Effort | Dependencies |
|-------|-------|-------------|--------------|
| 1 | P0.1 (Cleanup Audit DocType) | 1 day | None |
| 1 | P0.2 (Error Codes & Monitoring) | 1 day | None |
| 2 | P0.1 cont (Soft-delete, Restore) | 2 days | P0.1 |
| 2 | P1.3 (Donor Mapping) | 2 days | None |
| 3 | P1.4 (DB Indexes) | 0.5 days | None |
| 3 | P2.6 (Configurable Grace Period) | 0.5 days | None |
| 4 | P2.5 (Caching) | 1 day | None |
| 4 | P2.7 (Tests) | 2 days | All above |
| 4 | P2.8 (Deprecate Expense Code) | 0.5 days | None |

**Total Estimated Effort:** 10-12 days

---

## Success Criteria

1. **Cleanup Safety:**
   - All cleanup operations create audit records with full data backup
   - Restore capability tested and documented
   - auto_cleanup disabled by default

2. **Error Visibility:**
   - All OperationResult.fail() calls include error codes
   - Full tracebacks logged to Error Log
   - Dashboard/alert for repeated failures

3. **Data Mapping:**
   - Zero silent failures in donor→member mapping
   - Ambiguous mappings logged for admin review
   - Explicit link fields added to DocTypes

4. **Performance:**
   - Required indexes present and verified in CI
   - Query count tests passing
   - Caching implemented for high-traffic endpoints

5. **Test Coverage:**
   - Concurrency tests for history operations
   - Dry-run mode tests for cleanup
   - Query performance assertions

---

## Review & Approval

- [ ] Technical review by lead developer
- [ ] Security review for cleanup/restore functionality
- [ ] Testing plan approved
- [ ] Documentation updated

**Prepared by:** Claude Code
**Review requested from:** Development Team Lead
