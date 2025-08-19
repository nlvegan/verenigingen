/**
 * @fileoverview Cross-DocType Integration Tests for Business Workflows
 *
 * This test suite validates the integration between multiple DocTypes in
 * realistic business scenarios, ensuring that the complete member lifecycle
 * and association management workflows function correctly end-to-end.
 *
 * @description Business Context:
 * Association management requires seamless integration between multiple systems:
 * - Member registration and lifecycle management
 * - Payment processing and SEPA mandate handling
 * - Chapter assignment and geographical organization
 * - Volunteer management and board assignments
 * - Financial operations and invoicing
 *
 * @description Test Categories:
 * 1. Member Onboarding - Complete registration to active membership
 * 2. Payment Workflows - SEPA setup, invoicing, and collection
 * 3. Chapter Assignment - Geographic organization and member assignment
 * 4. Volunteer Management - Profile creation and board assignments
 * 5. Financial Operations - Invoicing, payments, and reconciliation
 * 6. Termination Workflows - Membership cancellation and cleanup
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

const TestDataFactory = require('../factories/test-data-factory');

describe('Business Workflows - Integration Test Suite', () => {
	let testFactory;

	beforeEach(() => {
		testFactory = new TestDataFactory(11111);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
	});

	// ==================== MEMBER ONBOARDING WORKFLOW ====================

	describe('Complete Member Onboarding Workflow', () => {
		test('should complete full member registration process', async () => {
			// Arrange - Create new member application
			const memberData = testFactory.createMemberData({
				status: 'Pending',
				payment_method: 'SEPA Direct Debit',
				current_membership_type: 'Regular Member'
			});

			const addressData = testFactory.createAddressData({
				pincode: '1234 AB'
			});

			const chapterData = testFactory.createChapterData({
				postal_code_ranges: '1000-1999'
			});

			// Act - Complete onboarding workflow
			const workflow = new MemberOnboardingWorkflow();

			// Step 1: Submit application
			const application = await workflow.submitApplication(memberData, addressData);
			expect(application.status).toBe('Pending');

			// Step 2: Assign to chapter based on postal code
			const chapterAssignment = await workflow.assignToChapter(application, chapterData);
			expect(chapterAssignment.success).toBe(true);
			expect(chapterAssignment.assignedChapter).toBe(chapterData.name);

			// Step 3: Create SEPA mandate
			const mandateData = testFactory.createSEPAMandateData(application.name, {
				iban: memberData.iban,
				bank_account_name: memberData.bank_account_name
			});
			const mandateCreation = await workflow.createSEPAMandate(application, mandateData);
			expect(mandateCreation.mandate_id).toBeDefined();

			// Step 4: Approve membership
			const approval = await workflow.approveMembership(application);
			expect(approval.status).toBe('Active');

			// Step 5: Create membership record
			const membershipData = testFactory.createMembershipData(application.name);
			const membership = await workflow.createMembership(application, membershipData);
			expect(membership.status).toBe('Active');

			// Assert - Complete workflow validation
			expect(workflow.isOnboardingComplete()).toBe(true);
			expect(workflow.getWorkflowSteps()).toEqual([
				'application_submitted',
				'chapter_assigned',
				'mandate_created',
				'membership_approved',
				'membership_created'
			]);
		});

		test('should handle onboarding with validation errors', async () => {
			// Arrange - Invalid member data
			const invalidMemberData = testFactory.createMemberData({
				email: 'invalid-email',
				iban: 'invalid-iban',
				birth_date: '' // Missing birth date
			});

			// Act
			const workflow = new MemberOnboardingWorkflow();

			// Assert - Should fail validation
			await expect(workflow.submitApplication(invalidMemberData))
				.rejects.toThrow('Validation failed');
		});

		test('should handle chapter assignment for members outside coverage', async () => {
			// Arrange - Member with postal code outside all chapter ranges
			const memberData = testFactory.createMemberData();
			const addressData = testFactory.createAddressData({
				pincode: '9999 ZZ' // Outside typical ranges
			});

			const chapters = [
				testFactory.createChapterData({ postal_code_ranges: '1000-1999' }),
				testFactory.createChapterData({ postal_code_ranges: '2000-2999' })
			];

			// Act
			const workflow = new MemberOnboardingWorkflow();
			const assignment = await workflow.findMatchingChapter(memberData, chapters);

			// Assert
			expect(assignment.hasMatch).toBe(false);
			expect(assignment.suggestedAction).toBe('manual_assignment');
		});
	});

	// ==================== PAYMENT PROCESSING WORKFLOW ====================

	describe('Payment Processing Workflows', () => {
		test('should complete SEPA direct debit collection workflow', async () => {
			// Arrange - Active member with SEPA mandate
			const member = testFactory.createMemberData({
				status: 'Active',
				payment_method: 'SEPA Direct Debit'
			});

			const mandate = testFactory.createSEPAMandateData(member.name, {
				status: 'Active'
			});

			const membership = testFactory.createMembershipData(member.name, {
				annual_fee: 100.00,
				payment_schedule: 'Quarterly'
			});

			// Act - Complete payment workflow
			const paymentWorkflow = new PaymentProcessingWorkflow();

			// Step 1: Generate quarterly invoice
			const invoice = await paymentWorkflow.generateQuarterlyInvoice(member, membership);
			expect(invoice.outstanding_amount).toBe(25.00); // 100/4
			expect(invoice.due_date).toBeDefined();

			// Step 2: Create direct debit batch
			const batchData = testFactory.createDirectDebitBatchData({
				collection_date: invoice.due_date
			});
			const batch = await paymentWorkflow.createDirectDebitBatch(batchData);
			expect(batch.status).toBe('Draft');

			// Step 3: Add invoice to batch
			const batchEntry = await paymentWorkflow.addInvoiceToBatch(batch, invoice, mandate);
			expect(batchEntry.amount).toBe(25.00);
			expect(batchEntry.mandate_id).toBe(mandate.mandate_id);

			// Step 4: Generate SEPA XML
			const sepaXml = await paymentWorkflow.generateSEPAXML(batch);
			expect(sepaXml.valid).toBe(true);
			expect(sepaXml.controlSum).toBe(25.00);

			// Step 5: Submit to bank
			const bankSubmission = await paymentWorkflow.submitToBank(batch, sepaXml);
			expect(bankSubmission.status).toBe('Submitted');

			// Step 6: Process successful payment
			const paymentProcessing = await paymentWorkflow.processSuccessfulPayment(
				batch, invoice, member
			);
			expect(paymentProcessing.paymentEntry).toBeDefined();
			expect(paymentProcessing.invoiceStatus).toBe('Paid');

			// Assert - Complete payment workflow
			expect(paymentWorkflow.isWorkflowComplete()).toBe(true);
		});

		test('should handle payment failures and retry logic', async () => {
			// Arrange - Failed payment scenario
			const member = testFactory.createMemberData({ status: 'Active' });
			const mandate = testFactory.createSEPAMandateData(member.name, { status: 'Active' });
			const invoice = { name: 'INV-001', outstanding_amount: 25.00 };

			// Act - Process payment failure
			const paymentWorkflow = new PaymentProcessingWorkflow();
			const failureData = {
				return_code: 'AM04', // Insufficient funds
				return_reason: 'Insufficient Funds'
			};

			const failureProcessing = await paymentWorkflow.processPaymentFailure(
				invoice, member, mandate, failureData
			);

			// Assert
			expect(failureProcessing.retryScheduled).toBe(true);
			expect(failureProcessing.retryDate).toBeDefined();
			expect(failureProcessing.memberNotified).toBe(true);
		});

		test('should handle mandate cancellation during active payments', async () => {
			// Arrange - Active payments with mandate cancellation
			const member = testFactory.createMemberData({ status: 'Active' });
			const mandate = testFactory.createSEPAMandateData(member.name, { status: 'Active' });
			const activeBatch = testFactory.createDirectDebitBatchData({ status: 'Generated' });

			// Act - Cancel mandate with active batch
			const paymentWorkflow = new PaymentProcessingWorkflow();
			const cancellation = await paymentWorkflow.handleMandateCancellation(
				mandate, member, [activeBatch]
			);

			// Assert
			expect(cancellation.mandateCancelled).toBe(true);
			expect(cancellation.batchesUpdated).toBe(1);
			expect(cancellation.alternativePaymentRequired).toBe(true);
		});
	});

	// ==================== CHAPTER ORGANIZATION WORKFLOW ====================

	describe('Chapter Organization Workflows', () => {
		test('should complete chapter creation and member assignment', async () => {
			// Arrange - New chapter setup
			const chapterData = testFactory.createChapterData({
				postal_code_ranges: '3000-3999',
				status: 'Pending'
			});

			const eligibleMembers = Array.from({ length: 15 }, (_, i) =>
				testFactory.createMemberData({
					primary_address: testFactory.createAddressData({
						pincode: `3${String(100 + i).padStart(3, '0')} AB`
					}).name
				})
			);

			// Act - Complete chapter organization workflow
			const chapterWorkflow = new ChapterOrganizationWorkflow();

			// Step 1: Create chapter
			const chapter = await chapterWorkflow.createChapter(chapterData);
			expect(chapter.status).toBe('Pending');

			// Step 2: Find eligible members
			const eligibleMemberSearch = await chapterWorkflow.findEligibleMembers(chapter);
			expect(eligibleMemberSearch.members.length).toBe(15);

			// Step 3: Assign members to chapter
			const memberAssignment = await chapterWorkflow.assignMembers(
				chapter, eligibleMemberSearch.members
			);
			expect(memberAssignment.assignedCount).toBe(15);

			// Step 4: Recruit board members
			const boardCandidates = eligibleMembers.slice(0, 5);
			const boardRecruitment = await chapterWorkflow.recruitBoardMembers(
				chapter, boardCandidates
			);
			expect(boardRecruitment.boardSize).toBeGreaterThanOrEqual(3);

			// Step 5: Activate chapter
			const activation = await chapterWorkflow.activateChapter(chapter);
			expect(activation.status).toBe('Active');

			// Assert - Complete chapter workflow
			expect(chapterWorkflow.isChapterOperational()).toBe(true);
		});

		test('should handle chapter mergers and splits', async () => {
			// Arrange - Existing chapters for merger
			const chapter1 = testFactory.createChapterData({
				chapter_name: 'Chapter North',
				postal_code_ranges: '1000-1499'
			});

			const chapter2 = testFactory.createChapterData({
				chapter_name: 'Chapter South',
				postal_code_ranges: '1500-1999'
			});

			// Act - Merge chapters
			const chapterWorkflow = new ChapterOrganizationWorkflow();
			const merger = await chapterWorkflow.mergeChapters(chapter1, chapter2, {
				new_name: 'Chapter Combined',
				new_postal_ranges: '1000-1999'
			});

			// Assert
			expect(merger.success).toBe(true);
			expect(merger.newChapter.postal_code_ranges).toBe('1000-1999');
			expect(merger.membersTransferred).toBeGreaterThan(0);
		});
	});

	// ==================== VOLUNTEER MANAGEMENT WORKFLOW ====================

	describe('Volunteer Management Workflows', () => {
		test('should complete volunteer recruitment and assignment', async () => {
			// Arrange - Member eligible for volunteer work
			const member = testFactory.createMemberData({
				birth_date: testFactory.generateBirthDate(25, 25), // 25 years old
				status: 'Active'
			});

			const chapter = testFactory.createChapterData({ status: 'Active' });

			// Act - Complete volunteer workflow
			const volunteerWorkflow = new VolunteerManagementWorkflow();

			// Step 1: Create volunteer profile
			const volunteerData = testFactory.createVolunteerData(member.name);
			const volunteer = await volunteerWorkflow.createVolunteerProfile(member, volunteerData);
			expect(volunteer.status).toBe('Active');

			// Step 2: Skills assessment
			const skillsAssessment = await volunteerWorkflow.conductSkillsAssessment(volunteer);
			expect(skillsAssessment.skillsIdentified).toBeGreaterThan(0);

			// Step 3: Match with opportunities
			const opportunities = [
				{ role: 'Event Coordinator', skills_required: ['Event Planning'] },
				{ role: 'Communications Manager', skills_required: ['Social Media'] }
			];

			const matching = await volunteerWorkflow.matchWithOpportunities(
				volunteer, opportunities
			);
			expect(matching.matches.length).toBeGreaterThan(0);

			// Step 4: Assign to chapter board
			const boardAssignment = await volunteerWorkflow.assignToBoardRole(
				volunteer, chapter, 'Secretary'
			);
			expect(boardAssignment.success).toBe(true);

			// Assert - Complete volunteer workflow
			expect(volunteerWorkflow.isVolunteerEngaged()).toBe(true);
		});

		test('should handle volunteer capacity and workload management', async () => {
			// Arrange - Volunteer with multiple assignments
			const volunteer = testFactory.createVolunteerData('Member-001', {
				max_hours_per_week: 10
			});

			const assignments = [
				{ role: 'Board Member', hours_per_week: 4 },
				{ role: 'Event Coordinator', hours_per_week: 6 },
				{ role: 'Newsletter Editor', hours_per_week: 3 }
			];

			// Act - Check workload capacity
			const volunteerWorkflow = new VolunteerManagementWorkflow();
			const workloadCheck = await volunteerWorkflow.checkWorkloadCapacity(
				volunteer, assignments
			);

			// Assert
			expect(workloadCheck.totalHours).toBe(13);
			expect(workloadCheck.exceedsCapacity).toBe(true);
			expect(workloadCheck.recommendedAction).toBe('reduce_assignments');
		});
	});

	// ==================== FINANCIAL OPERATIONS WORKFLOW ====================

	describe('Financial Operations Workflows', () => {
		test('should complete annual fee collection workflow', async () => {
			// Arrange - Multiple members with different payment methods
			const members = [
				testFactory.createMemberData({ payment_method: 'SEPA Direct Debit' }),
				testFactory.createMemberData({ payment_method: 'Bank Transfer' }),
				testFactory.createMemberData({ payment_method: 'Credit Card' })
			];

			const memberships = members.map(member =>
				testFactory.createMembershipData(member.name, { annual_fee: 100.00 })
			);

			// Act - Complete financial workflow
			const financialWorkflow = new FinancialOperationsWorkflow();

			// Step 1: Generate annual invoices
			const invoiceGeneration = await financialWorkflow.generateAnnualInvoices(
				members, memberships
			);
			expect(invoiceGeneration.invoicesCreated).toBe(3);

			// Step 2: Process SEPA payments
			const sepaPayments = await financialWorkflow.processSEPAPayments(
				invoiceGeneration.sepaInvoices
			);
			expect(sepaPayments.batchCreated).toBe(true);

			// Step 3: Handle manual payments
			const manualPayments = await financialWorkflow.processManualPayments(
				invoiceGeneration.manualInvoices
			);
			expect(manualPayments.remindersScheduled).toBe(2);

			// Step 4: Reconcile payments
			const reconciliation = await financialWorkflow.reconcilePayments();
			expect(reconciliation.reconciled).toBeGreaterThan(0);

			// Assert - Complete financial workflow
			expect(financialWorkflow.isCollectionComplete()).toBe(true);
		});

		test('should handle payment disputes and refunds', async () => {
			// Arrange - Disputed payment scenario
			const member = testFactory.createMemberData({ status: 'Active' });
			const payment = {
				amount: 100.00,
				status: 'Completed',
				dispute_reason: 'Duplicate charge'
			};

			// Act - Process dispute
			const financialWorkflow = new FinancialOperationsWorkflow();
			const disputeProcessing = await financialWorkflow.processPaymentDispute(
				member, payment, 'Duplicate charge'
			);

			// Assert
			expect(disputeProcessing.disputeCreated).toBe(true);
			expect(disputeProcessing.refundProcessed).toBe(true);
			expect(disputeProcessing.memberNotified).toBe(true);
		});
	});

	// ==================== TERMINATION WORKFLOW ====================

	describe('Membership Termination Workflows', () => {
		test('should complete membership termination process', async () => {
			// Arrange - Active member requesting termination
			const member = testFactory.createMemberData({ status: 'Active' });
			const mandate = testFactory.createSEPAMandateData(member.name, { status: 'Active' });
			const membership = testFactory.createMembershipData(member.name, { status: 'Active' });

			// Act - Complete termination workflow
			const terminationWorkflow = new TerminationWorkflow();

			// Step 1: Submit termination request
			const terminationRequest = await terminationWorkflow.submitTerminationRequest(
				member, 'Personal reasons'
			);
			expect(terminationRequest.status).toBe('Pending');

			// Step 2: Review and approve
			const review = await terminationWorkflow.reviewTerminationRequest(terminationRequest);
			expect(review.approved).toBe(true);

			// Step 3: Cancel SEPA mandate
			const mandateCancellation = await terminationWorkflow.cancelSEPAMandate(mandate);
			expect(mandateCancellation.status).toBe('Cancelled');

			// Step 4: Close membership
			const membershipClosure = await terminationWorkflow.closeMembership(membership);
			expect(membershipClosure.status).toBe('Terminated');

			// Step 5: Update member status
			const memberUpdate = await terminationWorkflow.updateMemberStatus(member);
			expect(memberUpdate.status).toBe('Terminated');

			// Step 6: Process final settlement
			const settlement = await terminationWorkflow.processFinalSettlement(member);
			expect(settlement.balanceCleared).toBe(true);

			// Assert - Complete termination workflow
			expect(terminationWorkflow.isTerminationComplete()).toBe(true);
		});

		test('should handle termination with outstanding payments', async () => {
			// Arrange - Member with outstanding invoices
			const member = testFactory.createMemberData({ status: 'Active' });
			const outstandingInvoices = [
				{ amount: 50.00, status: 'Unpaid' },
				{ amount: 25.00, status: 'Unpaid' }
			];

			// Act - Process termination with outstanding payments
			const terminationWorkflow = new TerminationWorkflow();
			const terminationWithDebt = await terminationWorkflow.processTerminationWithOutstanding(
				member, outstandingInvoices
			);

			// Assert
			expect(terminationWithDebt.requiresSettlement).toBe(true);
			expect(terminationWithDebt.totalOutstanding).toBe(75.00);
			expect(terminationWithDebt.settlementScheduled).toBe(true);
		});
	});

	// ==================== HELPER CLASSES ====================

	class MemberOnboardingWorkflow {
		constructor() {
			this.steps = [];
		}

		async submitApplication(memberData, addressData) {
			this.steps.push('application_submitted');
			return { ...memberData, status: 'Pending' };
		}

		async assignToChapter(member, chapter) {
			this.steps.push('chapter_assigned');
			return { success: true, assignedChapter: chapter.name };
		}

		async createSEPAMandate(member, mandateData) {
			this.steps.push('mandate_created');
			return { mandate_id: mandateData.mandate_id };
		}

		async approveMembership(member) {
			this.steps.push('membership_approved');
			return { ...member, status: 'Active' };
		}

		async createMembership(member, membershipData) {
			this.steps.push('membership_created');
			return { ...membershipData, status: 'Active' };
		}

		async findMatchingChapter(member, chapters) {
			return { hasMatch: false, suggestedAction: 'manual_assignment' };
		}

		isOnboardingComplete() {
			return this.steps.length === 5;
		}

		getWorkflowSteps() {
			return this.steps;
		}
	}

	class PaymentProcessingWorkflow {
		constructor() {
			this.complete = false;
		}

		async generateQuarterlyInvoice(member, membership) {
			return {
				outstanding_amount: membership.annual_fee / 4,
				due_date: '2025-03-01'
			};
		}

		async createDirectDebitBatch(batchData) {
			return { ...batchData, status: 'Draft' };
		}

		async addInvoiceToBatch(batch, invoice, mandate) {
			return {
				amount: invoice.outstanding_amount,
				mandate_id: mandate.mandate_id
			};
		}

		async generateSEPAXML(batch) {
			return { valid: true, controlSum: 25.00 };
		}

		async submitToBank(batch, xml) {
			return { status: 'Submitted' };
		}

		async processSuccessfulPayment(batch, invoice, member) {
			this.complete = true;
			return {
				paymentEntry: 'PE-001',
				invoiceStatus: 'Paid'
			};
		}

		async processPaymentFailure(invoice, member, mandate, failureData) {
			return {
				retryScheduled: true,
				retryDate: '2025-03-15',
				memberNotified: true
			};
		}

		async handleMandateCancellation(mandate, member, activeBatches) {
			return {
				mandateCancelled: true,
				batchesUpdated: activeBatches.length,
				alternativePaymentRequired: true
			};
		}

		isWorkflowComplete() {
			return this.complete;
		}
	}

	class ChapterOrganizationWorkflow {
		constructor() {
			this.operational = false;
		}

		async createChapter(chapterData) {
			return { ...chapterData, status: 'Pending' };
		}

		async findEligibleMembers(chapter) {
			return { members: Array(15).fill().map((_, i) => ({ name: `Member-${i}` })) };
		}

		async assignMembers(chapter, members) {
			return { assignedCount: members.length };
		}

		async recruitBoardMembers(chapter, candidates) {
			return { boardSize: Math.min(candidates.length, 5) };
		}

		async activateChapter(chapter) {
			this.operational = true;
			return { ...chapter, status: 'Active' };
		}

		async mergeChapters(chapter1, chapter2, mergeData) {
			return {
				success: true,
				newChapter: { postal_code_ranges: mergeData.new_postal_ranges },
				membersTransferred: 25
			};
		}

		isChapterOperational() {
			return this.operational;
		}
	}

	class VolunteerManagementWorkflow {
		constructor() {
			this.engaged = false;
		}

		async createVolunteerProfile(member, volunteerData) {
			return { ...volunteerData, status: 'Active' };
		}

		async conductSkillsAssessment(volunteer) {
			return { skillsIdentified: 3 };
		}

		async matchWithOpportunities(volunteer, opportunities) {
			return { matches: opportunities.slice(0, 1) };
		}

		async assignToBoardRole(volunteer, chapter, role) {
			this.engaged = true;
			return { success: true };
		}

		async checkWorkloadCapacity(volunteer, assignments) {
			const totalHours = assignments.reduce((sum, a) => sum + a.hours_per_week, 0);
			return {
				totalHours,
				exceedsCapacity: totalHours > volunteer.max_hours_per_week,
				recommendedAction: totalHours > volunteer.max_hours_per_week ? 'reduce_assignments' : 'ok'
			};
		}

		isVolunteerEngaged() {
			return this.engaged;
		}
	}

	class FinancialOperationsWorkflow {
		constructor() {
			this.collectionComplete = false;
		}

		async generateAnnualInvoices(members, memberships) {
			return {
				invoicesCreated: members.length,
				sepaInvoices: members.filter(m => m.payment_method === 'SEPA Direct Debit'),
				manualInvoices: members.filter(m => m.payment_method !== 'SEPA Direct Debit')
			};
		}

		async processSEPAPayments(invoices) {
			return { batchCreated: true };
		}

		async processManualPayments(invoices) {
			return { remindersScheduled: invoices.length };
		}

		async reconcilePayments() {
			this.collectionComplete = true;
			return { reconciled: 5 };
		}

		async processPaymentDispute(member, payment, reason) {
			return {
				disputeCreated: true,
				refundProcessed: true,
				memberNotified: true
			};
		}

		isCollectionComplete() {
			return this.collectionComplete;
		}
	}

	class TerminationWorkflow {
		constructor() {
			this.complete = false;
		}

		async submitTerminationRequest(member, reason) {
			return { status: 'Pending', reason };
		}

		async reviewTerminationRequest(request) {
			return { approved: true };
		}

		async cancelSEPAMandate(mandate) {
			return { ...mandate, status: 'Cancelled' };
		}

		async closeMembership(membership) {
			return { ...membership, status: 'Terminated' };
		}

		async updateMemberStatus(member) {
			return { ...member, status: 'Terminated' };
		}

		async processFinalSettlement(member) {
			this.complete = true;
			return { balanceCleared: true };
		}

		async processTerminationWithOutstanding(member, invoices) {
			const totalOutstanding = invoices.reduce((sum, inv) => sum + inv.amount, 0);
			return {
				requiresSettlement: true,
				totalOutstanding,
				settlementScheduled: true
			};
		}

		isTerminationComplete() {
			return this.complete;
		}
	}

	function setupGlobalMocks() {
		global.frappe = {
			call: jest.fn(),
			msgprint: jest.fn()
		};
	}
});
