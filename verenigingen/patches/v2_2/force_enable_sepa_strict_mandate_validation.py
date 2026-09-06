"""#631: turn on `Verenigingen Settings.sepa_strict_mandate_validation` for every site.

Without strict mode, a mandate whose sign date cannot be resolved silently gets
`DtOfSgntr` = today's date in the generated SEPA XML -- a signature date the
system does not actually know, sent to the bank as fact. Strict mode is the
designed safety net for this (`_handle_validation_issues` in
`sepa_xml_adapter.py` refuses the batch instead, naming the invoice/mandate),
but it shipped **off** by default, so the net caught nothing anywhere nobody
had ticked the box -- including production.

This is a FORCED overwrite, not the usual "seed only if unset" pattern (see
`seed_enable_dutch_name_fields.py`): a Check field on a Single doctype is
unconditionally rewritten by `update_single()` on every full-document save (it
deletes and reinserts every field's row -- `frappe/model/document.py`), so an
install whose Settings page has ever been saved even once already carries an
EXPLICIT stored `0` for this field -- indistinguishable in `tabSingles` from a
deliberate opt-out. Measured on veg11.veganisme.org: `tabSingles` already has
an explicit `0` row for this field, from ordinary use of the Settings page,
not a deliberate choice about mandate validation specifically. A "seed only if
unset" patch would therefore be a no-op for every already-deployed site and
would only protect installs created after this patch ships -- missing the
installs the issue is actually about.

Flipping the default to strict is a deliberate, security-relevant policy
change (#631), so this patch forces the new default onto every site rather
than only new ones. It is not destructive to the escape hatch: the field
stays a real, working toggle, and an administrator who needs permissive mode
can switch it back off afterward with full knowledge of the tradeoff (the
field's description now says so). Before writing this patch, the blast radius
was measured read-only on veg11.veganisme.org (a copy of another test
system's data, not a production figure): 0 of 65 Active SEPA Mandates are
missing a sign date, and 0 of 13 Direct Debit Batch Invoice rows reference a
mandate that fails to resolve one -- so turning strict mode on there today
would not have blocked anything.
"""

import frappe


def execute():
    frappe.reload_doc("verenigingen", "doctype", "verenigingen_settings")
    frappe.db.set_single_value("Verenigingen Settings", "sepa_strict_mandate_validation", 1)
