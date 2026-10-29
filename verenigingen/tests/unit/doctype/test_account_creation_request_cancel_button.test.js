/**
 * @fileoverview Account Creation Request: "Cancel Request" button gating (#1635)
 *
 * The condition was `frm.doc.status in ['Requested', 'Queued', 'Processing']`.
 * JS `in` tests array INDICES ('0','1','2','length'), never values, so the
 * button never rendered. The server's `cancel_request` refuses only
 * `Completed`; `Failed` is cancellable (and that is the status an old request
 * is stuck in, see #1614). `Cancelled` is also "accepted" by the server but
 * re-cancelling is meaningless, so the button is not offered there.
 *
 * These tests drive the real controller's `refresh` handler.
 */

/* global describe, it, expect, beforeAll, beforeEach */

const { setupTestMocks, cleanupTestMocks, createMockForm } = require('../../setup/frappe-mocks');
const { loadFrappeController } = require('../../setup/controller-loader');
const { getControllerPath } = require('../../setup/test-paths');

setupTestMocks();

describe('Account Creation Request: Cancel Request button (#1635)', () => {
	let handlers;

	beforeAll(() => {
		const all = loadFrappeController(getControllerPath('account_creation_request'));
		handlers = all['Account Creation Request'];
		expect(handlers.refresh).toBeDefined();
	});

	beforeEach(() => {
		cleanupTestMocks();
	});

	function cancelButtonRenderedFor(status) {
		const frm = createMockForm({
			doc: { name: 'ACR-0001', doctype: 'Account Creation Request', status }
		});
		frm.add_custom_button = jest.fn(() => ({ addClass: jest.fn() }));
		frm.dashboard = {
			clear_headline: jest.fn(),
			set_headline: jest.fn(),
			set_headline_alert: jest.fn(),
			add_comment: jest.fn()
		};
		frm.is_dirty = jest.fn(() => false);
		handlers.refresh(frm);
		return frm.add_custom_button.mock.calls.some((call) => call[0] === 'Cancel Request');
	}

	['Requested', 'Queued', 'Processing', 'Failed'].forEach((status) => {
		it(`renders Cancel Request for ${status}`, () => {
			expect(cancelButtonRenderedFor(status)).toBe(true);
		});
	});

	['Completed', 'Cancelled'].forEach((status) => {
		it(`does not render Cancel Request for ${status}`, () => {
			expect(cancelButtonRenderedFor(status)).toBe(false);
		});
	});
});
