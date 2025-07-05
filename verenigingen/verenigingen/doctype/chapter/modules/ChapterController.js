// verenigingen/verenigingen/doctype/chapter/modules/ChapterController.js

import { BoardManager } from './BoardManager.js';
import { MemberManager } from './MemberManager.js';
import { CommunicationManager } from './CommunicationManager.js';
import { ChapterStatistics } from './ChapterStatistics.js';
import { ChapterUI } from './ChapterUI.js';
import { ChapterState } from './ChapterState.js';
import { ChapterValidation } from '../utils/ChapterValidation.js';
import { ChapterConfig } from '../config/ChapterConfig.js';

export class ChapterController {
    constructor(frm) {
        this.frm = frm;
        this.state = new ChapterState();
        this.ui = new ChapterUI(frm, this.state);

        // Initialize managers
        this.boardManager = new BoardManager(frm, this.state, this.ui);
        this.memberManager = new MemberManager(frm, this.state, this.ui);
        this.communicationManager = new CommunicationManager(frm, this.state);
        this.statistics = new ChapterStatistics(frm, this.state);

        // Bind event handlers
        this.bindEvents();

        // Initialize state
        this.initializeState();
    }

    bindEvents() {
        // Subscribe to state changes
        this.state.subscribe((path, value) => {
            this.handleStateChange(path, value);
        });
    }

    initializeState() {
        if (this.frm.doc.name) {
            // Load initial data
            this.state.update('chapter', {
                name: this.frm.doc.name,
                region: this.frm.doc.region,
                boardMembers: this.frm.doc.board_members || [],
                members: this.frm.doc.members || []
            });
        }
    }

    refresh() {
        // Clear any existing UI elements
        this.ui.clearCustomButtons();

        // Add navigation buttons
        this.addNavigationButtons();

        // Add action buttons
        this.addActionButtons();

        // Add board management buttons
        if (this.frm.doc.name) {
            this.boardManager.addButtons();
            this.memberManager.addButtons();
            this.communicationManager.addButtons();
            this.statistics.addButtons();
        }

        // Update UI elements
        this.ui.updateMembersSummary();
        this.ui.updatePostalCodePreview();

        // Set up board members grid
        this.boardManager.setupGrid();

        // Check for board memberships for current user
        this.checkUserBoardMemberships();
    }

    addNavigationButtons() {
        const buttons = [
            {
                label: __('View Members'),
                action: () => this.memberManager.viewMembers(),
                group: __('View')
            },
            {
                label: __('Current SEPA Mandate'),
                action: () => this.navigateToCurrentMandate(),
                group: __('View'),
                condition: () => this.hasCurrentMandate()
            }
        ];

        buttons.forEach(btn => {
            if (!btn.condition || btn.condition()) {
                this.ui.addButton(btn.label, btn.action, btn.group);
            }
        });
    }

    addActionButtons() {
        const buttons = [
            {
                label: __('Manage Board Members'),
                action: () => this.boardManager.showManageDialog(),
                group: __('Board')
            },
            {
                label: __('Transition Board Role'),
                action: () => this.boardManager.showTransitionDialog(),
                group: __('Board')
            },
            {
                label: __('View Board History'),
                action: () => this.boardManager.showHistory(),
                group: __('Board')
            },
            {
                label: __('Sync with Volunteer System'),
                action: () => this.boardManager.syncWithVolunteerSystem(),
                group: __('Board')
            },
            {
                label: __('Bulk Remove Board Members'),
                action: () => this.boardManager.showBulkRemoveDialog(),
                group: __('Board')
            }
        ];

        buttons.forEach(btn => {
            this.ui.addButton(btn.label, btn.action, btn.group);
        });
    }

    async checkUserBoardMemberships() {
        try {
            const result = await frappe.call({
                method: 'verenigingen.verenigingen.doctype.member.member.get_board_memberships',
                args: {
                    member_name: this.frm.doc.name
                }
            });

            if (result.message && result.message.length) {
                this.ui.showBoardMemberships(result.message);
            }
        } catch (error) {
            console.error('Error checking board memberships:', error);
        }
    }

    hasCurrentMandate() {
        // Check if chapter has a current SEPA mandate
        return this.frm.doc.current_sepa_mandate ? true : false;
    }

    navigateToCurrentMandate() {
        if (this.frm.doc.current_sepa_mandate) {
            frappe.set_route('Form', 'SEPA Mandate', this.frm.doc.current_sepa_mandate);
        }
    }

    async beforeSave() {
        // Validate board members
        const validation = await this.boardManager.validateBoardMembers();
        if (!validation.isValid) {
            frappe.validated = false;
            frappe.msgprint({
                title: __('Validation Error'),
                indicator: 'red',
                message: validation.errors.join('<br>')
            });
            return false;
        }

        // Validate postal codes
        const postalValidation = ChapterValidation.validatePostalCodes(this.frm.doc.postal_codes);
        if (!postalValidation.isValid) {
            this.ui.showPostalCodeWarning(postalValidation.invalidPatterns);
        }

        return true;
    }

    afterSave() {
        // Refresh the form to show updated data
        this.frm.refresh();

        // Show success message
        frappe.show_alert({
            message: __('Chapter saved successfully'),
            indicator: 'green'
        }, 5);
    }

    handleStateChange(path, value) {
        // Handle state changes
        console.log('State changed:', path, value);

        // Update UI based on state changes
        if (path.startsWith('boardMembers')) {
            this.boardManager.handleBoardMembersChange();
        } else if (path.startsWith('ui.bulkActionsVisible')) {
            this.ui.toggleBulkActions(value);
        }
    }
    validate() {
        // Run validation checks
        const validations = [];

        // Validate chapter info
        const chapterValidation = ChapterValidation.validateChapterInfo(this.frm.doc);
        if (!chapterValidation.isValid) {
            validations.push(...chapterValidation.errors);
        }

        // Validate board members
        const boardValidation = ChapterValidation.validateBoardMembers(this.frm.doc.board_members);
        if (!boardValidation.isValid) {
            validations.push(...boardValidation.errors);
        }

        // Validate postal codes
        if (this.frm.doc.postal_codes) {
            const postalValidation = ChapterValidation.validatePostalCodes(this.frm.doc.postal_codes);
            if (!postalValidation.isValid) {
                validations.push(...postalValidation.errors);
            }
        }

        if (validations.length > 0) {
            frappe.msgprint({
                title: __('Validation Errors'),
                indicator: 'red',
                message: validations.join('<br>')
            });
            return false;
        }

        return true;
    }

    onSubmit() {
        // Handle form submission
        console.log('Chapter submitted:', this.frm.doc.name);

        // Notify board members about chapter submission
        if (ChapterConfig.features.enableCommunications) {
            this.communicationManager.notifyBoardMembers('chapter_submitted');
        }
    }

    onPostalCodesChange() {
        // Handle postal codes change
        const validation = ChapterValidation.validatePostalCodes(this.frm.doc.postal_codes);

        if (!validation.isValid) {
            this.ui.showPostalCodeWarning(validation.invalidPatterns);
        }

        this.ui.updatePostalCodePreview();
    }

    onChapterHeadChange() {
        // Handle chapter head change
        if (this.frm.doc.chapter_head) {
            // Verify the member exists and is active
            frappe.db.get_value('Member', this.frm.doc.chapter_head, 'status', (r) => {
                if (r && r.status !== 'Active') {
                    frappe.msgprint(__('Warning: Selected chapter head is not an active member'));
                }
            });
        }
    }

    onRegionChange() {
        // Handle region change
        if (this.frm.doc.region) {
            // Update state
            this.state.update('chapter.region', this.frm.doc.region);

            // Suggest postal codes for the region if available
            this.suggestPostalCodesForRegion();
        }
    }

    onPublishedChange() {
        // Handle published status change
        if (this.frm.doc.published) {
            frappe.show_alert({
                message: __('Chapter is now published and visible to members'),
                indicator: 'green'
            }, 5);
        } else {
            frappe.show_alert({
                message: __('Chapter is now unpublished and hidden from members'),
                indicator: 'orange'
            }, 5);
        }
    }

    async updateChapterHead() {
        // Update chapter head based on board members with chair role
        const boardMembers = this.boardManager.getActiveBoardMembers();

        // Find members with chair roles
        const chairMembers = [];
        for (const member of boardMembers) {
            if (member.chapter_role) {
                try {
                    const role = await frappe.db.get_doc('Chapter Role', member.chapter_role);
                    if (role.is_chair && role.is_active) {
                        chairMembers.push(member);
                    }
                } catch (error) {
                    console.error('Error checking role:', error);
                }
            }
        }

        if (chairMembers.length > 0) {
            // Get the member ID from the volunteer
            try {
                const volunteer = await frappe.db.get_doc('Volunteer', chairMembers[0].volunteer);
                if (volunteer.member) {
                    this.frm.set_value('chapter_head', volunteer.member);
                }
            } catch (error) {
                console.error('Error setting chapter head:', error);
            }
        } else {
            this.frm.set_value('chapter_head', null);
        }
    }

    validatePostalCodes() {
        // Validate postal codes field
        const validation = ChapterValidation.validatePostalCodes(this.frm.doc.postal_codes);

        if (!validation.isValid) {
            frappe.msgprint({
                title: __('Invalid Postal Codes'),
                indicator: 'red',
                message: __('The following postal code patterns are invalid: {0}',
                    [validation.invalidPatterns.join(', ')])
            });

            // Set field to valid patterns only
            this.frm.set_value('postal_codes', validation.validPatterns.join(', '));
        }

        return validation.isValid;
    }

    async suggestPostalCodesForRegion() {
        // Suggest postal codes based on region
        try {
            const suggestions = await frappe.db.get_list('Chapter', {
                filters: {
                    region: this.frm.doc.region,
                    name: ['!=', this.frm.doc.name]
                },
                fields: ['postal_codes'],
                limit: 5
            });

            if (suggestions && suggestions.length > 0) {
                const allCodes = new Set();
                suggestions.forEach(s => {
                    if (s.postal_codes) {
                        s.postal_codes.split(',').forEach(code => allCodes.add(code.trim()));
                    }
                });

                if (allCodes.size > 0) {
                    frappe.show_alert({
                        message: __('Other chapters in {0} use postal codes: {1}',
                            [this.frm.doc.region, Array.from(allCodes).join(', ')]),
                        indicator: 'blue'
                    }, 10);
                }
            }
        } catch (error) {
            console.error('Error suggesting postal codes:', error);
        }
    }
    destroy() {
        // Cleanup all managers
        this.boardManager.destroy();
        this.memberManager.destroy();
        this.communicationManager.destroy();
        this.statistics.destroy();
        this.ui.destroy();
        this.state.destroy();
    }
}
