# verenigingen/hooks/doctypes.py
"""DocType JavaScript mappings.

Maps DocTypes to custom JavaScript files that enhance or override
the default form behavior. These scripts are loaded when viewing
the corresponding DocType forms.
"""

# Custom JavaScript for DocType forms
doctype_js = {
    "Member": "verenigingen/doctype/member/member.js",
    "Membership": "public/js/membership.js",
    "Membership Type": "public/js/membership_type.js",
    "Chapter": "public/js/chapter_email_integration.js",
    "Direct Debit Batch": "public/js/direct_debit_batch.js",
    "Membership Termination Request": "public/js/membership_termination_request.js",
    "Expense Claim": "public/js/expense_claim_custom.js",
    "Customer": "public/js/customer_member_link.js",
    "Sales Invoice": "public/js/sales_invoice_ing_checkout.js",
}

# Custom JavaScript for DocType list views (currently unused)
# doctype_list_js = {
#     "Membership Termination Request": "public/js/membership_termination_request_list.js",
#     "Termination Appeals Process": "public/js/termination_appeals_process_list.js",
# }
