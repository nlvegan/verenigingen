frappe.listview_settings['E-Boekhouden Migration'] = {
	get_indicator(doc) {
		const status_map = {
			Draft: [__('Draft'), 'grey', 'migration_status,=,Draft'],
			'In Progress': [__('In Progress'), 'blue', 'migration_status,=,In Progress'],
			Completed: [__('Completed'), 'green', 'migration_status,=,Completed'],
			Failed: [__('Failed'), 'red', 'migration_status,=,Failed'],
			Cancelled: [__('Cancelled'), 'grey', 'migration_status,=,Cancelled']
		};
		return status_map[doc.migration_status] || [__(doc.migration_status), 'grey'];
	},

	onload(listview) {
		listview.page.add_action_item(__('Mass Cancel'), () => {
			const selected = listview.get_checked_items();
			const cancellable = selected.filter((d) => d.docstatus === 1);

			if (!cancellable.length) {
				frappe.msgprint(__('Select at least one submitted migration to cancel.'));
				return;
			}

			frappe.confirm(__('Cancel {0} submitted migration(s)?', [cancellable.length]), () => {
				let cancelled = 0;
				let failed = 0;
				const total = cancellable.length;

				frappe.call({
					method: 'verenigingen.e_boekhouden.api.eboekhouden_migration.mass_cancel_migrations',
					args: { names: cancellable.map((d) => d.name) },
					freeze: true,
					freeze_message: __('Cancelling {0} migration(s)...', [total]),
					callback(r) {
						if (r.message) {
							cancelled = r.message.cancelled || 0;
							failed = r.message.failed || 0;
						}
						if (failed) {
							frappe.msgprint(
								__('Cancelled {0}, failed {1}. Check error log for details.', [cancelled, failed])
							);
						} else {
							frappe.show_alert({
								message: __('{0} migration(s) cancelled.', [cancelled]),
								indicator: 'green'
							});
						}
						listview.refresh();
					}
				});
			});
		});
	}
};
