"""A Membership Dues Schedule referenced by a submitted Sales Invoice.

Shared by `test_member_cleanup_service.py` (the #1306 guard's own unit tests)
and `test_enhanced_test_factory_drain.py` (#1306 round 4's harness-drain
regression test) -- both need the exact same shape: a schedule that a real,
submitted Sales Invoice references via `membership_dues_schedule_display`, so
`MemberCleanupService._find_blocked_schedules` refuses to let it (and its
Member) be deleted. Extracted here after `scripts/validation/
duplicate_helper_validator.py` flagged the two independently-written copies
as a near-identical pair (#1306 round 4 self-review).
"""

import frappe


def make_referenceable_dues_schedule(test_case, member):
    """A schedule keyed to `member`. Deliberately does NOT clear the
    Member's own current_dues_schedule / application_dues_schedule
    back-link that a bare insert sets as a save() side effect (confirmed
    empirically) -- #1264 round 2's review caught that clearing it here
    would hide whether the fix (handle_member_deletion calling
    clear_member_schedule_backlinks_before_delete) actually handles that
    back-link itself. The caller is expected to ALSO reference this schedule
    from a Sales Invoice (make_submitted_invoice_for_schedule), which is the
    reference that must still block the delete.
    """
    mt_name = frappe.db.get_value("Membership Type", {}, "name")
    schedule = frappe.new_doc("Membership Dues Schedule")
    schedule.schedule_name = f"CLEANUP-ERRLOG-{frappe.generate_hash(length=6)}"
    schedule.membership_type = mt_name
    schedule.member = member.name
    schedule.status = "Active"
    schedule.billing_frequency = "Annual"
    schedule.currency = "EUR"
    schedule.is_template = 0
    schedule.dues_rate = 25
    schedule.flags.ignore_validate = True
    schedule.insert(ignore_permissions=True, ignore_mandatory=True)
    return schedule


def make_submitted_invoice_for_schedule(test_case, schedule_name, customer=None):
    """A submitted invoice referencing `schedule_name`.

    `customer`: pass explicitly when the caller's own Member/Customer must
    NOT be entangled with this invoice's own `customer_address` -- e.g. when
    the caller will exercise the ORDINARY (non-anonymized) Member-deletion
    cascade, which reaches Customer/Address handling and can collide with an
    invoice still referencing the SAME Customer's Address (#1306 round 4,
    unrelated to the guard itself -- see #1346's "second, independent
    contributor" note). Defaults to an arbitrary existing Customer, which is
    fine for callers that only exercise the anonymize-instead-of-delete path
    (the whole cascade, including Customer handling, is skipped there).
    """
    company = "_Test Company"
    if not customer:
        customer = frappe.db.get_value("Customer", {}, "name")
    item = frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
    income_account = frappe.db.get_value(
        "Account",
        {
            "company": company,
            "account_type": "Income Account",
            "is_group": 0,
            "account_currency": frappe.db.get_value("Company", company, "default_currency"),
        },
        "name",
    )
    cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
    invoice = frappe.new_doc("Sales Invoice")
    invoice.customer = customer
    invoice.company = company
    invoice.membership_dues_schedule_display = schedule_name
    invoice.set_posting_time = 1
    invoice.append(
        "items",
        {
            "item_code": item,
            "qty": 1,
            "rate": 25,
            "income_account": income_account,
            "cost_center": cost_center,
        },
    )
    invoice.insert(ignore_permissions=True)
    invoice.submit()
    return invoice
