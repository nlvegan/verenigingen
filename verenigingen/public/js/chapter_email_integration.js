/**
 * Chapter Email Integration
 * Phase 2 Implementation - Email/Newsletter UI Components
 *
 * Adds email sending functionality to Chapter forms
 */

frappe.provide('frappe.verenigingen.email');

// Chapter form customization
frappe.ui.form.on('Chapter', {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.name) {
			// Add email buttons group
			frm.add_custom_button(__('Send to All Members'), () => {
				frappe.verenigingen.email.show_email_dialog(frm.doc.name, 'all');
			}, __('📧 Email'));

			frm.add_custom_button(__('Send to Board'), () => {
				frappe.verenigingen.email.show_email_dialog(frm.doc.name, 'board');
			}, __('📧 Email'));

			frm.add_custom_button(__('Send to Volunteers'), () => {
				frappe.verenigingen.email.show_email_dialog(frm.doc.name, 'volunteers');
			}, __('📧 Email'));

			// Add preview button
			frm.add_custom_button(__('Preview Recipients'), () => {
				frappe.verenigingen.email.show_recipient_preview(frm.doc.name);
			}, __('📧 Email'));
		}
	}
});

// Email functionality namespace
frappe.verenigingen.email = {
	/**
     * Show email composition dialog
     */
	show_email_dialog(chapter_name, segment) {
		// First get recipient count
		frappe.call({
			method: 'verenigingen.email.simplified_email_manager.get_segment_recipient_count',
			args: {
				chapter_name,
				segment
			},
			callback(r) {
				if (!r.message || !r.message.success) {
					frappe.msgprint(__('Could not get recipient count: {0}', [r.message?.error || 'Unknown error']));
					return;
				}

				const recipient_count = r.message.recipients_count || 0;
				const sample_recipients = r.message.sample_recipients || [];

				// Show the email dialog
				const dialog = new frappe.ui.Dialog({
					title: __('Send Email to {0}', [segment === 'all' ? 'All Members'
						: segment === 'board' ? 'Board Members' : 'Volunteers']),
					fields: [
						{
							fieldname: 'recipient_info',
							fieldtype: 'HTML',
							options: `
                                <div class="alert alert-info">
                                    <strong>${__('Recipients')}:</strong> ${recipient_count} ${__('members')}<br>
                                    ${sample_recipients.length > 0
		? `<small>${__('Sample')}: ${sample_recipients.slice(0, 3)
			.map(recipient => recipient.full_name || recipient.email).join(', ')}...</small>` : ''}
                                </div>
                            `
						},
						{
							fieldname: 'subject',
							fieldtype: 'Data',
							label: __('Subject'),
							reqd: 1
						},
						{
							fieldname: 'use_template',
							fieldtype: 'Check',
							label: __('Use Email Template'),
							onchange() {
								const template_field = dialog.get_field('email_template');
								const content_field = dialog.get_field('content');
								if (this.get_value()) {
									template_field.df.hidden = 0;
									content_field.df.hidden = 1;
								} else {
									template_field.df.hidden = 1;
									content_field.df.hidden = 0;
								}
								dialog.refresh();
							}
						},
						{
							fieldname: 'email_template',
							fieldtype: 'Link',
							label: __('Email Template'),
							options: 'Email Template',
							hidden: 1,
							onchange() {
								if (this.get_value()) {
									frappe.vereiningen.email.load_template(dialog, this.get_value());
								}
							}
						},
						{
							fieldname: 'content',
							fieldtype: 'Text Editor',
							label: __('Message'),
							reqd: 1
						},
						{
							fieldname: 'test_send',
							fieldtype: 'Check',
							label: __('Test Mode (Preview Only)'),
							description: __('Check to preview without sending')
						}
					],
					size: 'large',
					primary_action_label: __('Send'),
					primary_action(values) {
						if (recipient_count === 0) {
							frappe.msgprint(__('No recipients found for this segment'));
							return;
						}

						// Confirm before sending
						const confirm_msg = values.test_send
							? __('Preview email for {0} recipients?', [recipient_count])
							: __('Send email to {0} recipients?', [recipient_count]);

						frappe.confirm(confirm_msg, () => {
							frappe.vereiningen.email.send_email(
								chapter_name,
								segment,
								values.subject,
								values.content,
								values.test_send
							);
							dialog.hide();
						});
					}
				});

				dialog.show();
			}
		});
	},

	/**
     * Load email template content
     */
	load_template(dialog, template_name) {
		frappe.call({
			method: 'frappe.client.get',
			args: {
				doctype: 'Email Template',
				name: template_name
			},
			callback(r) {
				if (r.message) {
					dialog.set_value('subject', r.message.subject || '');
					dialog.set_value('content', r.message.response || '');
				}
			}
		});
	},

	/**
     * Send the actual email
     */
	send_email(chapter_name, segment, subject, content, test_mode) {
		if (test_mode) {
			// Show preview
			frappe.msgprint({
				title: __('Email Preview'),
				message: `
                    <strong>${__('Subject')}:</strong> ${subject}<br><br>
                    <strong>${__('Segment')}:</strong> ${segment}<br><br>
                    <strong>${__('Content')}:</strong><br>
                    <div style="border: 1px solid #ddd; padding: 10px; margin-top: 10px;">
                        ${content}
                    </div>
                `,
				indicator: 'blue'
			});
			return;
		}

		// Send actual email
		frappe.call({
			method: 'verenigingen.email.simplified_email_manager.send_chapter_email',
			args: {
				chapter_name,
				segment,
				subject,
				content
			},
			freeze: true,
			freeze_message: __('Sending emails...'),
			callback(r) {
				if (r.message && r.message.success) {
					frappe.show_alert({
						message: __('Email queued for {0} recipients', [r.message.recipients_count]),
						indicator: 'green'
					}, 5);

					// Show link to newsletter
					if (r.message.newsletter) {
						frappe.msgprint(__('Newsletter created: <a href="/app/newsletter/{0}">{0}</a>',
							[r.message.newsletter]));
					}
				} else {
					frappe.msgprint(__('Error sending email: {0}',
						[r.message?.error || 'Unknown error']));
				}
			},
			error(err) {
				frappe.msgprint(__('Error sending email: {0}', [err.message || 'Unknown error']));
			}
		});
	},

	/**
     * Show recipient preview dialog
     */
	show_recipient_preview(chapter_name) {
		const dialog = new frappe.ui.Dialog({
			title: __('Email Recipients Preview'),
			fields: [
				{
					fieldname: 'preview_html',
					fieldtype: 'HTML',
					options: '<div id="recipient-preview">Loading...</div>'
				}
			],
			size: 'large'
		});

		dialog.show();

		// Load preview data for all segments
		const segments = ['all', 'board', 'volunteers'];
		let preview_html = '<div class="recipient-preview-container">';
		let loaded = 0;

		segments.forEach(segment => {
			frappe.call({
				method: 'verenigingen.email.simplified_email_manager.get_segment_recipient_count',
				args: {
					chapter_name,
					segment
				},
				callback(r) {
					loaded++;

					if (r.message && r.message.success) {
						const data = r.message;
						preview_html += `
                            <div class="segment-preview" style="margin-bottom: 20px;">
                                <h5>${segment === 'all' ? 'All Members'
		: segment === 'board' ? 'Board Members' : 'Volunteers'}</h5>
                                <p><strong>${__('Total')}:</strong> ${data.recipients_count} ${__('recipients')}</p>
                                ${data.sample_recipients && data.sample_recipients.length > 0 ? `
                                    <p><strong>${__('Sample')}:</strong></p>
                                    <ul>
                                        ${data.sample_recipients.map(recipient => `
                                            <li>${recipient.full_name} (${recipient.email})
                                                ${recipient.role ? ` - ${recipient.role}` : ''}</li>
                                        `).join('')}
                                    </ul>
                                ` : '<p><em>No recipients in this segment</em></p>'}
                            </div>
                        `;
					}

					// Update dialog when all segments are loaded
					if (loaded === segments.length) {
						preview_html += '</div>';
						dialog.fields_dict.preview_html.$wrapper.html(preview_html);
					}
				}
			});
		});
	}
};

// Organization-wide newsletter functionality (for System Managers)
if (frappe.boot.user.roles.includes('System Manager')
    || frappe.boot.user.roles.includes('Verenigingen Manager')) {
	// Add to navbar
	$(document).ready(() => {
		if ($('.navbar-nav .dropdown-help').length) {
			$('.navbar-nav .dropdown-help').before(`
                <li class="dropdown">
                    <a class="dropdown-toggle" data-toggle="dropdown" href="#"
                       onclick="return false;" title="${__('Organization Newsletter')}">
                        <span>📧</span>
                    </a>
                    <ul class="dropdown-menu" id="toolbar-newsletter">
                        <li><a onclick="frappe.verenigingen.email.show_org_newsletter_dialog()">
                            ${__('Send Organization Newsletter')}</a></li>
                        <li><a onclick="frappe.verenigingen.email.show_email_groups()">
                            ${__('Manage Email Groups')}</a></li>
                    </ul>
                </li>
            `);
		}
	});

	// Organization newsletter dialog
	frappe.verenigingen.email.show_org_newsletter_dialog = function () {
		const dialog = new frappe.ui.Dialog({
			title: __('Send Organization Newsletter'),
			fields: [
				{
					fieldname: 'filter_section',
					fieldtype: 'Section Break',
					label: __('Recipients')
				},
				{
					fieldname: 'member_status',
					fieldtype: 'Select',
					label: __('Member Status'),
					options: 'All\nActive\nInactive\nPending',
					default: 'Active'
				},
				{
					fieldname: 'chapter',
					fieldtype: 'Link',
					label: __('Chapter (Optional)'),
					options: 'Chapter',
					description: __('Leave empty to send to all chapters')
				},
				{
					fieldname: 'message_section',
					fieldtype: 'Section Break',
					label: __('Message')
				},
				{
					fieldname: 'subject',
					fieldtype: 'Data',
					label: __('Subject'),
					reqd: 1
				},
				{
					fieldname: 'content',
					fieldtype: 'Text Editor',
					label: __('Message'),
					reqd: 1
				}
			],
			size: 'large',
			primary_action_label: __('Send Newsletter'),
			primary_action(values) {
				// Build filters
				const filters = {};
				if (values.member_status && values.member_status !== 'All') {
					filters.status = values.member_status;
				}
				if (values.chapter) {
					// This would need a custom filter implementation
					filters.chapter = values.chapter;
				}

				frappe.call({
					method: 'verenigingen.email.simplified_email_manager.send_organization_newsletter',
					args: {
						subject: values.subject,
						content: values.content,
						filters
					},
					freeze: true,
					freeze_message: __('Sending newsletter...'),
					callback(r) {
						if (r.message && r.message.success) {
							frappe.show_alert({
								message: __('Newsletter queued for {0} recipients',
									[r.message.recipients_count]),
								indicator: 'green'
							}, 5);
							dialog.hide();
						} else {
							frappe.msgprint(__('Error: {0}',
								[r.message?.error || 'Unknown error']));
						}
					}
				});
			}
		});

		dialog.show();
	};

	// Email groups management
	frappe.verenigingen.email.show_email_groups = function () {
		frappe.set_route('List', 'Email Group');
	};
}
