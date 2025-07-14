# Performance Optimization Implementation Plan

## Current Issues
- Slow processing of large datasets
- Memory issues with bulk operations
- No progress visibility
- Inefficient database queries

## Implementation Strategy

### Step 1: Batch Processing Optimization

1. **Chunked Data Fetching**
   ```python
   def fetch_mutations_chunked(date_from, date_to, chunk_size=500):
       """Fetch data in chunks to avoid memory issues"""
       current_date = date_from

       while current_date < date_to:
           # Calculate chunk end date
           chunk_end = min(
               current_date + timedelta(days=30),
               date_to
           )

           # Fetch chunk
           mutations = fetch_mutations_for_period(
               current_date,
               chunk_end,
               limit=chunk_size
           )

           yield mutations

           # Move to next chunk
           current_date = chunk_end + timedelta(days=1)

           # Allow other processes to run
           frappe.db.commit()
   ```

2. **Parallel Processing**
   ```python
   from concurrent.futures import ThreadPoolExecutor, as_completed
   import threading

   def process_mutations_parallel(mutations, max_workers=4):
       """Process mutations in parallel threads"""
       results = []
       thread_local = threading.local()

       def process_mutation(mutation):
           # Ensure each thread has its own database connection
           if not hasattr(thread_local, 'db'):
               thread_local.db = frappe.get_db()

           try:
               return import_single_transaction(mutation)
           except Exception as e:
               return {"error": str(e), "mutation": mutation}

       with ThreadPoolExecutor(max_workers=max_workers) as executor:
           futures = {
               executor.submit(process_mutation, m): m
               for m in mutations
           }

           for future in as_completed(futures):
               result = future.result()
               results.append(result)

               # Update progress
               progress = len(results) / len(mutations) * 100
               frappe.publish_progress(
                   progress,
                   title="Processing Mutations",
                   description=f"Completed {len(results)} of {len(mutations)}"
               )

       return results
   ```

### Step 2: Database Query Optimization

1. **Bulk Operations**
   ```python
   def bulk_create_invoices(invoice_data_list):
       """Create multiple invoices in one operation"""

       # Prepare bulk data
       invoices = []
       items = []
       taxes = []

       for data in invoice_data_list:
           invoice = prepare_invoice_data(data)
           invoice_items = prepare_item_data(data, invoice['name'])
           invoice_taxes = prepare_tax_data(data, invoice['name'])

           invoices.append(invoice)
           items.extend(invoice_items)
           taxes.extend(invoice_taxes)

       # Bulk insert
       if invoices:
           frappe.db.bulk_insert('Sales Invoice', invoices)
       if items:
           frappe.db.bulk_insert('Sales Invoice Item', items)
       if taxes:
           frappe.db.bulk_insert('Sales Taxes and Charges', taxes)

       # Single commit
       frappe.db.commit()
   ```

2. **Query Optimization**
   ```python
   def get_existing_invoices_optimized(invoice_numbers):
       """Check for existing invoices efficiently"""
       if not invoice_numbers:
           return {}

       # Use IN clause for bulk lookup
       placeholders = ', '.join(['%s'] * len(invoice_numbers))
       existing = frappe.db.sql(f"""
           SELECT
               custom_eboekhouden_invoice_number as ebh_number,
               name,
               docstatus
           FROM `tabSales Invoice`
           WHERE custom_eboekhouden_invoice_number IN ({placeholders})
       """, invoice_numbers, as_dict=True)

       return {inv['ebh_number']: inv for inv in existing}
   ```

### Step 3: Memory Management

1. **Generator-Based Processing**
   ```python
   def process_large_import(migration_id):
       """Process large imports without loading all data in memory"""
       migration = frappe.get_doc("E-Boekhouden Migration", migration_id)

       def mutation_generator():
           """Yield mutations one at a time"""
           for chunk in fetch_mutations_chunked(
               migration.date_from,
               migration.date_to
           ):
               for mutation in chunk:
                   yield mutation

       # Process using generator
       success_count = 0
       error_count = 0

       for mutation in mutation_generator():
           try:
               import_single_transaction(mutation)
               success_count += 1
           except Exception:
               error_count += 1

           # Periodic cleanup
           if (success_count + error_count) % 100 == 0:
               frappe.db.commit()
               frappe.clear_cache()
   ```

2. **Resource Monitoring**
   ```python
   import psutil
   import gc

   def monitor_resources(func):
       """Decorator to monitor resource usage"""
       def wrapper(*args, **kwargs):
           process = psutil.Process()

           # Before
           mem_before = process.memory_info().rss / 1024 / 1024  # MB

           try:
               result = func(*args, **kwargs)

               # After
               mem_after = process.memory_info().rss / 1024 / 1024
               mem_increase = mem_after - mem_before

               if mem_increase > 100:  # More than 100MB increase
                   frappe.log_error(
                       f"High memory usage: {mem_increase:.2f}MB increase",
                       "Performance Warning"
                   )
                   # Force garbage collection
                   gc.collect()

               return result

           except Exception as e:
               raise e

       return wrapper
   ```

### Step 4: Progress Tracking

1. **Real-time Progress Updates**
   ```python
   class ImportProgressTracker:
       def __init__(self, total_records):
           self.total = total_records
           self.processed = 0
           self.success = 0
           self.failed = 0
           self.start_time = time.time()

       def update(self, success=True):
           self.processed += 1
           if success:
               self.success += 1
           else:
               self.failed += 1

           # Calculate metrics
           progress = (self.processed / self.total) * 100
           elapsed = time.time() - self.start_time
           rate = self.processed / elapsed if elapsed > 0 else 0
           eta = (self.total - self.processed) / rate if rate > 0 else 0

           # Publish update
           frappe.publish_progress(
               progress,
               title=f"Import Progress: {progress:.1f}%",
               description=self.get_status_message(eta)
           )

       def get_status_message(self, eta):
           return (
               f"Processed: {self.processed}/{self.total} | "
               f"Success: {self.success} | Failed: {self.failed} | "
               f"ETA: {timedelta(seconds=int(eta))}"
           )
   ```

2. **Persistent Progress Storage**
   ```python
   def save_progress_checkpoint(migration_id, tracker):
       """Save progress to database"""
       frappe.db.set_value(
           "E-Boekhouden Migration",
           migration_id,
           {
               "imported_records": tracker.success,
               "failed_records": tracker.failed,
               "progress_percentage": tracker.get_progress(),
               "current_operation": tracker.get_current_operation()
           },
           update_modified=False
       )
       frappe.db.commit()
   ```

### Step 5: Caching Strategy

1. **Lookup Cache**
   ```python
   class ImportCache:
       def __init__(self):
           self.accounts = {}
           self.parties = {}
           self.tax_templates = {}
           self.items = {}

       def get_account(self, account_code):
           if account_code not in self.accounts:
               self.accounts[account_code] = frappe.db.get_value(
                   "E-Boekhouden Account Mapping",
                   {"eboekhouden_account_code": account_code},
                   "erpnext_account"
               )
           return self.accounts[account_code]

       def get_party(self, party_code, party_type):
           key = f"{party_type}:{party_code}"
           if key not in self.parties:
               self.parties[key] = get_or_create_party(
                   party_code,
                   party_type
               )
           return self.parties[key]

       def clear(self):
           """Clear cache to free memory"""
           self.accounts.clear()
           self.parties.clear()
           self.tax_templates.clear()
           self.items.clear()
   ```

### Step 6: Performance Monitoring

1. **Import Metrics**
   ```python
   def collect_import_metrics(migration_id):
       """Collect performance metrics"""
       return {
           "total_time": get_migration_duration(migration_id),
           "records_per_second": calculate_throughput(migration_id),
           "memory_peak": get_peak_memory_usage(migration_id),
           "database_queries": count_database_queries(migration_id),
           "error_rate": calculate_error_rate(migration_id),
           "bottlenecks": identify_slow_operations(migration_id)
       }
   ```

2. **Optimization Recommendations**
   ```python
   def analyze_performance(metrics):
       """Provide optimization recommendations"""
       recommendations = []

       if metrics["records_per_second"] < 10:
           recommendations.append(
               "Consider increasing batch size or parallel workers"
           )

       if metrics["memory_peak"] > 1024:  # 1GB
           recommendations.append(
               "High memory usage detected. Enable chunked processing"
           )

       if metrics["error_rate"] > 5:
           recommendations.append(
               "High error rate. Review data quality and mappings"
           )

       return recommendations
   ```
