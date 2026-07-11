"""Context for the payment-plan installment pay page."""

import frappe
from frappe import _

from verenigingen.api.payment_plan_management import get_next_payable_installment
from verenigingen.utils.member_utils import get_current_user_member_name
from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Pay Installment")

    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login"
        raise frappe.Redirect

    plan_name = frappe.form_dict.get("plan")
    member = get_current_user_member_name()
    if not member or not plan_name or not frappe.db.exists("Payment Plan", plan_name):
        context.no_access = True
        context.message = _("Payment plan not found.")
        return context

    plan = frappe.get_doc("Payment Plan", plan_name)
    if plan.member != member:
        context.no_access = True
        context.message = _("You can only pay your own payment plans.")
        return context

    context.plan = plan
    context.member = member
    context.installment = get_next_payable_installment(plan)
    # Phase 1: only online (Mollie) methods are wired for payment plans.
    context.payment_methods = [m for m in PaymentHook.get_available_methods() if m["id"] == "mollie"]
    return context


# Add route configuration
no_cache = 1
sitemap = 0  # Don't include in sitemap
