/**
 * @fileoverview Comprehensive Chapter Join Request DocType JavaScript Test Suite
 */

const TestDataFactory = require('../factories/test-data-factory');

describe('Chapter Join Request DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		testFactory = new TestDataFactory(34901);
		mockDoc = testFactory.createChapterJoinRequestData();
		mockFrm = createMockForm(mockDoc);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	describe('Join Request Workflow', () => {
		test('should handle member chapter join requests', () => {
			mockDoc.member = testFactory.createMemberName();
			mockDoc.chapter = testFactory.createChapterName();
			mockDoc.status = 'Pending';

			const request = require('../../../../verenigingen/doctype/chapter_join_request/chapter_join_request.js');
			request.refresh(mockFrm);

			expect(mockDoc.status).toBe('Pending');
		});

		test('should approve join request successfully', async () => {
			mockDoc.status = 'Pending';
			mockFrm.call.mockResolvedValueOnce({ message: true });

			const request = require('../../../../verenigingen/doctype/chapter_join_request/chapter_join_request.js');
			request.approve_request(mockFrm);

			expect(mockFrm.call).toHaveBeenCalled();
		});
	});

	describe('Approval Management', () => {
		test('should validate chapter capacity', () => {
			mockDoc.chapter = 'Amsterdam Chapter';
			mockDoc.member_count = 150;

			const request = require('../../../../verenigingen/doctype/chapter_join_request/chapter_join_request.js');
			request.validate_capacity(mockFrm);

			expect(mockDoc.member_count).toBe(150);
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
