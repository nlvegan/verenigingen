# FAQ and Troubleshooting Guide

This guide answers frequently asked questions and provides solutions to common issues in the Verenigingen system. It is written for administrators and staff who manage members, payments, chapters, and integrations day-to-day.

## Quick Reference

**For comprehensive error recovery procedures, see:** [**Error Recovery Guide**](troubleshooting/ERROR_RECOVERY_GUIDE.md)

The Error Recovery Guide provides detailed step-by-step procedures for:

- **Payment Failures** - SEPA direct debit failures, mandate errors, reconciliation issues
- **Portal Access Issues** - Login failures, permission errors, session timeouts
- **Data Processing Errors** - Import failures, validation errors, duplicate entries
- **Integration Failures** - eBoekhouden connectivity, API timeouts, webhook failures
- **System-Level Issues** - Database problems, Redis/cache issues, background job failures

**Admin Dashboards** (accessible from your site URL):

| Dashboard | URL Path | Purpose |
|-----------|----------|---------|
| Monitoring Dashboard | `/monitoring_dashboard` | System health and background jobs |
| eBoekhouden Dashboard | `/e-boekhouden-dashboard` | Accounting sync status and errors |
| eBoekhouden Status | `/e-boekhouden-status` | eBoekhouden connection health |
| Mollie Member Reconciliation | `/mollie_member_reconciliation` | Match Mollie payments to members |
| Mollie Subscription Audit | `/mollie_subscription_audit` | Review Mollie subscription status |
| Dues Invoice Manager | `/dues-invoice-manager` | Manage and generate dues invoices |
| Dues Invoice Debugger | `/dues-invoice-debugger` | Diagnose invoice generation problems |
| Dues Coverage Manager | `/dues-coverage-manager` | Review dues coverage periods |
| SEPA Batch Optimizer | `/batch-optimizer` | Optimize SEPA batch processing |
| Email Group Admin | `/email-group-admin` | Manage email group memberships |
| Chapter Page | `/chapter` | Public chapter overview |

---

## Table of Contents

- [Member Management](#member-management)
- [Payment and Billing Issues](#payment-and-billing-issues)
- [SEPA Direct Debit](#sepa-direct-debit)
- [Mollie Payments](#mollie-payments)
- [Chapter Management](#chapter-management)
- [eBoekhouden Sync](#eboekhouden-sync)
- [Permissions and Access](#permissions-and-access)
- [Common Validation Errors](#common-validation-errors)
- [Troubleshooting](#troubleshooting)
- [Contact and Support](#contact-and-support)

---

## Member Management

### Approving Members

**Q: How do I approve a new membership application?**

A: Open the Member record in the desk. Verify that the applicant's information is complete (name, email, address, membership type). Click the "Approve" action button. The system will automatically:

1. Create a membership record
2. Set up a dues schedule based on the membership type
3. Create a user account for the member
4. Assign the member to a chapter based on their postal code
5. Send a welcome email

If anything is missing, you will see a specific error message (see [Common Validation Errors](#common-validation-errors)).

**Q: I get "No membership types available in the system" when approving.**

A: No membership types have been created yet. Go to the desk, search for "Membership Type", and create at least one active membership type with a dues schedule template assigned.

**Q: I get "Membership Type is not active" when approving.**

A: The membership type selected for this applicant has been deactivated. Either reactivate the membership type or change the applicant's selected membership type to an active one before approving.

**Q: I get "Cannot approve application: Membership Type does not have a valid dues schedule template."**

A: Every membership type needs a dues schedule template that defines contribution amounts and billing frequency. Go to the Membership Type record and assign a valid Dues Schedule Template.

**Q: I get "Member already has an active membership" or "Member already has an active dues schedule."**

A: This member was already approved previously. Check the member's existing membership and dues schedule records. If this is a re-application, the old membership may need to be terminated first.

**Q: I get "This application cannot be approved in its current state."**

A: The member's application status does not allow approval. Only applications in certain states (typically "Pending Review" or similar) can be approved. Check the member's current status in the Member record.

### Rejecting Members

**Q: How do I reject a membership application?**

A: Open the Member record and click the "Reject" action. You can optionally select an email template to send the applicant a notification explaining the decision.

**Q: I get "Invalid email template specified" when rejecting with notification.**

A: The email template you selected does not exist or has been deleted. Choose a different template from the dropdown, or reject without sending a notification and follow up manually.

**Q: I get "This application cannot be rejected in its current state."**

A: Similar to approval, only applications in the correct status can be rejected. If the member has already been approved, you cannot reject them -- you would need to use the termination process instead.

### Merging Members

**Q: When would I merge two member records?**

A: Merge members when you find duplicate records for the same person. This consolidates their membership history, payment records, chapter memberships, and contact information into a single record. The source member is deleted after the merge.

**Q: What happens during a merge?**

A: The system transfers all related records (secondary emails, chapter memberships, payment history, comments) from the source member to the target member, then deletes the source member and its dependencies. A comment is added to the target member documenting the merge.

### Terminating Members

**Q: How do I terminate a membership?**

A: Create a Membership Termination Request from the member's record. You must provide:

1. A termination reason
2. For disciplinary actions: supporting documentation

Submit the request for approval. Once approved by an authorized user, the termination can be executed.

**Q: I get "Termination reason is required."**

A: Every termination request must include a reason. Fill in the termination reason field before submitting.

**Q: I get "Documentation is required for disciplinary actions."**

A: When the termination type involves disciplinary action, you must attach documentation (evidence, correspondence, etc.) before the request can be submitted.

**Q: I get "Only draft requests can be submitted for approval."**

A: This termination request has already been submitted. Check its current status -- it may be pending approval, already approved, or already executed.

**Q: I get "Secondary approver is required for this termination type."**

A: Certain termination types (such as disciplinary) require a second approver for oversight. Assign a secondary approver before submitting.

**Q: I get "Only approved requests can be executed."**

A: The termination request must be approved by an authorized user before it can be executed. Check whether the request is still pending approval.

**Q: I get "User does not have permission to approve termination requests."**

A: The designated approver does not have the required role. Only users with specific approval roles (such as System Manager or Verenigingen Administrator) can approve termination requests.

**Q: I get "Member no longer exists."**

A: The member record was deleted between the time the termination was approved and when execution was attempted. This is unusual and may indicate a data issue. Check the error log for details.

### Member Accounts

**Q: I get "Email is required to create a user" or "First name is required" or "Last name is required."**

A: The member record is missing basic information needed to create their login account. Fill in the missing fields (email, first name, last name) on the Member record before approving.

**Q: I get "Failed to create user."**

A: The user account could not be created. Common causes include: the email address is already used by another user, the email format is invalid, or there is a system configuration issue. Check the specific error details in the message.

---

## Payment and Billing Issues

### Invoice Generation

**Q: I get "No default company configured in Verenigingen Settings."**

A: The billing system needs to know which company to create invoices under. Go to Verenigingen Settings (in the desk search bar, type "Verenigingen Settings") and set the Default Company field.

**Q: I get "Accounting Configuration Required."**

A: The accounting setup is incomplete. This typically means income accounts, cost centers, or other financial settings required for invoice creation are not configured. Check Verenigingen Settings and ensure all accounting fields are filled in.

**Q: I get "Invoice generation failed."**

A: Something went wrong during invoice creation. The error message will contain details. Common causes: missing accounting configuration, invalid member data, or missing customer records.

**Q: I get "Coverage dates were not set during invoice creation."**

A: This is a system error indicating the invoice was created without proper coverage date tracking. Contact your system administrator.

**Q: I get "Member has no active membership."**

A: You cannot generate an invoice for a member who does not have a current active membership. Verify the member's membership status.

**Q: I get "Member already has a dues schedule."**

A: This member already has a billing schedule set up. You cannot create a duplicate. If you need to change their billing, edit the existing Membership Dues Schedule record.

### Dues Schedule Validation

**Q: I get "Dues rate cannot be less than minimum contribution."**

A: The contribution amount is below the configured minimum. The minimum is set in Verenigingen Settings or on the dues schedule template. Either increase the amount or ask an administrator to adjust the minimum.

**Q: I get "Dues rate exceeds maximum limit. Please contact an administrator if this amount is correct."**

A: The contribution amount is unusually high and exceeds the configured safety limit. If this amount is intentional, ask an administrator to approve or adjust the limit.

**Q: I get "Next Invoice Date cannot be before Last Invoice Date."**

A: The dates on the dues schedule are inconsistent. The next billing date must be after the last invoice date. Correct the dates on the Membership Dues Schedule record.

**Q: I get "Selected contribution amount is less than the minimum required for this membership type."**

A: Each membership type has a minimum contribution. The amount entered is too low. Check the membership type configuration for the correct minimum.

### Fee Overrides

**Q: I get "Membership fee override must be greater than 0."**

A: When setting a custom fee for a member, the amount must be a positive number.

**Q: I get "Please provide a reason for the fee override."**

A: Fee overrides require a documented reason for audit purposes. Enter a brief explanation of why this member's fee differs from the standard amount.

**Q: I get "You do not have permission to override membership fees."**

A: Only users with specific roles (Verenigingen Administrator or System Manager) can override membership fees. Contact an administrator if you need this permission.

### Progressive Dues

**Q: I get "Progressive mode requires a Reference Income (median) to be set."**

A: When using progressive (income-based) dues, the template must have a reference income configured. This is the national median income used as the 100% reference point. Set it on the Dues Schedule Template.

**Q: I get "Lower Income Threshold must be less than Reference Income."**

A: The income threshold settings are misconfigured. The lower income threshold (below which minimum dues apply) must be lower than the reference income. Adjust the values on the template.

---

## SEPA Direct Debit

**Q: I get "IBAN is required for SEPA Direct Debit payment method."**

A: Members using SEPA Direct Debit must have a valid IBAN on their record. Add the member's IBAN before saving.

**Q: I get "Account Holder Name is required for SEPA Direct Debit payment method."**

A: The bank account holder name is required alongside the IBAN. Fill in the Account Holder Name field on the member record.

**Q: I get "Invalid IBAN" when saving a member.**

A: The IBAN entered does not pass format validation. Double-check the IBAN with the member. Common mistakes include transposed digits, missing country code, or incorrect length. Use an online IBAN checker to verify.

**Q: I get "SEPA XML canonicalization failed."**

A: This is a technical error during SEPA file generation. It typically indicates a system configuration issue. Contact your system administrator.

**Q: How do I handle returned/rejected SEPA payments?**

A: SEPA return files (pain.002 format) can be uploaded through the system. The pain002 ingestion service processes return codes and updates payment statuses accordingly. Common return reasons include:

- Insufficient funds in the member's account
- Account closed or frozen
- Mandate cancelled or expired
- Invalid account number

After processing returns, contact affected members to arrange alternative payment.

**Q: I get "Reason must be at least 10 characters for audit purposes."**

A: When performing SEPA phantom hash administration (resolving duplicate detection issues), you must provide a meaningful explanation of at least 10 characters.

---

## Mollie Payments

**Q: I get "Customer ID and Subscription ID are required."**

A: When cancelling a Mollie subscription, both the Mollie customer ID and subscription ID must be provided. These are stored on the member or donation record.

**Q: I get "You are not authorized to cancel subscriptions for this customer."**

A: You can only cancel subscriptions that belong to your own account, or you need administrator privileges. Contact an administrator if you need to cancel another member's subscription.

**Q: How do I check if Mollie webhooks are working?**

A: Visit the **Mollie Subscription Audit** dashboard at `/mollie_subscription_audit` on your site. This shows the status of all Mollie subscriptions and highlights any synchronization issues. You can also check the **Mollie Member Reconciliation** page at `/mollie_member_reconciliation` to match Mollie payments with member records.

**Q: Mollie payments are not being matched to members.**

A: Use the Mollie Member Reconciliation dashboard at `/mollie_member_reconciliation` to review unmatched payments. Common causes:

1. The member's email in Mollie does not match their email in the system
2. The Mollie customer ID is not linked to the member record
3. The payment was made by a non-member (donation without membership)

**Q: I get "Invalid Mollie data in CSV import."**

A: When importing Mollie transaction data via CSV, the file contains invalid or unexpected data. Check the CSV format and ensure it matches the expected Mollie export format.

---

## Chapter Management

**Q: I get "Member and Chapter are required."**

A: When assigning or removing a member from a chapter, both the member reference and the chapter must be specified. Ensure neither field is empty.

**Q: I get "Chapter does not exist."**

A: The chapter name referenced does not match any existing Chapter record. Verify the chapter name is spelled correctly and that the chapter has been created.

**Q: I get "Failed to update member chapter display."**

A: The system could not update the chapter display information on the member record. This is usually a temporary issue. Try saving again, or check the error log for details.

**Q: I get "Verenigingen Administrators cannot edit the National Board chapter."**

A: The National Board chapter has special protections. Only System Managers can modify it. If you need to make changes, ask a System Manager.

**Q: How are members assigned to chapters automatically?**

A: Chapter assignment uses postal code patterns. Each chapter has postal code ranges configured. When a member's address is saved, the system matches their postal code to the correct chapter. To review or fix chapter assignments:

1. Open the Chapter record to see its postal code patterns
2. Verify the member's postal code is correct
3. If the postal code does not match any chapter, the member will not be assigned automatically

**Q: I get "No member record found for your account" when trying to join a chapter.**

A: Your user account is not linked to a member record. Contact an administrator to ensure your user account is properly connected to your membership.

**Q: I get "Introduction is required" when requesting to join a chapter.**

A: When joining a chapter, you must write a brief introduction about yourself. Fill in the introduction field and submit again.

---

## eBoekhouden Sync

### Connection and Configuration

**Q: I get "E-Boekhouden Settings not configured. Please configure API token first."**

A: The eBoekhouden integration has not been set up. Go to E-Boekhouden Settings (search in the desk) and enter your API token.

**Q: I get "E-Boekhouden API not configured."**

A: Same as above -- the API token field in E-Boekhouden Settings is empty. Enter your eBoekhouden API credentials.

**Q: I get "Failed to fetch ledger accounts from E-Boekhouden."**

A: The system could not retrieve account data from eBoekhouden. This usually means:

1. The API token is invalid or expired -- verify in E-Boekhouden Settings
2. The eBoekhouden service is temporarily unavailable -- try again later
3. Network connectivity issues -- check your server's internet connection

Check the eBoekhouden Status dashboard at `/e-boekhouden-status` for connection health details.

**Q: I get "Failed to fetch mutations from E-Boekhouden."**

A: Similar to the ledger fetch error. The API connection failed when trying to retrieve transactions. Check the same items listed above.

### Account Mapping

**Q: I get "Account Code Missing" or "Account Mapping Missing."**

A: An eBoekhouden account code does not have a corresponding ERPNext account mapped. Go to the E-Boekhouden Account Mapping page and map the missing account. The eBoekhouden Dashboard at `/e-boekhouden-dashboard` shows unmapped accounts.

**Q: I get "Account Mapping Required."**

A: The system needs to know which ERPNext account corresponds to the eBoekhouden account being processed. Set up the mapping in E-Boekhouden Account Mapping before running the migration.

**Q: I get "No staged data found. Please stage data first."**

A: Before running a migration or previewing impact, you must first stage (fetch and prepare) the data from eBoekhouden. Click the "Stage Data" button on the E-Boekhouden Account Mapping page first.

**Q: I get "Tegenrekening Mapping Failed."**

A: The contra-account (tegenrekening) in an eBoekhouden transaction could not be mapped to an ERPNext account. Check your account mappings for completeness.

### Migration Issues

**Q: I get "Journal Entry is not balanced."**

A: During migration, a transaction could not be converted to a balanced journal entry. This usually indicates a data quality issue in the eBoekhouden transaction. Review the specific transaction in eBoekhouden and correct any discrepancies.

**Q: I get "Invalid invoice data: missing or invalid Relatie information."**

A: An eBoekhouden invoice is missing the customer or supplier (Relatie) information. Check the original transaction in eBoekhouden.

**Q: I get "Unexpected error in eBoekhouden integration."**

A: This is a catch-all error for unexpected failures. Check the Error Log in the desk (search for "Error Log") and look for entries titled "eBoekhouden" for detailed information.

**Q: How do I check the eBoekhouden sync status?**

A: Use these dashboards:

1. **eBoekhouden Dashboard** at `/e-boekhouden-dashboard` -- shows sync status, recent migrations, and error summaries
2. **eBoekhouden Status** at `/e-boekhouden-status` -- shows connection health and configuration status

---

## Permissions and Access

**Q: I get "Access denied" or "Insufficient permissions."**

A: Your user account does not have the role needed for this action. Common role requirements:

| Action | Required Role |
|--------|--------------|
| Approve/reject members | Verenigingen Administrator or System Manager |
| Generate bulk invoices | Verenigingen Administrator or System Manager |
| Override membership fees | Verenigingen Administrator or System Manager |
| Approve terminations | System Manager or designated approver role |
| Run eBoekhouden migration | Verenigingen Administrator or System Manager |
| Manage ANBI data | Verenigingen Administrator or System Manager |
| Reset member ID counter | System Manager only |
| Edit National Board chapter | System Manager only |
| Delete payment entries | Verenigingen Administrator |

Ask a System Manager to assign the appropriate role to your account.

**Q: I get "Please login to access volunteer information" or "Please login to access the volunteer expense portal."**

A: You must be logged in to access volunteer features. If you are logged in and still see this error, your session may have expired. Log out and log back in.

**Q: I get "You don't have permission to create email templates."**

A: Creating email templates requires administrator privileges. Contact your system administrator.

**Q: I get "You don't have permission to activate volunteers."**

A: Volunteer activation requires specific permissions. Contact a Verenigingen Administrator.

**Q: I get "Insufficient permissions to check duplicates."**

A: Duplicate member detection requires read access to member records. Ensure your role includes Member read permission.

**Q: I get "You do not have permission to access this member."**

A: You are trying to view a member record you do not have access to. Permission may be restricted by chapter or role.

---

## Common Validation Errors

This section lists error messages you may encounter, what they mean, and how to resolve them.

### Member Records

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Email is required to create a user" | Member email field is empty | Add the member's email address |
| "First name is required to create a user" | First name field is empty | Add the member's first name |
| "Last name is required to create a user" | Last name field is empty | Add the member's last name |
| "Member email is required for billing notifications" | Email needed for invoicing | Add email before approving |
| "Please select a membership type" | No membership type chosen | Select a type on the application |
| "Member ID is already in use" | Duplicate member ID | System will auto-assign; contact admin if manual |
| "Counter value must be greater than 0" | Invalid member ID counter | Use a positive number |
| "Invalid member reference" | Member name/ID is incorrect | Verify the member reference |

### Membership and Billing

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Member has no active membership" | No current membership found | Check membership status |
| "Member already has a dues schedule" | Duplicate schedule | Edit existing schedule instead |
| "Membership Type does not exist" | Invalid type reference | Check Membership Type list |
| "Membership Type is not active" | Type was deactivated | Reactivate or choose another |
| "No dues schedule template" | Template not assigned to type | Assign template to Membership Type |
| "Dues schedule template does not exist" | Template was deleted | Create new template and assign |
| "Dues rate cannot be less than minimum contribution" | Amount too low | Increase amount or adjust minimum |
| "Dues rate exceeds maximum limit" | Amount too high | Verify amount; ask admin to adjust limit |
| "Custom dues rate must be a valid number" | Non-numeric value entered | Enter a valid number |
| "Custom dues rate must be non-negative" | Negative amount entered | Enter a positive number |
| "Next Invoice Date cannot be before Last Invoice Date" | Date order wrong | Correct the dates |

### SEPA and Payment

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "IBAN is required for SEPA Direct Debit" | Missing IBAN | Add IBAN to member record |
| "Account Holder Name is required for SEPA Direct Debit" | Missing account holder | Add bank account holder name |
| "Invalid IBAN" | IBAN format check failed | Verify IBAN with member |
| "Customer not found for donor" | No customer record linked | Create customer for this donor |
| "Failed to create membership invoice" | Invoice creation failed | Check accounting configuration |
| "Payment can only be processed for approved applications" | Wrong application status | Approve the application first |
| "Donation donor does not match agreement donor" | Mismatched records | Verify donation and agreement link |
| "Donation is already linked to an agreement" | Duplicate link | This donation is already processed |

### eBoekhouden

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "E-Boekhouden Settings not configured" | Missing API token | Configure in E-Boekhouden Settings |
| "E-Boekhouden API not configured" | Empty API token | Enter API credentials |
| "Failed to fetch ledger accounts" | API connection failed | Check token and connectivity |
| "Account Code Missing" | Unmapped account code | Add mapping in Account Mapping |
| "Account Mapping Missing" | No ERPNext mapping | Set up account mapping |
| "No staged data found" | Data not staged yet | Click "Stage Data" first |
| "Bank Account Configuration Error" | Bank account not set up | Configure bank account in ERPNext |
| "Company Required" | No company for cost center | Set company in Verenigingen Settings |
| "Journal Entry is not balanced" | Debit/credit mismatch | Review transaction in eBoekhouden |

### Chapters and Volunteers

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Member and Chapter are required" | Missing required fields | Provide both member and chapter |
| "Chapter does not exist" | Invalid chapter reference | Verify chapter name |
| "Activity Type is required" | Missing activity type | Select an activity type |
| "Role is required" | Missing volunteer role | Select a role |
| "End date cannot be before start date" | Date order wrong | Correct the dates |
| "Default Role Profile does not exist" | Missing role profile | Create the role profile first |
| "National chapter not configured in settings" | Missing setting | Set national chapter in Verenigingen Settings |
| "Company not configured in Verenigingen Settings" | Missing company | Set company in Verenigingen Settings |

---

## Troubleshooting

### Step 1: Check the Error Log

Most errors are recorded in the Error Log. To view it:

1. Go to the desk (your site URL + `/app`)
2. In the search bar, type "Error Log" and press Enter
3. Look at recent entries for errors related to your issue
4. The error title and traceback will help identify the problem

### Step 2: Check Background Jobs

Many operations (bulk invoicing, eBoekhouden sync, email sending) run as background jobs. To check their status:

1. In the desk, search for "Background Jobs"
2. Look for failed jobs (shown in red)
3. Click on a failed job to see the error details

You can also check the Monitoring Dashboard at `/monitoring_dashboard` for a visual overview.

### Step 3: Review Log Files

If the desk logs do not have enough detail, check the server log files:

| Log File | Location | Contents |
|----------|----------|----------|
| Web server log | `frappe-bench/logs/web.log` | HTTP request errors |
| Worker error log | `frappe-bench/logs/worker.error.log` | Background job failures |
| Scheduler log | `frappe-bench/logs/scheduler.log` | Scheduled task issues |
| Site-specific log | `frappe-bench/sites/veg11.veganisme.org/logs/` | Site-specific errors |

Ask your system administrator to check these files if you do not have server access.

### Step 4: Use the Admin Dashboards

The system includes several dashboards for diagnosing specific issues:

**For payment problems:**
- Dues Invoice Debugger at `/dues-invoice-debugger` -- diagnose why invoices are not generating correctly
- Dues Coverage Manager at `/dues-coverage-manager` -- check if dues coverage periods have gaps
- Dues Invoice Manager at `/dues-invoice-manager` -- review and manage invoices
- SEPA Batch Optimizer at `/batch-optimizer` -- check SEPA batch status

**For eBoekhouden problems:**
- eBoekhouden Dashboard at `/e-boekhouden-dashboard` -- overall sync status
- eBoekhouden Status at `/e-boekhouden-status` -- connection health

**For Mollie problems:**
- Mollie Member Reconciliation at `/mollie_member_reconciliation` -- match payments to members
- Mollie Subscription Audit at `/mollie_subscription_audit` -- subscription status

**For system health:**
- Monitoring Dashboard at `/monitoring_dashboard` -- overall system status

### Step 5: Use Debug Scripts

For system administrators with server access, debug scripts are available in the `scripts/debug/` directory:

| Script | Purpose |
|--------|---------|
| `debug_chapter_assignment.py` | Diagnose chapter assignment issues |
| `debug_team_assignment.py` | Diagnose team assignment issues |
| `debug_volunteer_lookup.py` | Diagnose volunteer record lookup issues |
| `debug_dashboard_access.py` | Diagnose dashboard permission issues |
| `debug_service_layer.py` | Diagnose service layer errors |
| `check_eboekhouden_workspace.py` | Verify eBoekhouden workspace setup |
| `check_ledger_mappings.py` | Verify eBoekhouden account mappings |
| `check_email_templates.py` | Verify email template configuration |
| `check_scheduler_status.py` | Check if scheduled tasks are running |
| `check_scheduler_logs.py` | Review scheduler log entries |
| `system_status_check.py` | General system health check |
| `membership_dues_coverage_debugger.py` | Debug dues coverage calculation |
| `payment_history_debugger.py` | Debug payment history records |
| `fix_expense_claim_accounts.py` | Fix expense claim account configuration |
| `board/debug_board_addition.py` | Debug board member addition |
| `board/debug_chapter_membership.py` | Debug chapter membership issues |
| `chapter/bench_debug_chapter.py` | Debug chapter-related issues |
| `employee/debug_employee_creation.py` | Debug employee record creation |

Run these from the app directory:

```bash
cd ~/frappe-bench/apps/verenigingen
python scripts/debug/<script_name>.py
```

### Step 6: Clear Cache

Many display and permission issues can be resolved by clearing the cache:

1. In the desk, press `Ctrl+Shift+R` (or `Cmd+Shift+R` on Mac) to hard-refresh the browser
2. If the issue persists, ask your system administrator to clear the server cache

### Common Problem Scenarios

**Scenario: Member approval fails with no clear error**

1. Check that a membership type is selected on the member record
2. Verify the membership type is active and has a dues schedule template
3. Ensure the member has an email address
4. Check the Error Log for detailed error information

**Scenario: Invoices are not being generated for some members**

1. Visit the Dues Invoice Debugger at `/dues-invoice-debugger`
2. Check that each member has an active dues schedule
3. Verify the "Next Invoice Date" has passed
4. Ensure the member has a linked customer record
5. Check that Verenigingen Settings has a default company configured

**Scenario: eBoekhouden sync shows errors**

1. Check the eBoekhouden Status page at `/e-boekhouden-status` for connection issues
2. Review the eBoekhouden Dashboard at `/e-boekhouden-dashboard` for specific errors
3. Verify all account mappings are complete (unmapped accounts cause failures)
4. Check the Error Log for entries titled "E-Boekhouden"

**Scenario: SEPA batch processing fails**

1. Visit the SEPA Batch Optimizer at `/batch-optimizer` for batch status
2. Verify all members in the batch have valid IBANs and active mandates
3. Check that SEPA creditor settings are configured in Verenigingen Settings
4. Review the Error Log for SEPA-related errors

**Scenario: Mollie payments not appearing in the system**

1. Check the Mollie Subscription Audit at `/mollie_subscription_audit`
2. Use the Mollie Member Reconciliation page at `/mollie_member_reconciliation`
3. Verify webhook URL is correctly configured in the Mollie dashboard
4. Check the Error Log for webhook processing errors

**Scenario: Member cannot log into the portal**

1. Verify the member has a linked user account (check the "User" field on the Member record)
2. Ensure the user account is enabled (not disabled or locked)
3. Check that the user has the "Verenigingen Member" role
4. Try resetting the member's password

---

## General Questions

### What is Verenigingen?

**Q: What is the Verenigingen app and what does it do?**

A: Verenigingen is a comprehensive association management system built on the Frappe/ERPNext platform. It provides:

- Complete member lifecycle management (application, approval, billing, termination)
- Payment processing with SEPA direct debit and Mollie
- Volunteer coordination and expense management
- Chapter-based organization with automatic postal code assignment
- Financial integration with ERPNext and eBoekhouden
- Dutch compliance features (ANBI, GDPR)

### Data and Privacy

**Q: Is the system GDPR compliant?**

A: Yes, the system includes GDPR compliance features:

- Member consent management
- Data access and portability tools
- Audit trails for data access
- Role-based access control for sensitive data

**Q: Where is data stored?**

A: Data is stored in your own MariaDB/MySQL database on your server. No data is shared with third parties except through explicitly configured integrations (eBoekhouden, Mollie).

---

## Contact and Support

### Self-Help Resources

1. Check this FAQ for your specific error message
2. Use the admin dashboards listed above to diagnose issues
3. Review the Error Log in the desk for technical details
4. For detailed recovery procedures, see the [Error Recovery Guide](troubleshooting/ERROR_RECOVERY_GUIDE.md)

### Bugs, Feature Requests, and Other Issues

These can be submitted to [github.com/nlvegan/verenigingen/issues](https://github.com/nlvegan/verenigingen/issues).
