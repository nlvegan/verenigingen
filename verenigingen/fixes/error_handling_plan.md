# Error Handling and Retry Mechanism Implementation Plan

## Current Issues
- Errors cause complete import failure
- No retry mechanism for transient failures
- Poor error reporting and debugging
- No way to resume failed imports

## Implementation Strategy

### Step 1: Create Error Tracking Infrastructure

1. **Import Error Log DocType**
   ```
   Fields:
   - error_type (Select: Validation/Connection/Data/Permission)
   - source_document (Dynamic Link)
   - error_message (Text)
   - error_details (Long Text) - Full traceback
   - retry_count (Int)
   - max_retries (Int, default: 3)
   - resolution_status (Select: Pending/Retrying/Resolved/Failed)
   - eboekhouden_data (JSON) - Original data for retry
   - occurred_at (Datetime)
   - resolved_at (Datetime)
   ```

2. **Error Categories**
   ```python
   ERROR_CATEGORIES = {
       "TRANSIENT": {
           "types": ["ConnectionError", "Timeout", "RateLimitExceeded"],
           "retry": True,
           "max_retries": 3,
           "backoff": "exponential"
       },
       "DATA_VALIDATION": {
           "types": ["ValidationError", "MandatoryError", "InvalidValue"],
           "retry": False,
           "requires_fix": True
       },
       "BUSINESS_LOGIC": {
           "types": ["DuplicateEntry", "LinkValidationError"],
           "retry": True,
           "max_retries": 1,
           "requires_review": True
       },
       "FATAL": {
           "types": ["PermissionError", "DocTypeNotFound"],
           "retry": False,
           "alert_admin": True
       }
   }
   ```

### Step 2: Implement Retry Logic

1. **Decorator for Retryable Operations**
   ```python
   from functools import wraps
   import time

   def with_retry(max_retries=3, backoff_factor=2):
       def decorator(func):
           @wraps(func)
           def wrapper(*args, **kwargs):
               last_error = None

               for attempt in range(max_retries + 1):
                   try:
                       return func(*args, **kwargs)
                   except Exception as e:
                       last_error = e
                       error_category = categorize_error(e)

                       if not should_retry(error_category, attempt, max_retries):
                           raise

                       wait_time = backoff_factor ** attempt
                       frappe.log_error(
                           f"Retry {attempt + 1}/{max_retries} after {wait_time}s",
                           f"E-Boekhouden Import Retry: {func.__name__}"
                       )
                       time.sleep(wait_time)

               raise last_error
           return wrapper
       return decorator
   ```

2. **Transaction-Level Retry**
   ```python
   @with_retry(max_retries=3)
   def import_single_transaction(mutation_data):
       """Import a single transaction with retry logic"""
       try:
           # Attempt import
           result = create_erpnext_document(mutation_data)

           # Clear any previous errors for this transaction
           clear_error_log(mutation_data.get('id'))

           return result

       except Exception as e:
           # Log error with context
           log_import_error(
               error_type=type(e).__name__,
               source_data=mutation_data,
               error_message=str(e),
               traceback=frappe.get_traceback()
           )
           raise
   ```

### Step 3: Error Recovery Mechanisms

1. **Batch Processing with Error Isolation**
   ```python
   def import_batch_with_recovery(mutations, batch_size=50):
       """Process in batches with error isolation"""
       results = {
           "success": [],
           "failed": [],
           "skipped": []
       }

       for i in range(0, len(mutations), batch_size):
           batch = mutations[i:i + batch_size]

           for mutation in batch:
               try:
                   # Check if previously failed
                   if should_skip_transaction(mutation):
                       results["skipped"].append(mutation)
                       continue

                   # Attempt import
                   doc = import_single_transaction(mutation)
                   results["success"].append({
                       "mutation": mutation,
                       "document": doc.name
                   })

               except Exception as e:
                   results["failed"].append({
                       "mutation": mutation,
                       "error": str(e)
                   })

                   # Don't let one failure stop the batch
                   continue

           # Update progress
           frappe.publish_progress(
               percent=(i + batch_size) / len(mutations) * 100,
               title=f"Importing batch {i//batch_size + 1}",
               description=f"Success: {len(results['success'])}, Failed: {len(results['failed'])}"
           )

       return results
   ```

2. **Manual Error Resolution Interface**
   ```python
   @frappe.whitelist()
   def get_pending_errors(filters=None):
       """Get errors requiring manual intervention"""
       conditions = ["resolution_status = 'Pending'"]

       if filters:
           if filters.get("error_type"):
               conditions.append(f"error_type = '{filters['error_type']}'")
           if filters.get("date_from"):
               conditions.append(f"occurred_at >= '{filters['date_from']}'")

       return frappe.db.sql("""
           SELECT
               name, error_type, source_document,
               error_message, retry_count, occurred_at
           FROM `tabImport Error Log`
           WHERE {conditions}
           ORDER BY occurred_at DESC
       """.format(conditions=" AND ".join(conditions)), as_dict=True)
   ```

### Step 4: Intelligent Error Handling

1. **Context-Aware Error Messages**
   ```python
   def enhance_error_message(error, context):
       """Provide actionable error messages"""
       enhanced_messages = {
           "ValidationError": {
               "missing_account": "Account '{field}' not found. Please map the account in E-Boekhouden Account Mapping.",
               "invalid_date": "Invalid date format. Expected YYYY-MM-DD, got '{value}'.",
               "negative_amount": "Negative amounts should be handled as credit notes or reversals."
           },
           "DuplicateEntry": {
               "invoice": "Invoice {invoice_number} already exists. Check if this is a modified invoice.",
               "payment": "Payment for {invoice} may already be recorded. Verify in Payment Entry list."
           }
       }

       error_type = type(error).__name__
       if error_type in enhanced_messages:
           # Match error pattern and enhance
           for pattern, message in enhanced_messages[error_type].items():
               if pattern in str(error).lower():
                   return message.format(**context)

       return str(error)
   ```

2. **Auto-Fix Capabilities**
   ```python
   def attempt_auto_fix(error_log):
       """Try to automatically fix certain errors"""
       fixes_applied = []

       if "missing_account" in error_log.error_message:
           # Try to create account mapping
           account_code = extract_account_code(error_log.error_message)
           if auto_map_account(account_code):
               fixes_applied.append("Created account mapping")

       elif "duplicate_entry" in error_log.error_message.lower():
           # Check if it's a modified version
           if check_for_modification(error_log.eboekhouden_data):
               fixes_applied.append("Identified as modification, updating existing")

       return fixes_applied
   ```

### Step 5: Monitoring and Alerting

1. **Error Dashboard**
   ```python
   def get_error_statistics():
       """Get error statistics for dashboard"""
       return {
           "total_errors": get_error_count(),
           "by_type": get_errors_by_type(),
           "by_date": get_error_trend(),
           "resolution_rate": calculate_resolution_rate(),
           "common_errors": get_top_errors(limit=5)
       }
   ```

2. **Automated Alerts**
   ```python
   def check_error_thresholds():
       """Check if error rates exceed thresholds"""
       error_rate = calculate_error_rate()

       if error_rate > 10:  # More than 10% failure rate
           send_admin_alert(
               subject="High Error Rate in E-Boekhouden Import",
               message=f"Current error rate: {error_rate}%"
           )

       # Check for stuck imports
       stuck_imports = get_long_running_imports()
       if stuck_imports:
           send_admin_alert(
               subject="Stuck E-Boekhouden Imports Detected",
               imports=stuck_imports
           )
   ```

### Step 6: Resume Capability

1. **Checkpoint System**
   ```python
   def save_import_checkpoint(migration_id, last_processed):
       """Save progress checkpoint"""
       frappe.cache().hset(
           f"ebh_import_{migration_id}",
           "last_processed",
           last_processed
       )

   def resume_import(migration_id):
       """Resume from last checkpoint"""
       last_processed = frappe.cache().hget(
           f"ebh_import_{migration_id}",
           "last_processed"
       )

       if last_processed:
           return continue_from_checkpoint(migration_id, last_processed)
   ```
