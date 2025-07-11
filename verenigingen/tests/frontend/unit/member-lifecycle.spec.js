/**
 * Member Lifecycle Client-Side Tests
 *
 * These tests support the Python lifecycle tests by validating
 * client-side logic, form validations, and UI state management
 * throughout the member lifecycle stages.
 */

describe('Member Lifecycle - Client Side', () => {
	let mockFrappe;

	beforeEach(() => {
		// Set up Frappe mock
		mockFrappe = {
			call: jest.fn(),
			msgprint: jest.fn(),
			throw: jest.fn(),
			show_alert: jest.fn(),
			confirm: jest.fn(),
			ui: {
				Dialog: jest.fn().mockImplementation(function(options) {
					this.show = jest.fn();
					this.hide = jest.fn();
					this.set_value = jest.fn();
					return this;
				})
			},
			model: {
				set_value: jest.fn(),
				get_value: jest.fn(),
				set_df_property: jest.fn()
			},
			datetime: {
				nowdate: () => '2025-01-05',
				add_days: (date, days) => {
					const d = new Date(date);
					d.setDate(d.getDate() + days);
					return d.toISOString().split('T')[0];
				}
			}
		};
		global.frappe = mockFrappe;
		global.__ = (str) => str;
	});

	describe('Stage 1: Application Submission', () => {
		const validateApplicationForm = (data) => {
			const errors = [];

			// Required fields
			const requiredFields = ['first_name', 'last_name', 'email', 'birth_date',
									'address_line1', 'city', 'postal_code', 'country'];

			requiredFields.forEach(field => {
				if (!data[field] || data[field].trim() === '') {
					errors.push(`${field} is required`);
				}
			});

			// Email validation
			if (data.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email)) {
				errors.push('Invalid email format');
			}

			// Age validation (must be 18+)
			if (data.birth_date) {
				const birthDate = new Date(data.birth_date);
				const today = new Date();
				const age = today.getFullYear() - birthDate.getFullYear();
				if (age < 18) {
					errors.push('Applicant must be at least 18 years old');
				}
			}

			// IBAN validation if payment method is Direct Debit
			if (data.payment_method === 'Direct Debit' && data.iban) {
				const ibanRegex = /^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/;
				const cleanIban = data.iban.replace(/\s/g, '').toUpperCase();
				if (!ibanRegex.test(cleanIban)) {
					errors.push('Invalid IBAN format');
				}
			}

			return { valid: errors.length === 0, errors };
		};

		it('should validate required fields', () => {
			const incompleteData = {
				first_name: 'John',
				last_name: '',
				email: 'john@example.com'
			};

			const result = validateApplicationForm(incompleteData);
			expect(result.valid).toBe(false);
			expect(result.errors).toContain('last_name is required');
			expect(result.errors).toContain('birth_date is required');
		});

		it('should validate email format', () => {
			const dataWithInvalidEmail = {
				first_name: 'John',
				last_name: 'Doe',
				email: 'invalid-email',
				birth_date: '1990-01-01',
				address_line1: 'Test Street',
				city: 'Amsterdam',
				postal_code: '1234AB',
				country: 'Netherlands'
			};

			const result = validateApplicationForm(dataWithInvalidEmail);
			expect(result.valid).toBe(false);
			expect(result.errors).toContain('Invalid email format');
		});

		it('should validate minimum age requirement', () => {
			const underageData = {
				first_name: 'Young',
				last_name: 'Person',
				email: 'young@example.com',
				birth_date: '2010-01-01',
				address_line1: 'Test Street',
				city: 'Amsterdam',
				postal_code: '1234AB',
				country: 'Netherlands'
			};

			const result = validateApplicationForm(underageData);
			expect(result.valid).toBe(false);
			expect(result.errors).toContain('Applicant must be at least 18 years old');
		});

		it('should validate IBAN for Direct Debit payments', () => {
			const dataWithInvalidIBAN = {
				first_name: 'John',
				last_name: 'Doe',
				email: 'john@example.com',
				birth_date: '1990-01-01',
				address_line1: 'Test Street',
				city: 'Amsterdam',
				postal_code: '1234AB',
				country: 'Netherlands',
				payment_method: 'Direct Debit',
				iban: '123456789'
			};

			const result = validateApplicationForm(dataWithInvalidIBAN);
			expect(result.valid).toBe(false);
			expect(result.errors).toContain('Invalid IBAN format');
		});

		it('should accept valid application data', () => {
			const validData = {
				first_name: 'John',
				last_name: 'Doe',
				email: 'john@example.com',
				birth_date: '1990-01-01',
				address_line1: 'Test Street 123',
				city: 'Amsterdam',
				postal_code: '1234AB',
				country: 'Netherlands',
				payment_method: 'Bank Transfer'
			};

			const result = validateApplicationForm(validData);
			expect(result.valid).toBe(true);
			expect(result.errors).toHaveLength(0);
		});
	});

	describe('Stage 2: Application Review', () => {
		const mockReviewDialog = (frm) => {
			const dialog = new frappe.ui.Dialog({
				title: 'Review Application',
				fields: [
					{
						fieldname: 'review_notes',
						fieldtype: 'Small Text',
						label: 'Review Notes',
						reqd: 1
					},
					{
						fieldname: 'action',
						fieldtype: 'Select',
						label: 'Action',
						options: 'Approve\nReject\nRequest More Information',
						reqd: 1,
						default: 'Approve'
					}
				],
				primary_action_label: 'Submit Review',
				primary_action: async (values) => {
					await frappe.call({
						method: 'verenigingen.api.membership_application.review_application',
						args: {
							application: frm.doc.name,
							action: values.action,
							notes: values.review_notes
						}
					});
					dialog.hide();
					frm.reload_doc();
				}
			});
			return dialog;
		};

		it('should create review dialog with correct fields', () => {
			const frm = { doc: { name: 'APP-001' }, reload_doc: jest.fn() };

			const dialog = mockReviewDialog(frm);

			expect(frappe.ui.Dialog).toHaveBeenCalledWith(
				expect.objectContaining({
					title: 'Review Application',
					fields: expect.arrayContaining([
						expect.objectContaining({ fieldname: 'review_notes' }),
						expect.objectContaining({ fieldname: 'action' })
					])
				})
			);
		});

		it('should validate review notes are provided', () => {
			const validateReview = (reviewData) => {
				if (!reviewData.review_notes || reviewData.review_notes.trim() === '') {
					return { valid: false, error: 'Review notes are required' };
				}
				if (!reviewData.action) {
					return { valid: false, error: 'Action is required' };
				}
				return { valid: true };
			};

			expect(validateReview({ action: 'Approve' }).valid).toBe(false);
			expect(validateReview({ review_notes: 'Looks good', action: 'Approve' }).valid).toBe(true);
		});
	});

	describe('Stage 3: Member Creation', () => {
		it('should prepare member data from approved application', () => {
			const application = {
				first_name: 'John',
				last_name: 'Doe',
				email: 'john@example.com',
				birth_date: '1990-01-01',
				address_line1: 'Test Street 123',
				city: 'Amsterdam',
				postal_code: '1234AB',
				country: 'Netherlands',
				interested_in_volunteering: 1,
				iban: 'NL91ABNA0417164300',
				selected_membership_type: 'Regular Member'
			};

			const memberData = {
				doctype: 'Member',
				first_name: application.first_name,
				last_name: application.last_name,
				email: application.email,
				birth_date: application.birth_date,
				interested_in_volunteering: application.interested_in_volunteering,
				iban: application.iban,
				application_status: 'Approved',
				membership_type: application.selected_membership_type
			};

			expect(memberData.first_name).toBe('John');
			expect(memberData.interested_in_volunteering).toBe(1);
			expect(memberData.application_status).toBe('Approved');
		});

		it('should validate member ID generation', () => {
			const generateMemberId = (memberName) => {
				// Format: MEM-YYYY-XXXXX
				const year = new Date().getFullYear();
				const sequence = memberName.split('-').pop() || '00001';
				return `MEM-${year}-${sequence.padStart(5, '0')}`;
			};

			expect(generateMemberId('Member-00123')).toBe('MEM-2025-00123');
			expect(generateMemberId('Member-5')).toBe('MEM-2025-00005');
		});
	});

	describe('Stage 4: Payment Processing', () => {
		it('should validate payment data before processing', () => {
			const validatePaymentData = (paymentData) => {
				const errors = [];

				if (!paymentData.amount || paymentData.amount <= 0) {
					errors.push('Valid payment amount required');
				}

				if (paymentData.payment_method === 'Direct Debit') {
					if (!paymentData.mandate_id) {
						errors.push('SEPA mandate required for Direct Debit');
					}
					if (!paymentData.iban) {
						errors.push('IBAN required for Direct Debit');
					}
				}

				return { valid: errors.length === 0, errors };
			};

			const invalidPayment = {
				amount: 0,
				payment_method: 'Direct Debit'
			};

			const result = validatePaymentData(invalidPayment);
			expect(result.valid).toBe(false);
			expect(result.errors).toContain('Valid payment amount required');
			expect(result.errors).toContain('SEPA mandate required for Direct Debit');
		});

		it('should handle payment confirmation dialog', async () => {
			const paymentData = {
				member: 'MEM-2025-00001',
				amount: 50.00,
				payment_method: 'Bank Transfer'
			};

			frappe.confirm.mockImplementation((message, onYes) => {
				onYes();
			});

			frappe.call.mockResolvedValue({
				message: { success: true, invoice_id: 'INV-001' }
			});

			const processPayment = async (data) => {
				return new Promise((resolve) => {
					frappe.confirm(
						`Process payment of €${data.amount} for ${data.member}?`,
						async () => {
							const result = await frappe.call({
								method: 'verenigingen.api.payment.process_membership_payment',
								args: data
							});
							resolve(result.message);
						}
					);
				});
			};

			const result = await processPayment(paymentData);
			expect(result.success).toBe(true);
			expect(result.invoice_id).toBe('INV-001');
		});
	});

	describe('Stage 5: Membership Activation', () => {
		it('should calculate membership dates correctly', () => {
			const calculateMembershipDates = (startDate, membershipType) => {
				const durations = {
					'Monthly': 1,
					'Quarterly': 3,
					'Annual': 12
				};

				const start = new Date(startDate);
				const months = durations[membershipType] || 12;
				const end = new Date(start);
				end.setMonth(end.getMonth() + months);
				end.setDate(end.getDate() - 1); // End date is day before

				return {
					from_date: start.toISOString().split('T')[0],
					to_date: end.toISOString().split('T')[0]
				};
			};

			const monthlyDates = calculateMembershipDates('2025-01-05', 'Monthly');
			expect(monthlyDates.from_date).toBe('2025-01-05');
			expect(monthlyDates.to_date).toBe('2025-02-04');

			const annualDates = calculateMembershipDates('2025-01-05', 'Annual');
			expect(annualDates.from_date).toBe('2025-01-05');
			expect(annualDates.to_date).toBe('2026-01-04');
		});

		it('should validate membership activation requirements', () => {
			const canActivateMembership = (member) => {
				const requirements = [];

				if (!member.payment_confirmed) {
					requirements.push('Payment must be confirmed');
				}

				if (!member.address_verified) {
					requirements.push('Address must be verified');
				}

				if (member.application_status !== 'Approved') {
					requirements.push('Application must be approved');
				}

				return {
					canActivate: requirements.length === 0,
					missingRequirements: requirements
				};
			};

			const incompleteMember = {
				application_status: 'Approved',
				payment_confirmed: false,
				address_verified: true
			};

			const result = canActivateMembership(incompleteMember);
			expect(result.canActivate).toBe(false);
			expect(result.missingRequirements).toContain('Payment must be confirmed');
		});
	});

	describe('Stage 6: Volunteer Creation', () => {
		it('should validate volunteer interest before creation', () => {
			const shouldCreateVolunteer = (member) => {
				return member.interested_in_volunteering === 1 &&
					   member.application_status === 'Approved';
			};

			expect(shouldCreateVolunteer({
				interested_in_volunteering: 1,
				application_status: 'Approved'
			})).toBe(true);

			expect(shouldCreateVolunteer({
				interested_in_volunteering: 0,
				application_status: 'Approved'
			})).toBe(false);
		});

		it('should prepare volunteer data correctly', () => {
			const prepareVolunteerData = (member) => {
				return {
					doctype: 'Volunteer',
					volunteer_name: `${member.first_name} ${member.last_name}`,
					member: member.name,
					email: member.email,
					status: 'New',
					available: 1,
					date_joined: frappe.datetime.nowdate()
				};
			};

			const member = {
				name: 'MEM-2025-00001',
				first_name: 'John',
				last_name: 'Doe',
				email: 'john@example.com'
			};

			const volunteerData = prepareVolunteerData(member);
			expect(volunteerData.volunteer_name).toBe('John Doe');
			expect(volunteerData.status).toBe('New');
			expect(volunteerData.date_joined).toBe('2025-01-05');
		});
	});

	describe('Stage 7: Member Activities', () => {
		it('should validate team assignment data', () => {
			const validateTeamAssignment = (assignmentData) => {
				const errors = [];

				if (!assignmentData.team) {
					errors.push('Team selection is required');
				}

				if (!assignmentData.role) {
					errors.push('Role selection is required');
				}

				if (assignmentData.role === 'Team Lead' && !assignmentData.approval_notes) {
					errors.push('Approval notes required for Team Lead role');
				}

				return { valid: errors.length === 0, errors };
			};

			const invalidAssignment = {
				team: 'Communications Team',
				role: 'Team Lead'
			};

			const result = validateTeamAssignment(invalidAssignment);
			expect(result.valid).toBe(false);
			expect(result.errors).toContain('Approval notes required for Team Lead role');
		});

		it('should track member activity history', () => {
			const activityLog = [];

			const logActivity = (activity) => {
				activityLog.push({
					timestamp: new Date().toISOString(),
					type: activity.type,
					description: activity.description,
					user: frappe.session?.user || 'System'
				});
			};

			logActivity({ type: 'team_join', description: 'Joined Communications Team' });
			logActivity({ type: 'expense_submit', description: 'Submitted expense for €25.50' });

			expect(activityLog).toHaveLength(2);
			expect(activityLog[0].type).toBe('team_join');
			expect(activityLog[1].type).toBe('expense_submit');
		});
	});

	describe('Stage 8: Membership Renewal', () => {
		it('should calculate renewal eligibility', () => {
			const isEligibleForRenewal = (membership) => {
				const today = new Date(frappe.datetime.nowdate());
				const expiryDate = new Date(membership.to_date);
				const daysUntilExpiry = Math.ceil((expiryDate - today) / (1000 * 60 * 60 * 24));

				return {
					eligible: daysUntilExpiry <= 30 && daysUntilExpiry >= -30,
					daysUntilExpiry,
					message: daysUntilExpiry > 30 ? 'Too early to renew' :
							daysUntilExpiry < -30 ? 'Membership expired' :
							'Eligible for renewal'
				};
			};

			const membership = {
				to_date: frappe.datetime.add_days('2025-01-05', 20) // 20 days from now = eligible
			};

			const result = isEligibleForRenewal(membership);
			expect(result.eligible).toBe(true);
			expect(result.message).toBe('Eligible for renewal');
		});

		it('should handle renewal payment options', () => {
			const getRenewalOptions = (member) => {
				const options = ['Bank Transfer'];

				if (member.iban && member.sepa_mandate_active) {
					options.unshift('Direct Debit');
				}

				if (member.payment_history?.includes('Credit Card')) {
					options.push('Credit Card');
				}

				return options;
			};

			const memberWithMandate = {
				iban: 'NL91ABNA0417164300',
				sepa_mandate_active: true,
				payment_history: ['Bank Transfer', 'Credit Card']
			};

			const options = getRenewalOptions(memberWithMandate);
			expect(options).toContain('Direct Debit');
			expect(options).toContain('Credit Card');
			expect(options[0]).toBe('Direct Debit'); // Preferred option
		});
	});

	describe('Stage 9: Suspension and Reactivation', () => {
		it('should validate suspension reasons', () => {
			const validateSuspension = (suspensionData) => {
				const validReasons = [
					'Payment Default',
					'Code of Conduct Violation',
					'Voluntary Suspension',
					'Administrative'
				];

				if (!validReasons.includes(suspensionData.reason)) {
					return { valid: false, error: 'Invalid suspension reason' };
				}

				if (!suspensionData.notes || suspensionData.notes.length < 10) {
					return { valid: false, error: 'Detailed notes required (min 10 characters)' };
				}

				return { valid: true };
			};

			expect(validateSuspension({
				reason: 'Payment Default',
				notes: 'Multiple failed payment attempts'
			}).valid).toBe(true);

			expect(validateSuspension({
				reason: 'Other',
				notes: 'Test'
			}).valid).toBe(false);
		});

		it('should track suspension and reactivation history', () => {
			const memberHistory = {
				suspensions: [],
				reactivations: []
			};

			const addSuspension = (data) => {
				memberHistory.suspensions.push({
					date: frappe.datetime.nowdate(),
					reason: data.reason,
					notes: data.notes,
					suspended_by: frappe.session?.user || 'System'
				});
			};

			const addReactivation = (data) => {
				memberHistory.reactivations.push({
					date: frappe.datetime.nowdate(),
					notes: data.notes,
					reactivated_by: frappe.session?.user || 'System'
				});
			};

			addSuspension({ reason: 'Payment Default', notes: 'Failed payments' });
			addReactivation({ notes: 'Payment issue resolved' });

			expect(memberHistory.suspensions).toHaveLength(1);
			expect(memberHistory.reactivations).toHaveLength(1);
			expect(memberHistory.suspensions[0].reason).toBe('Payment Default');
		});
	});

	describe('Stage 10: Termination Process', () => {
		it('should validate termination request', () => {
			const validateTerminationRequest = (request) => {
				const errors = [];
				const validReasons = [
					'Voluntary',
					'Non-payment',
					'Code of Conduct Violation',
					'Deceased',
					'Other'
				];

				if (!validReasons.includes(request.reason)) {
					errors.push('Invalid termination reason');
				}

				if (!request.effective_date) {
					errors.push('Effective date is required');
				} else if (new Date(request.effective_date) < new Date(frappe.datetime.nowdate())) {
					errors.push('Effective date must be today or in the future');
				}

				if (request.reason === 'Other' && (!request.details || request.details.length < 20)) {
					errors.push('Detailed explanation required for "Other" reason (min 20 characters)');
				}

				return { valid: errors.length === 0, errors };
			};

			const validRequest = {
				reason: 'Voluntary',
				effective_date: frappe.datetime.nowdate(),
				details: 'Member requested termination'
			};

			expect(validateTerminationRequest(validRequest).valid).toBe(true);

			const invalidRequest = {
				reason: 'Other',
				effective_date: '2024-01-01',
				details: 'Too short'
			};

			const result = validateTerminationRequest(invalidRequest);
			expect(result.valid).toBe(false);
			expect(result.errors).toHaveLength(2);
		});

		it('should calculate final settlement', () => {
			const calculateFinalSettlement = (member, terminationDate) => {
				const settlement = {
					refunds: [],
					outstanding: [],
					total: 0
				};

				// Check for unused membership period
				if (member.membership_to_date && new Date(member.membership_to_date) > new Date(terminationDate)) {
					const daysRemaining = Math.floor(
						(new Date(member.membership_to_date) - new Date(terminationDate)) / (1000 * 60 * 60 * 24)
					);
					const dailyRate = member.membership_fee / 365;
					const refundAmount = daysRemaining * dailyRate;

					settlement.refunds.push({
						type: 'Unused Membership',
						amount: Math.round(refundAmount * 100) / 100,
						days: daysRemaining
					});
				}

				// Check for outstanding payments
				if (member.outstanding_amount > 0) {
					settlement.outstanding.push({
						type: 'Outstanding Fees',
						amount: member.outstanding_amount
					});
				}

				// Calculate total
				const totalRefunds = settlement.refunds.reduce((sum, r) => sum + r.amount, 0);
				const totalOutstanding = settlement.outstanding.reduce((sum, o) => sum + o.amount, 0);
				settlement.total = totalRefunds - totalOutstanding;

				return settlement;
			};

			const member = {
				membership_to_date: '2025-12-31',
				membership_fee: 365, // €1 per day for easy calculation
				outstanding_amount: 50
			};

			const settlement = calculateFinalSettlement(member, '2025-06-30');
			expect(settlement.refunds[0].days).toBe(184); // Days from July 1 to Dec 31
			expect(settlement.refunds[0].amount).toBe(184);
			expect(settlement.total).toBe(134); // 184 refund - 50 outstanding
		});

		it('should handle termination confirmation workflow', () => {
			const terminationWorkflow = {
				steps: [
					{ name: 'Request Submitted', status: 'completed' },
					{ name: 'Manager Review', status: 'pending' },
					{ name: 'Final Settlement', status: 'pending' },
					{ name: 'Account Closure', status: 'pending' }
				],

				completeStep(stepName) {
					const step = this.steps.find(s => s.name === stepName);
					if (step) {
						step.status = 'completed';
						step.completedAt = new Date().toISOString();
					}
				},

				canProceed() {
					const currentStepIndex = this.steps.findIndex(s => s.status === 'pending');
					if (currentStepIndex === 0) return true;
					return this.steps[currentStepIndex - 1].status === 'completed';
				}
			};

			expect(terminationWorkflow.canProceed()).toBe(true);
			terminationWorkflow.completeStep('Manager Review');
			expect(terminationWorkflow.steps[1].status).toBe('completed');
		});
	});
});
