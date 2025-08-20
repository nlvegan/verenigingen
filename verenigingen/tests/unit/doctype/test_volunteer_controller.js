/**
 * @fileoverview Unit Tests for Volunteer DocType Controller
 *
 * Comprehensive test suite for volunteer management JavaScript controller,
 * covering assignment management, skills database, timeline visualization,
 * and member integration functionality using the real controller.
 *
 * @author Verenigingen Development Team
 * @version 2.0.0 - Updated to use real controller loading
 */

/* global describe, it, expect, jest, beforeEach, afterEach, beforeAll */

// Import test setup utilities
const {
	setupTestMocks,
	cleanupTestMocks,
	createMockForm,
	dutchTestData
} = require('../../setup/frappe-mocks');
const {
	loadFrappeController,
	testFormEvent
} = require('../../setup/controller-loader');
const { validateDutchEmail } = require('../../setup/dutch-validators');

// Initialize test environment
setupTestMocks();

// Mock jQuery for controller dependencies
global.$ = jest.fn((selector) => ({
	appendTo: jest.fn(() => global.$()),
	find: jest.fn(() => global.$()),
	click: jest.fn(),
	remove: jest.fn(),
	css: jest.fn(),
	addClass: jest.fn(),
	removeClass: jest.fn(),
	val: jest.fn(),
	text: jest.fn(),
	html: jest.fn(),
	on: jest.fn()
}));

describe('Volunteer DocType Controller', () => {
	let volunteerHandlers;
	let frm;

	beforeAll(() => {
		// Load the real volunteer controller
		const controllerPath = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/volunteer/volunteer.js';
		const allHandlers = loadFrappeController(controllerPath);
		volunteerHandlers = allHandlers.Volunteer;

		expect(volunteerHandlers).toBeDefined();
		expect(volunteerHandlers.refresh).toBeDefined();
	});

	beforeEach(() => {
		cleanupTestMocks();

		frm = createMockForm({
			doc: {
				name: 'VOL-2024-001',
				doctype: 'Volunteer',
				volunteer_name: 'Anna van der Berg',
				member: 'MEM-2024-001',
				status: 'Active',
				start_date: '2024-01-15',
				email: 'anna.van.der.berg@example.org',
				__islocal: 0
			}
		});

		// Mock volunteer-specific form fields
		frm.fields_dict = {
			assignment_section: {
				wrapper: global.$('<div>')
			},
			skills_and_qualifications: {
				grid: {
					add_custom_button: jest.fn()
				}
			}
		};

		// Mock contacts.render_address_and_contact
		global.frappe.contacts = {
			render_address_and_contact: jest.fn(),
			clear_address_and_contact: jest.fn()
		};

		// Mock dynamic_link global
		global.frappe.dynamic_link = null;

		// Ensure datetime mocks are properly set
		global.frappe.datetime = {
			get_today: () => '2024-01-15',
			str_to_user: (date) => date || '2024-01-15',
			now_date: () => '2024-01-15',
			user_to_str: (date) => date || '2024-01-15',
			moment: (date) => ({
				format: (fmt) => date || '2024-01-15'
			})
		};
	});

	afterEach(() => {
		cleanupTestMocks();
	});

	describe('Assignment Management', () => {
		describe('render_aggregated_assignments', () => {
			beforeEach(() => {
				// Mock server response for assignment data
				global.frappe.call.mockImplementation(({ method, doc, callback }) => {
					if (method === 'get_aggregated_assignments') {
						if (callback) {
							callback({
								message: [
									{
										role: 'Event Coordinator',
										source_type: 'Activity',
										source_doctype_display: 'Activity',
										source_name_display: 'Test Activity',
										source_link: '/app/activity/test-activity',
										start_date: '2024-01-01',
										end_date: null,
										editable: true
									},
									{
										role: 'Team Lead',
										source_type: 'Team',
										source_doctype_display: 'Team',
										source_name_display: 'Marketing Team',
										source_link: '/app/team/marketing-team',
										start_date: '2024-02-01',
										end_date: '2024-12-31',
										editable: false
									}
								]
							});
						}
					}
				});
			});

			it('should render assignment history correctly', () => {
				frm.doc.__islocal = 0;

				testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

				// Verify that get_aggregated_assignments was called
				expect(global.frappe.call).toHaveBeenCalledWith(
					expect.objectContaining({
						method: 'get_aggregated_assignments',
						doc: frm.doc
					})
				);
			});

			it('should handle empty assignment history', () => {
				// Override mock to return empty assignments
				global.frappe.call.mockImplementation(({ method, callback }) => {
					if (method === 'get_aggregated_assignments' && callback) {
						callback({ message: [] });
					}
				});

				frm.doc.__islocal = 0;

				expect(() => {
					testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });
				}).not.toThrow();
			});

			it('should handle API errors gracefully', () => {
				// Mock API error
				global.frappe.call.mockImplementation(({ method, error }) => {
					if (method === 'get_aggregated_assignments' && error) {
						error('Failed to fetch assignments');
					}
				});

				frm.doc.__islocal = 0;

				expect(() => {
					testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });
				}).not.toThrow();
			});
		});

		describe('add_activity_button', () => {
			it('should add the Add Activity button for saved records', () => {
				frm.doc.__islocal = 0;

				testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

				// Check for Add Activity button
				const addActivityCall = frm.add_custom_button.mock.calls.find(
					call => call[0].includes('Add Activity')
				);
				expect(addActivityCall).toBeDefined();
				expect(addActivityCall[2]).toBe('Assignments');
			});

			it('should not add buttons for new records', () => {
				frm.doc.__islocal = 1;

				testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

				// Should not have Add Activity button for new records
				const addActivityCall = frm.add_custom_button.mock.calls.find(
					call => call[0].includes('Add Activity')
				);
				expect(addActivityCall).toBeUndefined();
			});
		});
	});

	describe('Skills Management', () => {
		it('should add skills grid custom button', () => {
			testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

			expect(frm.fields_dict.skills_and_qualifications.grid.add_custom_button).toHaveBeenCalledWith(
				'Add Skill',
				expect.any(Function)
			);
		});

		it('should handle missing skills grid gracefully', () => {
			frm.fields_dict.skills_and_qualifications = null;

			expect(() => {
				testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });
			}).not.toThrow();
		});
	});

	describe('Timeline Visualization', () => {
		it('should add View Timeline button for saved records', () => {
			frm.doc.__islocal = 0;

			testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

			// Check for View Timeline button
			const viewTimelineCall = frm.add_custom_button.mock.calls.find(
				call => call[0].includes('View Timeline')
			);
			expect(viewTimelineCall).toBeDefined();
			expect(viewTimelineCall[2]).toBe('View');
		});

		it('should add Volunteer Report button for saved records', () => {
			frm.doc.__islocal = 0;

			testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

			// Check for Volunteer Report button
			const reportCall = frm.add_custom_button.mock.calls.find(
				call => call[0].includes('Volunteer Report')
			);
			expect(reportCall).toBeDefined();
			expect(reportCall[2]).toBe('View');
		});
	});

	describe('Member Integration', () => {
		beforeEach(() => {
			// Mock member data response
			global.frappe.call.mockImplementation(({ method, args, callback }) => {
				if (method === 'frappe.client.get' && callback) {
					callback({ message: dutchTestData.members[0] });
				} else if (method === 'frappe.client.get_value' && callback) {
					callback({
						message: {
							organization_email_domain: 'example.org'
						}
					});
				}
			});
		});

		it('should fetch member data when member field changes', () => {
			frm.doc.member = 'MEM-2024-001';

			testFormEvent('Volunteer', 'member', frm, { Volunteer: volunteerHandlers });

			expect(global.frappe.call).toHaveBeenCalledWith(
				expect.objectContaining({
					method: 'frappe.client.get',
					args: {
						doctype: 'Member',
						name: 'MEM-2024-001'
					}
				})
			);
		});

		it('should update dynamic link when member is selected', () => {
			frm.doc.member = 'MEM-2024-001';

			testFormEvent('Volunteer', 'member', frm, { Volunteer: volunteerHandlers });

			expect(global.frappe.dynamic_link).toEqual({
				doc: { name: 'MEM-2024-001', doctype: 'Member' },
				fieldname: 'name',
				doctype: 'Member'
			});
		});

		it('should add View Member button when member is linked', () => {
			frm.doc.member = 'MEM-2024-001';
			frm.doc.__islocal = 0;

			testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

			// Check that View Member button was added
			const viewMemberCall = frm.add_custom_button.mock.calls.find(
				call => call[0].includes('View Member')
			);
			expect(viewMemberCall).toBeDefined();
			expect(viewMemberCall[2]).toBe('Links');
		});
	});

	describe('Form Query Filters', () => {
		it('should set up query filters for assignment history', () => {
			testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

			expect(frm.set_query).toHaveBeenCalledWith(
				'reference_doctype',
				'assignment_history',
				expect.any(Function)
			);

			// Test the query function
			const queryCall = frm.set_query.mock.calls.find(
				call => call[0] === 'reference_doctype' && call[1] === 'assignment_history'
			);
			expect(queryCall).toBeDefined();

			const queryFunction = queryCall[2];
			const result = queryFunction();

			expect(result).toEqual({
				filters: {
					name: ['in', ['Chapter', 'Team', 'Event', 'Volunteer Activity', 'Commission']]
				}
			});
		});
	});

	describe('Address and Contact Management', () => {
		it('should toggle display for address and contact fields', () => {
			testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

			expect(frm.toggle_display).toHaveBeenCalledWith(['address_html', 'contact_html'], true);
		});

		it('should render address and contact for saved records', () => {
			frm.doc.__islocal = 0;

			testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

			expect(global.frappe.contacts.render_address_and_contact).toHaveBeenCalledWith(frm);
		});

		it('should clear address and contact for new records', () => {
			frm.doc.__islocal = 1;

			testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

			expect(global.frappe.contacts.clear_address_and_contact).toHaveBeenCalledWith(frm);
		});
	});

	describe('Performance and Error Handling', () => {
		it('should not cause excessive server calls during refresh', () => {
			const initialCallCount = global.frappe.call.mock.calls.length;

			testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });

			const finalCallCount = global.frappe.call.mock.calls.length;
			const callsAdded = finalCallCount - initialCallCount;

			// Should not make more than 2-3 calls
			expect(callsAdded).toBeLessThanOrEqual(3);
		});

		it('should execute refresh handler without errors', () => {
			expect(() => {
				testFormEvent('Volunteer', 'refresh', frm, { Volunteer: volunteerHandlers });
			}).not.toThrow();
		});

		it('should execute member handler without errors', () => {
			expect(() => {
				testFormEvent('Volunteer', 'member', frm, { Volunteer: volunteerHandlers });
			}).not.toThrow();
		});
	});
});

// Export test utilities for reuse
module.exports = {
	testVolunteerHandler: (event, mockForm) => {
		return testFormEvent('Volunteer', event, mockForm, { Volunteer: volunteerHandlers });
	}
};
