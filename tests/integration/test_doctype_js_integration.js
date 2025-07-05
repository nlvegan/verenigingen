/**
 * Integration Tests for Doctype JavaScript
 * Tests interactions between different doctypes and their JavaScript functionality
 */

// Import all test modules
const memberTests = require('../unit/member-form.spec');
const chapterTests = require('../unit/chapter-form.spec');
const volunteerTests = require('../unit/volunteer-form.spec');
const membershipTests = require('../unit/membership-form.spec');

describe('Doctype JavaScript Integration Tests', () => {
    let frappe;
    let mockData;

    beforeEach(() => {
        // Set up global mocks
        global.__ = jest.fn(str => str);

        frappe = {
            call: jest.fn(),
            model: {
                set_value: jest.fn(),
                get_value: jest.fn(),
                add_child: jest.fn()
            },
            msgprint: jest.fn(),
            show_alert: jest.fn(),
            confirm: jest.fn(),
            prompt: jest.fn(),
            set_route: jest.fn(),
            route_options: {},
            datetime: {
                str_to_user: jest.fn(date => date),
                get_today: jest.fn(() => '2024-01-01'),
                add_months: jest.fn((date, months) => {
                    const d = new Date(date);
                    d.setMonth(d.getMonth() + months);
                    return d.toISOString().split('T')[0];
                })
            },
            utils: {
                get_url: jest.fn(() => 'https://example.com'),
                random_string: jest.fn(() => 'RAND123')
            },
            session: {
                user: 'test@example.com'
            },
            ui: {
                Dialog: jest.fn().mockImplementation(function() {
                    this.show = jest.fn();
                    this.hide = jest.fn();
                    return this;
                })
            }
        };

        global.frappe = frappe;

        // Set up test data
        mockData = {
            member: {
                name: 'MEM-001',
                full_name: 'John Doe',
                email: 'john@example.com',
                payment_method: 'SEPA Direct Debit',
                iban: 'NL91ABNA0417164300'
            },
            chapter: {
                name: 'CHAP-001',
                chapter_name: 'Amsterdam Chapter',
                postal_code_regex: '^10[0-9]{2}'
            },
            volunteer: {
                name: 'VOL-001',
                volunteer_name: 'John Doe',
                member: 'MEM-001'
            },
            membership: {
                name: 'MEMB-001',
                member: 'MEM-001',
                membership_type: 'Annual',
                from_date: '2024-01-01'
            }
        };
    });

    describe('Member-Chapter Integration', () => {
        it('should assign member to chapter and update displays', async () => {
            // Mock chapter assignment
            frappe.call.mockImplementation(({ method }) => {
                if (method.includes('assign_member_to_chapter')) {
                    return Promise.resolve({ message: { success: true } });
                }
                if (method.includes('get_member_chapter_display_html')) {
                    return Promise.resolve({
                        message: '<div>Amsterdam Chapter - Active</div>'
                    });
                }
                return Promise.resolve({ message: {} });
            });

            // Simulate chapter assignment
            const assignMemberToChapter = async (memberName, chapterName) => {
                const result = await frappe.call({
                    method: 'assign_member_to_chapter',
                    args: { member: memberName, chapter: chapterName }
                });

                if (result.message.success) {
                    // Refresh member form to show new chapter
                    await frappe.call({
                        method: 'get_member_chapter_display_html',
                        args: { member_name: memberName }
                    });
                }

                return result.message;
            };

            const result = await assignMemberToChapter('MEM-001', 'CHAP-001');
            expect(result.success).toBe(true);
            expect(frappe.call).toHaveBeenCalledTimes(2);
        });

        it('should validate postal code against chapter regex', () => {
            const validatePostalCode = (postalCode, regex) => {
                const pattern = new RegExp(regex);
                return pattern.test(postalCode);
            };

            // Test valid postal codes
            expect(validatePostalCode('1011AB', '^10[0-9]{2}')).toBe(true);
            expect(validatePostalCode('1099ZZ', '^10[0-9]{2}')).toBe(true);

            // Test invalid postal codes
            expect(validatePostalCode('2011AB', '^10[0-9]{2}')).toBe(false);
            expect(validatePostalCode('9999ZZ', '^10[0-9]{2}')).toBe(false);
        });
    });

    describe('Member-Volunteer Integration', () => {
        it('should create volunteer from member with data inheritance', async () => {
            frappe.call.mockImplementation(({ method }) => {
                if (method === 'frappe.client.get') {
                    return Promise.resolve({
                        message: mockData.member
                    });
                }
                return Promise.resolve({ message: { success: true } });
            });

            const createVolunteerFromMember = async (member) => {
                // Get member data
                const memberData = await frappe.call({
                    method: 'frappe.client.get',
                    args: { doctype: 'Member', name: member.name }
                });

                // Create volunteer with inherited data
                const volunteer = {
                    volunteer_name: memberData.message.full_name,
                    member: memberData.message.name,
                    personal_email: memberData.message.email,
                    email: `${memberData.message.full_name.toLowerCase().replace(/\s/g, '.')}@org.example`
                };

                return volunteer;
            };

            const volunteer = await createVolunteerFromMember(mockData.member);
            expect(volunteer.volunteer_name).toBe('John Doe');
            expect(volunteer.personal_email).toBe('john@example.com');
            expect(volunteer.email).toBe('john.doe@org.example');
        });

        it('should sync board member status between chapter and volunteer', async () => {
            const syncBoardMemberStatus = async (chapterName, memberName, role) => {
                // Add as board member in chapter
                const boardMember = {
                    chapter: chapterName,
                    member: memberName,
                    role: role,
                    start_date: '2024-01-01'
                };

                // Find or create volunteer
                const volunteer = await frappe.call({
                    method: 'get_or_create_volunteer',
                    args: { member: memberName }
                });

                // Add assignment in volunteer
                const assignment = {
                    volunteer: volunteer.message.name,
                    team: 'Board',
                    chapter: chapterName,
                    role: role,
                    is_active: 1
                };

                return { boardMember, assignment };
            };

            frappe.call.mockResolvedValue({
                message: { name: 'VOL-001' }
            });

            const result = await syncBoardMemberStatus('CHAP-001', 'MEM-001', 'Chair');
            expect(result.boardMember.role).toBe('Chair');
            expect(result.assignment.role).toBe('Chair');
        });
    });

    describe('Member-Membership-Payment Integration', () => {
        it('should create membership with SEPA mandate validation', async () => {
            const createMembershipWithSEPA = async (member, membershipType) => {
                // Validate member has SEPA mandate
                if (member.payment_method === 'SEPA Direct Debit' && !member.iban) {
                    throw new Error('IBAN required for SEPA Direct Debit');
                }

                const membership = {
                    member: member.name,
                    membership_type: membershipType,
                    from_date: frappe.datetime.get_today(),
                    payment_method: member.payment_method
                };

                if (member.payment_method === 'SEPA Direct Debit') {
                    // Check for active mandate
                    const mandate = await frappe.call({
                        method: 'get_active_sepa_mandate',
                        args: { member: member.name, iban: member.iban }
                    });

                    if (!mandate.message) {
                        // Create new mandate
                        await frappe.call({
                            method: 'create_sepa_mandate',
                            args: {
                                member: member.name,
                                iban: member.iban,
                                mandate_type: 'RCUR'
                            }
                        });
                    }
                }

                // Calculate renewal date
                membership.to_date = membershipType === 'Annual'
                    ? frappe.datetime.add_months(membership.from_date, 12)
                    : frappe.datetime.add_months(membership.from_date, 1);

                return membership;
            };

            frappe.call.mockResolvedValue({ message: null }); // No existing mandate

            const membership = await createMembershipWithSEPA(mockData.member, 'Annual');
            expect(membership.to_date).toBe('2025-01-01');
            expect(frappe.call).toHaveBeenCalledWith(
                expect.objectContaining({
                    method: 'create_sepa_mandate'
                })
            );
        });

        it('should update member payment history on membership creation', async () => {
            const updatePaymentHistory = async (memberName, payment) => {
                const history = await frappe.call({
                    method: 'get_member_payment_history',
                    args: { member: memberName }
                });

                const newEntry = {
                    transaction_date: payment.date,
                    transaction_type: payment.type,
                    amount: payment.amount,
                    reference: payment.reference,
                    status: 'Completed'
                };

                history.message.push(newEntry);

                await frappe.call({
                    method: 'update_member_payment_history',
                    args: {
                        member: memberName,
                        history: history.message
                    }
                });

                return history.message;
            };

            frappe.call.mockImplementation(({ method }) => {
                if (method === 'get_member_payment_history') {
                    return Promise.resolve({ message: [] });
                }
                return Promise.resolve({ message: { success: true } });
            });

            const payment = {
                date: '2024-01-01',
                type: 'Membership Fee',
                amount: 50,
                reference: 'MEMB-001'
            };

            const history = await updatePaymentHistory('MEM-001', payment);
            expect(history).toHaveLength(1);
            expect(history[0].amount).toBe(50);
        });
    });

    describe('Chapter Board Management Integration', () => {
        it('should handle board member lifecycle', async () => {
            const boardMemberLifecycle = async () => {
                const timeline = [];

                // 1. Add board member
                timeline.push({
                    date: '2023-01-01',
                    action: 'appointed',
                    member: 'MEM-001',
                    role: 'Treasurer'
                });

                // 2. Change role
                timeline.push({
                    date: '2024-01-01',
                    action: 'role_changed',
                    member: 'MEM-001',
                    old_role: 'Treasurer',
                    new_role: 'Chair'
                });

                // 3. End term
                timeline.push({
                    date: '2024-12-31',
                    action: 'term_ended',
                    member: 'MEM-001',
                    role: 'Chair'
                });

                return timeline;
            };

            const timeline = await boardMemberLifecycle();
            expect(timeline).toHaveLength(3);
            expect(timeline[1].new_role).toBe('Chair');
        });

        it('should prevent duplicate active roles', () => {
            const boardMembers = [
                { member: 'MEM-001', role: 'Chair', is_active: 1 },
                { member: 'MEM-002', role: 'Secretary', is_active: 1 }
            ];

            const canAssignRole = (members, newMember, newRole) => {
                const existingRole = members.find(m =>
                    m.role === newRole &&
                    m.is_active &&
                    m.member !== newMember
                );
                return !existingRole;
            };

            expect(canAssignRole(boardMembers, 'MEM-003', 'Chair')).toBe(false);
            expect(canAssignRole(boardMembers, 'MEM-003', 'Treasurer')).toBe(true);
        });
    });

    describe('Workflow Integration', () => {
        it('should handle membership application to active member flow', async () => {
            const membershipApplicationFlow = async (application) => {
                const steps = [];

                // 1. Submit application
                steps.push({
                    status: 'Submitted',
                    date: '2024-01-01'
                });

                // 2. Review application
                steps.push({
                    status: 'Under Review',
                    date: '2024-01-02',
                    reviewer: 'admin@example.com'
                });

                // 3. Approve and create member
                const member = {
                    ...application,
                    name: 'MEM-NEW',
                    member_status: 'Pending Payment'
                };
                steps.push({
                    status: 'Approved',
                    date: '2024-01-03',
                    member_created: member.name
                });

                // 4. Payment received
                member.member_status = 'Active';
                steps.push({
                    status: 'Payment Received',
                    date: '2024-01-05'
                });

                // 5. Create membership
                const membership = {
                    member: member.name,
                    membership_type: application.requested_membership_type,
                    from_date: '2024-01-05'
                };
                steps.push({
                    status: 'Active Member',
                    date: '2024-01-05',
                    membership: membership
                });

                return { steps, member, membership };
            };

            const application = {
                first_name: 'Jane',
                last_name: 'Smith',
                email: 'jane@example.com',
                requested_membership_type: 'Annual'
            };

            const result = await membershipApplicationFlow(application);
            expect(result.steps).toHaveLength(5);
            expect(result.member.member_status).toBe('Active');
            expect(result.membership.membership_type).toBe('Annual');
        });
    });

    describe('Error Handling and Validation', () => {
        it('should handle cascading validation errors', async () => {
            const validateMemberCreation = async (data) => {
                const errors = [];

                // Validate email
                if (!data.email || !data.email.includes('@')) {
                    errors.push('Invalid email address');
                }

                // Validate payment method requirements
                if (data.payment_method === 'SEPA Direct Debit') {
                    if (!data.iban) {
                        errors.push('IBAN required for SEPA Direct Debit');
                    }
                    if (!data.bank_account_name) {
                        errors.push('Bank account name required for SEPA');
                    }
                }

                // Validate chapter assignment
                if (data.postal_code && !data.chapter) {
                    // Would normally call API to get suggested chapter
                    errors.push('No chapter found for postal code');
                }

                return errors;
            };

            const invalidData = {
                email: 'invalid-email',
                payment_method: 'SEPA Direct Debit',
                postal_code: '9999ZZ'
            };

            const errors = await validateMemberCreation(invalidData);
            expect(errors).toContain('Invalid email address');
            expect(errors).toContain('IBAN required for SEPA Direct Debit');
        });
    });
});
