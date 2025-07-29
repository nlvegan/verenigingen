frappe.ui.form.on('Expulsion Report Entry', {
	refresh: function(frm) {
		// Set page indicator based on status
		set_status_indicator(frm);

		// Add custom buttons
		add_action_buttons(frm);

		// Make read-only fields based on status
		set_field_properties(frm);

		// Show/hide fields based on status
		toggle_status_fields(frm);
	},

	onload: function(frm) {
		// Set default values for new documents
		if (frm.is_new()) {
			frm.set_value('expulsion_date', frappe.datetime.get_today());
			frm.set_value('status', 'Active');
		}

		// Set query filters
		set_query_filters(frm);
	},

	status: function(frm) {
		toggle_status_fields(frm);
		set_field_properties(frm);
	},

	member_id: function(frm) {
		if (frm.doc.member_id) {
			// Fetch member details
			frappe.call({
				method: 'frappe.client.get_value',
				args: {
					doctype: 'Member',
					filters: {name: frm.doc.member_id},
					fieldname: ['full_name', 'current_chapter_display', 'email']
				},
				callback: function(r) {
					if (r.message) {
						frm.set_value('member_name', r.message.full_name);
						if (r.message.current_chapter_display && !frm.doc.chapter_involved) {
							frm.set_value('chapter_involved', r.message.current_chapter_display);
						}
					}
				}
			});
		}
	}
});

function set_status_indicator(frm) {
	const indicator_map = {
		'Active': ['Active', 'red'],
		'Under Appeal': ['Under Appeal', 'orange'],
		'Reversed': ['Reversed', 'green']
	};

	const [label, color] = indicator_map[frm.doc.status] || ['Unknown', 'gray'];
	frm.page.set_indicator(label, color);
}

function add_action_buttons(frm) {
	frm.clear_custom_buttons();

	if (frm.doc.status === 'Active' && !frm.doc.under_appeal) {
		// Check for existing appeal
		frm.add_custom_button(__('File Appeal'), function() {
			// Check if termination request exists
			frappe.call({
				method: 'frappe.client.get_list',
				args: {
					doctype: 'Membership Termination Request',
					filters: {
						member: frm.doc.member_id,
						status: 'Executed',
						termination_type: frm.doc.expulsion_type
					},
					fields: ['name'],
					limit: 1
				},
				callback: function(r) {
					if (r.message && r.message.length > 0) {
						// Use the existing appeal creation dialog
						if (window.show_appeal_creation_dialog) {
							window.show_appeal_creation_dialog(r.message[0].name);
						} else {
							frappe.msgprint(__('Appeal creation dialog not available'));
						}
					} else {
						frappe.msgprint(__('No executed termination request found for this expulsion'));
					}
				}
			});
		}, __('Actions'));
	}

	if (frm.doc.status === 'Active') {
		frm.add_custom_button(__('Reverse Expulsion'), function() {
			frappe.prompt([
				{
					fieldname: 'reversal_reason',
					label: __('Reversal Reason'),
					fieldtype: 'Small Text',
					reqd: 1
				}
			], function(values) {
				frappe.call({
					method: 'reverse_expulsion',
					doc: frm.doc,
					args: {
						reversal_reason: values.reversal_reason
					},
					callback: function(r) {
						if (r.message) {
							frm.refresh();
							frappe.show_alert({
								message: __('Expulsion reversed successfully'),
								indicator: 'green'
							}, 5);
						}
					}
				});
			}, __('Confirm Reversal'));
		}, __('Actions'));
	}

	// Add view buttons
	if (frm.doc.member_id) {
		frm.add_custom_button(__('View Member'), function() {
			frappe.set_route('Form', 'Member', frm.doc.member_id);
		}, __('View'));
	}

	if (frm.doc.chapter_involved) {
		frm.add_custom_button(__('View Chapter'), function() {
			frappe.set_route('Form', 'Chapter', frm.doc.chapter_involved);
		}, __('View'));
	}

	// Add governance review button
	if (!frm.doc.compliance_checked) {
		frm.add_custom_button(__('Mark Compliance Verified'), function() {
			frm.set_value('compliance_checked', 1);
			frm.set_value('board_review_date', frappe.datetime.get_today());
			frm.save();
		}, __('Governance'));
	}
}

function set_field_properties(frm) {
	// Make certain fields read-only based on status
	if (frm.doc.status === 'Reversed') {
		frm.set_df_property('expulsion_type', 'read_only', 1);
		frm.set_df_property('expulsion_date', 'read_only', 1);
		frm.set_df_property('documentation', 'read_only', 1);
	}

	// Member details should always be read-only after creation
	if (!frm.is_new()) {
		frm.set_df_property('member_id', 'read_only', 1);
		frm.set_df_property('member_name', 'read_only', 1);
	}
}

function toggle_status_fields(frm) {
	// Show/hide fields based on status
	const is_reversed = frm.doc.status === 'Reversed';
	const is_under_appeal = frm.doc.under_appeal;

	frm.toggle_display(['reversal_date', 'reversal_reason'], is_reversed);
	frm.toggle_display(['appeal_date'], is_under_appeal);
}

function set_query_filters(frm) {
	// Filter members to only show those with executed terminations
	frm.set_query('member_id', function() {
		return {
			query: 'frappe.client.get_list',
			filters: {
				doctype: 'Member',
				filters: [
					['Member', 'name', 'in',
						frappe.db.get_list('Membership Termination Request', {
							filters: {status: 'Executed'},
							fields: ['member']
						}).then(r => r.map(d => d.member))
					]
				]
			}
		};
	});

	// Filter initiator and approver to users with appropriate roles
	frm.set_query('initiated_by', function() {
		return {
			filters: {
				'enabled': 1
			}
		};
	});

	frm.set_query('approved_by', function() {
		return {
			filters: {
				'enabled': 1
			}
		};
	});
}

// Child table events if needed
frappe.ui.form.on('Expulsion Report Entry Item', {
	// Add child table events here if required
});
