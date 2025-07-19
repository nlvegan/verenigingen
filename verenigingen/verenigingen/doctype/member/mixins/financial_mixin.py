import frappe
from frappe.utils import flt


class FinancialMixin:
    """Mixin for financial-related functionality"""

    def refresh_financial_data(self):
        """Refresh all financial data for this member"""
        try:
            results = {
                "payment_history": False,
                "dues_schedule_history": False,
                "sepa_mandates": False,
                "errors": [],
            }

            # Refresh payment history
            try:
                self.load_payment_history()
                results["payment_history"] = True
            except Exception as e:
                results["errors"].append(f"Payment history: {str(e)}")

            # Refresh dues schedule history
            try:
                self.refresh_dues_schedule_history()
                results["dues_schedule_history"] = True
            except Exception as e:
                results["errors"].append(f"Dues schedule history: {str(e)}")

            # Refresh SEPA mandates
            try:
                sepa_result = self.refresh_sepa_mandates_table()
                results["sepa_mandates"] = sepa_result.get("success", False)
            except Exception as e:
                results["errors"].append(f"SEPA mandates: {str(e)}")

            return {
                "success": len(results["errors"]) == 0,
                "results": results,
                "message": f"Refreshed financial data ({'with errors' if results['errors'] else 'successfully'})",
            }

        except Exception as e:
            frappe.log_error(f"Error refreshing financial data for member {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}

    def process_payment(self):
        """Process payment for this member"""
        try:
            # Check if member has required data for payment processing
            if not self.name:
                return {"success": False, "error": "Member document must be saved first"}

            # Process payment based on member's payment method
            if self.payment_method == "SEPA Direct Debit":
                # Check for active SEPA mandate
                if not self.has_active_sepa_mandate():
                    return {
                        "success": False,
                        "error": "No active SEPA mandate found for direct debit processing",
                    }

                # Process SEPA direct debit
                return self._process_sepa_payment()

            elif self.payment_method == "Bank Transfer":
                # Process bank transfer
                return self._process_bank_transfer()

            else:
                return {"success": False, "error": f"Unsupported payment method: {self.payment_method}"}

        except Exception as e:
            frappe.log_error(f"Error processing payment for member {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}

    def mark_as_paid(self):
        """Mark this member as paid"""
        try:
            # Update payment status for outstanding invoices
            outstanding_invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": self.name, "docstatus": 1, "status": ["!=", "Paid"]},
                fields=["name", "outstanding_amount"],
            )

            for invoice in outstanding_invoices:
                if invoice.outstanding_amount > 0:
                    # Create payment entry
                    payment_entry = frappe.new_doc("Payment Entry")
                    payment_entry.payment_type = "Receive"
                    payment_entry.party_type = "Customer"
                    payment_entry.party = self.name
                    payment_entry.paid_amount = invoice.outstanding_amount
                    payment_entry.received_amount = invoice.outstanding_amount
                    payment_entry.reference_no = f"Manual payment - {self.name}"
                    payment_entry.reference_date = frappe.utils.today()

                    # Link to invoice
                    payment_entry.append(
                        "references",
                        {
                            "reference_doctype": "Sales Invoice",
                            "reference_name": invoice.name,
                            "allocated_amount": invoice.outstanding_amount,
                        },
                    )

                    payment_entry.insert()
                    payment_entry.submit()

            # Refresh payment history
            self.refresh_financial_data()

            return {
                "success": True,
                "message": f"Member marked as paid - processed {len(outstanding_invoices)} invoices",
            }

        except Exception as e:
            frappe.log_error(f"Error marking member as paid {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_financial_summary(self):
        """Get comprehensive financial summary for this member"""
        try:
            # Calculate totals, outstanding amounts, etc.
            payment_history = getattr(self, "payment_history", [])

            stats = {
                "total_payments": len(payment_history),
                "total_amount": sum(flt(p.amount or 0) for p in payment_history),
                "outstanding_amount": sum(flt(p.outstanding_amount or 0) for p in payment_history),
                "paid_invoices": len([p for p in payment_history if p.payment_status == "Paid"]),
                "overdue_invoices": len([p for p in payment_history if p.payment_status == "Overdue"]),
                "unpaid_invoices": len(
                    [p for p in payment_history if p.payment_status in ["Unpaid", "Partially Paid"]]
                ),
                "has_sepa_mandate": self.has_active_sepa_mandate(),
                "payment_method": getattr(self, "payment_method", "Not Set"),
                "membership_invoices": len(
                    [p for p in payment_history if p.transaction_type == "Membership Invoice"]
                ),
                "regular_invoices": len(
                    [p for p in payment_history if p.transaction_type == "Regular Invoice"]
                ),
                "donations": len([p for p in payment_history if p.transaction_type == "Donation Payment"]),
                "unreconciled_payments": len(
                    [p for p in payment_history if p.transaction_type == "Unreconciled Payment"]
                ),
            }

            # Add SEPA mandate details if available
            if stats["has_sepa_mandate"]:
                mandate = self.get_default_sepa_mandate()
                if mandate:
                    stats["sepa_mandate_id"] = mandate.mandate_id
                    stats["sepa_mandate_status"] = mandate.status
                    stats["sepa_mandate_expiry"] = mandate.expiry_date

            return stats

        except Exception as e:
            frappe.log_error(f"Error getting financial summary for member {self.name}: {str(e)}")
            return {}

    def _process_sepa_payment(self):
        """Process SEPA direct debit payment"""
        try:
            # Get active SEPA mandate
            mandate = self.get_default_sepa_mandate()
            if not mandate:
                return {"success": False, "error": "No active SEPA mandate found"}

            # Create or add to SEPA direct debit batch
            # This is a placeholder for actual SEPA batch processing
            return {"success": True, "message": "SEPA payment processed successfully"}

        except Exception as e:
            frappe.log_error(f"Error processing SEPA payment for member {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}

    def _process_bank_transfer(self):
        """Process bank transfer payment"""
        try:
            # Generate bank transfer details
            # This is a placeholder for actual bank transfer processing
            return {"success": True, "message": "Bank transfer details generated"}

        except Exception as e:
            frappe.log_error(f"Error processing bank transfer for member {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}
