frappe.query_reports["Members Without Chapter"] = {
    "onload": function(report) {
        // Event delegation for assign chapter buttons
        $(document).on('click', '.assign-chapter-btn', function(e) {
            e.preventDefault();
            e.stopPropagation();

            const memberName = $(this).data('member');
            const chapterName = $(this).data('chapter');

            frappe.confirm(
                `Are you sure you want to assign ${memberName} to ${chapterName}?`,
                function() {
                    assignMemberToChapter(memberName, chapterName, report);
                }
            );
        });

        // Event delegation for manual assign buttons
        $(document).on('click', '.manual-assign-btn', function(e) {
            e.preventDefault();
            e.stopPropagation();

            const memberName = $(this).data('member');
            showManualAssignDialog(memberName, report);
        });
    }
};

function assignMemberToChapter(memberName, chapterName, report) {
    frappe.call({
        method: 'verenigingen.api.member_management.assign_member_to_chapter',
        args: {
            member_name: memberName,
            chapter_name: chapterName
        },
        callback: function(r) {
            if (r.message && r.message.success) {
                frappe.msgprint({
                    message: `${memberName} has been assigned to ${chapterName}`,
                    indicator: 'green'
                });
                // Refresh the report
                if (report && report.refresh) {
                    report.refresh();
                }
            } else {
                frappe.msgprint({
                    message: r.message?.error || 'Failed to assign member to chapter',
                    indicator: 'red'
                });
            }
        },
        error: function(r) {
            frappe.msgprint({
                message: 'Error assigning member to chapter',
                indicator: 'red'
            });
        }
    });
}

function showManualAssignDialog(memberName, report) {
    // Get available chapters
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'Chapter',
            filters: {
                published: 1
            },
            fields: ['name', 'region'],
            order_by: 'name'
        },
        callback: function(r) {
            if (r.message) {
                let chapters = r.message;
                let options = chapters.map(ch => ({
                    label: ch.region ? `${ch.name} - ${ch.region}` : ch.name,
                    value: ch.name
                }));

                let dialog = new frappe.ui.Dialog({
                    title: `Assign ${memberName} to Chapter`,
                    fields: [
                        {
                            fieldtype: 'Select',
                            fieldname: 'chapter',
                            label: 'Select Chapter',
                            options: options,
                            reqd: 1
                        }
                    ],
                    primary_action_label: 'Assign',
                    primary_action: function(values) {
                        assignMemberToChapter(memberName, values.chapter, report);
                        dialog.hide();
                    }
                });

                dialog.show();
            }
        }
    });
}
