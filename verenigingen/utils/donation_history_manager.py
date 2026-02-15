"""
Donation History Manager for tracking donation history on donor records.

Inherits BaseHistoryManager for existence checks, recursion guards, and
safe_child_table_update persistence (only syncs the specific child table,
so broken links on unrelated parts of the Donor doc are never validated).
"""

import frappe
from frappe.utils import getdate

from verenigingen.utils.base_history_manager import BaseHistoryManager
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api


class DonationHistoryManager(BaseHistoryManager):
    """Manages donation history tracking for donor records."""

    PARENT_DOCTYPE = "Donor"
    CHILD_TABLE = "donor_history"
    PERMISSION = "Donor:write"
    RECURSION_FLAG = "_updating_donation_history"

    @staticmethod
    def add_donation_entry(donor_name: str, donation_doc) -> dict:
        """Add or update a single donation entry in donor history."""

        def _callback(donor):
            DonationHistoryManager._fix_broken_entries(donor)

            existing_entry = None
            for entry in donor.donor_history:
                if entry.donation_reference == donation_doc.name:
                    existing_entry = entry
                    break

            if existing_entry:
                _update_entry_fields(existing_entry, donation_doc)
            else:
                donor.append("donor_history", _build_entry_dict(donation_doc))

            _sort_history(donor)
            return None  # trigger save

        result = DonationHistoryManager._with_doc(
            donor_name,
            f"add donation entry ({donation_doc.name})",
            _callback,
            error_title="Donation History Add Failed",
        )

        if not result:
            return {"success": False, "error": "; ".join(result.errors)}

        # Determine action from callback context via result message
        existing = (
            any(
                e.donation_reference == donation_doc.name
                for e in frappe.get_doc("Donor", donor_name).donor_history
            )
            if result.success
            else False
        )
        return {"success": True, "action": "updated" if existing else "added", "donation": donation_doc.name}

    @staticmethod
    def remove_donation_entry(donor_name: str, donation_name: str) -> dict:
        """Remove a donation entry from donor history."""

        def _callback(donor):
            for i, entry in enumerate(donor.donor_history):
                if entry.donation_reference == donation_name:
                    donor.donor_history.pop(i)
                    return None  # trigger save
            return True  # not found, nothing to save

        result = DonationHistoryManager._with_doc(
            donor_name,
            f"remove donation entry ({donation_name})",
            _callback,
            error_title="Donation History Remove Failed",
        )

        if not result:
            return {"success": False, "error": "; ".join(result.errors)}
        return {"success": True, "message": f"Removed donation {donation_name} from history"}

    @staticmethod
    def sync_donation_history(donor_name: str) -> dict:
        """Sync donation history from actual donation records."""

        donations = frappe.get_all(
            "Donation",
            filters={"donor": donor_name},
            fields=[
                "name",
                "donation_date",
                "amount",
                "payment_method",
                "status",
                "fund_designation",
                "donation_purpose",
                "paid",
                "docstatus",
                "journal_entry",
            ],
            order_by="donation_date desc",
        )

        def _callback(donor):
            DonationHistoryManager._fix_broken_entries(donor)
            donor.donor_history = []
            for donation in donations:
                if donation.docstatus == 1 or (donation.docstatus == 0 and donation.amount):
                    donor.append(
                        "donor_history",
                        {
                            "donation_reference": donation.name,
                            "donation_date": donation.donation_date,
                            "donation_amount": donation.amount,
                            "payment_method": donation.mode_of_payment,
                            "donation_status": donation.status,
                            "fund_designation": donation.fund_designation,
                            "donation_purpose": donation.donation_purpose,
                            "paid": donation.paid,
                            "journal_entry": donation.journal_entry,
                        },
                    )
            return None  # trigger save

        result = DonationHistoryManager._with_doc(
            donor_name,
            "sync donation history",
            _callback,
            error_title="Donation History Sync Failed",
        )

        if not result:
            return {"success": False, "error": "; ".join(result.errors)}
        return {
            "success": True,
            "donations_synced": len(donations),
            "message": f"Synced {len(donations)} donations to donor history",
        }

    @staticmethod
    def get_donation_summary(donor_name: str) -> dict:
        """Get donation summary statistics (read-only, no _with_doc needed)."""
        try:
            donor = frappe.get_doc("Donor", donor_name)

            if not donor.donor_history:
                return {
                    "total_donations": 0,
                    "total_amount": 0,
                    "paid_amount": 0,
                    "unpaid_amount": 0,
                    "last_donation_date": None,
                    "payment_methods": {},
                }

            total_amount = sum(float(entry.donation_amount or 0) for entry in donor.donor_history)
            paid_amount = sum(
                float(entry.donation_amount or 0) for entry in donor.donor_history if entry.paid
            )

            payment_methods = {}
            for entry in donor.donor_history:
                method = entry.payment_method or "Unknown"
                payment_methods[method] = payment_methods.get(method, 0) + 1

            last_donation_date = None
            if donor.donor_history:
                dates = [entry.donation_date for entry in donor.donor_history if entry.donation_date]
                if dates:
                    last_donation_date = max(dates)

            return {
                "total_donations": len(donor.donor_history),
                "total_amount": total_amount,
                "paid_amount": paid_amount,
                "unpaid_amount": total_amount - paid_amount,
                "last_donation_date": last_donation_date,
                "payment_methods": payment_methods,
            }

        except Exception as e:
            frappe.log_error(f"Error getting donation summary: {str(e)}")
            return {"error": str(e)}

    @staticmethod
    def _fix_broken_entries(donor):
        """Self-healing: fix entries missing mandatory donation_date."""
        broken_entries_fixed = 0
        for entry in donor.donor_history or []:
            if not entry.donation_date:
                if entry.donation_reference:
                    linked_date = frappe.db.get_value("Donation", entry.donation_reference, "donation_date")
                    entry.donation_date = linked_date or frappe.utils.nowdate()
                else:
                    entry.donation_date = frappe.utils.nowdate()
                broken_entries_fixed += 1

        if broken_entries_fixed > 0:
            frappe.logger().info(
                f"Fixed {broken_entries_fixed} broken donor_history entries for {donor.name}"
            )


# --- Private helpers ---


def _update_entry_fields(entry, donation_doc):
    """Update an existing history entry from a donation document."""
    entry.donation_date = donation_doc.donation_date
    entry.donation_amount = donation_doc.amount
    entry.payment_method = donation_doc.mode_of_payment
    entry.donation_status = donation_doc.status
    entry.fund_designation = donation_doc.fund_designation
    entry.donation_purpose = donation_doc.donation_purpose
    entry.paid = donation_doc.paid
    entry.journal_entry = getattr(donation_doc, "journal_entry", None)


def _build_entry_dict(donation_doc) -> dict:
    """Build a child table row dict from a donation document."""
    return {
        "donation_reference": donation_doc.name,
        "donation_date": donation_doc.donation_date,
        "donation_amount": donation_doc.amount,
        "payment_method": donation_doc.mode_of_payment,
        "donation_status": donation_doc.status,
        "fund_designation": donation_doc.fund_designation,
        "donation_purpose": donation_doc.donation_purpose,
        "paid": donation_doc.paid,
        "journal_entry": getattr(donation_doc, "journal_entry", None),
    }


def _sort_history(donor):
    """Sort donor history by date, most recent first."""
    donor.donor_history = sorted(
        donor.donor_history,
        key=lambda x: getdate(x.donation_date) if x.donation_date else getdate("1900-01-01"),
        reverse=True,
    )


# --- Whitelisted API endpoints ---


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def sync_all_donor_histories():
    """Sync donation history for all donors."""
    donors = frappe.get_all("Donor", fields=["name"])
    success_count = 0
    error_count = 0

    for donor in donors:
        result = DonationHistoryManager.sync_donation_history(donor.name)
        if result.get("success"):
            success_count += 1
        else:
            error_count += 1

    return {
        "success": True,
        "donors_processed": len(donors),
        "successful_syncs": success_count,
        "failed_syncs": error_count,
    }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def sync_donor_history(donor_name: str):
    """Sync donation history for a specific donor."""
    return DonationHistoryManager.sync_donation_history(donor_name)


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_donor_summary(donor_name: str):
    """Get donation summary for a donor."""
    return DonationHistoryManager.get_donation_summary(donor_name)


# --- Document event hooks ---


def on_donation_insert(doc, method):
    """Called when a new donation is created."""
    if doc.donor:
        DonationHistoryManager.add_donation_entry(doc.donor, doc)


def on_donation_update(doc, method):
    """Called when a donation is updated."""
    if doc.donor:
        DonationHistoryManager.add_donation_entry(doc.donor, doc)


def on_donation_submit(doc, method):
    """Called when a donation is submitted."""
    if doc.donor:
        DonationHistoryManager.add_donation_entry(doc.donor, doc)


def on_donation_cancel(doc, method):
    """Called when a donation is cancelled."""
    if doc.donor:
        DonationHistoryManager.add_donation_entry(doc.donor, doc)


def on_donation_delete(doc, method):
    """Called when a donation is deleted."""
    if doc.donor:
        DonationHistoryManager.remove_donation_entry(doc.donor, doc.name)
