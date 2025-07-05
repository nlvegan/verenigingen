frappe.listview_settings['Membership'] = {
	get_indicator: function(doc) {
		if (doc.status === 'Draft') {
			return [__('Draft'), 'gray', 'status,=,Draft'];
		} else if (doc.status === 'Active') {
			return [__('Active'), 'green', 'status,=,Active'];
		} else if (doc.status === 'Pending') {
			return [__('Pending'), 'yellow', 'status,=,Pending'];
		} else if (doc.status === 'Inactive') {
			return [__('Inactive'), 'orange', 'status,=,Inactive'];
		} else if (doc.status === 'Expired') {
			return [__('Expired'), 'gray', 'status,=,Expired'];
		} else if (doc.status === 'Cancelled') {
			return [__('Cancelled'), 'red', 'status,=,Cancelled'];
		}
		// Default fallback
		return [doc.status || __('Unknown'), 'gray'];
	}
};
