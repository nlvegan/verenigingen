import frappe

def check_volunteer_history():
    volunteer = frappe.get_doc('Volunteer', 'Assoc-Vol-2025-10-101174')
    history = volunteer.assignment_history or []

    print(f"Volunteer: {volunteer.name}")
    print(f"Total assignment history entries: {len(history)}\n")

    for i, h in enumerate(history):
        print(f"Entry {i+1}:")
        print(f"  Type: {h.assignment_type}")
        print(f"  Reference: {h.reference_doctype} - {h.reference_name}")
        print(f"  Role: {h.role}")
        print(f"  Start Date: {h.start_date}")
        print(f"  End Date: {h.end_date or 'Active'}")
        print(f"  Status: {h.status}")
        print()

    return {"total": len(history), "entries": history}

check_volunteer_history()
