frappe.query_reports["Orphaned Subscriptions Report"] = {
    "filters": [
        {
            "fieldname": "issue_type",
            "label": __("Issue Type"),
            "fieldtype": "Select",
            "options": "\nOrphaned Subscriptions\nInvalid Membership Links\nActive Without Subscription\nCancelled with Active Subscription\nAll Issues",
            "default": "All Issues"
        },
        {
            "fieldname": "from_date",
            "label": __("From Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -6)
        },
        {
            "fieldname": "to_date",
            "label": __("To Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today()
        }
    ],

    "formatter": function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        if (column.fieldname == "issue" && data.issue) {
            value = `<div style="color: #e24c4c;">${value}</div>`;
        }

        if (column.fieldname == "status") {
            if (data.status == "Active") {
                value = `<span class="indicator-pill green">${value}</span>`;
            } else if (data.status == "Cancelled") {
                value = `<span class="indicator-pill red">${value}</span>`;
            } else if (data.status == "Expired") {
                value = `<span class="indicator-pill gray">${value}</span>`;
            } else if (data.status == "Pending") {
                value = `<span class="indicator-pill orange">${value}</span>`;
            }
        }

        return value;
    }
};
