# Mollie Payment Integration - Complete User Guide

## Table of Contents

1. [Introduction & Overview](#introduction--overview)
2. [Prerequisites & Requirements](#prerequisites--requirements)
3. [Initial Setup Guide](#initial-setup-guide)
4. [Daily Operations Guide](#daily-operations-guide)
5. [Administrative Management](#administrative-management)
6. [Troubleshooting Guide](#troubleshooting-guide)
7. [FAQ](#faq)
8. [Technical Reference](#technical-reference)

---

## Introduction & Overview

### What is the Mollie Integration?

The Mollie payment integration provides automated recurring payment processing for Dutch associations, replacing manual payment handling with a streamlined, compliant solution. This integration transforms how your vereniging handles membership dues by automating the entire payment cycle from subscription creation to payment reconciliation.

### Business Benefits for Dutch Associations

**Automated Recurring Payments**
- Eliminates manual payment processing for membership dues
- Reduces administrative overhead by up to 80%
- Ensures consistent cash flow through automated collections
- Supports multiple payment methods including iDEAL, SEPA Direct Debit, and credit cards

**Regulatory Compliance**
- Full GDPR compliance for member data handling
- Meets Dutch/EU payment regulations (PSD2)
- Maintains audit trails for financial transparency
- Integrates with existing e-Boekhouden accounting systems

**Member Experience**
- Professional payment portal with your association's branding
- Flexible payment intervals (monthly, quarterly, annually)
- Automatic payment confirmations and receipts
- Self-service subscription management options

**Financial Management**
- Real-time payment status tracking
- Automated Sales Invoice creation and reconciliation
- Comprehensive financial dashboard with balance monitoring
- Integration with existing ERPNext accounting workflows

### How It Works

1. **Member Setup**: Members are configured with Mollie payment method and subscription details
2. **Automatic Billing**: Membership Dues Schedules generate Sales Invoices automatically
3. **Payment Processing**: Mollie handles the payment collection via various methods
4. **Webhook Processing**: Successful payments automatically create Payment Entries
5. **Reconciliation**: Payments are automatically matched to invoices and member records
6. **Reporting**: All transactions are tracked in Member Payment History and financial reports

---

## Prerequisites & Requirements

### System Requirements

**Technical Prerequisites**
- ERPNext/Frappe Framework v15+
- Verenigingen app installed and configured
- Internet connectivity for API communication
- SSL certificate for webhook endpoints

**Mollie Account Requirements**
- Active Mollie business account
- Verified business registration with KvK (Chamber of Commerce)
- Completed Mollie onboarding process
- API access enabled (free with Mollie account)

**Permissions Required**
- System Manager or Verenigingen Administrator role
- Access to Mollie Settings configuration
- Permission to modify member payment methods

### Mollie Account Setup

**Getting Your Mollie Credentials**
1. **Create Mollie Account**: Visit [www.mollie.com](https://www.mollie.com) and register your business
2. **Complete Verification**: Submit required business documents (KvK registration, bank details)
3. **Enable API Access**: Navigate to Developers → API keys in your Mollie dashboard
4. **Generate Test Keys**: Create test keys for initial setup (starting with `test_`)
5. **Generate Live Keys**: After testing, generate live keys for production

**Required Information**
- **Profile ID**: Found in your Mollie dashboard under Settings → Profiles
- **API Secret Key**: Generated in Developers → API keys (test and live versions)
- **Organization Access Token**: For backend API features (optional, for advanced reporting)

---

## Initial Setup Guide

### Step 1: Configure Mollie Settings

**Accessing Configuration**
1. Navigate to **Verenigingen Payments** workspace
2. Click **Mollie Settings** under Payment Gateways
3. If first time, the system will create a new configuration

**Basic Configuration**
```
Profile ID: [Your Mollie Profile ID]
Secret Key: [Your Test API Secret Key]
Test Mode: ✓ (Enable for initial testing)
```

**Subscription Settings**
```
Enable Subscriptions: ✓
Default Subscription Interval: 1 month
Subscription Description Template: Membership dues for {member_name}
```

**Backend API Settings (Optional)**
```
Enable Backend API: ✓ (For financial dashboard)
Organization Access Token: [Your OAT token]
```

**Click Save** - The system will automatically validate your credentials.

### Step 2: Configure Payment Accounts

**Reconciliation Settings**
Configure the accounting integration for proper financial tracking:

```
Mollie Bank Account: [Select your main bank account]
Mollie Clearing Account: [Create/select clearing account]
Payment Processing Fees Account: [Account for Mollie fees]
```

**Account Setup Example**
- **Mollie Bank Account**: "1020 - ABN AMRO Bank"
- **Mollie Clearing Account**: "1025 - Mollie Payments Clearing"
- **Processing Fees Account**: "6400 - Payment Processing Costs"

### Step 3: Test the Integration

**Using Built-in Test Tools**
1. Open **ERPNext Console** (Settings → Developer → Console)
2. Run connectivity test:
```python
from verenigingen.utils.mollie_test_helpers import *
test_mollie_connectivity()
```

**Create Test Member with Subscription**
```python
# Create test member
result = create_test_member_with_subscription("Test", "User")

# Test subscription creation
test_mollie_subscription_creation(result['member'], 25.0, "1 month")

# Simulate webhook payment
test_mollie_webhook_simulation(result['member'], 25.0)
```

### Step 4: Configure Webhooks

**Automatic Webhook Configuration**
The system automatically configures webhook URLs when you save Mollie Settings:
- **Payment Webhook**: `/api/method/verenigingen.utils.payment_gateways.mollie_webhook`
- **Subscription Webhook**: `/api/method/verenigingen.utils.payment_gateways.mollie_subscription_webhook`

**Mollie Dashboard Configuration**
1. Log into your Mollie dashboard
2. Go to **Developers** → **Webhooks**
3. Verify the webhook URLs are listed and active
4. Test webhook delivery if needed

### Step 5: Go Live

**Switching to Production**
1. Return to **Mollie Settings**
2. Replace test API key with live key
3. Uncheck **Test Mode**
4. Save configuration
5. Test with a small transaction first

---

## Daily Operations Guide

### Setting Up Recurring Payments for Members

**For New Members**
1. **Navigate to Member Record**
   - Go to **Verenigingen** → **Members**
   - Open the member record

2. **Configure Payment Method**
   - Go to **Financial Information** tab
   - Set **Payment Method**: "Mollie"
   - Save the member record

3. **Create Subscription**
   - Use the **Create Subscription** button or
   - Use Script Report to bulk create subscriptions
   ```python
   # In Script Report or Console
   create_member_subscription("MEMBER-NAME", 25.0, "1 month")
   ```

4. **Verify Setup**
   - Check that **Mollie Customer ID** and **Subscription ID** are populated
   - Verify **Subscription Status** shows "active"
   - Confirm **Next Payment Date** is set correctly

**For Existing SEPA Members**
When migrating from SEPA to Mollie:
1. **Cancel existing SEPA mandates** (optional, can run parallel initially)
2. **Update payment method** to Mollie
3. **Create Mollie subscription** with same amount and frequency
4. **Verify first payment** processes correctly before deactivating SEPA

### Managing Subscription Statuses

**Monitoring Active Subscriptions**
- **Dashboard View**: Verenigingen Payments workspace shows active Mollie subscriptions
- **Member Lists**: Filter members by `payment_method = "Mollie"` and `subscription_status = "active"`
- **Real-time Status**: Member records show current subscription status and next payment date

**Common Status Values**
- **active**: Subscription processing normally
- **pending**: Awaiting first payment or payment in process
- **cancelled**: Subscription terminated (manually or by member)
- **suspended**: Temporarily paused (usually due to payment failures)
- **completed**: Fixed-term subscription completed

**Status Management Actions**
```python
# Check subscription status
get_member_subscription_status("MEMBER-NAME")

# Cancel subscription
cancel_member_subscription("MEMBER-NAME")

# Get subscription details
get_mollie_subscription_status("MEMBER-NAME")
```

### Processing Payment Failures and Retries

**Automatic Retry Logic**
Mollie automatically retries failed payments according to their schedule:
- **1st retry**: 2 days after initial failure
- **2nd retry**: 7 days after initial failure
- **3rd retry**: 14 days after initial failure
- **Final action**: Subscription cancelled if all retries fail

**Manual Intervention Process**
1. **Identify Failed Payments**
   - Monitor webhook notifications
   - Check Member Payment History for gaps
   - Review Mollie dashboard for failed charges

2. **Contact Member**
   - Send payment failure notification
   - Request updated payment method if needed
   - Provide alternative payment options

3. **Resolve Issues**
   - Update member payment details if needed
   - Manually retry payment through Mollie dashboard
   - Create manual Payment Entry if payment received via other method

### Handling Refunds and Adjustments

**Processing Refunds**
1. **Identify Refund Request**
   - Member request or administrative decision
   - Overpayment or duplicate payment

2. **Process via Mollie Dashboard**
   - Log into Mollie dashboard
   - Find the original payment
   - Process partial or full refund

3. **Update ERPNext Records**
   - Create Credit Note for the refunded amount
   - Update Member Payment History
   - Add notes to member record

**Fee Adjustments**
For members requiring different dues amounts:
1. **Update Membership Dues Schedule** with new amount
2. **Cancel existing Mollie subscription**
3. **Create new subscription** with updated amount
4. **Notify member** of the change

### Payment Reconciliation

**Automatic Reconciliation Process**
The system automatically reconciles payments when webhooks are received:
1. **Webhook Received**: Mollie sends payment notification
2. **Find Member**: System locates member with subscription ID
3. **Match Invoice**: Finds most recent unpaid Sales Invoice
4. **Create Payment Entry**: Automatically creates and submits Payment Entry
5. **Update Records**: Updates Member Payment History and subscription status

**Manual Reconciliation**
For payments requiring manual handling:
1. **Identify Unmatched Payments** in Mollie dashboard
2. **Find corresponding member** and invoice in ERPNext
3. **Create Payment Entry manually**:
   - Payment Type: Receive
   - Party: Customer (linked to member)
   - Reference No: Mollie payment ID
   - Amount: Payment amount
   - Link to Sales Invoice

### Monitoring Financial Dashboard

**Accessing the Dashboard**
- **URL**: `/mollie_dashboard` (from any ERPNext page)
- **Navigation**: Verenigingen Payments → Mollie Dashboard link
- **Auto-refresh**: Dashboard updates every 30 seconds

**Key Metrics Displayed**
- **Current Balance**: Available funds in Mollie account
- **Pending Balance**: Payments awaiting settlement
- **Revenue Metrics**: Weekly, monthly, quarterly revenue
- **Recent Settlements**: Latest transfers to your bank
- **Reconciliation Status**: Percentage of payments reconciled

**Dashboard Interpretation**
- **Green indicators**: Normal operations
- **Yellow/Orange**: Attention needed (pending items)
- **Red indicators**: Issues requiring immediate action

---

## Administrative Functions

### Dashboard and Reporting Capabilities

**Financial Dashboard Features**
- **Real-time balance monitoring** from Mollie accounts
- **Settlement tracking** with automatic reconciliation
- **Revenue analysis** across multiple time periods
- **Cost breakdown** including transaction fees
- **Reconciliation status** with success rates

**Accessing Reports**
1. **Mollie Balance Report**
   - Navigate to **Reports** → **Mollie Balance Report**
   - Shows real-time balance data with multi-currency support
   - Export capabilities for accounting integration

2. **Member Payment Analysis**
   - **Overdue Member Payments**: Lists unpaid invoices
   - **Membership Dues Coverage**: Analyzes payment coverage
   - **Revenue Projections**: Forecasts based on active subscriptions

### Payment History Tracking

**Member-Level Tracking**
Each member record maintains comprehensive payment history:
- **Payment History Tab**: Shows all payments with details
- **Automatic Updates**: Webhook processing updates history automatically
- **Manual Entries**: Can add manual payments if needed

**System-Level Tracking**
- **Payment Entry Documents**: Standard ERPNext payment tracking
- **Sales Invoice Integration**: Links payments to specific invoices
- **Mollie Audit Log**: Tracks all Mollie API interactions

### Subscription Management

**Bulk Operations**
```python
# Create subscriptions for all SEPA members
members = frappe.get_all("Member",
    filters={"payment_method": "SEPA Direct Debit", "status": "Active"})
for member in members:
    create_member_subscription(member.name, 25.0, "1 month")

# Cancel all subscriptions (emergency procedure)
members = frappe.get_all("Member",
    filters={"payment_method": "Mollie", "subscription_status": "active"})
for member in members:
    cancel_member_subscription(member.name)
```

**Subscription Analytics**
- **Active Subscriptions**: Count and total value
- **Cancellation Rates**: Track churn metrics
- **Payment Success Rates**: Monitor payment reliability
- **Revenue Forecasting**: Predict future income

### Error Handling and Monitoring

**Error Log Monitoring**
1. **Navigate to Error Log** (Settings → Error Log)
2. **Filter by "Mollie"** to see integration-specific errors
3. **Common Error Types**:
   - API authentication failures
   - Network connectivity issues
   - Webhook processing errors
   - Payment reconciliation failures

**Alert Configuration**
Set up monitoring for critical events:
- **Failed webhook deliveries**
- **Payment processing errors**
- **API quota warnings**
- **Balance threshold alerts**

### Financial Reconciliation

**Bank Statement Reconciliation**
1. **Download Mollie settlement data** from dashboard
2. **Match settlements** to bank statements
3. **Reconcile in ERPNext** using Bank Reconciliation tool
4. **Verify all payments** are properly recorded

**Month-End Procedures**
1. **Review Mollie Balance Report** for discrepancies
2. **Reconcile all settlements** for the period
3. **Process any manual adjustments** required
4. **Generate financial reports** for board/accounting

---

## Troubleshooting Guide

### Common Setup Issues

**"Invalid Mollie credentials" Error**
- **Check Profile ID**: Ensure exact copy from Mollie dashboard
- **Verify API Key**: Confirm test/live key matches test mode setting
- **Check Permissions**: Ensure API key has necessary permissions
- **Network Access**: Verify server can reach api.mollie.com

**Webhook Not Receiving Updates**
- **Check URL accessibility**: Ensure webhooks can reach your server
- **Verify SSL certificate**: Mollie requires valid SSL for webhooks
- **Review Mollie logs**: Check webhook delivery logs in Mollie dashboard
- **Test webhook endpoint**: Use curl or webhook testing tools

**Subscription Creation Fails**
- **Verify member has email**: Email required for Mollie customer creation
- **Check amount formatting**: Ensure amount is positive number
- **Validate currency**: Must be EUR for most Dutch operations
- **Review member customer link**: Member must have linked Customer record

### Payment Failure Scenarios

**"No unpaid invoices found" Warning**
- **Check Membership Dues Schedule**: Ensure schedule is active and generating invoices
- **Verify invoice generation**: Run schedule manually to create test invoice
- **Review customer linkage**: Confirm member's customer field is correct
- **Check invoice status**: Ensure invoices are submitted (docstatus = 1)

**Payment Amount Mismatch**
- **Tolerance check**: System allows 1 cent difference for currency precision
- **Manual verification**: Check if partial payment is intentional
- **Schedule review**: Verify dues schedule amount matches subscription
- **Currency conversion**: Check for currency conversion issues

**Failed Payment Processing**
1. **Check Mollie dashboard** for payment status details
2. **Review member's payment method** in Mollie (expired cards, etc.)
3. **Contact member** for payment method update
4. **Process manual payment** if needed via alternative method

### API Connection Problems

**Rate Limiting Issues**
- **Reduce API frequency**: Implement longer delays between calls
- **Use batch processing**: Group operations where possible
- **Monitor quota usage**: Check Mollie dashboard for API limits
- **Contact Mollie support**: For quota increase if needed

**Authentication Errors**
- **Regenerate API keys**: Create new keys if existing ones compromised
- **Check key format**: Ensure proper test_/live_ prefix
- **Verify permissions**: Confirm API key has subscription permissions
- **Update Organization Token**: For backend API features

### Reconciliation Discrepancies

**Unmatched Payments**
1. **Identify orphaned payments** in Mollie dashboard
2. **Check webhook delivery** in Mollie logs
3. **Manual payment entry creation**:
   ```python
   # Create manual payment entry
   manual_payment_confirmation("DONATION-ID", "tr_mollie_payment_id",
                             "Manual reconciliation - webhook missed")
   ```

**Balance Discrepancies**
- **Compare Mollie balance** with ERPNext Payment Entry totals
- **Check settlement timing**: Mollie settles on business days only
- **Review fee calculations**: Verify processing fees are recorded
- **Account for refunds**: Ensure refunds are properly recorded

### Data Integrity Issues

**Missing Subscription IDs**
- **Re-sync from Mollie**: Use API to fetch current subscription status
- **Manual population**: Update member records with correct IDs
- **Data validation script**:
   ```python
   # Validate all Mollie members have subscription IDs
   members = frappe.get_all("Member",
       filters={"payment_method": "Mollie"},
       fields=["name", "mollie_customer_id", "mollie_subscription_id"])
   for member in members:
       if not member.mollie_subscription_id:
           print(f"Missing subscription ID: {member.name}")
   ```

---

## FAQ

### General Questions

**Q: Can we run SEPA and Mollie payments simultaneously?**
A: Yes, members can have different payment methods. You can gradually migrate from SEPA to Mollie by updating individual member payment methods. Both systems will work in parallel.

**Q: What payment methods does Mollie support for our members?**
A: Mollie supports iDEAL, SEPA Direct Debit, credit cards (Visa, Mastercard), Bancontact, and other European payment methods. The specific methods available depend on your Mollie account configuration.

**Q: How long does it take for payments to reach our bank account?**
A: Standard settlements occur on business days, typically 1-2 business days after payment. Exact timing depends on your Mollie settlement schedule and bank processing times.

**Q: Can members change their payment frequency?**
A: Yes, but this requires cancelling the current subscription and creating a new one with the desired interval. This should be done by administrators through the member record.

### Technical Questions

**Q: What happens if our server is down when Mollie sends a webhook?**
A: Mollie will retry webhook delivery multiple times over several days. If all retries fail, you can manually process payments by checking the Mollie dashboard and creating Payment Entries in ERPNext.

**Q: How do we handle members who want to pay annually instead of monthly?**
A: Update their Membership Dues Schedule to "Yearly" frequency, cancel their current Mollie subscription, and create a new subscription with "1 year" interval.

**Q: Can we customize the payment description that members see?**
A: Yes, modify the "Subscription Description Template" in Mollie Settings. Use `{member_name}` as a placeholder for dynamic member names.

**Q: What data does Mollie store about our members?**
A: Mollie stores the customer name, email, and payment method details. No sensitive personal information beyond what's required for payment processing is shared.

### Financial Questions

**Q: How are Mollie processing fees handled?**
A: Configure the "Payment Processing Fees Account" in Mollie Settings. The system can automatically record fees when processing settlements, depending on your accounting integration setup.

**Q: What happens if a member's payment fails repeatedly?**
A: After 3 automatic retry attempts, Mollie cancels the subscription. You'll need to contact the member to resolve payment issues and potentially create a new subscription.

**Q: Can we offer prorated payments for members joining mid-period?**
A: Yes, adjust the first invoice amount in their Membership Dues Schedule or create a custom one-time payment before setting up the regular subscription.

**Q: How do we handle refunds for overpayments?**
A: Process refunds through the Mollie dashboard, then create a Credit Note in ERPNext and update the member's payment history manually.

### Compliance Questions

**Q: Is the integration GDPR compliant?**
A: Yes, the integration follows GDPR requirements. Member consent for payment processing is obtained through membership agreements, and data processing is limited to payment purposes.

**Q: Are transaction records suitable for tax audits?**
A: Yes, all transactions are recorded in ERPNext with complete audit trails, Payment Entry documents, and links to source documents (Sales Invoices, members).

**Q: How long are payment records retained?**
A: Payment records are retained according to your ERPNext data retention policies. For tax compliance, maintain records for at least 7 years as required by Dutch law.

---

## Technical Reference

### Field Reference

**Member DocType - Mollie Fields**
```
mollie_customer_id: Mollie Customer ID (auto-populated)
mollie_subscription_id: Mollie Subscription ID (auto-populated)
subscription_status: Current status (active/cancelled/pending/suspended)
next_payment_date: Next scheduled payment (auto-updated)
subscription_cancelled_date: When subscription was cancelled
```

**Mollie Settings DocType**
```
profile_id: Mollie Profile ID (required)
secret_key: API Secret Key (encrypted)
test_mode: Enable for testing (boolean)
enable_subscriptions: Allow subscription creation (boolean)
subscription_webhook_url: Auto-generated webhook URL
default_subscription_interval: Default billing frequency
organization_access_token: Backend API token (optional)
mollie_bank_account: Bank account for settlements
```

### API Endpoints

**Webhook Endpoints**
- **Payment Webhook**: `/api/method/verenigingen.utils.payment_gateways.mollie_webhook`
- **Subscription Webhook**: `/api/method/verenigingen.utils.payment_gateways.mollie_subscription_webhook`

**Management Functions**
```python
# Create subscription
create_member_subscription(member_id, amount, interval, description)

# Cancel subscription
cancel_member_subscription(member_id)

# Check status
get_member_subscription_status(member_id)

# Process manual payment
manual_payment_confirmation(donation_id, payment_reference, notes)
```

### Configuration Examples

**Standard Association Setup**
```
Monthly Membership: €25/month
Quarterly Option: €70/quarter (€5 discount)
Annual Option: €270/year (€30 discount)

Payment Methods: iDEAL (primary), SEPA Direct Debit (backup)
Settlement Schedule: Daily to main account
Processing Fees: Recorded to expense account 6400
```

**Large Association Setup**
```
Tiered Membership: €15-€100/month based on income
Payment Processing: Automated with exception handling
Settlement: Weekly to optimize cash flow
Dashboard Monitoring: Real-time alerts for failures
Bulk Operations: Monthly subscription review and updates
```

### Advanced Configuration

**Custom Webhook Processing**
For specialized webhook handling, modify:
```python
# verenigingen/utils/payment_gateways.py
@frappe.whitelist(allow_guest=True)
def mollie_subscription_webhook():
    # Custom processing logic here
    pass
```

**Integration with e-Boekhouden**
The Mollie integration works with existing e-Boekhouden sync:
- Payment Entries sync to e-Boekhouden automatically
- Mollie fees can be mapped to specific expense accounts
- Settlement data provides reconciliation for accounting

**Performance Optimization**
For high-volume associations:
- Enable background job processing for webhook handling
- Implement batch payment processing for efficiency
- Use database indexing on Mollie fields for faster queries
- Configure appropriate cache settings for dashboard data

---

*This guide covers the complete Mollie payment integration for Nederlandse verenigingen. For additional support or advanced customization requirements, consult your system administrator or the development team.*

**Document Version**: 1.0
**Last Updated**: August 2025
**System Compatibility**: ERPNext v15+, Verenigingen App v2.0+
