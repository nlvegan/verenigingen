/**
 * @fileoverview Account Creation Request: retry/queue buttons with a falsy r.message (#1476)
 *
 * A backend method that returns None reaches the callback as `r.message === undefined`.
 * The failure branch used to read `r.message.error` and threw a TypeError instead of
 * showing the 'Unknown error' fallback (same defect as donor.js, #1454).
 * These tests drive the real controller's buttons; frappe.call is stubbed to
 * invoke the callback with `{}` (no message key), the shape frappe delivers.
 */

/* global describe, it, expect, beforeAll, beforeEach */

const { setupTestMocks, cleanupTestMocks, createMockForm } = require('../../setup/frappe-mocks');
const { loadFrappeController } = require('../../setup/controller-loader');
const { getControllerPath } = require('../../setup/test-paths');

setupTestMocks();

describe('Account Creation Request: falsy r.message in retry/queue callbacks (#1476)', () => {
	let handlers;

	beforeAll(() => {
		handlers = loadFrappeController(getControllerPath('account_creation_request'))['Account Creation Request'];
	});

	beforeEach(() => {
		cleanupTestMocks();
	});

	function clickButton(label, status, callResponse) {
		const frm = createMockForm({
			doc: { name: 'ACR-0001', doctype: 'Account Creation Request', status }
		});
		const buttons = {};
		frm.add_custom_button = jest.fn((name, fn) => {
			buttons[name] = fn;
			return { addClass: jest.fn() };
		});
		frm.dashboard = {
			clear_headline: jest.fn(),
			set_headline: jest.fn(),
			set_headline_alert: jest.fn(),
			add_comment: jest.fn()
		};
		frm.is_dirty = jest.fn(() => false);
		global.frappe.confirm = jest.fn((msg, onYes) => onYes());
		global.frappe.call = jest.fn(({ callback }) => callback(callResponse));
		global.frappe.msgprint = jest.fn();
		handlers.refresh(frm);
		expect(buttons[label]).toBeDefined();
		buttons[label]();
	}

	[
		['retry', 'Retry Processing'],
		['queue', 'Queue for Processing']
	].forEach(([name, label]) => {
		it(`${name}: shows 'Unknown error' instead of throwing when r.message is undefined`, () => {
			// status chosen per button below
			const status = name === 'retry' ? 'Failed' : 'Requested';
			expect(() => clickButton(label, status, {})).not.toThrow();
			expect(global.frappe.msgprint).toHaveBeenCalledWith(expect.stringContaining('Unknown error'));
		});

		it(`${name}: still shows the backend error when r.message carries one (control)`, () => {
			const status = name === 'retry' ? 'Failed' : 'Requested';
			clickButton(label, status, { message: { success: false, error: 'boom-from-backend' } });
			expect(global.frappe.msgprint).toHaveBeenCalledWith(expect.stringContaining('boom-from-backend'));
		});
	});
});
