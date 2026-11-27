/**
 * @fileoverview A failed Frappe call must not put the raw Python traceback (`exc`) in front of
 * the user (issue #2249). Drives the REAL shipped code: APIService, ChapterAPI, and the two
 * error formatters of templates/pages/mollie_payment_processing.html (pulled out of the page's
 * inline script by name). Only the framework edge (frappe.call / frappe.upload) is stubbed.
 *
 * The bodies below are shaped like a real Frappe 417/500 response: `exc` is the traceback as a
 * string, `exception` the last line, `_server_messages` what frappe.throw showed.
 */
const fs = require('fs');
const path = require('path');

global.frappe = global.frappe || {};
global.__ = (s) => s;
global.DOMParser = window.DOMParser;
global.frappe.provide = function provide(p) {
	let obj = global;
	for (const part of p.split('.')) {
		obj[part] = obj[part] || {};
		obj = obj[part];
	}
	return obj;
};
require('../../public/js/utils/operation-result-helpers.js');
require('../../public/js/services/api-service.js');

const TRACEBACK =
	'Traceback (most recent call last):\n  File "apps/frappe/frappe/app.py", line 1, in application\n' +
	'frappe.exceptions.ValidationError: Member is blocked\n';
const READABLE = 'Member is blocked';

const failureBody = (extra = {}) => ({
	exc: TRACEBACK,
	exc_type: 'ValidationError',
	exception: 'frappe.exceptions.ValidationError: Member is blocked',
	_server_messages: JSON.stringify([JSON.stringify({ message: READABLE })]),
	...extra
});

/** Pull `function <name>(...) {...}` out of the page's inline script and compile it. */
function pageFunction(name) {
	const html = fs.readFileSync(path.join(__dirname, '../../templates/pages/mollie_payment_processing.html'), 'utf8');
	const start = html.indexOf(`function ${name}(`);
	if (start < 0) throw new Error(`${name} not found in the page`);
	let depth = 0;
	const i = html.indexOf('{', start);
	for (let j = i; j < html.length; j++) {
		if (html[j] === '{') depth++;
		if (html[j] === '}' && --depth === 0) {
			// eslint-disable-next-line no-new-func
			return new Function(`${html.slice(start, j + 1)}; return ${name};`)();
		}
	}
	throw new Error('unbalanced');
}

describe('APIService', () => {
	const run = (body) => {
		global.frappe.call = jest.fn((opts) => opts.callback(body));
		const api = new window.APIService({ retryCount: 0 });
		return api.call('some.method');
	};

	test('rejects with the readable server message, not the traceback', async () => {
		const error = await run(failureBody()).catch((e) => e);
		expect(error.message).toBe(READABLE);
		expect(error.message).not.toMatch(/Traceback/);
	});

	test('a body with only a traceback gets a generic message, never the traceback', async () => {
		const error = await run({ exc: TRACEBACK }).catch((e) => e);
		expect(error).toBeInstanceOf(Error);
		expect(error.message).not.toMatch(/Traceback/);
		expect(error.message.trim()).not.toBe('');
	});

	test('control: a successful response still resolves', async () => {
		await expect(run({ message: { ok: 1 } })).resolves.toEqual({ ok: 1 });
	});
});

describe('ChapterAPI', () => {
	let ChapterAPI;
	beforeAll(async () => {
		global.frappe.msgprint = jest.fn();
		({ ChapterAPI } = await import('../../verenigingen/doctype/chapter/utils/ChapterAPI.js'));
	});

	test('_makeCall rejects with the readable message, not the traceback', async () => {
		global.frappe.call = jest.fn(async () => failureBody());
		const api = new ChapterAPI();
		const error = await api._makeCall('some.method', {}, { retry: false, showError: false }).catch((e) => e);
		expect(error.message).not.toMatch(/Traceback/);
		expect(error.message).toBe(READABLE);
	});

	test('uploadFile rejects with the readable message, not the traceback', async () => {
		global.frappe.upload = { make: (opts) => opts.callback(failureBody()) };
		const api = new ChapterAPI();
		const error = await api.uploadFile(new File(['x'], 'x.txt')).catch((e) => e);
		expect(error.message).not.toMatch(/Traceback/);
		expect(error.message).toBe(READABLE);
	});

	test('control: the readable message is still classified as an expected ValidationError', () => {
		// handleError/shouldLogError key off the exception CLASS; the readable text no longer
		// carries it, so it must travel on the error itself.
		const api = new ChapterAPI();
		const error = Object.assign(new Error(READABLE), { excType: 'ValidationError' });
		expect(api.shouldLogError(error)).toBe(false);
		expect(api.shouldLogError(new Error('boom'))).toBe(true);
	});

	test('a real failure through _makeCall is classified as expected (not logged to the server)', async () => {
		global.frappe.call = jest.fn(async () => failureBody());
		const api = new ChapterAPI();
		const error = await api._makeCall('some.method', {}, { retry: false, showError: false }).catch((e) => e);
		expect(api.shouldLogError(error)).toBe(false);
	});
});

describe('mollie_payment_processing.html', () => {
	test('formatBulkProcessingError shows the server message, not the traceback', () => {
		const text = pageFunction('formatBulkProcessingError')(failureBody());
		expect(text).toContain(READABLE);
		expect(text).not.toMatch(/Traceback|File "/);
	});

	test('formatBulkProcessingError with only a traceback shows no traceback', () => {
		const text = pageFunction('formatBulkProcessingError')({ exc: TRACEBACK });
		expect(text).not.toMatch(/Traceback|File "/);
	});

	test('formatBulkHttpFailure (the real HTTP 500 path) shows no traceback but keeps the status', () => {
		const text = pageFunction('formatBulkHttpFailure')(500, JSON.stringify(failureBody()));
		expect(text).toContain('500');
		expect(text).toContain(READABLE);
		expect(text).not.toMatch(/Traceback|File "/);
	});

	test('control: a non-JSON error body (a proxy HTML page) is kept as text', () => {
		const text = pageFunction('formatBulkHttpFailure')(502, 'Bad Gateway');
		expect(text).toContain('Bad Gateway');
	});
});
