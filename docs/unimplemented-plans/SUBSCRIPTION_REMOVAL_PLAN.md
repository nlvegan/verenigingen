# SUBSCRIPTION SYSTEM COMPLETE REMOVAL PLAN

## Executive Summary
This plan outlines the complete removal of the legacy subscription system from the Verenigingen app. Since we're in active development, we will **completely remove** all subscription-related code rather than maintaining backwards compatibility.

## Current Inventory (as of latest scan)

### File Counts
- **Python files with subscription references**: 83
- **JavaScript files with subscription references**: 90
- **JSON files with subscription references**: 16
- **Markdown files with subscription references**: 149
- **Files with "subscription" in filename**: 24

### DocType Specific Counts (high priority)
- **Python files in doctypes**: 154 references
- **JSON files in doctypes**: 20 references

## PHASE D: COMPLETE SUBSCRIPTION SYSTEM REMOVAL

### 1. FILES TO DELETE COMPLETELY (HIGH PRIORITY)

#### 1.1 Direct Subscription Files
```bash
# Delete these files entirely:
rm archived_unused/member_subscription_history/member_subscription_history.py
rm archived_unused/member_subscription_history/member_subscription_history.json
rm archived_unused/member_subscription_history/__pycache__/member_subscription_history.cpython-312.pyc

rm scripts/debug/simple_subscription_check.py
rm scripts/debug/check_subscription_invoice_table.py
rm scripts/debug/test_subscription_metrics.py
rm scripts/api_maintenance/fix_subscription.py
rm verenigingen/patches/fix_subscription_date_update.py

rm verenigingen/tests/backend/components/test_fee_override_subscription.py
rm verenigingen/fixtures/subscription_plan.json
rm verenigingen/utils/__pycache__/subscription_diagnostics.cpython-312.pyc
rm verenigingen/utils/__pycache__/subscription_processing.cpython-312.pyc
```

#### 1.2 Subscription Report (Convert to Dues Schedule)
```bash
# Transform orphaned_subscriptions_report to dues_schedule_report
# Then delete original subscription references
mv verenigingen/verenigingen/report/orphaned_subscriptions_report \
   verenigingen/verenigingen/report/orphaned_dues_schedules_report
```

### 2. DOCTYPE JSON CLEANUP (HIGH PRIORITY)

#### 2.1 Member DocType (`member.json`)
Remove these sections/fields:
```json
"subscription_section"
"current_subscription_summary_section"
"current_subscription_summary"
"subscription_history_section"
```

#### 2.2 Contribution Amendment Request (`contribution_amendment_request.json`)
Remove these fields:
```json
"old_subscription_cancelled"
```

#### 2.3 Verenigingen Settings (`verenigingen_settings.json`)
Remove these fields:
```json
"enable_subscription_system"
```

### 3. PYTHON CODE CLEANUP (HIGH PRIORITY)

#### 3.1 Member.py - Remove Functions Completely
Delete these functions entirely:
```python
def refresh_subscription_history(self)
def update_active_subscriptions(self)
def get_subscription_status(self)
def get_current_subscription(self)
def create_subscription_plan(self)
def cancel_active_subscriptions(self)
```

#### 3.2 Membership Type - Remove Legacy Fields
Remove legacy handling for:
```python
# Remove these property handlers:
if hasattr(self, 'subscription_period')
if hasattr(self, 'subscription_period_in_months')
```

#### 3.3 Member.js - Remove Client-Side Functions
Delete these JavaScript functions:
```javascript
refresh_subscription_history()
update_subscription_status()
show_subscription_details()
```

### 4. IMPORTS AND REFERENCES CLEANUP (MEDIUM PRIORITY)

#### 4.1 Remove Subscription Imports
Scan and remove imports like:
```python
from erpnext.accounts.doctype.subscription.subscription import *
from verenigingen.utils.subscription_processing import *
```

#### 4.2 Update Database Queries
Replace references to subscription tables:
```python
# Change from:
frappe.db.get_all("Subscription", ...)

# To:
frappe.db.get_all("Membership Dues Schedule", ...)
```

### 5. DOCUMENTATION CLEANUP (MEDIUM PRIORITY)

#### 5.1 Remove Subscription Documentation
Clean up these files (149 markdown files with references):
```bash
# Remove subscription sections from:
docs/features/membership-management.md
docs/ADMIN_GUIDE.md
docs/api/subscription-endpoints.md
docs/troubleshooting/subscription-issues.md
```

#### 5.2 Update Configuration Examples
Remove subscription examples from:
- Installation guides
- Configuration templates
- API documentation
- Troubleshooting guides

### 6. BUSINESS LOGIC REIMPLEMENTATION (HIGH PRIORITY)

#### 6.1 Fee Override Logic
Reimplement in `Membership Dues Schedule`:
```python
def validate_fee_override(self):
    """Validate fee override requires both amount and reason"""
    if self.custom_amount and not self.custom_amount_reason:
        frappe.throw("Custom amount requires a reason")

    # Set audit fields
    if self.custom_amount:
        self.custom_amount_approved_by = frappe.session.user
        self.custom_amount_approved_date = frappe.utils.nowdate()
```

#### 6.2 Period Calculation Logic
Reimplement in `Membership Dues Schedule`:
```python
def calculate_next_period_dates(self):
    """Calculate next billing period dates"""
    if self.billing_frequency == "Monthly":
        self.next_due_date = add_months(self.effective_date, 1)
    elif self.billing_frequency == "Annual":
        self.next_due_date = add_months(self.effective_date, 12)
```

#### 6.3 Monitoring and Metrics
Reimplement in `zabbix_integration.py`:
```python
def get_dues_schedule_metrics():
    """Get comprehensive dues schedule metrics"""
    return {
        "active_schedules": frappe.db.count("Membership Dues Schedule", {"status": "Active"}),
        "pending_schedules": frappe.db.count("Membership Dues Schedule", {"status": "Pending"}),
        "overdue_schedules": get_overdue_schedules_count(),
        "revenue_this_month": get_monthly_revenue(),
        "processing_errors": get_processing_errors_count()
    }
```

### 7. DATABASE MIGRATION (MEDIUM PRIORITY)

#### 7.1 Create Migration Script
```python
# Create: verenigingen/patches/remove_subscription_system.py
def execute():
    """Remove subscription system fields and data"""

    # Remove subscription fields from Member DocType
    remove_subscription_fields()

    # Remove subscription history child table
    if frappe.db.table_exists("tabMember Subscription History"):
        frappe.db.sql("DROP TABLE `tabMember Subscription History`")

    # Remove subscription settings
    remove_subscription_settings()

    # Update field references
    update_field_references()
```

#### 7.2 Data Migration
```python
# Migrate any critical data to dues schedule system
def migrate_subscription_data_to_dues_schedule():
    """Migrate essential subscription data to dues schedule system"""

    # Migrate active subscriptions to dues schedules
    active_subscriptions = frappe.get_all("Subscription",
        filters={"status": "Active"},
        fields=["name", "party", "plans", "start_date"])

    for subscription in active_subscriptions:
        create_dues_schedule_from_subscription(subscription)
```

### 8. TESTING AND VALIDATION (HIGH PRIORITY)

#### 8.1 Create New Test Suite
```python
# Create: verenigingen/tests/test_dues_schedule_system.py
class TestDuesScheduleSystem(unittest.TestCase):

    def test_fee_override_validation(self):
        """Test fee override validation logic"""

    def test_period_calculation(self):
        """Test billing period calculations"""

    def test_dues_schedule_creation(self):
        """Test dues schedule creation from membership"""

    def test_invoice_generation(self):
        """Test invoice generation from dues schedule"""
```

#### 8.2 Validation Scripts
```python
# Create: scripts/validation/validate_subscription_removal.py
def validate_no_subscription_references():
    """Validate no subscription references remain"""

    # Check for subscription imports
    # Check for subscription table references
    # Check for subscription function calls
    # Report any remaining references
```

### 9. HOOKS AND CONFIGURATION CLEANUP (MEDIUM PRIORITY)

#### 9.1 Update hooks.py
Remove subscription-related hooks:
```python
# Remove these scheduled tasks:
"verenigingen.utils.subscription_processing.process_all_subscriptions"
"verenigingen.utils.subscription_processing.update_subscription_status"

# Remove these document events:
"Subscription": {
    "after_insert": "verenigingen.utils.subscription_processing.handle_new_subscription"
}
```

#### 9.2 Update Configuration Templates
Remove subscription configuration from:
- Installation scripts
- Configuration examples
- Environment templates

### 10. EXECUTION PHASES

#### Phase 1: Critical Code Removal (Week 1)
- Delete subscription files
- Remove subscription functions from Member and related DocTypes
- Update DocType JSON files
- Create basic dues schedule reimplementations

#### Phase 2: Reference Cleanup (Week 2)
- Remove all subscription imports
- Update database queries
- Clean up JavaScript references
- Update hooks and configuration

#### Phase 3: Documentation and Testing (Week 3)
- Clean up documentation
- Create comprehensive test suite
- Validate removal completeness
- Create migration scripts

#### Phase 4: Business Logic Reimplementation (Week 4)
- Implement fee override system in dues schedule
- Create monitoring and metrics
- Build diagnostic tools
- Performance optimization

## Success Criteria

✅ **Zero subscription references** in active code
✅ **All business logic** reimplemented in dues schedule system
✅ **Complete test coverage** for new system
✅ **Documentation** reflects only dues schedule system
✅ **No broken functionality** after removal

## Risk Mitigation

- **Full backup** before starting removal
- **Staged deployment** with rollback capability
- **Comprehensive testing** at each phase
- **Validation scripts** to verify completeness
- **Documentation** of migration process

## Commands for Validation

```bash
# Monitor progress with these commands:
find . -name "*.py" -exec grep -l "subscription" {} \; | wc -l
find . -name "*.js" -exec grep -l "subscription" {} \; | wc -l
find . -name "*.json" -exec grep -l "subscription" {} \; | wc -l

# Validate specific areas:
grep -R "subscription" ./verenigingen/verenigingen/doctype/ --include="*.py" | wc -l
grep -R "subscription" ./verenigingen/verenigingen/doctype/ --include="*.json" | wc -l

# Check for remaining subscription files:
find . -name "*subscription*" -type f | grep -v node_modules
```

## Next Steps

1. **Start with Phase 1** - Delete subscription files and functions
2. **Run validation commands** after each major change
3. **Test thoroughly** before proceeding to next phase
4. **Document any issues** encountered during removal
5. **Update this plan** as needed based on discoveries

This plan ensures complete removal of the subscription system while preserving all valuable business logic in the new dues schedule system.
