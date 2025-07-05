// verenigingen/verenigingen/doctype/chapter/modules/CommunicationManager.js

import { ChapterAPI } from '../utils/ChapterAPI.js';

export class CommunicationManager {
    constructor(frm, state) {
        this.frm = frm;
        this.state = state;
        this.api = new ChapterAPI();
        this.emailTemplates = new Map();
    }

    addButtons() {
        this.frm.add_custom_button(__('Email Board Members'), () => this.showEmailBoardDialog(), __('Communication'));
        this.frm.add_custom_button(__('Email All Members'), () => this.showEmailMembersDialog(), __('Communication'));
        this.frm.add_custom_button(__('Send Newsletter'), () => this.showNewsletterDialog(), __('Communication'));
        this.frm.add_custom_button(__('Communication History'), () => this.showCommunicationHistory(), __('Communication'));
    }

    async showEmailBoardDialog() {
        try {
            // Get active board members with email
            const boardMembers = this.getActiveBoardMembersWithEmail();

            if (!boardMembers.length) {
                frappe.msgprint(__('No active board members with email addresses found'));
                return;
            }

            const recipientList = boardMembers.map(m => `${m.volunteer_name} (${m.email})`).join('\n');

            const dialog = new frappe.ui.Dialog({
                title: __('Email Board Members'),
                fields: [
                    {
                        fieldtype: 'HTML',
                        options: `<div class="alert alert-info">
                            <p><strong>${__('Recipients')} (${boardMembers.length}):</strong></p>
                            <pre style="max-height: 100px; overflow-y: auto;">${recipientList}</pre>
                        </div>`
                    },
                    {
                        fieldname: 'subject',
                        fieldtype: 'Data',
                        label: __('Subject'),
                        reqd: 1,
                        default: __('Message from {0} Chapter', [this.frm.doc.name])
                    },
                    {
                        fieldname: 'use_template',
                        fieldtype: 'Check',
                        label: __('Use Email Template'),
                        onchange: function() {
                            dialog.fields_dict.email_template.df.hidden = !this.get_value();
                            dialog.fields_dict.message.df.hidden = this.get_value();
                            dialog.refresh();
                        }
                    },
                    {
                        fieldname: 'email_template',
                        fieldtype: 'Link',
                        label: __('Email Template'),
                        options: 'Email Template',
                        hidden: 1,
                        get_query: () => ({
                            filters: { 'enabled': 1 }
                        }),
                        onchange: async function() {
                            const template = this.get_value();
                            if (template) {
                                await this.loadEmailTemplate(dialog, template);
                            }
                        }.bind(this)
                    },
                    {
                        fieldname: 'message',
                        fieldtype: 'Text Editor',
                        label: __('Message'),
                        reqd: 1
                    },
                    {
                        fieldname: 'attach_files',
                        fieldtype: 'Attach',
                        label: __('Attachments')
                    },
                    {
                        fieldname: 'send_individually',
                        fieldtype: 'Check',
                        label: __('Send as Individual Emails'),
                        description: __('Send separate emails to each recipient instead of using BCC')
                    }
                ],
                primary_action_label: __('Send'),
                primary_action: async (values) => {
                    await this.sendEmailToBoardMembers(values, boardMembers);
                    dialog.hide();
                }
            });

            dialog.show();

        } catch (error) {
            frappe.msgprint(__('Error preparing email dialog: {0}', [error.message]));
        }
    }

    async showEmailMembersDialog() {
        try {
            // Get chapter members with email
            const members = await this.getChapterMembersWithEmail();

            if (!members.length) {
                frappe.msgprint(__('No chapter members with email addresses found'));
                return;
            }

            const dialog = new frappe.ui.Dialog({
                title: __('Email Chapter Members'),
                size: 'large',
                fields: [
                    {
                        fieldtype: 'HTML',
                        options: `<div class="alert alert-info">
                            <p><strong>${__('Total Recipients')}: ${members.length}</strong></p>
                            <p>${__('This will send emails to all active chapter members.')}</p>
                        </div>`
                    },
                    {
                        fieldname: 'filter_section',
                        fieldtype: 'Section Break',
                        label: __('Filter Recipients')
                    },
                    {
                        fieldname: 'member_status',
                        fieldtype: 'MultiSelect',
                        label: __('Member Status'),
                        options: [
                            { label: __('Active'), value: 'Active' },
                            { label: __('Expired'), value: 'Expired' },
                            { label: __('Suspended'), value: 'Suspended' }
                        ],
                        default: ['Active']
                    },
                    {
                        fieldname: 'membership_type',
                        fieldtype: 'Link',
                        label: __('Membership Type'),
                        options: 'Membership Type',
                        description: __('Optional: Filter by membership type')
                    },
                    {
                        fieldname: 'email_section',
                        fieldtype: 'Section Break',
                        label: __('Email Content')
                    },
                    {
                        fieldname: 'subject',
                        fieldtype: 'Data',
                        label: __('Subject'),
                        reqd: 1,
                        default: __('Newsletter from {0} Chapter', [this.frm.doc.name])
                    },
                    {
                        fieldname: 'message',
                        fieldtype: 'Text Editor',
                        label: __('Message'),
                        reqd: 1
                    },
                    {
                        fieldname: 'include_unsubscribe',
                        fieldtype: 'Check',
                        label: __('Include Unsubscribe Link'),
                        default: 1
                    },
                    {
                        fieldname: 'schedule_section',
                        fieldtype: 'Section Break',
                        label: __('Scheduling')
                    },
                    {
                        fieldname: 'send_now',
                        fieldtype: 'Check',
                        label: __('Send Immediately'),
                        default: 1,
                        onchange: function() {
                            dialog.fields_dict.send_after.df.hidden = this.get_value();
                            dialog.refresh();
                        }
                    },
                    {
                        fieldname: 'send_after',
                        fieldtype: 'Datetime',
                        label: __('Send After'),
                        hidden: 1
                    }
                ],
                primary_action_label: __('Send'),
                primary_action: async (values) => {
                    await this.sendEmailToMembers(values, members);
                    dialog.hide();
                }
            });

            dialog.show();

        } catch (error) {
            frappe.msgprint(__('Error preparing member email dialog: {0}', [error.message]));
        }
    }

    async showNewsletterDialog() {
        const dialog = new frappe.ui.Dialog({
            title: __('Send Chapter Newsletter'),
            size: 'extra-large',
            fields: [
                {
                    fieldname: 'newsletter_name',
                    fieldtype: 'Data',
                    label: __('Newsletter Title'),
                    reqd: 1
                },
                {
                    fieldname: 'target_audience',
                    fieldtype: 'Select',
                    label: __('Target Audience'),
                    options: [
                        __('All Chapter Members'),
                        __('Board Members Only'),
                        __('Active Members Only'),
                        __('Custom Selection')
                    ],
                    default: __('All Chapter Members'),
                    reqd: 1,
                    onchange: function() {
                        const isCustom = this.get_value() === __('Custom Selection');
                        dialog.fields_dict.custom_recipients.df.hidden = !isCustom;
                        dialog.refresh();
                    }
                },
                {
                    fieldname: 'custom_recipients',
                    fieldtype: 'Small Text',
                    label: __('Custom Recipients'),
                    description: __('Enter email addresses separated by commas'),
                    hidden: 1
                },
                {
                    fieldname: 'content_section',
                    fieldtype: 'Section Break',
                    label: __('Newsletter Content')
                },
                {
                    fieldname: 'header_image',
                    fieldtype: 'Attach Image',
                    label: __('Header Image')
                },
                {
                    fieldname: 'introduction',
                    fieldtype: 'Text Editor',
                    label: __('Introduction'),
                    description: __('Opening message for the newsletter')
                },
                {
                    fieldname: 'sections',
                    fieldtype: 'Table',
                    label: __('Newsletter Sections'),
                    fields: [
                        {
                            fieldname: 'title',
                            fieldtype: 'Data',
                            label: __('Section Title'),
                            in_list_view: 1,
                            reqd: 1
                        },
                        {
                            fieldname: 'content',
                            fieldtype: 'Text Editor',
                            label: __('Content'),
                            in_list_view: 1,
                            reqd: 1
                        },
                        {
                            fieldname: 'image',
                            fieldtype: 'Attach Image',
                            label: __('Image')
                        }
                    ]
                },
                {
                    fieldname: 'footer_section',
                    fieldtype: 'Section Break',
                    label: __('Footer')
                },
                {
                    fieldname: 'footer_message',
                    fieldtype: 'Small Text',
                    label: __('Footer Message'),
                    default: __('This newsletter is sent to members of {0} Chapter', [this.frm.doc.name])
                },
                {
                    fieldname: 'include_social_links',
                    fieldtype: 'Check',
                    label: __('Include Social Media Links'),
                    default: 1
                }
            ],
            primary_action_label: __('Send Newsletter'),
            primary_action: async (values) => {
                await this.sendNewsletter(values);
                dialog.hide();
            },
            secondary_action_label: __('Preview'),
            secondary_action: () => {
                this.previewNewsletter(dialog.get_values());
            }
        });

        dialog.show();
    }

    async showCommunicationHistory() {
        try {
            this.state.setLoading('communicationHistory', true);

            const communications = await this.api.getList('Communication', {
                filters: {
                    reference_doctype: 'Chapter',
                    reference_name: this.frm.doc.name
                },
                fields: ['name', 'subject', 'creation', 'sent_or_received', 'recipients', 'communication_medium', 'status'],
                order_by: 'creation desc',
                limit: 100
            });

            const html = this.generateCommunicationHistoryHTML(communications);

            const dialog = new frappe.ui.Dialog({
                title: __('Communication History - {0}', [this.frm.doc.name]),
                size: 'large',
                fields: [{
                    fieldtype: 'HTML',
                    options: html
                }],
                primary_action_label: __('Close'),
                primary_action: function() {
                    this.hide();
                }
            });

            dialog.show();

        } catch (error) {
            frappe.msgprint(__('Error loading communication history: {0}', [error.message]));
        } finally {
            this.state.setLoading('communicationHistory', false);
        }
    }

    generateCommunicationHistoryHTML(communications) {
        if (!communications || communications.length === 0) {
            return `<div class="text-muted text-center">${__('No communications found')}</div>`;
        }

        let html = `
            <div class="communication-history">
                <table class="table table-bordered">
                    <thead>
                        <tr>
                            <th>${__('Date')}</th>
                            <th>${__('Subject')}</th>
                            <th>${__('Type')}</th>
                            <th>${__('Recipients')}</th>
                            <th>${__('Status')}</th>
                            <th>${__('Actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        communications.forEach(comm => {
            const statusColor = comm.status === 'Sent' ? 'green' : 'orange';
            const recipientCount = comm.recipients ? comm.recipients.split(',').length : 0;

            html += `
                <tr>
                    <td>${frappe.datetime.str_to_user(comm.creation)}</td>
                    <td>${comm.subject || __('No Subject')}</td>
                    <td>${comm.communication_medium || 'Email'}</td>
                    <td>${recipientCount} ${__('recipients')}</td>
                    <td><span class="indicator ${statusColor}">${comm.status}</span></td>
                    <td>
                        <button class="btn btn-xs btn-default"
                                onclick="frappe.set_route('Form', 'Communication', '${comm.name}')">
                            ${__('View')}
                        </button>
                    </td>
                </tr>
            `;
        });

        html += `
                    </tbody>
                </table>
            </div>
        `;

        return html;
    }

    getActiveBoardMembersWithEmail() {
        return (this.frm.doc.board_members || [])
            .filter(member => member.is_active && member.email)
            .map(member => ({
                volunteer: member.volunteer,
                volunteer_name: member.volunteer_name,
                email: member.email,
                role: member.chapter_role
            }));
    }

    async getChapterMembersWithEmail() {
        const memberIds = (this.frm.doc.members || [])
            .filter(m => m.enabled)
            .map(m => m.member);

        if (memberIds.length === 0) return [];

        return await this.api.getList('Member', {
            filters: [
                ['name', 'in', memberIds],
                ['email', '!=', '']
            ],
            fields: ['name', 'full_name', 'email', 'status'],
            limit: 500
        });
    }

    async sendEmailToBoardMembers(values, boardMembers) {
        try {
            this.state.setLoading('sendEmail', true);

            const recipients = boardMembers.map(m => m.email);

            if (values.send_individually) {
                // Send individual emails
                let successCount = 0;

                for (const member of boardMembers) {
                    try {
                        await this.sendEmail({
                            recipients: member.email,
                            subject: this.personalizeContent(values.subject, member),
                            content: this.personalizeContent(values.message, member),
                            attachments: values.attach_files
                        });
                        successCount++;
                    } catch (error) {
                        console.error(`Failed to send email to ${member.email}:`, error);
                    }
                }

                frappe.msgprint(__('Emails sent to {0} board members', [successCount]));
            } else {
                // Send as BCC
                await this.sendEmail({
                    recipients: recipients.join(','),
                    subject: values.subject,
                    content: values.message,
                    attachments: values.attach_files,
                    use_bcc: true
                });

                frappe.msgprint(__('Email sent to {0} board members', [boardMembers.length]));
            }

        } catch (error) {
            frappe.msgprint(__('Error sending emails: {0}', [error.message]));
        } finally {
            this.state.setLoading('sendEmail', false);
        }
    }

    async sendEmailToMembers(values, members) {
        try {
            this.state.setLoading('sendMemberEmail', true);

            // Filter members based on criteria
            let filteredMembers = members;

            if (values.member_status && values.member_status.length > 0) {
                filteredMembers = filteredMembers.filter(m =>
                    values.member_status.includes(m.status)
                );
            }

            if (values.membership_type) {
                // Additional filtering by membership type would require fetching membership data
                // For now, we'll use all filtered members
            }

            const recipients = filteredMembers.map(m => m.email);

            if (recipients.length === 0) {
                frappe.msgprint(__('No recipients match the selected criteria'));
                return;
            }

            // Add unsubscribe link if requested
            let content = values.message;
            if (values.include_unsubscribe) {
                content += this.getUnsubscribeFooter();
            }

            if (values.send_now) {
                // Send immediately
                await this.sendEmail({
                    recipients: recipients.join(','),
                    subject: values.subject,
                    content: content,
                    use_bcc: true
                });

                frappe.msgprint(__('Email sent to {0} members', [recipients.length]));
            } else {
                // Schedule for later
                await this.scheduleEmail({
                    recipients: recipients,
                    subject: values.subject,
                    content: content,
                    send_after: values.send_after
                });

                frappe.msgprint(__('Email scheduled to be sent to {0} members after {1}',
                    [recipients.length, frappe.datetime.str_to_user(values.send_after)]));
            }

        } catch (error) {
            frappe.msgprint(__('Error sending member emails: {0}', [error.message]));
        } finally {
            this.state.setLoading('sendMemberEmail', false);
        }
    }

    async sendNewsletter(values) {
        try {
            this.state.setLoading('sendNewsletter', true);

            // Determine recipients
            let recipients = [];

            switch (values.target_audience) {
                case __('All Chapter Members'):
                    recipients = await this.getChapterMembersWithEmail();
                    break;
                case __('Board Members Only'):
                    recipients = this.getActiveBoardMembersWithEmail();
                    break;
                case __('Active Members Only'):
                    const members = await this.getChapterMembersWithEmail();
                    recipients = members.filter(m => m.status === 'Active');
                    break;
                case __('Custom Selection'):
                    recipients = values.custom_recipients
                        .split(',')
                        .map(email => ({ email: email.trim() }));
                    break;
            }

            if (recipients.length === 0) {
                frappe.msgprint(__('No recipients found for the selected audience'));
                return;
            }

            // Generate newsletter HTML
            const newsletterHTML = this.generateNewsletterHTML(values);

            // Send newsletter
            const recipientEmails = recipients.map(r => r.email).join(',');

            await this.sendEmail({
                recipients: recipientEmails,
                subject: values.newsletter_name,
                content: newsletterHTML,
                use_bcc: true,
                is_newsletter: true
            });

            frappe.msgprint(__('Newsletter sent to {0} recipients', [recipients.length]));

        } catch (error) {
            frappe.msgprint(__('Error sending newsletter: {0}', [error.message]));
        } finally {
            this.state.setLoading('sendNewsletter', false);
        }
    }

    generateNewsletterHTML(values) {
        let html = `
            <div style="max-width: 600px; margin: 0 auto; font-family: Arial, sans-serif;">
        `;

        // Header image
        if (values.header_image) {
            html += `<img src="${values.header_image}" style="width: 100%; max-height: 200px; object-fit: cover;">`;
        }

        // Newsletter title
        html += `<h1 style="color: #333; padding: 20px 0;">${values.newsletter_name}</h1>`;

        // Introduction
        if (values.introduction) {
            html += `<div style="margin-bottom: 30px;">${values.introduction}</div>`;
        }

        // Sections
        if (values.sections && values.sections.length > 0) {
            values.sections.forEach(section => {
                html += `
                    <div style="margin-bottom: 30px; padding: 20px; background: #f8f9fa; border-radius: 5px;">
                        <h2 style="color: #333; margin-bottom: 15px;">${section.title}</h2>
                `;

                if (section.image) {
                    html += `<img src="${section.image}" style="width: 100%; margin-bottom: 15px; border-radius: 3px;">`;
                }

                html += `<div>${section.content}</div>`;
                html += `</div>`;
            });
        }

        // Footer
        html += `<div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; text-align: center; color: #666;">`;

        if (values.footer_message) {
            html += `<p>${values.footer_message}</p>`;
        }

        if (values.include_social_links) {
            html += this.getSocialLinksHTML();
        }

        html += `</div></div>`;

        return html;
    }

    previewNewsletter(values) {
        const html = this.generateNewsletterHTML(values);

        const previewDialog = new frappe.ui.Dialog({
            title: __('Newsletter Preview'),
            size: 'large',
            fields: [{
                fieldtype: 'HTML',
                options: `<div style="border: 1px solid #ddd; padding: 20px; background: white;">${html}</div>`
            }]
        });

        previewDialog.show();
    }

    async sendEmail(options) {
        const args = {
            recipients: options.recipients,
            subject: options.subject,
            content: options.content,
            doctype: this.frm.doctype,
            name: this.frm.docname,
            send_email: 1
        };

        if (options.attachments) {
            args.attachments = options.attachments;
        }

        if (options.use_bcc) {
            args.bcc = args.recipients;
            args.recipients = frappe.session.user_email || 'noreply@example.com';
        }

        return await this.api.call('frappe.core.doctype.communication.email.make', args);
    }

    async scheduleEmail(options) {
        // Create an Email Queue entry
        return await this.api.insert({
            doctype: 'Email Queue',
            recipients: options.recipients,
            subject: options.subject,
            message: options.content,
            reference_doctype: 'Chapter',
            reference_name: this.frm.doc.name,
            send_after: options.send_after,
            priority: 1
        });
    }

    personalizeContent(content, recipient) {
        // Replace placeholders with recipient data
        return content
            .replace(/\{name\}/g, recipient.volunteer_name || recipient.full_name || '')
            .replace(/\{email\}/g, recipient.email || '')
            .replace(/\{role\}/g, recipient.role || '')
            .replace(/\{chapter\}/g, this.frm.doc.name || '');
    }

    getUnsubscribeFooter() {
        const unsubscribeUrl = `${frappe.utils.get_url()}/unsubscribe?chapter=${this.frm.doc.name}`;

        return `
            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; text-align: center; color: #666; font-size: 12px;">
                <p>${__('You are receiving this email as a member of {0} Chapter.', [this.frm.doc.name])}</p>
                <p><a href="${unsubscribeUrl}" style="color: #666;">${__('Unsubscribe from chapter emails')}</a></p>
            </div>
        `;
    }

    getSocialLinksHTML() {
        // This would typically come from chapter settings
        return `
            <div style="margin-top: 20px;">
                <a href="#" style="margin: 0 10px;"><img src="/assets/frappe/images/facebook.png" alt="Facebook" style="width: 24px;"></a>
                <a href="#" style="margin: 0 10px;"><img src="/assets/frappe/images/twitter.png" alt="Twitter" style="width: 24px;"></a>
                <a href="#" style="margin: 0 10px;"><img src="/assets/frappe/images/linkedin.png" alt="LinkedIn" style="width: 24px;"></a>
            </div>
        `;
    }

    async loadEmailTemplate(dialog, templateName) {
        try {
            const template = await this.api.getDoc('Email Template', templateName);

            if (template) {
                dialog.set_value('subject', template.subject || '');
                dialog.set_value('message', template.response || '');
            }
        } catch (error) {
            frappe.msgprint(__('Error loading email template: {0}', [error.message]));
        }
    }

    // Track email opens (if email tracking is enabled)
    async notifyBoardMembers(eventType, data = {}) {
        // Send notification to board members about chapter events
        const boardMembers = this.getActiveBoardMembersWithEmail();

        if (!boardMembers.length) {
            console.log('No active board members with email to notify');
            return;
        }

        let subject, message;

        switch (eventType) {
            case 'chapter_submitted':
                subject = __('Chapter {0} has been submitted', [this.frm.doc.name]);
                message = __('The chapter {0} has been submitted and is now active.', [this.frm.doc.name]);
                break;

            case 'member_added':
                subject = __('New member added to {0}', [this.frm.doc.name]);
                message = __('A new member has been added to chapter {0}.', [this.frm.doc.name]);
                break;

            case 'board_change':
                subject = __('Board change in {0}', [this.frm.doc.name]);
                message = __('There has been a change in the board members of chapter {0}.', [this.frm.doc.name]);
                break;

            default:
                subject = __('Chapter {0} notification', [this.frm.doc.name]);
                message = __('This is a notification from chapter {0}.', [this.frm.doc.name]);
        }

        // Add custom data to message
        if (data.customMessage) {
            message += '\n\n' + data.customMessage;
        }

        try {
            await this.sendEmail({
                recipients: boardMembers.map(m => m.email).join(','),
                subject: subject,
                content: message,
                use_bcc: true
            });

            console.log(`Board members notified about ${eventType}`);
        } catch (error) {
            console.error('Error notifying board members:', error);
        }
    }

    async trackEmailOpen(communicationId) {
        try {
            await this.api.call('frappe.core.doctype.communication.communication.mark_email_as_seen', {
                communication: communicationId
            });
        } catch (error) {
            console.error('Error tracking email open:', error);
        }
    }

    // Get communication statistics
    async getCommunicationStats() {
        const stats = {
            total_sent: 0,
            total_received: 0,
            last_communication: null
        };

        try {
            const communications = await this.api.getList('Communication', {
                filters: {
                    reference_doctype: 'Chapter',
                    reference_name: this.frm.doc.name
                },
                fields: ['sent_or_received', 'creation'],
                order_by: 'creation desc'
            });

            communications.forEach(comm => {
                if (comm.sent_or_received === 'Sent') {
                    stats.total_sent++;
                } else {
                    stats.total_received++;
                }
            });

            if (communications.length > 0) {
                stats.last_communication = communications[0].creation;
            }

        } catch (error) {
            console.error('Error getting communication stats:', error);
        }

        return stats;
    }

    destroy() {
        // Clear email templates cache
        this.emailTemplates.clear();

        // Clear references
        this.frm = null;
        this.state = null;
        this.api = null;
    }
}
