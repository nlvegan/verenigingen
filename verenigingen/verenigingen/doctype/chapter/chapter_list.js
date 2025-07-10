frappe.listview_settings['Chapter'] = {
	add_fields: ['chapter_head', 'region', 'postal_codes', 'published'],
	get_indicator: function(doc) {
		// Debug: log the actual value
		console.log('Chapter:', doc.name, 'published value:', doc.published, 'type:', typeof doc.published);
		return [__(doc.published ? 'Public' : 'Private'),
			doc.published ? 'green' : 'orange', 'published,=,' + doc.published];
	}
};
