# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""SEPA Mandate audit-trail hooks.

Wires the compliance audit trail (``SEPAAuditLog``) into the SEPA Mandate
document lifecycle so that every mandate creation and status change is recorded
automatically — regardless of the entry point that created it (self-service
portal, member API, import, or service). Previously the ``SEPAAuditLog.log_*``
helpers existed and were unit-tested but nothing called them on mandate save, so
there was no automatic compliance trail for mandate lifecycle events.

Registered via ``hooks/doc_events.py`` under "SEPA Mandate":
  - ``after_insert`` -> :func:`log_mandate_created`
  - ``on_update``    -> :func:`log_mandate_status_change`

``on_update`` (not ``after_save``) is used deliberately: ``after_save`` did not
fire for this doctype in practice, whereas ``on_update`` reliably runs once per
save. Status changes are therefore captured only when they flow through the
document ``save()`` path — a direct ``frappe.db.set_value(... "status" ...)`` or
raw SQL would bypass the audit trail (there are no such writes to
``SEPA Mandate.status`` in the codebase today).

Audit writes are best-effort: a failure to log must never block the mandate
operation itself, and the underlying ``log_sepa_event`` already swallows and
logs its own errors. The IBAN is masked by ``log_mandate_creation`` before it is
persisted (GDPR); status-change details carry only the masked IBAN.
"""

import frappe

from verenigingen.verenigingen_payments.doctype.sepa_audit_log.sepa_audit_log import SEPAAuditLog


def _mask_iban(iban):
    """Mask an IBAN for audit details, matching log_mandate_creation's format."""
    if iban and len(iban) > 8:
        return iban[:4] + "****" + iban[-4:]
    return "****"


def log_mandate_created(doc, method=None):
    """after_insert: record the creation of a SEPA Mandate in the audit trail."""
    try:
        member = frappe.get_doc("Member", doc.member) if doc.get("member") else None
        SEPAAuditLog.log_mandate_creation(
            member=member,
            mandate=doc,
            iban=doc.get("iban"),
            bic=doc.get("bic"),
            success=True,
        )
    except Exception as e:
        # Audit logging must never break mandate creation.
        frappe.log_error(f"SEPA mandate creation audit logging failed for {doc.name}: {str(e)}")


def log_mandate_status_change(doc, method=None):
    """on_update: record a SEPA Mandate status transition in the audit trail.

    Skips the initial insert (handled by :func:`log_mandate_created`) and any save
    that does not actually change ``status``.
    """
    try:
        previous = doc.get_doc_before_save()
        if previous is None:
            # This is the creating save; creation is logged by after_insert.
            return
        if previous.get("status") == doc.get("status"):
            return

        # Note: the controller's validate() recomputes status via
        # set_status_based_on_dates(), so an unrelated save of a date-expired mandate
        # legitimately emits one Active->Expired entry — this captures the real
        # transition at persist time. It is self-limiting: once persisted as Expired
        # the equality check above suppresses re-logging, and enforce_terminal_status()
        # prevents a flip-back.

        SEPAAuditLog.log_sepa_event(
            process_type="Mandate Creation",
            reference_doc=doc,
            action="mandate_status_changed",
            details={
                "member": doc.get("member"),
                "mandate_id": doc.get("mandate_id"),
                "previous_status": previous.get("status"),
                "new_status": doc.get("status"),
                "iban_masked": _mask_iban(doc.get("iban")),
                "compliance_status": "Compliant",
                "sensitive_data": True,
            },
        )
    except Exception as e:
        frappe.log_error(f"SEPA mandate status-change audit logging failed for {doc.name}: {str(e)}")
