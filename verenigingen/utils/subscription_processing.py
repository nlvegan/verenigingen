import frappe
from frappe import _
from frappe.utils import add_days, add_months, getdate


class SubscriptionHandler:
    """
    Custom handler for subscription processing in Verenigingen app
    Works around the 'Current Invoice Start Date' validation error in ERPNext
    """

    def __init__(self, subscription_name=None):
        self.subscription_name = subscription_name
        self.subscription = None
        if subscription_name:
            self.subscription = frappe.get_doc("Subscription", subscription_name)

    def process_subscription(self):
        """Process a subscription to generate the next invoice"""
        if not self.subscription:
            return False

        # Skip if subscription is not active
        if self.subscription.status != "Active":
            return False

        # Check if we're dealing with an annual or long-term subscription
        is_long_term = self._is_long_term_subscription()
        if not is_long_term:
            # For regular subscriptions, just call the standard process method
            try:
                self.subscription.process()
                return True
            except Exception as e:
                frappe.log_error(
                    f"Error processing standard subscription {self.subscription.name}: {str(e)}",
                    "Subscription Processing Error",
                )
                return False

        # For long-term subscriptions, we need special handling
        return self._process_long_term_subscription()

    def _is_long_term_subscription(self):
        """Check if this is a long-term subscription (annual or longer)"""
        if not self.subscription:
            return False

        # Get billing info from subscription plans
        try:
            billing_info = self.subscription.get_billing_cycle_and_interval()
            if not billing_info:
                return False

            # Get the billing interval from the first plan
            billing_interval = billing_info[0].get("billing_interval")
            billing_interval_count = billing_info[0].get("billing_interval_count")

            # Check for annual subscription
            if billing_interval == "Year":
                return True

            # Check for monthly billing with long intervals
            if billing_interval == "Month" and billing_interval_count >= 12:
                return True

            # Rest of the method...
        except Exception as e:
            frappe.log_error(f"Error determining subscription length: {str(e)}", "Subscription Length Error")
            return False

    def cancel_subscription(self):
        """Cancel a subscription using direct DB operations to bypass validation"""
        if not self.subscription:
            return False

        # Update the subscription directly in the database
        frappe.db.set_value(
            "Subscription",
            self.subscription_name,
            {"status": "Cancelled", "cancellation_date": frappe.utils.today()},
            update_modified=False,
        )

        # Add a comment to record this action
        frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Subscription",
                "reference_name": self.subscription_name,
                "content": "Subscription cancelled via custom handler",
            }
        ).insert(ignore_permissions=True)

        # Reload the subscription
        self.subscription.reload()

        return True

    def _process_long_term_subscription(self):
        """Handle long-term subscription processing to avoid date validation errors"""
        try:
            # Check if invoice needs to be generated
            if not self._should_generate_invoice():
                return False

            # Create invoice directly
            invoice = self._generate_invoice_directly()
            if not invoice:
                return False

            # Log success
            frappe.logger().info(
                f"Successfully created invoice {invoice} for subscription {self.subscription.name} using custom handler"
            )
            return True

        except AttributeError as e:
            # Handle missing attributes
            if "'Subscription' object has no attribute 'billing_interval'" in str(e):
                frappe.log_error(
                    f"Missing billing_interval for subscription {self.subscription.name}. Please set billing details.",
                    "Subscription Attribute Error",
                )
            raise
        except Exception as e:
            frappe.log_error(
                f"Error in custom subscription processing for {self.subscription.name}: {str(e)}",
                "Custom Subscription Processing Error",
            )
            return False

    def _should_generate_invoice(self):
        """Check if an invoice should be generated for this subscription"""
        if not self.subscription:
            return False

        # Check if we're near the end of the current period
        current_end = getdate(self.subscription.current_invoice_end)
        today = getdate(frappe.utils.today())

        # If generate_invoice_at is set to beginning of period, check against current_invoice_start
        if self.subscription.generate_invoice_at == "Beginning of the current subscription period":
            # If we're at or after the start date of a period, generate invoice
            current_start = getdate(self.subscription.current_invoice_start)
            if today >= current_start:
                # Check if invoice was already generated for this period
                if self._invoice_exists_for_period(current_start, current_end):
                    return False
                return True

        # Otherwise, check if we're at or after the end date
        elif today >= current_end:
            # Check if invoice was already generated for this period
            if self._invoice_exists_for_period(
                self.subscription.current_invoice_start, self.subscription.current_invoice_end
            ):
                return False
            return True

        return False

    def _invoice_exists_for_period(self, start_date, end_date):
        """Check if an invoice already exists for the given period"""
        if not self.subscription:
            return False

        # Convert dates to strings for comparison
        start_str = getdate(start_date).strftime("%Y-%m-%d")
        end_str = getdate(end_date).strftime("%Y-%m-%d")

        # Check invoices in the subscription
        for invoice_ref in self.subscription.invoices:
            try:
                invoice = frappe.get_doc("Sales Invoice", invoice_ref.invoice)
                # Check if this invoice's period matches our target period
                if hasattr(invoice, "subscription_start_date") and hasattr(invoice, "subscription_end_date"):
                    inv_start = getdate(invoice.subscription_start_date).strftime("%Y-%m-%d")
                    inv_end = getdate(invoice.subscription_end_date).strftime("%Y-%m-%d")
                    if inv_start == start_str and inv_end == end_str:
                        return True
            except Exception:
                # If we can't check the invoice, just continue
                continue

        return False

    def _generate_invoice_directly(self):
        """Generate an invoice directly without using subscription.process()"""
        if not self.subscription:
            return None

        # Calculate from_date and to_date for the invoice
        from_date = self.subscription.current_invoice_start
        to_date = self.subscription.current_invoice_end

        # Create a new sales invoice
        invoice = frappe.new_doc("Sales Invoice")

        # Set basic invoice properties
        invoice.customer = self.subscription.party if self.subscription.party_type == "Customer" else None
        invoice.posting_date = frappe.utils.today()
        invoice.subscription = self.subscription.name

        # Add subscription dates
        invoice.subscription_start_date = from_date
        invoice.subscription_end_date = to_date

        # Set due date if days_until_due is set
        if self.subscription.days_until_due:
            invoice.due_date = add_days(invoice.posting_date, self.subscription.days_until_due)

        # Set company
        invoice.company = self.subscription.company

        # Add items from subscription plans
        for plan in self.subscription.plans:
            plan_doc = frappe.get_doc("Subscription Plan", plan.plan)

            # Add the item
            invoice.append(
                "items",
                {
                    "item_code": plan_doc.item,
                    "qty": plan.qty,
                    "rate": plan_doc.cost,
                    "description": f"{self.subscription.name}: {from_date} to {to_date}",
                },
            )

        # Set cost center if specified
        if self.subscription.cost_center:
            for item in invoice.items:
                item.cost_center = self.subscription.cost_center

        # Save invoice
        invoice.flags.ignore_permissions = True
        invoice.set_missing_values()
        invoice.save()

        # Submit invoice if required
        if self.subscription.submit_invoice:
            invoice.submit()

        # Add invoice to subscription's invoice list
        self.subscription.append(
            "invoices",
            {"invoice": invoice.name, "posting_date": invoice.posting_date, "document_type": "Sales Invoice"},
        )

        # Calculate next invoice dates
        next_start_date = add_days(to_date, 1)

        # Calculate next end date based on billing interval
        if self.subscription.billing_interval == "Month":
            next_end_date = add_months(next_start_date, self.subscription.billing_interval_count)
            # Subtract one day to make it inclusive
            next_end_date = add_days(next_end_date, -1)
        elif self.subscription.billing_interval == "Year":
            next_end_date = add_months(next_start_date, 12 * self.subscription.billing_interval_count)
            # Subtract one day to make it inclusive
            next_end_date = add_days(next_end_date, -1)
        else:
            # For other intervals, just add 30 days per month as approximation
            days_to_add = 30 * self.subscription.billing_interval_count
            if self.subscription.billing_interval == "Week":
                days_to_add = 7 * self.subscription.billing_interval_count
            elif self.subscription.billing_interval == "Day":
                days_to_add = self.subscription.billing_interval_count

            next_end_date = add_days(next_start_date, days_to_add - 1)

        # Update the subscription with new dates - DIRECTLY in the database
        frappe.db.set_value(
            "Subscription",
            self.subscription.name,
            {
                "invoices": self.subscription.invoices,
                "current_invoice_start": next_start_date,
                "current_invoice_end": next_end_date,
            },
            update_modified=False,
        )

        # Refresh the document
        self.subscription.reload()

        return invoice.name


# Functions to be called from hooks or API endpoints


def process_all_subscriptions():
    """
    Process all active subscriptions using custom handler
    Can be scheduled daily
    """
    subscriptions = frappe.get_all(
        "Subscription", filters={"status": "Active", "docstatus": 1}, fields=["name"]
    )

    count = 0
    for subscription in subscriptions:
        try:
            handler = SubscriptionHandler(subscription.name)
            if handler.process_subscription():
                count += 1
        except Exception as e:
            frappe.log_error(
                f"Error processing subscription {subscription.name}: {str(e)}",
                "Subscription Processing Error",
            )

    return f"Processed {count} subscriptions with custom handler"


@frappe.whitelist()
def process_subscription(subscription_name):
    """
    Process a specific subscription using custom handler
    Can be called from UI or API
    """
    handler = SubscriptionHandler(subscription_name)
    result = handler.process_subscription()

    if result:
        frappe.msgprint(_("Subscription processed successfully"))
    else:
        frappe.msgprint(_("No invoice generated at this time"))

    return result
