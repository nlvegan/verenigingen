frappe.listview_settings['Donation'] = {
	add_fields: ["donor", "amount", "paid", "payment_method", "date"],
	get_indicator: function(doc) {
		return [__(doc.paid ? "Paid" : "Pending"),
			doc.paid ? "green" : "orange", "paid,=," + doc.paid];
	}
};
