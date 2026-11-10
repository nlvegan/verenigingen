/**
 * @fileoverview Server error text on the applicant-facing form must be escaped at
 * the HTML sink (issue #2276).
 *
 * Contract under test: an Error thrown by MembershipAPI carries PLAIN TEXT, and
 * the sinks that render it as HTML (the frappe.msgprint fallback in
 * handleSubmissionError, and ErrorHandler's notification / modal markup) escape
 * it once. Escaping in the feeder as well would double-escape, so each case
 * also checks the text an applicant reads is the original message.
 *
 * Drives the real shipped code. Only the framework edge is stubbed: $.ajax /
 * frappe.call (the network) and frappe.msgprint / $ (the DOM boundary, recorded
 * so the HTML a sink produced can be parsed by jsdom and inspected).
 *
 * jsdom note: sinks are checked by PARSING the produced HTML, never by
 * substring, because "no <img> element exists and the text reads back as the
 * message" is the property that matters.
 */

global.frappe = global.frappe || {};
global.frappe.provide = function provide(path) {
	let obj = global;
	for (const part of path.split('.')) {
		obj[part] = obj[part] || {};
		obj = obj[part];
	}
	return obj;
};

require('../../public/js/utils/operation-result-helpers.js');
require('../../public/js/membership_application.js');
require('../../public/js/components/error-handler.js');
// Production does not load error-handler.js on /apply_for_membership, so the
// submission-error tests run without it; the ErrorHandler tests use this reference.
const ErrorHandlerClass = window.ErrorHandler;
delete window.ErrorHandler;

const PAYLOAD = '<img src=x onerror=alert(1)>';
const READABLE = "Can't use R&D here";

/** Parse sink HTML the way a browser would. */
function parse(html) {
	const box = document.createElement('div');
	box.innerHTML = html;
	return box;
}

/** A MembershipAPI + the real handleSubmissionError, with no ErrorHandler loaded. */
function makeApp() {
	const app = Object.create(window.MembershipApplication.prototype);
	app._initializeServices();
	return app;
}

function captureMsgprint() {
	const seen = [];
	global.frappe.msgprint = jest.fn((opts) => seen.push(opts));
	return seen;
}

/** Make $.ajax answer with a failing HTTP response whose body is `body`. */
function ajaxFailsWith(body) {
	global.$.ajax = jest.fn((opts) => {
		opts.error({ responseText: JSON.stringify(body), status: 417, statusText: 'x' }, 'error', 'x');
	});
}

async function submitAndCollectMsgprint(app) {
	const seen = captureMsgprint();
	let thrown;
	try {
		await app.apiService.submitApplication({ first_name: 'A' });
	} catch (e) {
		thrown = e;
	}
	expect(thrown).toBeDefined();
	app.handleSubmissionError(thrown);
	expect(seen).toHaveLength(1);
	return seen[0].message;
}

beforeEach(() => {
	global.$ = Object.assign(
		jest.fn(() => ({ length: 0 })),
		{ ajax: jest.fn() }
	);
});

describe('submission error -> frappe.msgprint fallback', () => {
	test('top-level message (parsed.message branch): markup is inert', async () => {
		const app = makeApp();
		ajaxFailsWith({ message: PAYLOAD });
		const box = parse(await submitAndCollectMsgprint(app));
		expect(box.querySelector('img')).toBeNull();
		expect(box.textContent).toBe(PAYLOAD);
	});

	test('success-envelope branch (response.message.message) is inert and readable', async () => {
		for (const msg of [PAYLOAD, READABLE]) {
			const app = makeApp();
			global.$.ajax = jest.fn((opts) => opts.success({ message: { success: false, message: msg } }));
			const box = parse(await submitAndCollectMsgprint(app));
			expect(box.querySelector('img')).toBeNull();
			expect(box.textContent).toBe(msg);
		}
	});

	test('a plain message with & and an apostrophe reads back unchanged (no double escape)', async () => {
		const app = makeApp();
		ajaxFailsWith({ message: READABLE });
		expect(parse(await submitAndCollectMsgprint(app)).textContent).toBe(READABLE);
	});

	test('frappe.call exc branch reads back unchanged (no double escape)', async () => {
		const app = makeApp();
		const seen = captureMsgprint();
		global.frappe.call = jest.fn((opts) =>
			opts.callback({
				exc: 'Traceback',
				_server_messages: JSON.stringify([JSON.stringify({ message: READABLE })])
			})
		);
		let thrown;
		try {
			await app.apiService.call('x.y');
		} catch (e) {
			thrown = e;
		}
		app.handleSubmissionError(thrown);
		expect(parse(seen[0].message).textContent).toBe(READABLE);
	});

	const excBody = () => ({
		exc: 'Traceback',
		_server_messages: JSON.stringify([JSON.stringify({ message: READABLE })])
	});

	test('submitApplication xhr.responseJSON.exc branch reads back unchanged (no double escape)', async () => {
		const app = makeApp();
		global.$.ajax = jest.fn((opts) =>
			opts.error({ responseJSON: excBody(), responseText: JSON.stringify(excBody()), status: 417 }, 'error', 'x')
		);
		expect(parse(await submitAndCollectMsgprint(app)).textContent).toBe(READABLE);
	});

	test('call() error() r.responseJSON.exc branch reads back unchanged (no double escape)', async () => {
		const app = makeApp();
		global.frappe.call = jest.fn((opts) => opts.error({ responseJSON: excBody() }));
		const seen = captureMsgprint();
		let thrown;
		try {
			await app.apiService.call('x.y');
		} catch (e) {
			thrown = e;
		}
		app.handleSubmissionError(thrown);
		expect(parse(seen[0].message).textContent).toBe(READABLE);
	});

	test('frappe.call error() branch with r.message is inert', async () => {
		const app = makeApp();
		global.frappe.call = jest.fn((opts) => opts.error({ message: PAYLOAD }));
		const seen = captureMsgprint();
		let thrown;
		try {
			await app.apiService.call('x.y');
		} catch (e) {
			thrown = e;
		}
		app.handleSubmissionError(thrown);
		const box = parse(seen[0].message);
		expect(box.querySelector('img')).toBeNull();
		expect(box.textContent).toBe(PAYLOAD);
	});
});

describe('ErrorHandler HTML sinks', () => {
	/** $() recorder: html()/append() calls land in `sink`. */
	function installRecorder(sink) {
		global.$ = jest.fn(() => {
			// Chainable stub: html()/append() record their argument, every other jQuery call is a no-op.
			const api = new Proxy(
				{ length: 0 },
				{
					get: (target, prop) =>
						prop in target
							? target[prop]
							: (...args) => {
									if (prop === 'html' || prop === 'append') {
										sink.push(args[0]);
									}
									return api;
								}
				}
			);
			return api;
		});
	}

	function handler() {
		return Object.create(ErrorHandlerClass.prototype);
	}

	test.each([
		['markup', PAYLOAD],
		['plain', READABLE]
	])('notification title/message/action text (%s)', (_l, text) => {
		const sink = [];
		installRecorder(sink);
		handler()._renderNotification({
			id: 'n1',
			type: 'error',
			title: text,
			message: text,
			actions: [{ text, action: () => {} }]
		});
		const box = parse(sink.join(''));
		expect(box.querySelector('img')).toBeNull();
		expect(box.querySelector('strong').textContent).toBe(text);
		expect(box.querySelector('.small').textContent).toBe(text);
		expect(box.querySelector('button.btn-outline-primary').textContent).toBe(text);
	});

	test.each([
		['markup', PAYLOAD],
		['plain', READABLE]
	])('error modal title/message/details (%s)', (_l, text) => {
		const sink = [];
		installRecorder(sink);
		handler().showErrorModal({ title: text, message: text, details: text });
		const box = parse(sink.join(''));
		expect(box.querySelector('img')).toBeNull();
		expect(box.querySelector('h6').textContent).toBe(text);
		expect(box.querySelector('p').textContent).toBe(text);
		expect(box.querySelector('pre').textContent).toBe(text);
	});
});
