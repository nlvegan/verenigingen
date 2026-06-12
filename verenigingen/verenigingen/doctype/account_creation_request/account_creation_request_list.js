// Account Creation Request List View JavaScript
// Adds bulk actions for queue management

frappe.listview_settings['Account Creation Request'] = {
	onload(listview) {
		// Add bulk action to queue multiple requests
		listview.page.add_actions_menu_item(
			__('Queue for Processing'),
			() => {
				bulk_queue_account_creation_requests(listview);
			},
			false
		);
	},

	// Add indicator colors based on status
	get_indicator(doc) {
		const status_colors = {
			Requested: 'orange',
			Queued: 'blue',
			Processing: 'yellow',
			Completed: 'green',
			Failed: 'red',
			Cancelled: 'grey'
		};

		return [__(doc.status), status_colors[doc.status] || 'gray', `status,=,${doc.status}`];
	}
};

function bulk_queue_account_creation_requests(listview) {
	const selected_docs = listview.get_checked_items();

	if (!selected_docs.length) {
		frappe.msgprint(__('Please select at least one request to queue'));
		return;
	}

	// Filter to only Requested status
	const requested_docs = selected_docs.filter((doc) => doc.status === 'Requested');

	if (requested_docs.length === 0) {
		frappe.msgprint(__('Please select requests with "Requested" status'));
		return;
	}

	if (requested_docs.length !== selected_docs.length) {
		frappe.msgprint(
			__('Only {0} of {1} selected requests can be queued (must be in "Requested" status)', [
				requested_docs.length,
				selected_docs.length
			])
		);
	}

	frappe.confirm(__('Queue {0} account creation request(s) for processing?', [requested_docs.length]), () => {
		frappe.call({
			method: 'verenigingen.verenigingen.doctype.account_creation_request.account_creation_request.bulk_queue_requests',
			args: {
				request_names: requested_docs.map((doc) => doc.name)
			},
			callback(r) {
				if (r.message && r.message.success) {
					frappe.msgprint(__('Successfully queued {0} request(s) for processing', [r.message.queued_count]));
					listview.refresh();
				} else if (r.message) {
					// Show detailed error information
					let error_msg = r.message.error || 'Unknown error';
					if (r.message.errors && r.message.errors.length > 0) {
						error_msg += `<br><br>First errors:<br>${r.message.errors.slice(0, 5).join('<br>')}`;
					}
					frappe.msgprint({
						title: __('Error Queueing Requests'),
						indicator: 'red',
						message: error_msg
					});
				} else {
					frappe.msgprint(__('Error queueing requests: No response from server'));
				}
			},
			error(r) {
				// Enhanced error reporting
				let error_detail = 'Please check the error log.';
				if (r && r.message) {
					error_detail = r.message;
				} else if (r && r._server_messages) {
					try {
						const messages = JSON.parse(r._server_messages);
						error_detail = messages.map((m) => JSON.parse(m).message).join('; ');
					} catch (e) {
						error_detail = r._server_messages;
					}
				}
				frappe.msgprint({
					title: __('Failed to Queue Requests'),
					indicator: 'red',
					message: error_detail
				});
			}
		});
	});
}
