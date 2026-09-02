from frappe.model.document import Document


class EBoekhoudenCostCenterMapping(Document):
    """Child table (istable: 1) of E-Boekhouden Settings.cost_center_mappings.

    #596: this class used to define validate() (auto-fill cost_center_name from
    group_name, strip whitespace). Frappe never runs it -- there is no
    d.run_method("validate") for children anywhere in insert()/save(). The real
    consumer, create_cost_centers_from_mappings() (e_boekhouden_settings.py),
    already strips cost_center_name itself before use, and already treats a blank
    cost_center_name as a reason to SKIP the row (with a logged reason reported
    back to the caller) rather than crash -- so nothing here was a silent gap.
    The auto-fill-from-group_name convenience never actually ran either -- and
    neither does before_insert() (removed alongside validate()): Frappe never
    calls d.run_method("before_insert") for a child row inserted via
    parent.save() either, it calls d.db_insert() directly. Not restoring the
    convenience -- it is a UX nicety, not a correctness rule, and out of #596's
    scope.
    """
