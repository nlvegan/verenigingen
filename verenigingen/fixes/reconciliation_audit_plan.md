# Reconciliation and Audit Features Implementation Plan

## Current Issues
- No way to verify import completeness
- Difficult to track what was imported when
- No reconciliation with e-boekhouden
- Limited audit trail

## Implementation Strategy

### Step 1: Import Audit Trail

1. **E-Boekhouden Import Log DocType**
   ```
   Fields:
   - migration_id (Link to E-Boekhouden Migration)
   - source_mutation_id (Data) - E-boekhouden ID
   - erpnext_document_type (Link to DocType)
   - erpnext_document_name (Dynamic Link)
   - import_timestamp (Datetime)
   - import_status (Select: Success/Failed/Skipped)
   - original_data (JSON) - Full e-boekhouden record
   - transformation_log (JSON) - What was changed during import
   - validation_errors (Text)
   - reconciliation_status (Select: Matched/Discrepancy/Not Checked)
   - last_reconciliation_date (Datetime)
   ```

2. **Comprehensive Logging**
   ```python
   def log_import_transaction(mutation, result, migration_id):
       """Create detailed audit log for each import"""
       log = frappe.new_doc("E-Boekhouden Import Log")

       log.migration_id = migration_id
       log.source_mutation_id = mutation.get('id') or mutation.get('MutatieNr')
       log.original_data = json.dumps(mutation, default=str)

       if result.get('success'):
           log.import_status = 'Success'
           log.erpnext_document_type = result['doctype']
           log.erpnext_document_name = result['docname']
           log.transformation_log = json.dumps({
               'account_mapping': result.get('account_mapping'),
               'party_creation': result.get('party_creation'),
               'tax_calculation': result.get('tax_calculation')
           })
       else:
           log.import_status = 'Failed'
           log.validation_errors = result.get('error')

       log.import_timestamp = now()
       log.insert(ignore_permissions=True)
   ```

### Step 2: Reconciliation Framework

1. **Reconciliation Runner**
   ```python
   def run_reconciliation(company, date_from, date_to):
       """Compare ERPNext data with e-boekhouden"""
       reconciliation = frappe.new_doc("E-Boekhouden Reconciliation")
       reconciliation.company = company
       reconciliation.date_from = date_from
       reconciliation.date_to = date_to

       # Fetch data from both systems
       ebh_data = fetch_eboekhouden_summary(date_from, date_to)
       erp_data = fetch_erpnext_summary(company, date_from, date_to)

       # Compare totals
       discrepancies = []

       # By document type
       for doc_type in ['Sales Invoice', 'Purchase Invoice', 'Journal Entry']:
           ebh_total = ebh_data.get(doc_type, {}).get('total', 0)
           erp_total = erp_data.get(doc_type, {}).get('total', 0)

           if abs(ebh_total - erp_total) > 0.01:
               discrepancies.append({
                   'type': doc_type,
                   'eboekhouden_total': ebh_total,
                   'erpnext_total': erp_total,
                   'difference': ebh_total - erp_total
               })

       # By account
       account_differences = reconcile_by_account(ebh_data, erp_data)

       reconciliation.discrepancies = json.dumps(discrepancies)
       reconciliation.account_differences = json.dumps(account_differences)
       reconciliation.reconciliation_status = 'Completed'
       reconciliation.insert()

       return reconciliation
   ```

2. **Transaction-Level Reconciliation**
   ```python
   def reconcile_individual_transactions(date_from, date_to):
       """Match individual transactions between systems"""

       # Get all e-boekhouden transactions
       ebh_transactions = get_all_eboekhouden_transactions(date_from, date_to)

       # Get import logs
       import_logs = frappe.get_all(
           "E-Boekhouden Import Log",
           filters={
               "import_timestamp": ["between", [date_from, date_to]]
           },
           fields=["source_mutation_id", "erpnext_document_name", "import_status"]
       )

       # Create lookup map
       imported_map = {
           log.source_mutation_id: log
           for log in import_logs
       }

       # Find missing transactions
       missing = []
       for ebh_txn in ebh_transactions:
           txn_id = str(ebh_txn.get('id') or ebh_txn.get('MutatieNr'))
           if txn_id not in imported_map:
               missing.append({
                   'id': txn_id,
                   'date': ebh_txn.get('date'),
                   'amount': ebh_txn.get('amount'),
                   'description': ebh_txn.get('description')
               })

       return {
           'total_eboekhouden': len(ebh_transactions),
           'total_imported': len(import_logs),
           'missing_count': len(missing),
           'missing_transactions': missing[:100]  # First 100
       }
   ```

### Step 3: Audit Reports

1. **Import Summary Report**
   ```python
   def generate_import_summary_report(migration_id):
       """Generate comprehensive import summary"""

       migration = frappe.get_doc("E-Boekhouden Migration", migration_id)

       # Get statistics
       stats = frappe.db.sql("""
           SELECT
               import_status,
               erpnext_document_type,
               COUNT(*) as count,
               MIN(import_timestamp) as first_import,
               MAX(import_timestamp) as last_import
           FROM `tabE-Boekhouden Import Log`
           WHERE migration_id = %s
           GROUP BY import_status, erpnext_document_type
       """, migration_id, as_dict=True)

       # Get error analysis
       errors = frappe.db.sql("""
           SELECT
               validation_errors,
               COUNT(*) as count
           FROM `tabE-Boekhouden Import Log`
           WHERE migration_id = %s AND import_status = 'Failed'
           GROUP BY validation_errors
           ORDER BY count DESC
           LIMIT 10
       """, migration_id, as_dict=True)

       return {
           'migration': migration.as_dict(),
           'statistics': stats,
           'common_errors': errors,
           'duration': calculate_migration_duration(migration_id),
           'success_rate': calculate_success_rate(migration_id)
       }
   ```

2. **Discrepancy Report**
   ```python
   @frappe.whitelist()
   def get_reconciliation_discrepancies(filters):
       """Get detailed discrepancy report"""

       conditions = []
       if filters.get('company'):
           conditions.append(f"company = '{filters['company']}'")
       if filters.get('date_from'):
           conditions.append(f"date >= '{filters['date_from']}'")

       discrepancies = frappe.db.sql("""
           SELECT
               r.name as reconciliation_id,
               r.reconciliation_date,
               d.document_type,
               d.eboekhouden_amount,
               d.erpnext_amount,
               d.difference,
               d.possible_cause
           FROM `tabE-Boekhouden Reconciliation` r
           JOIN `tabReconciliation Discrepancy` d ON d.parent = r.name
           WHERE {conditions}
           ORDER BY r.reconciliation_date DESC, ABS(d.difference) DESC
       """.format(conditions=" AND ".join(conditions)), as_dict=True)

       return discrepancies
   ```

### Step 4: Data Integrity Checks

1. **Automated Validation**
   ```python
   def run_data_integrity_checks(company):
       """Run comprehensive data integrity checks"""

       checks = []

       # Check 1: Orphaned payments
       orphaned_payments = frappe.db.sql("""
           SELECT name, party, paid_amount
           FROM `tabPayment Entry`
           WHERE company = %s
           AND custom_eboekhouden_import = 1
           AND NOT EXISTS (
               SELECT 1 FROM `tabPayment Entry Reference`
               WHERE parent = `tabPayment Entry`.name
           )
       """, company, as_dict=True)

       if orphaned_payments:
           checks.append({
               'check': 'Orphaned Payments',
               'severity': 'High',
               'count': len(orphaned_payments),
               'details': orphaned_payments[:10]
           })

       # Check 2: Duplicate imports
       duplicates = find_duplicate_imports(company)
       if duplicates:
           checks.append({
               'check': 'Duplicate Imports',
               'severity': 'Medium',
               'count': len(duplicates),
               'details': duplicates
           })

       # Check 3: Balance mismatches
       balance_issues = check_account_balances(company)
       if balance_issues:
           checks.append({
               'check': 'Balance Mismatches',
               'severity': 'High',
               'count': len(balance_issues),
               'details': balance_issues
           })

       return checks
   ```

2. **Manual Review Queue**
   ```python
   def create_review_queue_entry(issue_type, details):
       """Create entry for manual review"""
       review = frappe.new_doc("Import Review Queue")
       review.issue_type = issue_type
       review.severity = determine_severity(issue_type)
       review.details = json.dumps(details)
       review.status = "Open"
       review.insert()

       # Notify responsible users
       notify_reviewers(review)
   ```

### Step 5: Reconciliation UI

1. **Reconciliation Dashboard Page**
   ```javascript
   frappe.pages['reconciliation-dashboard'] = {
       refresh: function(wrapper) {
           // Show reconciliation status
           show_reconciliation_summary();

           // Display discrepancy trends
           render_discrepancy_chart();

           // List recent issues
           show_recent_issues();

           // Quick actions
           add_reconciliation_actions();
       }
   }
   ```

2. **Interactive Reconciliation Tool**
   - Side-by-side comparison of e-boekhouden vs ERPNext
   - Ability to manually match transactions
   - Bulk resolution of discrepancies
   - Export reconciliation reports

### Step 6: Scheduled Reconciliation

1. **Daily Reconciliation Job**
   ```python
   def daily_reconciliation():
       """Run daily reconciliation checks"""
       yesterday = add_days(today(), -1)

       companies = get_companies_with_eboekhouden()

       for company in companies:
           # Run reconciliation
           recon = run_reconciliation(company, yesterday, yesterday)

           # Check for issues
           if recon.has_discrepancies():
               send_reconciliation_alert(company, recon)
   ```

2. **Monthly Audit Report**
   ```python
   def generate_monthly_audit_report():
       """Generate comprehensive monthly audit"""
       last_month_start = get_first_day_of_last_month()
       last_month_end = get_last_day_of_last_month()

       report = {
           'period': f"{last_month_start} to {last_month_end}",
           'imports': get_import_statistics(last_month_start, last_month_end),
           'reconciliations': get_reconciliation_summary(last_month_start, last_month_end),
           'data_integrity': run_monthly_integrity_checks(),
           'recommendations': generate_recommendations()
       }

       # Save and distribute report
       save_audit_report(report)
       distribute_to_stakeholders(report)
   ```
