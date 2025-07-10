// Chapter-related utility functions for Member doctype

function assign_chapter_for_member(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Assign Chapter to Member'),
		size: 'medium',
		fields: [
			{
				fieldtype: 'HTML',
				options: `<div class="mb-3">
                    <p>${__('Select a chapter to assign to this member.')}</p>
                    <div class="alert alert-warning">
                        <strong>${__('Note:')}</strong> ${__('If the member is currently assigned to another chapter, that membership (and any board roles) will be ended automatically.')}
                    </div>
                </div>`
			},
			{
				fieldname: 'chapter',
				fieldtype: 'Link',
				label: __('Chapter'),
				options: 'Chapter',
				reqd: 1,
				get_query: function() {
					return {
						filters: {
							'published': 1
						}
					};
				}
			},
			{
				fieldname: 'note',
				fieldtype: 'Small Text',
				label: __('Assignment Note (Optional)'),
				description: __('Optional note explaining the reason for this assignment')
			}
		],
		primary_action_label: __('Assign to Chapter'),
		primary_action: function(values) {
			if (values.chapter) {
				assign_chapter_to_member(frm, values.chapter, values.note);
				d.hide();
			} else {
				frappe.msgprint(__('Please select a chapter'));
			}
		}
	});

	d.show();
}

function assign_chapter_to_member(frm, chapter_name, note) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup',
		args: {
			member: frm.doc.name,
			chapter: chapter_name,
			note: note
		},
		callback: function(r) {
			if (r.message && r.message.success) {
				// Refresh the form to get the updated values
				frm.reload_doc();
				frappe.show_alert({
					message: __('Chapter assigned successfully'),
					indicator: 'green'
				}, 5);

				// Show additional info if previous memberships were cleaned up
				if (r.message.cleanup_performed) {
					frappe.show_alert({
						message: __('Previous chapter memberships and board roles have been ended'),
						indicator: 'blue'
					}, 7);
				}
			} else {
				frappe.msgprint({
					title: __('Assignment Failed'),
					message: r.message.message || __('Failed to assign chapter'),
					indicator: 'red'
				});
			}
		}
	});
}

// Export functions for use in member.js
window.ChapterUtils = {
	assign_chapter_for_member,
	assign_chapter_to_member
};
