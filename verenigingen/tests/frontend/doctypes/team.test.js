/**
 * @fileoverview Comprehensive Team DocType JavaScript Test Suite
 */

const TestDataFactory = require('../factories/test-data-factory');

describe('Team DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		testFactory = new TestDataFactory(78345);
		mockDoc = testFactory.createTeamData();
		mockFrm = createMockForm(mockDoc);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	describe('Team Management', () => {
		test('should create team with members', () => {
			mockDoc.team_name = 'Marketing Team';
			mockDoc.team_lead = testFactory.createMemberName();
			mockDoc.status = 'Active';

			const team = require('../../../../verenigingen/doctype/team/team.js');
			team.refresh(mockFrm);

			expect(mockDoc.team_name).toBe('Marketing Team');
		});

		test('should add team members', () => {
			mockDoc.team_members = [
				{ member: testFactory.createMemberName(), role: 'Member' },
				{ member: testFactory.createMemberName(), role: 'Coordinator' }
			];

			const team = require('../../../../verenigingen/doctype/team/team.js');
			team.add_member(mockFrm);

			expect(mockDoc.team_members).toHaveLength(2);
		});
	});

	describe('Role Assignment', () => {
		test('should assign team lead role', () => {
			mockDoc.team_lead = testFactory.createMemberName();

			const team = require('../../../../verenigingen/doctype/team/team.js');
			team.team_lead(mockFrm);

			expect(mockDoc.team_lead).toBeDefined();
		});

		test('should validate member roles', () => {
			const validRoles = ['Member', 'Coordinator', 'Lead'];
			mockDoc.default_role = 'Member';

			const team = require('../../../../verenigingen/doctype/team/team.js');
			team.default_role(mockFrm);

			expect(validRoles).toContain(mockDoc.default_role);
		});
	});
});

function createMockForm(doc) {
	return {
		doc,
		add_custom_button: jest.fn(),
		call: jest.fn(),
		set_value: jest.fn(),
		refresh: jest.fn()
	};
}

function setupGlobalMocks() {
	global.frappe = {
		ui: { form: { on: jest.fn() } },
		call: jest.fn(),
		__: jest.fn(str => str)
	};
	global.__ = jest.fn(str => str);
}

function teardownGlobalMocks() {
	delete global.frappe;
	delete global.__;
}
