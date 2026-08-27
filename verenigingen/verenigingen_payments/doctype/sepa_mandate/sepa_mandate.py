# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.validation_utilities import DateRangeValidator, DocumentExistenceValidator
from verenigingen.verenigingen_payments.services.sepa_mandate_identity_service import (
    sepa_mandate_identity_service,
)
from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
    sepa_mandate_lifecycle_service,
)
from verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service import (
    sepa_mandate_member_integration_service,
)
from verenigingen.verenigingen_payments.services.sepa_mandate_validation_service import (
    sepa_mandate_validation_service,
)
from verenigingen.verenigingen_payments.utils.mandate_candidates import (
    PURPOSE_FLAGS,
    PURPOSE_LABELS,
)
from verenigingen.verenigingen_payments.utils.sepa_mandate_service import (
    invalidate_mandate_cache_for_member,
)


class SEPAMandate(Document):
    def validate(self):
        self.set_scheme_default()
        self.auto_generate_mandate_id()
        self.enforce_terminal_status()
        self.validate_dates()
        self.validate_iban()
        self.set_status_based_on_dates()

        # Also synchronize status and is_active flag during validation
        self.sync_status_is_active()

        # Run last: relies on the normalized IBAN (set by validate_iban) and the
        # final status (set by set_status_based_on_dates / sync_status_is_active).
        self.validate_active_mandate_has_a_purpose()
        self.validate_single_active_mandate_per_purpose()

    def enforce_terminal_status(self):
        """Prevent reactivating a mandate that is in a terminal state.

        Cancelled and Expired are terminal SEPA mandate states: a cancelled or
        expired mandate must not be reverted to Active/Suspended. The correct
        workflow is to create a NEW mandate. Without this guard the status field
        could be flipped back to Active on a later save, silently resurrecting a
        revoked authorization. (set_value already treats these states specially.)
        """
        if self.is_new():
            return
        previous_status = frappe.db.get_value("SEPA Mandate", self.name, "status")
        if previous_status in ("Cancelled", "Expired") and self.status != previous_status:
            # Keep the terminal status; do not allow resurrection. We restore
            # silently (rather than throw) so unrelated saves of a terminal mandate
            # still succeed, but log a warning so the rejected transition is visible.
            frappe.logger().warning(
                f"SEPA Mandate {self.name}: blocked status change "
                f"{previous_status} -> {self.status}; keeping {previous_status}."
            )
            self.status = previous_status
            self.is_active = 0

    def validate_active_mandate_has_a_purpose(self):
        """An Active mandate must be marked for at least one purpose (#606).

        `validate_single_active_mandate_per_purpose` loops over the purpose flags
        that are set, so a mandate with NONE of them set had an empty loop and the
        one-Active-per-purpose invariant simply did not apply to it. Two
        all-purposes-zero Active mandates for one member were measured coexisting.

        Bucketing "no purpose" as a fourth purpose would close that hole and leave
        a larger one open. Since #597 every mandate-resolution query filters by
        purpose, so an all-zero Active mandate is found by NONE of them: it is an
        authorization that authorizes nothing, silently, on a member who believes
        they have signed one. Requiring a purpose makes the shape unreachable
        rather than merely unique.

        The realistic producer is Frappe's Data Import. `Document._set_defaults`
        returns early under `frappe.flags.in_import`, so the JSON default
        `used_for_memberships = 1` is NOT applied there. Measured on test_site_1
        against the pre-guard tree: the same `get_doc({...}).insert()` stored
        `used_for_memberships = 1` with the flag off and `0` with it on -- the
        column's `NOT NULL DEFAULT 1` does not rescue it, because Frappe writes an
        explicit 0. So a mandate CSV carrying `Status = Active` and no purpose
        column produced an inert Active mandate and said nothing. It now raises.
        (This is also why issue #606's claim that "Frappe applies the docfield
        default even for `frappe.get_doc(dict).insert()`" is only true with the
        flag off.)

        Scoped to Active, like its sibling: a purposeless Draft or Suspended
        mandate can still be staged, and Cancelled/Expired rows are untouched, so
        this cannot lock an operator out of a mandate they are trying to retire.

        Measured 2026-08-27: `tabSEPA Mandate` holds zero all-zero rows on veg11
        (71 rows, all `used_for_memberships = 1`) and zero on test_site_1. That
        bounds those two sites, not every install -- an install that does hold such
        a row will find it unsaveable while Active until a purpose is ticked.

        NOT the motivating case, though an earlier draft of this docstring said it
        was -- and it is a class of TWO, both deprecated: `api/member/sepa_api.py`'s
        `create_and_link_mandate_enhanced` and `doctype/member/member_utils.py`'s
        `create_and_link_mandate` have the identical shape, and no caller in the
        tree passes 0/0 to either. Taking the first:
        `create_and_link_mandate_enhanced(used_for_memberships=0,
        used_for_donations=0)` computes `wanted = []` and hands it to
        `cancel_active_mandates(purposes=[])`, whose
        `tuple(purposes) if purposes else PURPOSE_FLAGS` reads an empty list as
        "every purpose". But it then calls `carry_forward_purposes` BEFORE
        activating, so whenever anything WAS superseded the replacement inherits
        that purpose and this guard does not fire (measured both ways). The real
        defect there is the widened supersession -- a purposeless request cancels
        the member's donation mandate too and merges it onto one IBAN -- which is
        a separate bug, not this one. This guard only catches the case where
        nothing was cancelled.
        """
        if self.status != "Active":
            return
        if any(self.get(flag) for flag in PURPOSE_FLAGS):
            return

        frappe.throw(
            _(
                "SEPA mandate {0} is Active but is not marked for any purpose. "
                "Every direct debit query filters by purpose, so this mandate can "
                "never be used to collect anything -- and creating it supersedes "
                "the mandates that can. Tick at least one of {1}."
            ).format(self.mandate_id or self.name or _("(new)"), ", ".join(PURPOSE_FLAGS))
        )

    def validate_single_active_mandate_per_purpose(self):
        """At most ONE Active mandate per member PER PURPOSE.

        `SEPA Mandate` carries `used_for_memberships` / `used_for_donations` /
        `used_for_other` as independent checkboxes, and the app genuinely models a
        member holding an Active membership mandate alongside an Active donation
        mandate -- `test_payment_history_writer_parity` has a regression test for
        exactly that shape, and the fix it guards was to make BOTH payment-history
        writers filter on `used_for_memberships = 1`.

        What was never true is that two Active mandates sharing a purpose could be
        told apart. The old guard keyed on member + IBAN, on the stated grounds that
        the older one "supersedes via the Member SEPA Mandate Link `is_current`
        flag". That is not a discriminator:

        - no mandate-resolution query reads `is_current` AT ALL -- they all filter on
          `status` (and, where it matters, on purpose), so even a perfectly
          maintained flag could not have disambiguated a direct debit;
        - it is also unmaintained: both writers compute
          ``is_current = 1 if status == "Active" and is_active else 0``
          (`sepa_mandate_manager.py:678`,
          `sepa_mandate_member_integration_service.py:186`), so two Active mandates
          are BOTH flagged current;
        - the flag-clearing code that runs automatically,
          ``MemberSEPAMandateLink.check_current_mandate``, is never called -- Frappe
          does not run child-DocType ``validate()`` (#596).

        With no discriminator WITHIN a purpose, `get_invoice_mandate_info` fell back
        to `ORDER BY sm.creation DESC LIMIT 1` and debited an arbitrary IBAN (#584).
        Scoping the rule by purpose keeps the capability the app models and removes
        the ambiguity that has money behind it.

        A bank switch is still supported, and is what the sanctioned flow already
        does: cancel the old mandate for that purpose, then activate the new one.
        Draft and Suspended siblings are untouched, so a replacement can be staged.

        This is defence in depth, not the only gate: `frappe.db.set_value` on
        ``status`` bypasses ``validate`` entirely, which is why the read side filters
        by purpose AND refuses a pick that is still ambiguous.
        """
        if self.status != "Active" or not self.member:
            return

        overlapping = [flag for flag in PURPOSE_FLAGS if self.get(flag)]
        if not overlapping:
            # Unreachable for an Active mandate since #606 --
            # validate_active_mandate_has_a_purpose runs first and throws. Kept so
            # this method is safe to call on its own; it used to be the hole that
            # let two all-purposes-zero Active mandates coexist.
            return

        for flag in overlapping:
            existing = frappe.db.get_value(
                "SEPA Mandate",
                {
                    "member": self.member,
                    "status": "Active",
                    flag: 1,
                    "name": ["!=", self.name or ""],
                },
                ["name", "mandate_id", "iban"],
                as_dict=True,
            )
            if not existing:
                continue

            # Name the blocking mandate AND the purpose: without both, an operator
            # cannot tell which of a member's mandates to cancel, or why.
            frappe.throw(
                _(
                    "Member {0} already has an active SEPA mandate for {1}: {2} "
                    "(IBAN {3}). Cancel it before activating another one for the same "
                    "purpose -- two active mandates sharing a purpose mean an "
                    "arbitrarily chosen IBAN gets debited."
                ).format(
                    self.member,
                    PURPOSE_LABELS[flag],
                    existing.mandate_id,
                    existing.iban or _("not set"),
                )
            )

    def set_scheme_default(self):
        """Apply the JSON 'SEPA' default for the mandatory scheme field.

        Frappe v16 no longer applies a field's JSON default on a raw
        get_doc({...}).insert() (only at the form layer), so a mandate created
        without an explicit scheme hits a MandatoryError. Mirror the same
        controller-level default pattern used for status/mandate_id.
        """
        if not self.scheme:
            self.scheme = "SEPA"

    def auto_generate_mandate_id(self):
        """Auto-generate mandate_id using identity service"""
        # Only generate if mandate_id is not already set
        if self.mandate_id:
            return

        self.mandate_id = sepa_mandate_identity_service.generate_mandate_id(self)

    def sync_status_is_active(self):
        """Synchronize status and is_active flag using lifecycle service"""
        sepa_mandate_lifecycle_service.sync_status_and_active_flag(self)

    def set_status_based_on_dates(self):
        """Set status based on dates using lifecycle service"""
        self.status = sepa_mandate_lifecycle_service.set_status_based_on_dates(self)

    def set_value(self, fieldname, value):
        """Override set_value for special field handling"""
        # If setting is_active flag, update status accordingly
        if fieldname == "is_active":
            # Only update status if not in these special statuses
            if self.status not in ["Cancelled", "Expired", "Draft"]:
                if value:
                    # When activating, set status to Active
                    super().set_value(fieldname, value)
                    super().set_value("status", "Active")
                else:
                    # When deactivating, set status to Suspended
                    super().set_value(fieldname, value)
                    super().set_value("status", "Suspended")
            else:
                # Just set the is_active value without changing status
                super().set_value(fieldname, value)
        # If setting status, update is_active flag accordingly
        elif fieldname == "status":
            if value == "Active":
                super().set_value(fieldname, value)
                super().set_value("is_active", 1)
            elif value in ["Suspended", "Cancelled", "Expired"]:
                super().set_value(fieldname, value)
                super().set_value("is_active", 0)
            else:
                # Just set the status without changing is_active
                super().set_value(fieldname, value)
        else:
            # For other fields, just use the parent class implementation
            super().set_value(fieldname, value)
        return self

    def validate_dates(self):
        """Validate mandate dates using validation service"""
        validation_result = sepa_mandate_validation_service.validate_mandate_dates(self)

        if not validation_result["is_valid"]:
            frappe.throw("\n".join(validation_result["errors"]))

        # Show warnings if any
        for warning in validation_result["warnings"]:
            frappe.msgprint(warning, alert=True)

    def validate_iban(self):
        """Validate IBAN using validation service"""
        if not self.iban:
            return

        validation_result = sepa_mandate_validation_service.validate_mandate_iban(self)

        if not validation_result["is_valid"]:
            frappe.throw("\n".join(validation_result["errors"]))

        # Show warnings if any
        for warning in validation_result["warnings"]:
            frappe.msgprint(warning, alert=True)

    def after_insert(self):
        """Handle mandate creation using lifecycle service"""
        result = sepa_mandate_lifecycle_service.handle_mandate_creation(self)

        if not result["success"]:
            for error in result["errors"]:
                frappe.msgprint(error, alert=True)

        # Log notifications sent
        if result["notifications_sent"]:
            frappe.logger().info(f"Mandate creation notifications sent: {result['notifications_sent']}")

        # Invalidate cache for this member to ensure fresh data on next lookup
        if self.member:
            invalidate_mandate_cache_for_member(self.member)

    def on_update(self):
        """Handle mandate update using lifecycle service"""
        result = sepa_mandate_lifecycle_service.handle_mandate_update(self)

        if not result["success"]:
            for error in result["errors"]:
                frappe.msgprint(error, alert=True)

        # Log status changes and notifications
        if result["status_changed"]:
            frappe.logger().info(f"Mandate status changed for {self.name}")
        if result["notifications_sent"]:
            frappe.logger().info(f"Mandate update notifications sent: {result['notifications_sent']}")

        # Invalidate cache for this member to ensure fresh data on next lookup
        if self.member:
            invalidate_mandate_cache_for_member(self.member)

    def update_member_sepa_mandates_table(self):
        """Update the member's SEPA mandates child table using member integration service"""
        if not self.member:
            return

        result = sepa_mandate_member_integration_service.update_member_mandate_relationship(self)

        if not result["success"]:
            frappe.throw("\n".join(result["errors"]))

        # Show warnings if any
        for warning in result.get("warnings", []):
            frappe.msgprint(warning, alert=True)

    def on_trash(self):
        """Handle mandate deletion - invalidate cache"""
        # Invalidate cache for this member to ensure deleted mandate
        # doesn't appear in cached queries
        if self.member:
            invalidate_mandate_cache_for_member(self.member)


def has_permission(doc, user=None, ptype=None):
    """Custom permission check for SEPA Mandate"""
    if not user:
        user = frappe.session.user

    # Admin roles have full access
    if frappe.db.get_value(
        "Has Role",
        {
            "parent": user,
            "role": ["in", list(Roles.ADMIN_ROLES)],
        },
        "name",
    ):
        return True

    # Members can only access their own mandates
    if frappe.db.get_value("Has Role", {"parent": user, "role": "Verenigingen Member"}, "name"):
        if not doc or not doc.member:
            return False

        # Check if the mandate belongs to this member
        member = frappe.db.get_value("Member", {"email": user}, "name") or frappe.db.get_value(
            "Member", {"user": user}, "name"
        )
        return doc.member == member

    return False


def get_permission_query_conditions(user=None):
    """Custom permission query conditions for SEPA Mandate"""
    if not user:
        user = frappe.session.user

    # Admin roles can see all mandates
    if frappe.db.get_value(
        "Has Role",
        {
            "parent": user,
            "role": ["in", list(Roles.ADMIN_ROLES)],
        },
        "name",
    ):
        return ""

    # Members can only see their own mandates
    if frappe.db.get_value("Has Role", {"parent": user, "role": "Verenigingen Member"}, "name"):
        member = frappe.db.get_value("Member", {"email": user}, "name") or frappe.db.get_value(
            "Member", {"user": user}, "name"
        )
        if member:
            return f"`tabSEPA Mandate`.member = {frappe.db.escape(member)}"

    # Default: no access
    return "1=0"
