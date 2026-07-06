// Copyright (c) 2026, Verenigingen and contributors
// For license information, please see license.txt

frappe.query_reports['Critical Operation Rule Config Density'] = {
	filters: [
		{
			fieldname: 'operation_type',
			label: __('Operation Type'),
			fieldtype: 'Select',
			options: ['', 'financial', 'member_data', 'admin', 'reporting', 'utility', 'public'].join('\n')
		},
		{
			fieldname: 'security_level',
			label: __('Security Level'),
			fieldtype: 'Select',
			options: ['', 'critical', 'high', 'medium', 'low', 'public'].join('\n')
		}
	]
};
