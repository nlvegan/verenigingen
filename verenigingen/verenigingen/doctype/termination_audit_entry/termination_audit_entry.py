from frappe.model.document import Document


class TerminationAuditEntry(Document):
    """Child table (istable: 1) of Membership Termination Request.audit_trail.

    #596: this class used to define validate() (default timestamp and user).
    Frappe never runs it -- there is no d.run_method("validate") for children
    anywhere in insert()/save(). Not moved to the parent: the sole creation site,
    TerminationAuditService.add_entry() (services/termination/
    termination_audit_service.py), always sets both timestamp and user
    explicitly -- the defaults here were always redundant.
    """
