// Copyright (c) 2025, Your Company and contributors
// For license information, please see license.txt

frappe.ui.form.on('Chapter Role', {
	refresh: function(frm) {
		// Add visual indication for chair role
		if (frm.doc.is_chair && frm.doc.is_active) {
			frm.page.set_indicator(__('Chair Role'), 'blue');
			check_for_duplicate_chair_roles(frm);
		}

		// Add information about chair roles
		if (frm.doc.is_chair) {
			frm.set_intro(__('This role is marked as Chair. Members with this role will be automatically set as Chapter Heads.'), 'blue');
		}

		// Add button to view chapters using this role
		frm.add_custom_button(__('View Chapters Using This Role'), function() {
			frappe.set_route('List', 'Chapter Board Member', {
				'chapter_role': frm.doc.name
			});
		}, __('View'));

		// Add button to update affected chapters if this is a chair role
		if (frm.doc.is_chair && frm.doc.is_active) {
			frm.add_custom_button(__('Update Affected Chapters'), function() {
				update_chapters_with_this_role(frm);
			}, __('Actions'));
		}
	},

	is_chair: function(frm) {
		if (frm.doc.is_chair && frm.doc.is_active) {
			frappe.confirm(
				__('Setting this role as Chair will make board members with this role automatically set as Chapter Head. Continue?'),
				function() {
					// Yes - check for duplicates
					check_for_duplicate_chair_roles(frm);
				},
				function() {
					// No - uncheck
					frm.set_value('is_chair', 0);
				}
			);
		}
	},

	is_active: function(frm) {
		// If activating a chair role, check for duplicates
		if (frm.doc.is_active && frm.doc.is_chair) {
			check_for_duplicate_chair_roles(frm);
		}
	},

	role_name: function(frm) {
		// If role name contains 'chair' or related terms, suggest setting is_chair
		if (!frm.doc.is_chair && frm.doc.role_name && frm.doc.is_active) {
			const chairTerms = ['chair', 'chairperson', 'president', 'head'];
			const lowerName = frm.doc.role_name.toLowerCase();

			if (chairTerms.some(term => lowerName.includes(term))) {
				frappe.confirm(
					__('This role name suggests it might be a Chair role. Would you like to mark it as Chair?'),
					function() {
						// Yes - set as chair
						frm.set_value('is_chair', 1);
						check_for_duplicate_chair_roles(frm);
					}
				);
			}
		}
	},

	permissions_level: function(frm) {
		// If setting admin permissions level, suggest setting is_chair if not already set
		if (frm.doc.permissions_level === 'Admin' && !frm.doc.is_chair && frm.doc.is_active) {
			frappe.confirm(
				__('Admin roles are often chair roles. Would you like to mark this role as Chair?'),
				function() {
					// Yes - set as chair
					frm.set_value('is_chair', 1);
					check_for_duplicate_chair_roles(frm);
				}
			);
		}
	},

	after_save: function(frm) {
		// If this is a chair role, suggest updating affected chapters
		if (frm.doc.is_chair && frm.doc.is_active) {
			frappe.confirm(
				__('Would you like to update the Chapter Head for all chapters using this role now?'),
				function() {
					// Yes - update chapters
					update_chapters_with_this_role(frm);
				}
			);
		}
	}
});

// Function to check for duplicate chair roles
function check_for_duplicate_chair_roles(frm) {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Chapter Role',
			filters: {
				'is_chair': 1,
				'is_active': 1,
				'name': ['!=', frm.doc.name]
			},
			fields: ['name', 'role_name']
		},
		callback: function(r) {
			if (r.message && r.message.length > 0) {
				// Found other chair roles
				frm.set_intro(
					__('Warning: There are other roles also marked as Chair: {0}. Having multiple chair roles may cause confusion.',
						[r.message.map(role => role.role_name).join(', ')]),
					'orange'
				);

				// Show warning message
				frappe.msgprint({
					title: __('Multiple Chair Roles'),
					indicator: 'orange',
					message: __('There are other roles also marked as Chair:<br><br>{0}<br><br>Having multiple chair roles may cause confusion when automatically setting Chapter Heads.',
						[r.message.map(role => `• ${role.role_name}`).join('<br>')])
				});
			} else {
				// This is the only chair role
				frm.set_intro(__('This is the only role marked as Chair. Members with this role will be automatically set as Chapter Heads.'), 'blue');
			}
		}
	});
}

// Function to update chapters with this role
function update_chapters_with_this_role(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.chapter_role.chapter_role.update_chapters_with_role',
		args: {
			role: frm.doc.name
		},
		freeze: true,
		freeze_message: __('Updating chapters...'),
		callback: function(r) {
			if (r.message) {
				frappe.msgprint({
					title: __('Chapters Updated'),
					indicator: 'green',
					message: __('Updated {0} chapters with this role. {1} chapters had their Chapter Head changed.',
						[r.message.chapters_found, r.message.chapters_updated])
				});
			}
		}
	});
}
