frappe.ui.form.on('Volunteer Expense', {
	refresh: function(frm) {
		// Add custom buttons based on status
		if (frm.doc.status === 'Submitted' && !frm.doc.__islocal) {
			// Add approve/reject buttons for authorized users
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.can_approve_expense',
				args: {
					expense: frm.doc
				},
				callback: function(r) {
					if (r.message) {
						frm.add_custom_button(__('Approve'), function() {
							approve_expense(frm);
						}, __('Actions'));

						frm.add_custom_button(__('Reject'), function() {
							reject_expense(frm);
						}, __('Actions'));
					}
				}
			});
		}

		// Add reimbursed button for approved expenses
		if (frm.doc.status === 'Approved' && frappe.user.has_role(['Verenigingen Administrator', 'Chapter Board Member'])) {
			frm.add_custom_button(__('Mark as Reimbursed'), function() {
				mark_reimbursed(frm);
			}, __('Actions'));
		}

		// Set volunteer based on current user if creating new
		if (frm.doc.__islocal && !frm.doc.volunteer) {
			set_current_user_volunteer(frm);
		}
	},

	volunteer: function(frm) {
		if (frm.doc.volunteer) {
			// Auto-set organization if volunteer has only one
			auto_set_organization(frm);
		}
	},

	organization_type: function(frm) {
		// Clear opposite organization field when type changes
		if (frm.doc.organization_type === 'Chapter') {
			frm.set_value('team', '');
		} else if (frm.doc.organization_type === 'Team') {
			frm.set_value('chapter', '');
		}
	},

	category: function(frm) {
		// Update currency based on company default if needed
		if (frm.doc.category && !frm.doc.currency) {
			frm.set_value('currency', 'EUR');
		}
	},

	expense_date: function(frm) {
		// Validate expense date
		if (frm.doc.expense_date) {
			let expense_date = new Date(frm.doc.expense_date);
			let today = new Date();

			if (expense_date > today) {
				frappe.msgprint(__('Expense date cannot be in the future'));
				frm.set_value('expense_date', '');
			}
		}
	}
});

function approve_expense(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.approve_expense',
		args: {
			expense_name: frm.doc.name
		},
		callback: function(r) {
			if (!r.exc) {
				frm.reload_doc();
			}
		}
	});
}

function reject_expense(frm) {
	frappe.prompt({
		label: 'Rejection Reason',
		fieldname: 'reason',
		fieldtype: 'Text',
		reqd: 1
	}, function(data) {
		frappe.call({
			method: 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.reject_expense',
			args: {
				expense_name: frm.doc.name,
				reason: data.reason
			},
			callback: function(r) {
				if (!r.exc) {
					frm.reload_doc();
				}
			}
		});
	}, __('Reject Expense'), __('Reject'));
}

function mark_reimbursed(frm) {
	frappe.prompt({
		label: 'Reimbursement Details',
		fieldname: 'details',
		fieldtype: 'Text',
		reqd: 0
	}, function(data) {
		frm.set_value('status', 'Reimbursed');
		if (data.details) {
			frm.set_value('reimbursement_details', data.details);
		}
		frm.save();
	}, __('Mark as Reimbursed'), __('Update'));
}

function set_current_user_volunteer(frm) {
	// Try to get volunteer record for current user
	frappe.call({
		method: 'frappe.client.get_value',
		args: {
			doctype: 'Volunteer',
			filters: {
				user: frappe.session.user
			},
			fieldname: 'name'
		},
		callback: function(r) {
			if (r.message && r.message.name) {
				frm.set_value('volunteer', r.message.name);
			}
		}
	});
}

function auto_set_organization(frm) {
	// Auto-set organization if volunteer has only one chapter or team
	frappe.call({
		method: 'frappe.client.get',
		args: {
			doctype: 'Volunteer',
			name: frm.doc.volunteer
		},
		callback: function(r) {
			if (r.message && r.message.member) {
				// Check chapters first
				frappe.call({
					method: 'frappe.client.get_list',
					args: {
						doctype: 'Chapter Member',
						filters: {
							member: r.message.member,
							status: 'Active'
						},
						fields: ['chapter']
					},
					callback: function(chapters) {
						if (chapters.message && chapters.message.length === 1) {
							frm.set_value('organization_type', 'Chapter');
							frm.set_value('chapter', chapters.message[0].chapter);
						} else {
							// Check teams if no single chapter
							frappe.call({
								method: 'frappe.client.get_list',
								args: {
									doctype: 'Team Member',
									filters: {
										volunteer: frm.doc.volunteer,
										status: 'Active'
									},
									fields: ['parent']
								},
								callback: function(teams) {
									if (teams.message && teams.message.length === 1) {
										frm.set_value('organization_type', 'Team');
										frm.set_value('team', teams.message[0].parent);
									}
								}
							});
						}
					}
				});
			}
		}
	});
}
