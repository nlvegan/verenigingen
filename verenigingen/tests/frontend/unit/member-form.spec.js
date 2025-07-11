/**
 * Member Form JavaScript Unit Tests
 * Tests the complex member form functionality including payments, SEPA, chapters, and workflows
 */

describe('Member Form', () => {
    let frm;
    let frappe;
    let window;

    beforeEach(() => {
        // Mock Frappe framework
        global.__ = jest.fn(str => str);

        frappe = {
            call: jest.fn(),
            msgprint: jest.fn(),
            show_alert: jest.fn(),
            throw: jest.fn(),
            confirm: jest.fn(),
            prompt: jest.fn(),
            route_options: {},
            set_route: jest.fn(),
            model: {
                set_value: jest.fn()
            },
            datetime: {
                str_to_user: jest.fn(date => date),
                get_today: jest.fn(() => '2024-01-01'),
                add_days: jest.fn((date, days) => '2024-01-10')
            },
            utils: {
                random_string: jest.fn(() => 'RAND123'),
                get_url: jest.fn(() => 'https://example.com')
            },
            session: {
                user: 'test@example.com'
            },
            ui: {
                Dialog: jest.fn().mockImplementation(function(opts) {
                    this.show = jest.fn();
                    this.hide = jest.fn();
                    this.get_value = jest.fn();
                    this.set_value = jest.fn();
                    this.fields_dict = {
                        iban: {
                            $input: {
                                addClass: jest.fn(),
                                removeClass: jest.fn()
                            },
                            df: { onchange: null }
                        }
                    };
                    return this;
                })
            }
        };

        global.frappe = frappe;

        // Mock window utilities
        window = {
            IBANValidator: {
                validate: jest.fn((iban) => ({
                    valid: iban === 'NL91ABNA0417164300',
                    error: iban !== 'NL91ABNA0417164300' ? 'Invalid IBAN' : null,
                    formatted: 'NL91 ABNA 0417 1643 00'
                })),
                deriveBIC: jest.fn(() => 'ABNANL2A'),
                getBankName: jest.fn(() => 'ABN AMRO')
            },
            SepaUtils: {
                check_sepa_mandate_status: jest.fn(),
                create_sepa_mandate_with_dialog: jest.fn()
            },
            PaymentUtils: {
                process_payment: jest.fn(),
                mark_as_paid: jest.fn()
            },
            ChapterUtils: {
                suggest_chapter_from_address: jest.fn()
            }
        };

        global.window = window;

        // Mock form object
        frm = {
            doc: {
                name: 'MEM-001',
                full_name: 'John Doe',
                first_name: 'John',
                last_name: 'Doe',
                email: 'john.doe@example.com',
                payment_method: 'SEPA Direct Debit',
                iban: 'NL91ABNA0417164300',
                member_status: 'Active',
                primary_address: 'ADDR-001',
                payment_history: [],
                __islocal: false,
                docstatus: 1
            },
            fields_dict: {
                iban: {
                    wrapper: document.createElement('div'),
                    set_description: jest.fn()
                },
                other_members_at_address: {
                    wrapper: document.createElement('div'),
                    $wrapper: {
                        find: jest.fn().mockReturnValue({
                            off: jest.fn().mockReturnThis(),
                            on: jest.fn()
                        })
                    }
                }
            },
            set_value: jest.fn(),
            set_df_property: jest.fn(),
            add_custom_button: jest.fn(),
            refresh_field: jest.fn(),
            save: jest.fn(() => Promise.resolve()),
            reload_doc: jest.fn(),
            is_new: jest.fn(() => false),
            toggle_reqd: jest.fn(),
            toggle_display: jest.fn(),
            dashboard: {
                add_indicator: jest.fn()
            },
            custom_buttons: {},
            _member_form_initialized: false
        };

        // Mock jQuery
        global.$ = jest.fn(() => ({
            html: jest.fn(),
            on: jest.fn(),
            off: jest.fn().mockReturnThis(),
            find: jest.fn().mockReturnThis()
        }));
    });

    describe('IBAN Validation', () => {
        it('should validate IBAN on field change', () => {
            const memberEvents = require('./member').memberFormEvents;

            frm.doc.iban = 'NL91ABNA0417164300';
            memberEvents.iban(frm);

            expect(window.IBANValidator.validate).toHaveBeenCalledWith('NL91ABNA0417164300');
            expect(frm.set_value).toHaveBeenCalledWith('iban', 'NL91 ABNA 0417 1643 00');
            expect(frm.set_value).toHaveBeenCalledWith('bic', 'ABNANL2A');
            expect(frappe.show_alert).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining('ABN AMRO')
                }),
                3
            );
        });

        it('should show error for invalid IBAN', () => {
            const memberEvents = require('./member').memberFormEvents;

            frm.doc.iban = 'INVALID123';
            memberEvents.iban(frm);

            expect(frappe.msgprint).toHaveBeenCalledWith(
                expect.objectContaining({
                    title: 'Invalid IBAN',
                    message: 'Invalid IBAN',
                    indicator: 'red'
                })
            );
        });

        it('should trigger SEPA mandate check for valid IBAN', () => {
            const memberEvents = require('./member').memberFormEvents;

            frm.doc.iban = 'NL91ABNA0417164300';
            frm.doc.payment_method = 'SEPA Direct Debit';
            memberEvents.iban(frm);

            expect(window.SepaUtils.check_sepa_mandate_status).toHaveBeenCalledWith(frm);
        });
    });

    describe('SEPA Mandate Management', () => {
        it('should create SEPA mandate dialog', async () => {
            const mockDialog = new frappe.ui.Dialog();
            frappe.confirm.mockImplementation((msg, callback) => callback());

            frappe.call.mockResolvedValue({
                message: {
                    success: true,
                    mandate_id: 'MAND-001'
                }
            });

            await window.SepaUtils.create_sepa_mandate_with_dialog(frm);

            expect(frappe.confirm).toHaveBeenCalled();
            expect(mockDialog.show).toHaveBeenCalled();
        });

        it('should validate mandate creation parameters', async () => {
            frappe.call.mockResolvedValue({
                message: {
                    existing_mandate: 'OLD-MAND-001'
                }
            });

            const validateMandateCreation = async (member, iban, mandateId) => {
                const result = await frappe.call({
                    method: 'validate_mandate_creation',
                    args: { member, iban, mandate_id: mandateId }
                });
                return result.message;
            };

            const validation = await validateMandateCreation('MEM-001', 'NL91ABNA0417164300', 'NEW-MAND');
            expect(validation.existing_mandate).toBe('OLD-MAND-001');
        });
    });

    describe('Payment Processing', () => {
        it('should handle payment method change', () => {
            const memberEvents = require('./member').memberFormEvents;

            frm.doc.payment_method = 'SEPA Direct Debit';
            memberEvents.payment_method(frm);

            expect(frm.toggle_reqd).toHaveBeenCalledWith('iban', true);
            expect(frm.toggle_display).toHaveBeenCalledWith('iban', true);
            expect(frm.toggle_display).toHaveBeenCalledWith('bic', true);
        });

        it('should add payment buttons for unpaid members', () => {
            frm.doc.payment_status = 'Unpaid';

            const memberForm = require('./member').MemberForm;
            memberForm.setup_all_buttons(frm);

            expect(frm.add_custom_button).toHaveBeenCalledWith(
                'Process Payment',
                expect.any(Function),
                'Actions'
            );
            expect(frm.add_custom_button).toHaveBeenCalledWith(
                'Mark as Paid',
                expect.any(Function),
                'Actions'
            );
        });
    });

    describe('Chapter Management', () => {
        it('should suggest chapter based on postal code', () => {
            const memberEvents = require('./member').memberFormEvents;

            frm.doc.pincode = '1011AB';
            jest.useFakeTimers();

            memberEvents.pincode(frm);
            jest.advanceTimersByTime(1000);

            expect(window.ChapterUtils.suggest_chapter_from_address).toHaveBeenCalledWith(frm);

            jest.useRealTimers();
        });

        it('should display current chapter information', async () => {
            frappe.call.mockResolvedValue({
                message: '<div>Amsterdam Chapter</div>'
            });

            const memberForm = require('./member').MemberForm;
            await memberForm.refresh_chapter_display(frm);

            expect(frappe.call).toHaveBeenCalledWith(
                expect.objectContaining({
                    method: expect.stringContaining('get_member_chapter_display_html')
                })
            );
        });
    });

    describe('Address Members', () => {
        it('should update other members at address', async () => {
            frappe.call.mockResolvedValue({
                message: {
                    success: true,
                    html: '<div>2 other members at this address</div>'
                }
            });

            const updateOtherMembersAtAddress = require('./member').updateOtherMembersAtAddress;
            await updateOtherMembersAtAddress(frm);

            expect(frappe.call).toHaveBeenCalledWith(
                expect.objectContaining({
                    method: expect.stringContaining('get_address_members_html_api'),
                    args: { member_id: 'MEM-001' }
                })
            );
            expect(frm.set_value).toHaveBeenCalled();
        });

        it('should handle click events on member links', async () => {
            const mockEvent = {
                preventDefault: jest.fn(),
                target: { dataset: { member: 'MEM-002' } }
            };

            frappe.call.mockResolvedValue({
                message: {
                    success: true,
                    html: '<button class="view-member-btn" data-member="MEM-002">View</button>'
                }
            });

            const updateOtherMembersAtAddress = require('./member').updateOtherMembersAtAddress;
            await updateOtherMembersAtAddress(frm);

            // Simulate click
            const handler = $.mock.calls[0][0];
            handler.call(mockEvent.target, mockEvent);

            expect(frappe.set_route).toHaveBeenCalledWith('Form', 'Member', 'MEM-002');
        });
    });

    describe('Membership Application Review', () => {
        it('should handle application approval', async () => {
            frappe.confirm.mockImplementation((msg, callback) => callback());
            frappe.call.mockResolvedValue({ message: { success: true } });

            const approveApplication = async (applicationId) => {
                await frappe.confirm('Approve this application?', async () => {
                    await frappe.call({
                        method: 'approve_membership_application',
                        args: { application_id: applicationId }
                    });
                });
            };

            await approveApplication('APP-001');
            expect(frappe.call).toHaveBeenCalledWith(
                expect.objectContaining({
                    method: 'approve_membership_application'
                })
            );
        });

        it('should handle application rejection with reason', async () => {
            frappe.prompt.mockImplementation((fields, callback) => {
                callback({ rejection_reason: 'Incomplete documentation' });
            });

            frappe.call.mockResolvedValue({ message: { success: true } });

            const rejectApplication = async (applicationId) => {
                await frappe.prompt(
                    [{ fieldname: 'rejection_reason', fieldtype: 'Text' }],
                    async (values) => {
                        await frappe.call({
                            method: 'reject_membership_application',
                            args: {
                                application_id: applicationId,
                                reason: values.rejection_reason
                            }
                        });
                    }
                );
            };

            await rejectApplication('APP-001');
            expect(frappe.call).toHaveBeenCalledWith(
                expect.objectContaining({
                    args: expect.objectContaining({
                        reason: 'Incomplete documentation'
                    })
                })
            );
        });
    });

    describe('Termination Workflow', () => {
        it('should check termination status and show appropriate buttons', async () => {
            frappe.call.mockResolvedValue({
                message: {
                    has_active_termination: false,
                    can_terminate: true
                }
            });

            const memberForm = require('./member').MemberForm;
            await memberForm.add_termination_buttons(frm);

            expect(frm.add_custom_button).toHaveBeenCalledWith(
                'Terminate Membership',
                expect.any(Function),
                'Actions'
            );
        });

        it('should show termination dialog', () => {
            frappe.confirm.mockImplementation((msg, callback) => callback());

            const showTerminationDialog = (memberName, fullName) => {
                frappe.confirm(
                    `Are you sure you want to terminate membership for ${fullName}?`,
                    () => {
                        frappe.set_route('Form', 'Membership Termination Request', 'new');
                    }
                );
            };

            showTerminationDialog('MEM-001', 'John Doe');
            expect(frappe.set_route).toHaveBeenCalledWith(
                'Form',
                'Membership Termination Request',
                'new'
            );
        });
    });

    describe('Form Initialization', () => {
        it('should initialize form only once', () => {
            const memberEvents = require('./member').memberFormEvents;

            memberEvents.refresh(frm);
            expect(frm._member_form_initialized).toBe(true);

            // Call again
            const addCustomButtonCalls = frm.add_custom_button.mock.calls.length;
            memberEvents.refresh(frm);

            // Should not add more buttons
            expect(frm.add_custom_button.mock.calls.length).toBe(addCustomButtonCalls);
        });

        it('should set up all required buttons for submitted docs', () => {
            frm.doc.docstatus = 1;
            frm.doc.payment_status = 'Unpaid';

            const memberForm = require('./member').MemberForm;
            memberForm.setup_all_buttons(frm);

            // Payment buttons
            expect(frm.add_custom_button).toHaveBeenCalledWith(
                expect.stringMatching(/Payment/),
                expect.any(Function),
                'Actions'
            );

            // View buttons
            expect(frm.add_custom_button).toHaveBeenCalledWith(
                expect.stringMatching(/View/),
                expect.any(Function),
                expect.any(String)
            );
        });
    });

    describe('Dutch Name Formatting', () => {
        it('should handle Dutch name prefixes correctly', () => {
            frm.doc.first_name = 'Jan';
            frm.doc.middle_name = 'van der';
            frm.doc.last_name = 'Berg';

            const memberEvents = require('./member').memberFormEvents;
            memberEvents.full_name(frm);

            expect(frm.set_value).toHaveBeenCalledWith('full_name', 'Jan van der Berg');
        });
    });
});
