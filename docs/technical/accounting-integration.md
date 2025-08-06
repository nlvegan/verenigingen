# Donation Campaign Accounting Integration - Technical Documentation

## Architecture Overview

The Donation Campaign accounting integration enhances the existing campaign management system with sophisticated financial tracking capabilities. This implementation introduces accounting dimensions and optional project integration while maintaining backward compatibility and performance optimization.

### Design Principles

1. **Non-Breaking Changes**: All enhancements are additive, preserving existing functionality
2. **Automatic Generation**: Dimension codes auto-generate with intelligent fallbacks
3. **Performance Optimization**: Progress updates use optimized SQL queries for large datasets
4. **Inheritance Pattern**: Donations inherit accounting attributes from campaigns
5. **Optional Complexity**: Project integration is opt-in for advanced use cases

### System Components

```
Donation Campaign (Enhanced)
├── accounting_dimension_value (Auto-generated unique identifier)
├── project (Optional ERPNext Project link)
├── Enhanced Methods:
│   ├── set_accounting_dimension_value()
│   ├── create_project()
│   ├── get_project_summary()
│   └── get_accounting_entries()
└── Integration Points:
    ├── Donation DocType (inheritance)
    ├── GL Entry (dimension tagging)
    ├── Sales Invoice (dimension + project)
    └── Journal Entry (dimension tagging)
```

## Implementation Details

### Field Specifications

#### accounting_dimension_value
```json
{
  "fieldname": "accounting_dimension_value",
  "fieldtype": "Data",
  "label": "Campaign Dimension Value",
  "unique": 1,
  "length": 50,
  "translatable": 0,
  "description": "Unique code/value for this campaign when used as an accounting dimension. Leave blank to auto-generate from campaign name."
}
```

**Technical Constraints**:
- Maximum 50 characters (accounting system compatibility)
- Alphanumeric + underscore/hyphen only
- Case-insensitive uniqueness validation
- Auto-generation from campaign_name if empty

#### project
```json
{
  "fieldname": "project",
  "fieldtype": "Link",
  "label": "Campaign Project",
  "options": "Project",
  "description": "Link to a Project for tracking campaign activities, expenses, and tasks (optional)"
}
```

**Technical Constraints**:
- Optional field for advanced campaign management
- Links to standard ERPNext Project DocType
- Enables task and expense tracking integration
- Supports project-based financial reporting

### Auto-Generation Algorithm

#### Dimension Value Generation Logic

```python
def set_accounting_dimension_value(self):
    """Auto-generate accounting dimension value with intelligent fallbacks"""
    if not self.accounting_dimension_value and self.campaign_name:
        import re

        # Phase 1: Clean and normalize name
        clean_name = self.campaign_name.strip().upper().replace(' ', '_')
        dimension_value = re.sub(r'[^A-Z0-9\-_]', '', clean_name)
        dimension_value = dimension_value[:50].strip('_')

        # Phase 2: Handle numeric prefix (accounting system compatibility)
        if dimension_value and dimension_value[0].isdigit():
            dimension_value = 'CAMP_' + dimension_value[:46]

        # Phase 3: Ensure minimum viability
        if not dimension_value or len(dimension_value) < 3:
            dimension_value = f"CAMP_{frappe.generate_hash(length=8)}"

        # Phase 4: Ensure uniqueness with collision handling
        base_value = dimension_value
        counter = 1
        while frappe.db.exists("Donation Campaign", {
            "accounting_dimension_value": dimension_value,
            "name": ["!=", self.name or ""]
        }):
            suffix = f"_{counter}"
            max_base_len = 50 - len(suffix)
            dimension_value = f"{base_value[:max_base_len]}{suffix}"
            counter += 1

            # Prevent infinite loop with hash fallback
            if counter > 999:
                dimension_value = f"CAMP_{frappe.generate_hash(length=8)}"
                break
```

#### Generation Examples

| Campaign Name | Generated Dimension | Notes |
|---------------|-------------------|--------|
| "Annual Appeal 2025" | "ANNUAL_APPEAL_2025" | Standard case |
| "Spring Fundraiser & Gala!" | "SPRING_FUNDRAISER_GALA" | Special chars removed |
| "2025 Capital Campaign" | "CAMP_2025_CAPITAL_CAMPAIGN" | Numeric prefix handled |
| "AB" | "CAMP_A1B2C3D4" | Too short, hash generated |
| Duplicate name | "ORIGINAL_NAME_1" | Counter added for uniqueness |

### Progress Tracking Optimization

#### Performance-Optimized Progress Calculation

The system uses optimized SQL queries to handle large campaign datasets efficiently:

```python
def update_campaign_progress(campaign_name):
    """Optimized progress update using single SQL query"""
    summary = frappe.db.sql("""
        SELECT
            COUNT(*) as total_donations,
            SUM(amount) as total_raised,
            COUNT(DISTINCT CASE WHEN anonymous = 0 THEN donor END) as total_donors,
            AVG(amount) as average_donation_amount
        FROM `tabDonation`
        WHERE campaign = %s AND paid = 1 AND docstatus = 1
    """, campaign_name, as_dict=True)

    # Direct database update to avoid validation loops
    campaign.db_update()
```

**Performance Benefits**:
- Single SQL query replaces multiple document loads
- Optimized for campaigns with thousands of donations
- Background job processing prevents UI blocking
- Avoids recursive validation hooks

#### Background Job Integration

Progress updates are processed via background jobs to maintain system responsiveness:

```python
# Triggered by donation save/update hooks
frappe.enqueue(
    'vereinigungen.vereinigungen.doctype.donation_campaign.donation_campaign.update_campaign_progress',
    campaign_name=self.campaign,
    queue='short'
)
```

### Project Integration

#### Project Creation Method

```python
@frappe.whitelist()
def create_project(self, project_name=None):
    """Create ERPNext Project with validation and error handling"""
    if self.project:
        frappe.throw(_("Campaign already has a project linked"))

    # Auto-generate project name
    if not project_name:
        project_name = f"Campaign: {self.campaign_name}"

    # Validate uniqueness
    if frappe.db.exists("Project", {"project_name": project_name}):
        frappe.throw(_("Project with name '{0}' already exists").format(project_name))

    # Validate prerequisites
    if not self.start_date:
        frappe.throw(_("Campaign must have a start date before creating a project"))

    try:
        # Create project with campaign attributes
        project = frappe.get_doc({
            "doctype": "Project",
            "project_name": project_name,
            "expected_start_date": self.start_date,
            "expected_end_date": self.end_date,
            "project_type": "External",
            "status": "Open"
        })

        # Link back to campaign if custom field exists
        if hasattr(project, 'custom_donation_campaign'):
            project.custom_donation_campaign = self.name

        project.insert()

        # Update campaign with project link
        self.project = project.name
        self.save()

        return project

    except Exception as e:
        frappe.log_error(f"Failed to create project for campaign {self.name}: {str(e)}")
        frappe.throw(_("Failed to create project. Please check if Project DocType is properly configured."))
```

#### Project Summary Analytics

```python
@frappe.whitelist()
def get_project_summary(self):
    """Comprehensive project analytics with performance optimization"""
    if not self.project:
        return None

    project = frappe.get_doc("Project", self.project)

    # Optimized task query
    tasks = frappe.get_all(
        "Task",
        filters={"project": self.project},
        fields=["name", "subject", "status", "progress"],
    )

    # Optimized expense query
    expenses = frappe.get_all(
        "Expense Claim",
        filters={"project": self.project, "docstatus": 1},
        fields=["name", "total_claimed_amount", "posting_date"],
    )

    return {
        "project": project,
        "tasks": tasks,
        "expenses": expenses,
        "total_expenses": sum(e.total_claimed_amount or 0 for e in expenses),
        "task_completion": (
            sum(1 for t in tasks if t.status == "Completed") / len(tasks) * 100
        ) if tasks else 0
    }
```

## Integration Points

### Donation Inheritance Pattern

#### Dimension Inheritance Implementation

```python
# In Donation DocType
def get_campaign_accounting_dimension(self):
    """Get accounting dimension value from linked campaign"""
    if self.campaign:
        return frappe.db.get_value("Donation Campaign", self.campaign, "accounting_dimension_value")
    return None

def get_campaign_project(self):
    """Get project from linked campaign"""
    if self.campaign:
        return frappe.db.get_value("Donation Campaign", self.campaign, "project")
    return None
```

#### Sales Invoice Integration

```python
# Enhanced sales invoice creation with campaign attributes
def create_sales_invoice(self):
    """Create sales invoice with campaign dimension and project inheritance"""
    sales_invoice = frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": self.get_customer(),
        "posting_date": self.donation_date,
        "due_date": self.donation_date,
        # ... other fields
    })

    # Inherit campaign attributes
    campaign_dimension = self.get_campaign_accounting_dimension()
    campaign_project = self.get_campaign_project()

    if campaign_dimension:
        sales_invoice.custom_campaign_dimension = campaign_dimension

    if campaign_project:
        sales_invoice.project = campaign_project

    # Add donation item
    sales_invoice.append("items", {
        "item_code": self.get_donation_item_code(),
        "qty": 1,
        "rate": self.amount,
        "amount": self.amount,
    })

    sales_invoice.insert()
    sales_invoice.submit()

    return sales_invoice
```

#### Journal Entry Integration

```python
# Enhanced journal entry with dimension tagging
def create_journal_entry(self):
    """Create journal entry with campaign dimension inheritance"""
    je = frappe.get_doc({
        "doctype": "Journal Entry",
        "voucher_type": "Journal Entry",
        "posting_date": self.donation_date,
        "company": frappe.defaults.get_defaults().company,
    })

    # Add campaign dimension and project if available
    campaign_dimension = self.get_campaign_accounting_dimension()
    campaign_project = self.get_campaign_project()

    if campaign_dimension:
        je.custom_campaign_dimension = campaign_dimension

    if campaign_project:
        je.project = campaign_project

    # Add accounting entries
    je.append("accounts", {
        "account": self.get_donation_income_account(),
        "credit_in_account_currency": self.amount,
        "cost_center": self.cost_center,
    })

    je.append("accounts", {
        "account": self.get_receivable_account(),
        "debit_in_account_currency": self.amount,
        "party_type": "Customer",
        "party": self.get_customer(),
    })

    return je
```

### Financial Reporting Integration

#### Consolidated Accounting View

```python
def get_accounting_entries(self, from_date=None, to_date=None):
    """Get comprehensive financial view of campaign"""
    filters = {}

    # Multi-dimensional filtering
    if self.accounting_dimension_value:
        filters["custom_campaign_dimension"] = self.accounting_dimension_value

    if self.project:
        filters["project"] = self.project

    if from_date and to_date:
        filters["posting_date"] = ["between", [from_date, to_date]]

    # Get GL entries with dimension/project filtering
    gl_entries = frappe.get_all(
        "GL Entry",
        filters=filters,
        fields=["account", "debit", "credit", "posting_date", "voucher_type", "voucher_no"],
        order_by="posting_date desc"
    )

    # Get campaign donations for income verification
    donation_filters = {"campaign": self.name, "docstatus": 1, "paid": 1}
    if from_date and to_date:
        donation_filters["donation_date"] = ["between", [from_date, to_date]]

    donations = frappe.get_all(
        "Donation",
        filters=donation_filters,
        fields=["name", "amount", "donation_date", "donor"],
        order_by="donation_date desc"
    )

    return {
        "gl_entries": gl_entries,
        "donations": donations,
        "total_income": sum(d.amount for d in donations),
        "total_expenses": sum(gl.debit for gl in gl_entries if gl.debit),
        "net_funds": sum(d.amount for d in donations) - sum(gl.debit for gl in gl_entries if gl.debit)
    }
```

## Database Schema Changes

### New Fields Added to Donation Campaign

```sql
-- Accounting Integration Section
ALTER TABLE `tabDonation Campaign`
ADD COLUMN `accounting_dimension_value` VARCHAR(50) UNIQUE,
ADD COLUMN `project` VARCHAR(140);

-- Indexes for performance
CREATE INDEX idx_campaign_dimension
ON `tabDonation Campaign`(accounting_dimension_value);

CREATE INDEX idx_campaign_project
ON `tabDonation Campaign`(project);
```

### Custom Fields for Integration

```sql
-- Custom field on GL Entry for campaign dimension tracking
-- (Created via Custom Field DocType)
INSERT INTO `tabCustom Field` VALUES (
    'GL Entry-custom_campaign_dimension',
    'GL Entry',
    'custom_campaign_dimension',
    'Data',
    'Campaign Dimension',
    50,
    0,
    -- ... additional field properties
);

-- Custom field on Sales Invoice for campaign dimension
INSERT INTO `tabCustom Field` VALUES (
    'Sales Invoice-custom_campaign_dimension',
    'Sales Invoice',
    'custom_campaign_dimension',
    'Data',
    'Campaign Dimension',
    50,
    0,
    -- ... additional field properties
);
```

## Error Handling and Validation

### Validation Rules

1. **Dimension Uniqueness**:
   ```python
   # Enforced at database level with unique constraint
   # Additional validation in Python for user feedback
   if frappe.db.exists("Donation Campaign", {
       "accounting_dimension_value": self.accounting_dimension_value,
       "name": ["!=", self.name or ""]
   }):
       frappe.throw(_("Campaign dimension value must be unique"))
   ```

2. **Project Integration Prerequisites**:
   ```python
   def validate_project_creation(self):
       if not self.start_date:
           frappe.throw(_("Campaign must have a start date before creating a project"))

       if self.project and not frappe.db.exists("Project", self.project):
           frappe.throw(_("Linked project does not exist"))
   ```

3. **Data Integrity Checks**:
   ```python
   def validate_accounting_integration(self):
       # Ensure dimension value follows naming conventions
       if self.accounting_dimension_value:
           import re
           if not re.match(r'^[A-Z0-9_-]+$', self.accounting_dimension_value):
               frappe.throw(_("Dimension value must contain only uppercase letters, numbers, underscores, and hyphens"))
   ```

### Error Recovery Mechanisms

1. **Automatic Fallbacks**:
   - Hash-based dimension generation if name cleaning fails
   - Graceful degradation if project creation fails
   - Continue campaign operation without project if ERPNext Projects unavailable

2. **Logging and Monitoring**:
   ```python
   try:
       project = self.create_project()
   except Exception as e:
       frappe.log_error(
           f"Failed to create project for campaign {self.name}: {str(e)}",
           "Donation Campaign Project Creation"
       )
       # Continue without project - don't block campaign creation
   ```

3. **Data Consistency Checks**:
   ```python
   @frappe.whitelist()
   def validate_data_consistency(self):
       """Validate campaign data integrity"""
       issues = []

       # Check dimension uniqueness
       duplicates = frappe.db.sql("""
           SELECT accounting_dimension_value, COUNT(*)
           FROM `tabDonation Campaign`
           WHERE accounting_dimension_value IS NOT NULL
           GROUP BY accounting_dimension_value
           HAVING COUNT(*) > 1
       """)

       if duplicates:
           issues.append(f"Duplicate dimension values found: {duplicates}")

       # Check orphaned project links
       orphaned_projects = frappe.db.sql("""
           SELECT dc.name, dc.project
           FROM `tabDonation Campaign` dc
           LEFT JOIN `tabProject` p ON dc.project = p.name
           WHERE dc.project IS NOT NULL AND p.name IS NULL
       """)

       if orphaned_projects:
           issues.append(f"Orphaned project links: {orphaned_projects}")

       return issues
   ```

## Performance Optimization

### Query Optimization Strategies

1. **Progress Update Optimization**:
   ```python
   # Single aggregation query instead of loading all donations
   def get_campaign_metrics(campaign_name):
       return frappe.db.sql("""
           SELECT
               COUNT(*) as total_donations,
               SUM(amount) as total_raised,
               COUNT(DISTINCT CASE WHEN anonymous = 0 THEN donor END) as total_donors,
               AVG(amount) as average_donation_amount,
               MIN(amount) as min_donation,
               MAX(amount) as max_donation
           FROM `tabDonation`
           WHERE campaign = %(campaign)s
               AND paid = 1
               AND docstatus = 1
       """, {"campaign": campaign_name}, as_dict=True)[0]
   ```

2. **Background Processing**:
   ```python
   # Enqueue heavy operations to prevent UI blocking
   def on_update_after_submit(self):
       if self.campaign:
           frappe.enqueue(
               'update_campaign_progress',
               campaign_name=self.campaign,
               queue='short',
               timeout=300
           )
   ```

3. **Caching Strategy**:
   ```python
   @frappe.cache.cache_manager.cache('campaign_summary')
   def get_cached_campaign_summary(campaign_name):
       """Cache expensive campaign calculations"""
       return get_campaign_accounting_entries(campaign_name)
   ```

### Memory Management

1. **Large Dataset Handling**:
   ```python
   def process_large_campaign_data(campaign_name, batch_size=1000):
       """Process large campaigns in batches"""
       offset = 0
       while True:
           donations = frappe.db.sql("""
               SELECT name, amount, donor, donation_date
               FROM `tabDonation`
               WHERE campaign = %(campaign)s
               LIMIT %(limit)s OFFSET %(offset)s
           """, {
               "campaign": campaign_name,
               "limit": batch_size,
               "offset": offset
           }, as_dict=True)

           if not donations:
               break

           # Process batch
           process_donation_batch(donations)
           offset += batch_size
   ```

2. **Resource Cleanup**:
   ```python
   def cleanup_campaign_cache(campaign_name):
       """Clear cached data when campaign is updated"""
       cache_keys = [
           f"campaign_summary_{campaign_name}",
           f"campaign_metrics_{campaign_name}",
           f"campaign_donors_{campaign_name}"
       ]

       for key in cache_keys:
           frappe.cache.delete_key(key)
   ```

## Security Considerations

### Access Control

1. **Permission Validation**:
   ```python
   @frappe.whitelist()
   def create_project(self, project_name=None):
       """Ensure user has permission to create projects"""
       if not frappe.has_permission("Project", "create"):
           frappe.throw(_("You don't have permission to create projects"))

       if not frappe.has_permission("Donation Campaign", "write", doc=self):
           frappe.throw(_("You don't have permission to modify this campaign"))
   ```

2. **Data Sanitization**:
   ```python
   def sanitize_dimension_value(self, dimension_value):
       """Sanitize dimension value to prevent injection"""
       import re
       # Only allow alphanumeric, underscore, and hyphen
       return re.sub(r'[^A-Z0-9_-]', '', dimension_value.upper())
   ```

3. **Audit Trail**:
   ```python
   def log_accounting_change(self, old_dimension, new_dimension):
       """Log dimension changes for audit purposes"""
       frappe.get_doc({
           "doctype": "Version",
           "ref_doctype": "Donation Campaign",
           "docname": self.name,
           "data": frappe.as_json({
               "changed_fields": {
                   "accounting_dimension_value": {
                       "old_value": old_dimension,
                       "new_value": new_dimension
                   }
               }
           })
       }).insert(ignore_permissions=True)
   ```

### Data Privacy

1. **Anonymous Donation Handling**:
   ```python
   def get_anonymized_donor_list(self):
       """Return donor list respecting anonymity settings"""
       donors = frappe.db.sql("""
           SELECT
               CASE
                   WHEN d.anonymous = 1 THEN 'Anonymous Donor'
                   ELSE dn.donor_name
               END as display_name,
               SUM(d.amount) as total_amount
           FROM `tabDonation` d
           LEFT JOIN `tabDonor` dn ON d.donor = dn.name
           WHERE d.campaign = %(campaign)s
               AND d.paid = 1
               AND d.docstatus = 1
           GROUP BY d.donor, d.anonymous
       """, {"campaign": self.name}, as_dict=True)

       return donors
   ```

## Testing Framework

### Unit Test Coverage

```python
import unittest
import frappe
from frappe.utils import getdate

class TestDonationCampaignAccounting(unittest.TestCase):
    def setUp(self):
        self.campaign = self.create_test_campaign()

    def test_dimension_auto_generation(self):
        """Test automatic dimension value generation"""
        campaign = frappe.new_doc("Donation Campaign")
        campaign.campaign_name = "Test Campaign 2025"
        campaign.campaign_type = "Project Funding"
        campaign.start_date = getdate()
        campaign.insert()

        self.assertEqual(campaign.accounting_dimension_value, "TEST_CAMPAIGN_2025")

    def test_dimension_uniqueness(self):
        """Test dimension uniqueness enforcement"""
        # Create second campaign with same name pattern
        campaign2 = frappe.new_doc("Donation Campaign")
        campaign2.campaign_name = "Test Campaign 2025"  # Same as first
        campaign2.campaign_type = "Project Funding"
        campaign2.start_date = getdate()
        campaign2.insert()

        self.assertEqual(campaign2.accounting_dimension_value, "TEST_CAMPAIGN_2025_1")

    def test_project_creation(self):
        """Test project creation functionality"""
        project = self.campaign.create_project()

        self.assertIsNotNone(project)
        self.assertEqual(project.project_name, f"Campaign: {self.campaign.campaign_name}")
        self.assertEqual(self.campaign.project, project.name)

    def test_donation_inheritance(self):
        """Test donation inherits campaign attributes"""
        donation = frappe.new_doc("Donation")
        donation.campaign = self.campaign.name
        donation.donor = self.create_test_donor()
        donation.amount = 100
        donation.donation_date = getdate()
        donation.insert()

        dimension = donation.get_campaign_accounting_dimension()
        self.assertEqual(dimension, self.campaign.accounting_dimension_value)

    def test_progress_calculation(self):
        """Test campaign progress tracking"""
        # Create test donations
        self.create_test_donations()

        # Update progress
        self.campaign.update_progress()

        self.assertEqual(self.campaign.total_donations, 3)
        self.assertEqual(self.campaign.total_raised, 300)
        self.assertEqual(self.campaign.average_donation_amount, 100)
```

### Integration Test Suite

```python
class TestCampaignIntegration(unittest.TestCase):
    def test_full_donation_workflow(self):
        """Test complete donation workflow with campaign integration"""
        # Create campaign with project
        campaign = self.create_test_campaign()
        project = campaign.create_project()

        # Create and process donation
        donation = self.create_test_donation(campaign)
        sales_invoice = donation.create_sales_invoice()

        # Verify integration
        self.assertEqual(sales_invoice.custom_campaign_dimension, campaign.accounting_dimension_value)
        self.assertEqual(sales_invoice.project, project.name)

        # Verify GL entries
        gl_entries = campaign.get_accounting_entries()
        self.assertGreater(len(gl_entries['gl_entries']), 0)

    def test_performance_large_campaign(self):
        """Test performance with large number of donations"""
        import time

        campaign = self.create_test_campaign()

        # Create many donations
        start_time = time.time()
        self.create_bulk_donations(campaign, count=1000)
        creation_time = time.time() - start_time

        # Test progress update performance
        start_time = time.time()
        campaign.update_progress()
        update_time = time.time() - start_time

        # Performance assertions
        self.assertLess(creation_time, 30)  # Should complete in 30 seconds
        self.assertLess(update_time, 5)     # Progress update should be fast
```

## Migration Guide

### Upgrading Existing Systems

1. **Pre-Migration Checks**:
   ```python
   def pre_migration_validation():
       """Validate system state before migration"""
       # Check for existing campaigns without dimensions
       campaigns_needing_update = frappe.db.sql("""
           SELECT name, campaign_name
           FROM `tabDonation Campaign`
           WHERE accounting_dimension_value IS NULL
               OR accounting_dimension_value = ''
       """, as_dict=True)

       return len(campaigns_needing_update)
   ```

2. **Migration Script**:
   ```python
   def migrate_campaigns_to_accounting_integration():
       """Migrate existing campaigns to new accounting integration"""
       campaigns = frappe.get_all(
           "Donation Campaign",
           filters={"accounting_dimension_value": ["is", "not set"]},
           fields=["name"]
       )

       for campaign_data in campaigns:
           campaign = frappe.get_doc("Donation Campaign", campaign_data.name)
           campaign.set_accounting_dimension_value()
           campaign.db_update()

           frappe.db.commit()
   ```

3. **Post-Migration Validation**:
   ```python
   def post_migration_validation():
       """Validate migration completion"""
       issues = []

       # Check all campaigns have dimensions
       missing_dimensions = frappe.db.count(
           "Donation Campaign",
           {"accounting_dimension_value": ["is", "not set"]}
       )

       if missing_dimensions > 0:
           issues.append(f"{missing_dimensions} campaigns missing dimension values")

       # Check for duplicate dimensions
       duplicates = frappe.db.sql("""
           SELECT accounting_dimension_value, COUNT(*)
           FROM `tabDonation Campaign`
           WHERE accounting_dimension_value IS NOT NULL
           GROUP BY accounting_dimension_value
           HAVING COUNT(*) > 1
       """)

       if duplicates:
           issues.append(f"Duplicate dimensions found: {len(duplicates)}")

       return issues
   ```

### Rollback Procedures

```python
def rollback_accounting_integration():
    """Rollback accounting integration if needed"""
    # Remove custom fields
    custom_fields = [
        "GL Entry-custom_campaign_dimension",
        "Sales Invoice-custom_campaign_dimension",
        "Journal Entry-custom_campaign_dimension"
    ]

    for field_name in custom_fields:
        if frappe.db.exists("Custom Field", field_name):
            frappe.delete_doc("Custom Field", field_name)

    # Clear dimension values (optional - preserves data)
    # frappe.db.sql("UPDATE `tabDonation Campaign` SET accounting_dimension_value = NULL, project = NULL")

    frappe.db.commit()
```

## API Reference

### Public Methods

#### DonationCampaign.set_accounting_dimension_value()
Auto-generates unique accounting dimension value from campaign name.

**Returns**: `None` (sets `self.accounting_dimension_value`)

**Side Effects**:
- Updates `accounting_dimension_value` field
- Ensures uniqueness across all campaigns
- Follows accounting system naming conventions

#### DonationCampaign.create_project(project_name=None)
Creates linked ERPNext Project for campaign management.

**Parameters**:
- `project_name` (str, optional): Custom project name, defaults to "Campaign: {campaign_name}"

**Returns**: `Project` document

**Raises**:
- `frappe.ValidationError`: If campaign already has project or validation fails
- `frappe.PermissionError`: If user lacks project creation permission

#### DonationCampaign.get_project_summary()
Returns comprehensive project analytics and status.

**Returns**: `dict` with keys:
- `project`: Project document
- `tasks`: List of project tasks with status
- `expenses`: List of expense claims
- `total_expenses`: Sum of all expenses
- `task_completion`: Completion percentage

#### DonationCampaign.get_accounting_entries(from_date=None, to_date=None)
Returns consolidated financial view of campaign.

**Parameters**:
- `from_date` (date, optional): Start date filter
- `to_date` (date, optional): End date filter

**Returns**: `dict` with keys:
- `gl_entries`: General ledger entries
- `donations`: Campaign donations
- `total_income`: Sum of donation amounts
- `total_expenses`: Sum of expense amounts
- `net_funds`: Net campaign funds (income - expenses)

### Utility Functions

#### update_campaign_progress(campaign_name)
Background job function for updating campaign progress metrics.

**Parameters**:
- `campaign_name` (str): Name of campaign to update

**Usage**: Called automatically by donation hooks, or manually via:
```python
frappe.enqueue('update_campaign_progress', campaign_name='Campaign Name')
```

## Configuration Options

### System Settings

Add to Vereinigingen Settings for campaign configuration:

```python
# Default campaign settings
default_campaign_type = "Annual Giving"
auto_create_projects = False
dimension_prefix = "CAMP_"
enable_background_updates = True
max_dimension_length = 50
```

### Custom Field Configuration

For organizations requiring additional integration fields:

```python
# Custom field for campaign categories
{
    "doctype": "Custom Field",
    "dt": "Donation Campaign",
    "fieldname": "custom_campaign_category",
    "fieldtype": "Link",
    "options": "Campaign Category",
    "label": "Campaign Category",
    "insert_after": "campaign_type"
}

# Custom field for budget tracking
{
    "doctype": "Custom Field",
    "dt": "Donation Campaign",
    "fieldname": "custom_budget_amount",
    "fieldtype": "Currency",
    "label": "Campaign Budget",
    "insert_after": "monetary_goal"
}
```

## Conclusion

The Donation Campaign accounting integration provides a robust, scalable foundation for comprehensive fundraising management. The implementation balances feature richness with performance optimization, ensuring the system can handle both simple campaigns and complex multi-project initiatives.

Key technical achievements:
- **Zero-downtime migration** path for existing installations
- **Performance optimization** for large-scale campaigns
- **Flexible architecture** supporting simple and complex use cases
- **Comprehensive error handling** and data validation
- **Full audit trail** and security compliance
- **Extensive test coverage** ensuring reliability

This implementation serves as a foundation for future enhancements while maintaining backward compatibility and operational stability.

## Related Documentation

- [User Guide](/docs/features/donation-campaigns.md)
- [API Documentation](/docs/API_DOCUMENTATION.md)
- [System Administration](/docs/ADMIN_GUIDE.md)
- [ERPNext Project Integration](https://frappeframework.com/docs/user/en/projects)
- [Frappe Framework DocTypes](https://frappeframework.com/docs/user/en/api/document)
