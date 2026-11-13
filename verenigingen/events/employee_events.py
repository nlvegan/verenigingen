"""Employee document event handlers."""


def force_no_user_permission(doc, method=None):
    """#1655: a new Employee never pins its linked user to itself.

    ERPNext's `create_user_permission` defaults to 1 and, when a user is linked, adds User
    Permissions on the Employee and its Company. That hides every other employee's records
    from the user, including Expense Claims they approve. The app's own creation paths already
    set 0; hand-made Employees (Staff, #1606) did not. Insert only: Staff can still tick the box
    later or add User Permissions deliberately.
    """
    doc.create_user_permission = 0
