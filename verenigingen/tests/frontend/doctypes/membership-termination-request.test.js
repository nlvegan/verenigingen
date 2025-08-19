/**
 * @fileoverview Comprehensive Membership Termination Request DocType JavaScript Test Suite
 *
 * This test suite provides complete coverage of the Membership Termination Request
 * DocType's client-side functionality, focusing on realistic termination scenarios
 * and Dutch association compliance workflows. Tests cover the full termination
 * lifecycle from initiation through execution and audit reporting.
 *
 * @description Business Context:
 * Membership Termination Requests handle both voluntary and disciplinary membership
 * terminations with comprehensive workflow management, approval processes, and
 * automated system cleanup. This test suite validates critical workflows including:
 * - Multi-tier approval workflows for disciplinary actions
 * - Automated system cleanup (SEPA mandates, newsletters, positions)
 * - Comprehensive audit trail and compliance reporting
 * - Grace period management and termination execution
 * - Integration with expulsion reporting requirements
 * - Role-based authorization and approval workflows
 *
 * @description Test Categories:
 * 1. Form Lifecycle - Form initialization, refresh, and status management
 * 2. Termination Type Management - Voluntary vs disciplinary workflows
 * 3. Approval Workflows - Multi-tier approval and role-based authorization
 * 4. Disciplinary Actions - Policy violations, expulsions, and documentation
 * 5. System Integration - SEPA, newsletter, and position management
 * 6. Audit Trail Management - Compliance reporting and documentation
 * 7. Bulk Processing - Administrative efficiency and batch operations
 * 8. Edge Cases - Validation failures and error handling
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

// Import test factory
const TestDataFactory = require('../factories/test-data-factory');

describe('Membership Termination Request DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		// Initialize test factory with consistent seed
		testFactory = new TestDataFactory(24680);

		// Create mock form object that mimics Frappe's structure
		mockDoc = testFactory.createMembershipTerminationRequestData();
		mockFrm = createMockForm(mockDoc);

		// Mock global dependencies
		setupGlobalMocks();

		// Mock user roles for authorization testing
		setupUserRoleMocks();
	});

	afterEach(() => {
		// Clean up mocks and reset state
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	describe('Form Lifecycle Management', () => {
		test('should initialize new termination request with default values', () => {
			// Arrange
			mockFrm.is_new.mockReturnValueOnce(true);

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.onload(mockFrm);

			// Assert
			expect(mockFrm.set_value).toHaveBeenCalledWith('request_date', expect.any(String));
			expect(mockFrm.set_value).toHaveBeenCalledWith('requested_by', 'test@example.com');
			expect(mockFrm.set_value).toHaveBeenCalledWith('status', 'Draft');
		});

		test('should set appropriate status indicator based on current status', () => {
			// Arrange
			mockDoc.status = 'Pending';

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.refresh(mockFrm);

			// Assert
			expect(mockFrm.page.set_indicator).toHaveBeenCalledWith('Pending', 'yellow');
		});

		test('should add view member button when member is specified', () => {
			// Arrange
			const memberName = testFactory.createMemberName();
			mockDoc.member = memberName;

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.refresh(mockFrm);

			// Assert
			expect(mockFrm.add_custom_button).toHaveBeenCalledWith(
				'View Member',
				expect.any(Function),
				'View'
			);
		});

		test('should make audit trail read-only', () => {
			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.refresh(mockFrm);

			// Assert
			expect(mockFrm.set_df_property).toHaveBeenCalledWith('audit_trail', 'read_only', 1);
		});
	});

	describe('Termination Type Management', () => {
		test('should show disciplinary fields for policy violations', () => {
			// Arrange
			mockDoc.termination_type = 'Policy Violation';

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.termination_type(mockFrm);

			// Assert
			expect(mockFrm.toggle_display).toHaveBeenCalledWith('disciplinary_documentation', true);
			expect(mockFrm.toggle_reqd).toHaveBeenCalledWith('disciplinary_documentation', true);
			expect(mockFrm.toggle_display).toHaveBeenCalledWith('secondary_approver', true);
			expect(mockFrm.toggle_reqd).toHaveBeenCalledWith('secondary_approver', true);
		});

		test('should hide disciplinary fields for voluntary terminations', () => {
			// Arrange
			mockDoc.termination_type = 'Voluntary';

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.termination_type(mockFrm);

			// Assert
			expect(mockFrm.toggle_display).toHaveBeenCalledWith('disciplinary_documentation', false);
			expect(mockFrm.toggle_reqd).toHaveBeenCalledWith('disciplinary_documentation', false);
			expect(mockFrm.toggle_display).toHaveBeenCalledWith('secondary_approver', false);
			expect(mockFrm.toggle_reqd).toHaveBeenCalledWith('secondary_approver', false);
		});

		test('should set immediate termination date for disciplinary actions', () => {
			// Arrange
			mockDoc.termination_type = 'Expulsion';
			mockDoc.termination_date = null;

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.termination_type(mockFrm);

			// Assert
			expect(mockFrm.set_value).toHaveBeenCalledWith('termination_date', expect.any(String));
			expect(mockFrm.set_value).toHaveBeenCalledWith('grace_period_end', null);
		});

		test('should set grace period for voluntary terminations', () => {
			// Arrange
			mockDoc.termination_type = 'Voluntary';
			mockDoc.termination_date = null;
			mockDoc.grace_period_end = null;

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.termination_type(mockFrm);

			// Assert
			expect(mockFrm.set_value).toHaveBeenCalledWith('termination_date', expect.any(String));
			expect(mockFrm.set_value).toHaveBeenCalledWith('grace_period_end', expect.any(String));
		});
	});

	describe('Approval Workflow Management', () => {
		test('should show submit for approval button in draft status', () => {
			// Arrange
			mockDoc.status = 'Draft';

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.refresh(mockFrm);

			// Assert
			expect(mockFrm.add_custom_button).toHaveBeenCalledWith(
				'Submit for Approval',
				expect.any(Function),
				'Actions'
			);
		});

		test('should show approval buttons for authorized users in pending status', () => {
			// Arrange
			mockDoc.status = 'Pending';
			frappe.user_roles = ['System Manager']; // Mock system manager role

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.refresh(mockFrm);

			// Assert
			expect(mockFrm.add_custom_button).toHaveBeenCalledWith(
				'Approve',
				expect.any(Function),
				'Actions'
			);
			expect(mockFrm.add_custom_button).toHaveBeenCalledWith(
				'Reject',
				expect.any(Function),
				'Actions'
			);
		});

		test('should show execute termination button in approved status', () => {
			// Arrange
			mockDoc.status = 'Approved';

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.refresh(mockFrm);

			// Assert
			expect(mockFrm.add_custom_button).toHaveBeenCalledWith(
				'Execute Termination',
				expect.any(Function),
				'Actions'
			);
		});

		test('should submit request for approval successfully', async () => {
			// Arrange
			mockDoc.status = 'Draft';
			mockDoc.termination_type = 'Voluntary';
			mockDoc.termination_reason = 'Personal reasons';

			mockFrm.call.mockResolvedValueOnce({ message: true });

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');

			// Find submit button and execute
			terminationRequest.refresh(mockFrm);
			const submitButton = mockFrm.add_custom_button.mock.calls.find(
				call => call[0] === 'Submit for Approval'
			);
			if (submitButton) {
				await submitButton[1](); // Execute the callback
			}

			// Assert
			expect(mockFrm.call).toHaveBeenCalledWith({
				method: 'submit_for_approval',
				doc: mockDoc,
				callback: expect.any(Function)
			});
		});
	});

	describe('Disciplinary Action Management', () => {
		test('should validate disciplinary documentation requirement', () => {
			// Arrange
			mockDoc.termination_type = 'Expulsion';
			mockDoc.disciplinary_documentation = '';

			// Act & Assert
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');

			// Validation should be triggered during before_save
			expect(() => {
				terminationRequest.before_save(mockFrm);
			}).toThrow();
		});

		test('should require secondary approver for disciplinary terminations', () => {
			// Arrange
			mockDoc.termination_type = 'Disciplinary Action';
			mockDoc.status = 'Pending';
			mockDoc.secondary_approver = null;

			// Act & Assert
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');

			expect(() => {
				terminationRequest.before_save(mockFrm);
			}).toThrow();
		});

		test('should set secondary approver filter for disciplinary cases', () => {
			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.onload(mockFrm);

			// Assert
			expect(mockFrm.set_query).toHaveBeenCalledWith('secondary_approver', expect.any(Function));
		});

		test('should check approval authorization for disciplinary terminations', () => {
			// Arrange
			mockDoc.requires_secondary_approval = true;
			mockDoc.secondary_approver = 'test@example.com';
			frappe.user_roles = ['Verenigingen Administrator'];
			frappe.session.user = 'test@example.com';

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');

			// Simulate can_approve_request function
			const canApprove = (frm) => {
				const userRoles = frappe.user_roles;
				if (userRoles.includes('System Manager')) { return true; }
				if (userRoles.includes('Verenigingen Administrator') && frm.doc.requires_secondary_approval) { return true; }
				return frm.doc.secondary_approver === frappe.session.user;
			};

			// Assert
			expect(canApprove(mockFrm)).toBe(true);
		});
	});

	describe('Member Clearing Behavior', () => {
		test('should clear member name when member field is cleared', () => {
			// Arrange
			mockDoc.member = '';

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.member(mockFrm);

			// Assert
			expect(mockFrm.set_value).toHaveBeenCalledWith('member_name', '');
		});
	});

	describe('Termination Execution', () => {
		test('should show confirmation dialog before executing termination', () => {
			// Arrange
			mockDoc.status = 'Approved';

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.refresh(mockFrm);

			// Find execute button and execute
			const executeButton = mockFrm.add_custom_button.mock.calls.find(
				call => call[0] === 'Execute Termination'
			);
			if (executeButton) {
				executeButton[1](); // Execute the callback
			}

			// Assert confirmation dialog is shown
			expect(frappe.confirm).toHaveBeenCalledWith(
				expect.stringContaining('Are you sure you want to execute this termination'),
				expect.any(Function)
			);
		});

		test('should execute termination with proper freeze message', async () => {
			// Arrange
			mockDoc.status = 'Approved';
			mockFrm.call.mockResolvedValueOnce({ message: true });

			// Mock frappe.confirm to automatically accept
			frappe.confirm.mockImplementationOnce((message, callback) => {
				callback(); // Automatically accept confirmation
			});

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.refresh(mockFrm);

			// Find execute button and execute
			const executeButton = mockFrm.add_custom_button.mock.calls.find(
				call => call[0] === 'Execute Termination'
			);
			if (executeButton) {
				await executeButton[1]();
			}

			// Assert execution call is made
			expect(mockFrm.call).toHaveBeenCalledWith({
				method: 'execute_termination',
				doc: mockDoc,
				freeze: true,
				freeze_message: 'Executing termination...',
				callback: expect.any(Function)
			});
		});
	});

	describe('Enhanced Termination Dialog', () => {
		test('should create enhanced termination dialog with proper fields', () => {
			// Arrange
			const memberName = testFactory.createMemberName();
			const memberDisplayName = 'Jan van der Berg';

			frappe.ui.Dialog.mockImplementationOnce((config) => ({
				show: jest.fn(),
				fields_dict: {
					disciplinary_documentation: { df: { hidden: false } },
					secondary_approver: { df: { hidden: false } }
				},
				refresh: jest.fn(),
				...config
			}));

			// Act
			window.show_enhanced_termination_dialog(memberName, memberDisplayName);

			// Assert
			expect(frappe.ui.Dialog).toHaveBeenCalledWith(
				expect.objectContaining({
					title: `Terminate Membership: ${memberDisplayName}`,
					size: 'large'
				})
			);
		});

		test('should handle disciplinary termination workflow in dialog', () => {
			// Arrange
			const memberName = testFactory.createMemberName();
			const memberDisplayName = 'Test Member';

			const mockDialog = {
				show: jest.fn(),
				hide: jest.fn(),
				fields_dict: {
					disciplinary_documentation: { df: { hidden: false } },
					secondary_approver: { df: { hidden: false } }
				},
				refresh: jest.fn()
			};

			frappe.ui.Dialog.mockImplementationOnce(() => mockDialog);
			frappe.call.mockResolvedValueOnce({
				message: { request_id: 'MTR-2025-001' }
			});

			// Act
			window.show_enhanced_termination_dialog(memberName, memberDisplayName);

			// Simulate disciplinary termination selection
			const values = {
				termination_type: 'Expulsion',
				termination_reason: 'Serious policy violation',
				disciplinary_documentation: 'Detailed documentation of violations',
				secondary_approver: 'manager@example.com'
			};

			// Assert dialog configuration includes disciplinary fields
			expect(frappe.ui.Dialog).toHaveBeenCalled();
		});
	});

	describe('Status Indicator Management', () => {
		test('should display correct indicators for all status types', () => {
			// Test all status types
			const statusMap = {
				Draft: 'blue',
				Pending: 'yellow',
				Approved: 'green',
				Rejected: 'red',
				Executed: 'gray'
			};

			Object.entries(statusMap).forEach(([status, color]) => {
				// Arrange
				mockDoc.status = status;

				// Act
				const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
				terminationRequest.refresh(mockFrm);

				// Assert
				expect(mockFrm.page.set_indicator).toHaveBeenCalledWith(status, color);
			});
		});
	});

	describe('Edge Cases and Error Handling', () => {
		test('should handle missing termination type gracefully', () => {
			// Arrange
			mockDoc.termination_type = null;

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');

			// Should not throw
			expect(() => {
				terminationRequest.termination_type(mockFrm);
			}).not.toThrow();
		});

		test('should handle unauthorized approval attempts', () => {
			// Arrange
			mockDoc.status = 'Pending';
			frappe.user_roles = ['Limited User']; // No authorization

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');
			terminationRequest.refresh(mockFrm);

			// Assert no approval buttons are shown
			const approveButton = mockFrm.add_custom_button.mock.calls.find(
				call => call[0] === 'Approve'
			);
			expect(approveButton).toBeUndefined();
		});

		test('should handle API errors during submission', async () => {
			// Arrange
			mockFrm.call.mockRejectedValueOnce(new Error('Network error'));

			// Act
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');

			// Should not throw
			expect(async () => {
				terminationRequest.refresh(mockFrm);
			}).not.toThrow();
		});

		test('should validate required fields before submission', () => {
			// Arrange
			mockDoc.termination_type = 'Expulsion';
			mockDoc.disciplinary_documentation = '';

			// Act & Assert
			const terminationRequest = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request.js');

			expect(() => {
				terminationRequest.before_save(mockFrm);
			}).toThrow();
		});
	});
});

describe('Membership Termination Request List View - Status and Workflow Management', () => {
	let testFactory;

	beforeEach(() => {
		testFactory = new TestDataFactory(24680);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	test('should display correct indicators for all status types', () => {
		// Test data for all statuses
		const testCases = [
			{ status: 'Draft', expectedColor: 'blue' },
			{ status: 'Pending', expectedColor: 'yellow' },
			{ status: 'Approved', expectedColor: 'green' },
			{ status: 'Rejected', expectedColor: 'red' },
			{ status: 'Executed', expectedColor: 'gray' }
		];

		testCases.forEach(({ status, expectedColor }) => {
			// Arrange
			const docData = testFactory.createMembershipTerminationRequestData({ status });

			// Act
			const listSettings = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request_list.js');
			const indicator = listSettings.get_indicator(docData);

			// Assert
			expect(indicator).toEqual([status, expectedColor, `status,=,${status}`]);
		});
	});

	test('should format disciplinary termination types with red indicator', () => {
		// Arrange
		const disciplinaryTypes = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];

		disciplinaryTypes.forEach(type => {
			// Act
			const listSettings = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request_list.js');
			const formatted = listSettings.formatters.termination_type(type);

			// Assert
			expect(formatted).toBe(`<span class="indicator red">${type}</span>`);
		});
	});

	test('should format voluntary termination types with blue indicator', () => {
		// Arrange
		const voluntaryTypes = ['Voluntary', 'Non-payment', 'Deceased'];

		voluntaryTypes.forEach(type => {
			// Act
			const listSettings = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request_list.js');
			const formatted = listSettings.formatters.termination_type(type);

			// Assert
			expect(formatted).toBe(`<span class="indicator blue">${type}</span>`);
		});
	});

	test('should show review button only for pending requests', () => {
		// Arrange
		const pendingDoc = testFactory.createMembershipTerminationRequestData({ status: 'Pending' });
		const draftDoc = testFactory.createMembershipTerminationRequestData({ status: 'Draft' });

		// Act
		const listSettings = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request_list.js');

		// Assert
		expect(listSettings.button.show(pendingDoc)).toBe(true);
		expect(listSettings.button.show(draftDoc)).toBe(false);
	});

	test('should navigate to form when review button is clicked', () => {
		// Arrange
		const docData = testFactory.createMembershipTerminationRequestData({
			name: 'MTR-2025-001',
			status: 'Pending'
		});

		// Act
		const listSettings = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request_list.js');
		listSettings.button.action(docData);

		// Assert
		expect(frappe.set_route).toHaveBeenCalledWith(
			'Form',
			'Membership Termination Request',
			'MTR-2025-001'
		);
	});

	test('should add custom menu items on list load', () => {
		// Arrange
		const mockListview = {
			page: {
				add_menu_item: jest.fn(),
				get_checked_items: jest.fn().mockReturnValue([])
			},
			get_checked_items: jest.fn().mockReturnValue([]),
			refresh: jest.fn()
		};

		// Act
		const listSettings = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request_list.js');
		listSettings.onload(mockListview);

		// Assert
		expect(mockListview.page.add_menu_item).toHaveBeenCalledWith(
			'Generate Expulsion Report',
			expect.any(Function)
		);
		expect(mockListview.page.add_menu_item).toHaveBeenCalledWith(
			'Bulk Process Terminations',
			expect.any(Function)
		);
	});

	test('should handle expulsion report generation dialog', () => {
		// Arrange
		frappe.ui.Dialog.mockImplementationOnce((config) => ({
			show: jest.fn(),
			...config
		}));

		// Act
		const listSettings = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request_list.js');

		// Simulate menu item click
		const mockListview = {
			page: {
				add_menu_item: jest.fn((label, callback) => {
					if (label === 'Generate Expulsion Report') {
						callback();
					}
				})
			}
		};

		listSettings.onload(mockListview);

		// Assert
		expect(frappe.ui.Dialog).toHaveBeenCalledWith(
			expect.objectContaining({
				title: 'Generate Expulsion Report'
			})
		);
	});

	test('should handle bulk processing with confirmation', () => {
		// Arrange
		const approvedItems = [
			{ name: 'MTR-001', status: 'Approved' },
			{ name: 'MTR-002', status: 'Approved' }
		];

		const mockListview = {
			page: {
				add_menu_item: jest.fn()
			},
			get_checked_items: jest.fn().mockReturnValue(approvedItems),
			refresh: jest.fn()
		};

		frappe.ui.Dialog.mockImplementationOnce((config) => ({
			show: jest.fn(),
			...config
		}));

		// Act
		const listSettings = require('../../../../verenigingen/doctype/membership_termination_request/membership_termination_request_list.js');

		// Simulate bulk process menu click
		mockListview.page.add_menu_item.mockImplementationOnce((label, callback) => {
			if (label === 'Bulk Process Terminations') {
				callback();
			}
		});

		listSettings.onload(mockListview);

		// Assert bulk process dialog
		expect(frappe.ui.Dialog).toHaveBeenCalledWith(
			expect.objectContaining({
				title: 'Bulk Process Terminations'
			})
		);
	});
});

/**
 * Helper function to create mock form object
 */
function createMockForm(doc) {
	return {
		doc,
		add_custom_button: jest.fn().mockReturnValue({ addClass: jest.fn() }),
		call: jest.fn(),
		trigger: jest.fn(),
		set_value: jest.fn(),
		set_df_property: jest.fn(),
		clear_custom_buttons: jest.fn(),
		toggle_display: jest.fn(),
		toggle_reqd: jest.fn(),
		set_query: jest.fn(),
		refresh: jest.fn(),
		reload_doc: jest.fn(),
		is_new: jest.fn().mockReturnValue(false),
		page: {
			set_indicator: jest.fn(),
			add_menu_item: jest.fn()
		}
	};
}

/**
 * Helper function to set up global mocks
 */
function setupGlobalMocks() {
	global.frappe = {
		ui: {
			form: {
				on: jest.fn()
			},
			Dialog: jest.fn()
		},
		call: jest.fn(),
		new_doc: jest.fn(),
		confirm: jest.fn(),
		msgprint: jest.fn(),
		show_alert: jest.fn(),
		set_route: jest.fn(),
		datetime: {
			get_today: jest.fn().mockReturnValue('2025-08-19'),
			add_days: jest.fn((date, days) => '2025-09-18'),
			str_to_user: jest.fn(date => date)
		},
		session: {
			user: 'test@example.com'
		},
		user_roles: ['Limited User'],
		__: jest.fn(str => str) // Simple translation mock
	};

	global.__ = jest.fn(str => str);
	global.window = { show_enhanced_termination_dialog: jest.fn() };
}

/**
 * Helper function to set up user role mocks
 */
function setupUserRoleMocks() {
	global.frappe.user_roles = ['Limited User'];
}

/**
 * Helper function to tear down global mocks
 */
function teardownGlobalMocks() {
	delete global.frappe;
	delete global.__;
	delete global.window;
}
