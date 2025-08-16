frappe.listview_settings['Chapter Join Request'] = {
	get_indicator(doc) {
		if (doc.status === 'Pending') {
			return [__('Pending'), 'orange', 'status,=,Pending'];
		} else if (doc.status === 'Approved') {
			return [__('Approved'), 'green', 'status,=,Approved'];
		} else if (doc.status === 'Rejected') {
			return [__('Rejected'), 'red', 'status,=,Rejected'];
		}
	},

	onload(listview) {
		// Add custom filters for chapter board members
		listview.page.add_menu_item(__('My Chapter Requests'), () => {
			// Filter to show only requests for chapters where current user is a board member
			frappe.call({
				method: 'verenigingen.api.chapter_join.get_user_chapter_requests',
				callback(r) {
					if (r.message && r.message.chapters) {
						listview.filter_area.add([
							['Chapter Join Request', 'chapter', 'in', r.message.chapters]
						]);
					}
				}
			});
		});

		// Add quick approval actions
		if (frappe.user.has_role(['Verenigingen Manager', 'Verenigingen Chapter Board Member'])) {
			listview.page.add_actions_menu_item(__('Bulk Approve'), () => {
				const selected = listview.get_checked_items();
				if (selected.length === 0) {
					frappe.msgprint(__('Please select requests to approve'));
					return;
				}

				frappe.confirm(
					__('Approve {0} selected request(s)?', [selected.length]),
					() => {
						frappe.call({
							method: 'verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request.bulk_approve_requests',
							args: {
								request_names: selected.map(item => item.name)
							},
							callback(r) {
								if (r.message) {
									frappe.msgprint(r.message);
									listview.refresh();
								}
							}
						});
					}
				);
			});
		}
	}
};
