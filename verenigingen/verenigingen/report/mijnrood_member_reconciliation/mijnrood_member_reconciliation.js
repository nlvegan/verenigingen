frappe.query_reports["MijnRood Member Reconciliation"] = {
    filters: [
        {
            fieldname: "discrepancy_only",
            label: __("Discrepancies only"),
            fieldtype: "Check",
            default: 1,
        },
        {
            fieldname: "include_terminated",
            label: __("Include terminated (Quit/Banned/Deceased/Rejected/Expired)"),
            fieldtype: "Check",
            default: 0,
        },
    ],
};
