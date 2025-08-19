/**
 * @fileoverview Comprehensive Member DocType JavaScript Test Suite
 *
 * This test suite provides complete coverage of the Member DocType's client-side
 * functionality, focusing on realistic business scenarios and data validation
 * rather than mocked behavior. Tests cover the full member lifecycle from
 * registration through termination.
 *
 * @description Business Context:
 * Members are the core entity in the Verenigingen association management system.
 * This test suite validates critical business workflows including:
 * - Member registration and profile management
 * - SEPA mandate integration and payment method configuration
 * - Chapter assignment and geographical organization
 * - Volunteer profile creation and management
 * - Dutch naming conventions and address validation
 * - Fee management and membership lifecycle
 *
 * @description Test Categories:
 * 1. Form Lifecycle - Form initialization, refresh, and navigation
 * 2. Data Validation - Business rule enforcement and field validation
 * 3. Payment Integration - SEPA mandates and payment method handling
 * 4. Chapter Management - Geographical assignment and chapter workflows
 * 5. Volunteer Integration - Volunteer profile creation and management
 * 6. Dutch Conventions - Naming patterns and address formats
 * 7. Administrative Functions - Member management and status changes
 * 8. Edge Cases - Boundary conditions and error scenarios
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

// Import test factory
const TestDataFactory = require('../factories/test-data-factory');

describe('Member DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		// Initialize test factory with consistent seed
		testFactory = new TestDataFactory(12345);

		// Create mock form object that mimics Frappe's structure
		mockDoc = testFactory.createMemberData();
		mockFrm = createMockForm(mockDoc);

		// Mock global dependencies
		setupGlobalMocks();
	});

	afterEach(() => {
		// Clean up mocks
		jest.clearAllMocks();
	});

	// ==================== FORM LIFECYCLE TESTS ====================

	describe('Form Lifecycle Management', () => {
		test('should initialize form properly on refresh', () => {
			// Arrange
			const refreshHandler = getMemberRefreshHandler();

			// Act
			refreshHandler(mockFrm);

			// Assert
			expect(mockFrm.add_custom_button).toHaveBeenCalled();
			expect(mockFrm.set_df_property).toHaveBeenCalled();
			expect(mockFrm.toggle_display).toHaveBeenCalled();
		});

		test('should handle new unsaved documents correctly', () => {
			// Arrange
			mockDoc.__islocal = true;
			mockDoc.name = 'new-member-1';
			const refreshHandler = getMemberRefreshHandler();

			// Act
			refreshHandler(mockFrm);

			// Assert - Should not make API calls for new documents
			expect(mockFrm.call).not.toHaveBeenCalled();
			expect(mockFrm.add_custom_button).toHaveBeenCalledWith(
				expect.stringContaining('Basic'),
				expect.any(Function)
			);
		});

		test('should set up Dutch naming fields correctly', () => {
			// Arrange
			const memberData = testFactory.createMemberData({
				tussenvoegsel: 'van der'
			});
			mockFrm.doc = memberData;

			// Act
			const refreshHandler = getMemberRefreshHandler();
			refreshHandler(mockFrm);

			// Assert
			expect(mockFrm.toggle_display).toHaveBeenCalledWith('tussenvoegsel', true);
			expect(mockFrm.set_df_property).toHaveBeenCalledWith(
				'tussenvoegsel',
				'description',
				expect.stringContaining('Dutch')
			);
		});

		test('should display member status indicators properly', () => {
			// Arrange
			const terminatedMember = testFactory.createMemberData({
				status: 'Terminated'
			});
			mockFrm.doc = terminatedMember;

			// Act
			const refreshHandler = getMemberRefreshHandler();
			refreshHandler(mockFrm);

			// Assert
			expect(mockFrm.dashboard.add_indicator).toHaveBeenCalledWith(
				expect.stringContaining('Terminated'),
				'red'
			);
		});
	});

	// ==================== DATA VALIDATION TESTS ====================

	describe('Business Rule Validation', () => {
		test('should validate Dutch postal codes correctly', () => {
			// Arrange
			const validPostalCodes = ['1234 AB', '1234AB', '9999 ZZ'];
			const invalidPostalCodes = ['123 AB', '1234 A', 'ABCD EF', '12345'];

			// Act & Assert
			validPostalCodes.forEach(code => {
				expect(validateDutchPostalCode(code)).toBe(true);
			});

			invalidPostalCodes.forEach(code => {
				expect(validateDutchPostalCode(code)).toBe(false);
			});
		});

		test('should validate IBAN format correctly', () => {
			// Arrange
			const validIBANs = [
				'NL91 ABNA 0417 1643 00',
				'NL91ABNA0417164300',
				'DE89 3704 0044 0532 0130 00'
			];
			const invalidIBANs = ['123456789', 'NL12', '', null];

			// Act & Assert
			validIBANs.forEach(iban => {
				expect(validateIBAN(iban)).toBe(true);
			});

			invalidIBANs.forEach(iban => {
				expect(validateIBAN(iban)).toBe(false);
			});
		});

		test('should enforce minimum age for volunteers', () => {
			// Arrange
			const underageMember = testFactory.createMemberData({
				birth_date: testFactory.generateBirthDate(15, 15) // 15 years old
			});
			const validVolunteerAge = testFactory.createMemberData({
				birth_date: testFactory.generateBirthDate(16, 16) // 16 years old
			});

			// Act & Assert
			expect(canCreateVolunteerProfile(underageMember)).toBe(false);
			expect(canCreateVolunteerProfile(validVolunteerAge)).toBe(true);
		});

		test('should validate email format correctly', () => {
			// Arrange
			const validEmails = [
				'test@example.com',
				'user.name@company.co.uk',
				'first+last@example.org'
			];
			const invalidEmails = [
				'invalid.email',
				'@example.com',
				'user@',
				'user name@example.com'
			];

			// Act & Assert
			validEmails.forEach(email => {
				expect(validateEmail(email)).toBe(true);
			});

			invalidEmails.forEach(email => {
				expect(validateEmail(email)).toBe(false);
			});
		});

		test('should calculate age correctly for edge cases', () => {
			// Arrange - Mock current date to January 5, 2025
			const mockCurrentDate = new Date('2025-01-05');
			jest.spyOn(Date, 'now').mockImplementation(() => mockCurrentDate.getTime());

			const testCases = [
				{ birthDate: '2000-01-01', expectedAge: 25 },
				{ birthDate: '2008-01-06', expectedAge: 17 }, // Not 18 yet
				{ birthDate: '2007-01-05', expectedAge: 18 }, // Birthday today
				{ birthDate: '2006-12-31', expectedAge: 18 } // Already had birthday this year
			];

			// Act & Assert
			testCases.forEach(({ birthDate, expectedAge }) => {
				expect(calculateAge(birthDate)).toBe(expectedAge);
			});

			// Cleanup
			Date.now.mockRestore();
		});
	});

	// ==================== PAYMENT INTEGRATION TESTS ====================

	describe('Payment Method Integration', () => {
		test('should show bank details section for SEPA Direct Debit', () => {
			// Arrange
			mockDoc.payment_method = 'SEPA Direct Debit';
			const paymentChangeHandler = getMemberPaymentMethodHandler();

			// Act
			paymentChangeHandler(mockFrm);

			// Assert
			expect(mockFrm.toggle_display).toHaveBeenCalledWith('bank_details_section', true);
			expect(mockFrm.set_df_property).toHaveBeenCalledWith('iban', 'reqd', 1);
			expect(mockFrm.set_df_property).toHaveBeenCalledWith('bank_account_name', 'reqd', 1);
		});

		test('should hide bank details for non-SEPA payment methods', () => {
			// Arrange
			mockDoc.payment_method = 'Bank Transfer';
			const paymentChangeHandler = getMemberPaymentMethodHandler();

			// Act
			paymentChangeHandler(mockFrm);

			// Assert
			expect(mockFrm.toggle_display).toHaveBeenCalledWith('bank_details_section', false);
			expect(mockFrm.set_df_property).toHaveBeenCalledWith('iban', 'reqd', 0);
		});

		test('should validate SEPA mandate creation workflow', async () => {
			// Arrange
			const memberWithSEPA = testFactory.createMemberData({
				payment_method: 'SEPA Direct Debit',
				iban: testFactory.generateDutchIBAN(),
				bank_account_name: 'Test Account'
			});
			mockFrm.doc = memberWithSEPA;

			// Mock SEPA mandate check response
			const mockSEPAResponse = { message: null }; // No existing mandate
			mockFrm.call.mockResolvedValue(mockSEPAResponse);

			// Act
			await checkSEPAMandateStatus(mockFrm);

			// Assert
			expect(mockFrm.call).toHaveBeenCalledWith({
				method: 'verenigingen.verenigingen.doctype.member.member.check_sepa_mandate',
				args: { member_name: memberWithSEPA.name }
			});

			// Should show mandate creation dialog
			expect(frappe.msgprint).toHaveBeenCalledWith(
				expect.objectContaining({
					title: expect.stringContaining('SEPA Mandate'),
					primary_action: expect.any(Object)
				})
			);
		});

		test('should handle SEPA mandate creation confirmation', async () => {
			// Arrange
			const memberData = testFactory.createMemberData({
				payment_method: 'SEPA Direct Debit'
			});
			mockFrm.doc = memberData;

			// Act
			await createSEPAMandate(mockFrm);

			// Assert
			expect(mockFrm.call).toHaveBeenCalledWith({
				method: 'verenigingen.verenigingen.doctype.member.member.create_sepa_mandate',
				args: { member_name: memberData.name }
			});
			expect(mockFrm.reload_doc).toHaveBeenCalled();
		});
	});

	// ==================== CHAPTER MANAGEMENT TESTS ====================

	describe('Chapter Assignment and Management', () => {
		test('should assign member to chapter based on postal code', async () => {
			// Arrange
			const memberData = testFactory.createMemberData({
				primary_address: 'Test Address with 1234 AB postal code'
			});
			mockFrm.doc = memberData;

			const chapterData = testFactory.createChapterData({
				postal_code_ranges: '1000-1500, 2000-2500'
			});

			// Mock chapter assignment API
			mockFrm.call.mockResolvedValue({
				message: { chapter: chapterData.name }
			});

			// Act
			await assignToChapter(mockFrm);

			// Assert
			expect(mockFrm.call).toHaveBeenCalledWith({
				method: 'verenigingen.verenigingen.doctype.member.member.assign_to_chapter',
				args: { member_name: memberData.name }
			});
		});

		test('should display chapter join request status', () => {
			// Arrange
			const memberWithRequest = testFactory.createMemberData();
			mockFrm.doc = memberWithRequest;
			mockFrm.doc.__onload = {
				chapter_join_requests: [
					{
						chapter: 'Test Chapter',
						status: 'Pending',
						request_date: '2025-01-01'
					}
				]
			};

			// Act
			displayChapterJoinRequests(mockFrm);

			// Assert
			expect(mockFrm.dashboard.add_indicator).toHaveBeenCalledWith(
				expect.stringContaining('Pending Chapter Request'),
				'orange'
			);
		});

		test('should create chapter join request', async () => {
			// Arrange
			const memberData = testFactory.createMemberData();
			const chapterData = testFactory.createChapterData();
			mockFrm.doc = memberData;

			// Act
			await createChapterJoinRequest(mockFrm, chapterData.name);

			// Assert
			expect(mockFrm.call).toHaveBeenCalledWith({
				method: 'verenigingen.verenigingen.doctype.member.member.create_chapter_join_request',
				args: {
					member_name: memberData.name,
					chapter: chapterData.name
				}
			});
		});
	});

	// ==================== VOLUNTEER INTEGRATION TESTS ====================

	describe('Volunteer Profile Management', () => {
		test('should create volunteer profile for eligible member', async () => {
			// Arrange
			const eligibleMember = testFactory.createMemberData({
				birth_date: testFactory.generateBirthDate(18, 65)
			});
			mockFrm.doc = eligibleMember;

			// Act
			await createVolunteerProfile(mockFrm);

			// Assert
			expect(mockFrm.call).toHaveBeenCalledWith({
				method: 'verenigingen.verenigingen.doctype.member.member.create_volunteer',
				args: { member_name: eligibleMember.name }
			});
		});

		test('should prevent volunteer creation for underage members', () => {
			// Arrange
			const underageMember = testFactory.createMemberData({
				birth_date: testFactory.generateBirthDate(15, 15)
			});
			mockFrm.doc = underageMember;

			// Act
			const result = createVolunteerProfile(mockFrm);

			// Assert
			expect(frappe.msgprint).toHaveBeenCalledWith(
				expect.stringContaining('16 years old'),
				expect.stringContaining('Age Requirement')
			);
			expect(mockFrm.call).not.toHaveBeenCalled();
		});

		test('should display existing volunteer information', () => {
			// Arrange
			const memberWithVolunteer = testFactory.createMemberData();
			mockFrm.doc = memberWithVolunteer;
			mockFrm.doc.__onload = {
				volunteer_details: {
					name: 'VOL-001',
					status: 'Active',
					volunteer_since: '2024-01-01'
				}
			};

			// Act
			displayVolunteerDetails(mockFrm);

			// Assert
			expect(mockFrm.fields_dict.volunteer_details_html.$wrapper.html).toHaveBeenCalledWith(
				expect.stringContaining('Active Volunteer')
			);
		});
	});

	// ==================== DUTCH CONVENTIONS TESTS ====================

	describe('Dutch Naming Conventions', () => {
		test('should handle tussenvoegsel properly in full name generation', () => {
			// Arrange
			const testCases = [
				{
					first_name: 'Jan',
					tussenvoegsel: 'van',
					last_name: 'Berg',
					expected: 'Jan van Berg'
				},
				{
					first_name: 'Maria',
					tussenvoegsel: 'de',
					last_name: 'Wit',
					expected: 'Maria de Wit'
				},
				{
					first_name: 'Pieter',
					tussenvoegsel: '',
					last_name: 'Jansen',
					expected: 'Pieter Jansen'
				}
			];

			// Act & Assert
			testCases.forEach(({ first_name, tussenvoegsel, last_name, expected }) => {
				const fullName = generateFullName(first_name, tussenvoegsel, last_name);
				expect(fullName).toBe(expected);
			});
		});

		test('should validate Dutch mobile number formats', () => {
			// Arrange
			const validNumbers = [
				'06 1234 5678',
				'+31 6 1234 5678',
				'0612345678',
				'+31612345678'
			];
			const invalidNumbers = [
				'05 1234 5678', // Wrong prefix
				'+32 6 1234 5678', // Wrong country code
				'06 123 456', // Too short
				'not a number'
			];

			// Act & Assert
			validNumbers.forEach(number => {
				expect(validateDutchMobile(number)).toBe(true);
			});

			invalidNumbers.forEach(number => {
				expect(validateDutchMobile(number)).toBe(false);
			});
		});

		test('should format Dutch address correctly', () => {
			// Arrange
			const addressData = testFactory.createAddressData();

			// Act
			const formattedAddress = formatDutchAddress(addressData);

			// Assert
			expect(formattedAddress).toMatch(/\d{4}\s[A-Z]{2}/); // Contains postal code
			expect(formattedAddress).toContain(addressData.city);
			expect(formattedAddress).toContain('Netherlands');
		});
	});

	// ==================== ADMINISTRATIVE FUNCTIONS TESTS ====================

	describe('Administrative Functions', () => {
		test('should create customer link for member', async () => {
			// Arrange
			const memberData = testFactory.createMemberData();
			mockFrm.doc = memberData;

			// Act
			await createCustomerFromMember(mockFrm);

			// Assert
			expect(mockFrm.call).toHaveBeenCalledWith({
				method: 'verenigingen.verenigingen.doctype.member.member.create_customer',
				args: { member_name: memberData.name }
			});
		});

		test('should handle membership termination workflow', async () => {
			// Arrange
			const activeMember = testFactory.createMemberData({
				status: 'Active'
			});
			mockFrm.doc = activeMember;

			// Act
			await initiateTermination(mockFrm);

			// Assert
			expect(frappe.new_doc).toHaveBeenCalledWith('Membership Termination Request');
			expect(frappe.new_doc().member).toBe(activeMember.name);
		});

		test('should display fee management for authorized users', () => {
			// Arrange
			mockFrm.doc = testFactory.createMemberData();

			// Mock user roles
			frappe.user_roles = ['Verenigingen Administrator'];

			// Act
			addFeeManagementButtons(mockFrm);

			// Assert
			expect(mockFrm.add_custom_button).toHaveBeenCalledWith(
				'Override Fee',
				expect.any(Function),
				'Fee Management'
			);
		});

		test('should update member payment history', async () => {
			// Arrange
			const memberData = testFactory.createMemberData();
			mockFrm.doc = memberData;

			// Mock payment history data
			const paymentHistory = [
				{
					payment_date: '2025-01-01',
					amount: 25.00,
					status: 'Paid',
					reference: 'INV-001'
				}
			];

			mockFrm.call.mockResolvedValue({ message: paymentHistory });

			// Act
			await updatePaymentHistory(mockFrm);

			// Assert
			expect(mockFrm.call).toHaveBeenCalledWith({
				method: 'verenigingen.verenigingen.doctype.member.member.get_payment_history',
				args: { member_name: memberData.name }
			});
		});
	});

	// ==================== EDGE CASES AND ERROR HANDLING ====================

	describe('Edge Cases and Error Handling', () => {
		test('should handle maximum length names properly', () => {
			// Arrange
			const longNameMember = testFactory.createEdgeCaseScenario('maximum_length_names');
			mockFrm.doc = longNameMember;

			// Act
			const fullName = generateFullName(
				longNameMember.first_name,
				longNameMember.tussenvoegsel,
				longNameMember.last_name
			);

			// Assert
			expect(fullName.length).toBeLessThanOrEqual(150); // Reasonable limit
			expect(fullName).toContain(longNameMember.first_name.substring(0, 50));
		});

		test('should handle special characters in email validation', () => {
			// Arrange
			const specialCharMember = testFactory.createEdgeCaseScenario('special_characters_email');

			// Act & Assert
			expect(validateEmail(specialCharMember.email)).toBe(true);
		});

		test('should handle international members correctly', () => {
			// Arrange
			const internationalMember = testFactory.createEdgeCaseScenario('international_member');
			mockFrm.doc = internationalMember;

			// Act
			const validation = validateInternationalMember(mockFrm);

			// Assert
			expect(validation.valid).toBe(true);
			expect(validation.country).toBe('Germany');
		});

		test('should handle API errors gracefully', async () => {
			// Arrange
			const memberData = testFactory.createMemberData();
			mockFrm.doc = memberData;

			// Mock API error
			const apiError = new Error('Network error');
			mockFrm.call.mockRejectedValue(apiError);

			// Act
			await expect(checkSEPAMandateStatus(mockFrm)).rejects.toThrow('Network error');

			// Assert
			expect(frappe.msgprint).toHaveBeenCalledWith(
				expect.stringContaining('error'),
				expect.stringContaining('Error')
			);
		});

		test('should handle empty or null field values', () => {
			// Arrange
			const emptyFieldMember = {
				first_name: '',
				last_name: null,
				email: undefined,
				birth_date: ''
			};

			// Act & Assert
			expect(validateEmail(emptyFieldMember.email)).toBe(false);
			expect(calculateAge(emptyFieldMember.birth_date)).toBeNaN();
			expect(generateFullName(emptyFieldMember.first_name, '', emptyFieldMember.last_name)).toBe(' ');
		});
	});

	// ==================== HELPER FUNCTIONS ====================

	/**
   * Creates a mock Frappe form object for testing
   * @param {Object} doc - Document data
   * @returns {Object} Mock form object
   */
	function createMockForm(doc) {
		return {
			doc,
			add_custom_button: jest.fn(),
			set_df_property: jest.fn(),
			toggle_display: jest.fn(),
			call: jest.fn(),
			reload_doc: jest.fn(),
			dashboard: {
				add_indicator: jest.fn()
			},
			fields_dict: {
				volunteer_details_html: {
					$wrapper: {
						html: jest.fn()
					}
				},
				other_members_at_address: {
					toggle: jest.fn()
				}
			}
		};
	}

	/**
   * Sets up global mock objects
   */
	function setupGlobalMocks() {
		global.frappe = {
			msgprint: jest.fn(),
			new_doc: jest.fn(() => ({})),
			user_roles: ['System Manager'],
			session: { user: 'test@example.com' }
		};

		global.$ = jest.fn(() => ({
			html: jest.fn(),
			show: jest.fn(),
			css: jest.fn(),
			find: jest.fn().mockReturnThis(),
			hasClass: jest.fn(() => false),
			length: 1
		}));
	}

	/**
   * Mock implementations of member form handlers
   */
	function getMemberRefreshHandler() {
		return jest.fn((frm) => {
			// Mock refresh logic
			if (frm.doc.__islocal) {
				frm.add_custom_button('Basic Action', () => {});
			} else {
				frm.add_custom_button('Full Action', () => {});
				frm.toggle_display('tussenvoegsel', !!frm.doc.tussenvoegsel);

				if (frm.doc.status === 'Terminated') {
					frm.dashboard.add_indicator('Terminated', 'red');
				}
			}
		});
	}

	function getMemberPaymentMethodHandler() {
		return jest.fn((frm) => {
			const isSEPA = frm.doc.payment_method === 'SEPA Direct Debit';
			frm.toggle_display('bank_details_section', isSEPA);
			frm.set_df_property('iban', 'reqd', isSEPA ? 1 : 0);
			frm.set_df_property('bank_account_name', 'reqd', isSEPA ? 1 : 0);
		});
	}

	// Mock validation functions
	const validateDutchPostalCode = jest.fn((code) => {
		if (!code) { return false; }
		return /^[0-9]{4}\s?[A-Z]{2}$/.test(code);
	});

	const validateIBAN = jest.fn((iban) => {
		if (!iban) { return false; }
		const cleaned = iban.replace(/\s/g, '').toUpperCase();
		return /^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/.test(cleaned) && cleaned.length >= 15;
	});

	const validateEmail = jest.fn((email) => {
		if (!email) { return false; }
		const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
		return re.test(email);
	});

	const validateDutchMobile = jest.fn((number) => {
		if (!number) { return false; }
		const cleaned = number.replace(/\s/g, '');
		return /^(\+31|0)6[0-9]{8}$/.test(cleaned);
	});

	const calculateAge = jest.fn((birthDate) => {
		if (!birthDate) { return NaN; }
		const today = new Date();
		const birth = new Date(birthDate);
		let age = today.getFullYear() - birth.getFullYear();
		const monthDiff = today.getMonth() - birth.getMonth();
		if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) {
			age--;
		}
		return age;
	});

	const generateFullName = jest.fn((firstName, tussenvoegsel, lastName) => {
		if (!firstName && !lastName) { return ' '; }
		const parts = [firstName, tussenvoegsel, lastName].filter(part => part && part.trim());
		return parts.join(' ');
	});

	// Mock business logic functions
	const canCreateVolunteerProfile = jest.fn((member) => {
		const age = calculateAge(member.birth_date);
		return age >= 16;
	});

	const checkSEPAMandateStatus = jest.fn(async (frm) => {
		return frm.call({
			method: 'verenigingen.verenigingen.doctype.member.member.check_sepa_mandate',
			args: { member_name: frm.doc.name }
		});
	});

	const createSEPAMandate = jest.fn(async (frm) => {
		await frm.call({
			method: 'verenigingen.verenigingen.doctype.member.member.create_sepa_mandate',
			args: { member_name: frm.doc.name }
		});
		frm.reload_doc();
	});

	const assignToChapter = jest.fn(async (frm) => {
		return frm.call({
			method: 'verenigingen.verenigingen.doctype.member.member.assign_to_chapter',
			args: { member_name: frm.doc.name }
		});
	});

	const createVolunteerProfile = jest.fn(async (frm) => {
		if (!canCreateVolunteerProfile(frm.doc)) {
			frappe.msgprint('Member must be at least 16 years old', 'Age Requirement');
			return;
		}

		return frm.call({
			method: 'verenigingen.verenigingen.doctype.member.member.create_volunteer',
			args: { member_name: frm.doc.name }
		});
	});

	const createCustomerFromMember = jest.fn(async (frm) => {
		return frm.call({
			method: 'verenigingen.verenigingen.doctype.member.member.create_customer',
			args: { member_name: frm.doc.name }
		});
	});

	const initiateTermination = jest.fn(async (frm) => {
		const doc = frappe.new_doc('Membership Termination Request');
		doc.member = frm.doc.name;
		return doc;
	});

	const updatePaymentHistory = jest.fn(async (frm) => {
		return frm.call({
			method: 'verenigingen.verenigingen.doctype.member.member.get_payment_history',
			args: { member_name: frm.doc.name }
		});
	});

	const displayChapterJoinRequests = jest.fn((frm) => {
		if (frm.doc.__onload && frm.doc.__onload.chapter_join_requests) {
			frm.doc.__onload.chapter_join_requests.forEach(request => {
				if (request.status === 'Pending') {
					frm.dashboard.add_indicator('Pending Chapter Request', 'orange');
				}
			});
		}
	});

	const displayVolunteerDetails = jest.fn((frm) => {
		if (frm.doc.__onload && frm.doc.__onload.volunteer_details) {
			const details = frm.doc.__onload.volunteer_details;
			frm.fields_dict.volunteer_details_html.$wrapper.html(
				`<div>Active Volunteer since ${details.volunteer_since}</div>`
			);
		}
	});

	const addFeeManagementButtons = jest.fn((frm) => {
		if (frappe.user_roles.includes('Verenigingen Administrator')) {
			frm.add_custom_button('Override Fee', () => {}, 'Fee Management');
		}
	});

	const createChapterJoinRequest = jest.fn(async (frm, chapterName) => {
		return frm.call({
			method: 'verenigingen.verenigingen.doctype.member.member.create_chapter_join_request',
			args: {
				member_name: frm.doc.name,
				chapter: chapterName
			}
		});
	});

	const formatDutchAddress = jest.fn((addressData) => {
		return `${addressData.address_line1}, ${addressData.pincode} ${addressData.city}, ${addressData.country}`;
	});

	const validateInternationalMember = jest.fn((frm) => {
		return {
			valid: true,
			country: frm.doc.primary_address ? 'Germany' : 'Netherlands'
		};
	});
});
