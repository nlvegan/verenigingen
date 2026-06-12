frappe.listview_settings['MijnRood Sync Event'] = {
	get_indicator(doc) {
		const status_map = {
			Pending: [__('Pending'), 'orange', 'status,=,Pending'],
			Approved: [__('Approved'), 'blue', 'status,=,Approved'],
			Applied: [__('Applied'), 'green', 'status,=,Applied'],
			Rejected: [__('Rejected'), 'red', 'status,=,Rejected'],
			Ignored: [__('Ignored'), 'grey', 'status,=,Ignored']
		};
		return status_map[doc.status] || [doc.status, 'grey', `status,=,${doc.status}`];
	},

	formatters: {
		change_tags(val) {
			if (!val) { return ''; }
			const TAG_COLORS = {
				Status: 'red',
				Chapter: 'orange',
				Financial: 'orange',
				Contact: 'blue',
				Personal: 'grey',
				Address: 'grey',
				Roles: 'purple',
				'New Member': 'green',
				'New Application': 'green',
				'New Division': 'green',
				New: 'green',
				Deleted: 'red',
				Other: 'grey'
			};
			return val.split(',').map((tag) => {
				tag = tag.trim();
				const color = TAG_COLORS[tag] || 'grey';
				return `<span class="indicator-pill ${color}">${
					frappe.utils.escape_html(tag)}</span>`;
			}).join(' ');
		}
	},

	onload(listview) {
		// Default filter to Pending events
		if (!listview.filter_area.filter_list.length) {
			listview.filter_area.add([[listview.doctype, 'status', '=', 'Pending']]);
		}

		// Batch actions
		listview.page.add_action_item(__('Approve Selected'), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.throw(__('Please select at least one event'));
			}
			const names = selected.map((d) => { return d.name; });
			frappe.call({
				method: 'verenigingen.mijnrood_sync.services.event_application_service.batch_approve',
				args: { event_names: names },
				freeze: true,
				freeze_message: __('Approving events...'),
				callback() {
					listview.refresh();
				}
			});
		});

		listview.page.add_action_item(__('Apply Selected'), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.throw(__('Please select at least one event'));
			}
			const names = selected.map((d) => { return d.name; });
			frappe.confirm(
				__('Apply {0} selected events? This will modify member data.', [names.length]),
				() => {
					frappe.call({
						method: 'verenigingen.mijnrood_sync.services.event_application_service.batch_apply',
						args: { event_names: names },
						callback(r) {
							if (!r.message) { return; }
							_show_batch_progress_dialog(
								listview, r.message,
								'batch_apply_progress', 'batch_apply_complete',
								__('Applying {0} events...', [r.message.total])
							);
						}
					});
				}
			);
		});

		listview.page.add_action_item(__('Approve & Apply Selected'), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.throw(__('Please select at least one event'));
			}
			const names = selected.map((d) => { return d.name; });
			frappe.confirm(
				__('Approve and apply {0} selected events? This will modify member data.', [names.length]),
				() => {
					frappe.call({
						method: 'verenigingen.mijnrood_sync.services.event_application_service.batch_approve_and_apply',
						args: { event_names: names },
						callback(r) {
							if (!r.message) { return; }
							_show_batch_progress_dialog(
								listview, r.message,
								'batch_approve_apply_progress', 'batch_approve_apply_complete',
								__('Approving & applying {0} events...', [r.message.total])
							);
						}
					});
				}
			);
		});
	}
};

/**
 * Shared progress dialog for batch operations (Apply Selected / Approve & Apply Selected).
 */
function _show_batch_progress_dialog(listview, message, progress_event, complete_event, title) {
	const batch_id = message.batch_id;
	const total = message.total;
	const dialog = new frappe.ui.Dialog({
		title,
		fields: [
			{ fieldtype: 'HTML', fieldname: 'progress_area' }
		]
	});
	dialog.fields_dict.progress_area.$wrapper.html(
		`<div class="progress"><div class="progress-bar" style="width: 0%"></div></div>`
        + `<p class="batch-status text-muted">${__('Starting...')}</p>`
	);
	dialog.show();
	dialog.$wrapper.find('.modal-footer').hide();

	function onProgress(data) {
		if (data.batch_id !== batch_id) { return; }
		const pct = Math.round((data.current / data.total) * 100);
		dialog.fields_dict.progress_area.$wrapper
			.find('.progress-bar').css('width', `${pct}%`);
		dialog.fields_dict.progress_area.$wrapper
			.find('.batch-status').text(
				__('{0}/{1} processed — {2} applied, {3} errors',
					[data.current, data.total, data.applied, data.errors])
			);
	}

	function onComplete(data) {
		if (data.batch_id !== batch_id) { return; }
		frappe.realtime.off(progress_event, onProgress);
		frappe.realtime.off(complete_event, onComplete);
		dialog.hide();
		if (data.errors && data.errors.length) {
			const escaped_errors = data.errors.map((e) => {
				return frappe.utils.escape_html(e);
			});
			frappe.msgprint({
				title: __('Batch Results'),
				message: __('Applied {0}/{1}. Errors:<br>{2}',
					[data.applied, data.total, escaped_errors.join('<br>')]),
				indicator: 'orange'
			});
		} else {
			frappe.show_alert({
				message: __('{0} events applied successfully.', [data.applied]),
				indicator: 'green'
			});
		}
		listview.refresh();
	}

	frappe.realtime.on(progress_event, onProgress);
	frappe.realtime.on(complete_event, onComplete);

	dialog.on_hide = function () {
		frappe.realtime.off(progress_event, onProgress);
		frappe.realtime.off(complete_event, onComplete);
	};
}
