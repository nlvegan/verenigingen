frappe.query_reports["Team Members"] = {
	"filters": [
		{
			"fieldname": "team",
			"label": __("Team"),
			"fieldtype": "Link",
			"options": "Team",
			"reqd": 1
		}
	]
};
