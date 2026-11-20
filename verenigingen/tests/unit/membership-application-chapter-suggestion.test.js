/**
 * @fileoverview Chapter suggestion on the public /apply_for_membership form (#3032).
 *
 * Business context: the form is a GUEST page. Three handlers used to listen on
 * #postal_code and none could show a suggestion to a guest: one read
 * `data.suggested_chapters` (the endpoint answers `data.suggestions`) and called a
 * method that does not exist; one called `suggest_chapters_for_member`, which is
 * @standard_api and answers a Guest 403; one read `suggested_chapters` from
 * `validate_postal_code`. The survivor calls the guest-allowed
 * `suggest_chapters_for_postal_code` and renders into the template's own
 * #suggested-chapter-name / #accept-suggestion.
 *
 * Response bodies below were measured on a test site through the real WSGI app as
 * Guest: "1015CJ" -> success with data.suggestions; "1015 CJ" -> success:false
 * "Invalid postal code format" (so the client must strip the space itself).
 */

require('../../public/js/membership_application.js');

global.frappe = global.frappe || {};
global.frappe.provide = function provide(path) {
	let obj = global;
	for (const part of path.split('.')) {
		obj[part] = obj[part] || {};
		obj = obj[part];
	}
	return obj;
};

// Production loads the real helper on this page (web_include_js); a stub here
// once let the refusal tests pass only because unwrapOperationResult threw.
require('../../public/js/utils/operation-result-helpers.js');

const proto = window.MembershipApplication.prototype;
const METHOD = 'verenigingen.api.membership_application.suggest_chapters_for_postal_code';

const MEASURED_OK = {
	success: true,
	data: {
		postal_code: '1015CJ',
		suggestions: [
			{
				name: 'Test Amsterdam Chapter',
				chapter_name: 'Test Amsterdam Chapter',
				region: 'test-region',
				match_type: 'postal_range',
				relevance_score: 100,
				postal_code_ranges: '1000-1099'
			},
			{ name: 'Test Chapter Alpha', chapter_name: 'Test Chapter Alpha', relevance_score: 100 }
		],
		total_suggestions: 2
	},
	meta: {}
};

const MEASURED_FORMAT_REFUSAL = {
	success: false,
	error: { message: 'Invalid postal code format. Expected format: 1234AB', errors: ['invalid_postal_code_format'] },
	meta: {}
};

/**
 * The shared jest setup stubs `$`, and jQuery is not a dependency of this app, so
 * this is a minimal jQuery-shaped wrapper over the real jsdom DOM: just what the
 * suggestion handler uses. Delegated handlers (`$(document).on(ev, sel, fn)`)
 * fire when an event bubbles to the document from a matching target.
 */
function makeDomShim() {
	const delegated = [];
	const wrap = (nodes) => ({
		length: nodes.length,
		text(value) {
			if (value === undefined) {
				return nodes[0].textContent;
			}
			nodes.forEach((n) => (n.textContent = value));
			return this;
		},
		val(value) {
			if (value === undefined) {
				return nodes[0].value;
			}
			nodes.forEach((n) => (n.value = value));
			return this;
		},
		show() {
			nodes.forEach((n) => (n.style.display = ''));
			return this;
		},
		hide() {
			nodes.forEach((n) => (n.style.display = 'none'));
			return this;
		},
		css(prop) {
			return getComputedStyle(nodes[0])[prop];
		},
		on(events, selectorOrFn, maybeFn) {
			const selector = typeof selectorOrFn === 'string' ? selectorOrFn : null;
			const fn = selector ? maybeFn : selectorOrFn;
			events.split(' ').forEach((ev) => {
				if (selector) {
					delegated.push({ ev, selector, fn });
				} else {
					nodes.forEach((n) => n.addEventListener(ev, fn));
				}
			});
			return this;
		},
		off() {
			// Direct handlers are cleared by replacing the node; enough for these tests.
			nodes.forEach((n, i) => {
				const clone = n.cloneNode(true);
				n.replaceWith(clone);
				nodes[i] = clone;
			});
			return this;
		},
		trigger(ev) {
			nodes.forEach((n) => n.dispatchEvent(new Event(ev, { bubbles: true })));
			return this;
		}
	});
	const $ = (arg) => {
		if (arg === document) {
			const doc = wrap([document]);
			doc.on = (events, selector, fn) => {
				events.split(' ').forEach((ev) => delegated.push({ ev, selector, fn }));
				return doc;
			};
			return doc;
		}
		return wrap(Array.from(document.querySelectorAll(arg)));
	};
	['blur', 'change', 'click'].forEach((ev) =>
		document.addEventListener(
			ev,
			(e) =>
				delegated
					.filter((d) => d.ev === ev && e.target.matches && e.target.matches(d.selector))
					.forEach((d) => d.fn(e)),
			true
		)
	);
	return $;
}

/** The elements apply_for_membership.html actually renders for this feature. */
function renderTemplateMarkup() {
	document.body.innerHTML = `
		<input id="postal_code" value="">
		<select id="selected_chapter">
			<option value="">Select a chapter...</option>
			<option value="Test Amsterdam Chapter">Test Amsterdam Chapter</option>
		</select>
		<div id="chapter-selection">
			<div id="suggested-chapter" style="display: none;">
				<strong id="suggested-chapter-name"></strong>
				<button type="button" id="accept-suggestion">Join this chapter</button>
			</div>
		</div>`;
}

/** Make frappe.call answer with `message`; return the recorded calls. */
function answerWith(message) {
	global.frappe.call = jest.fn((opts) => {
		if (message instanceof Error) {
			opts.error && opts.error(message);
		} else {
			opts.callback && opts.callback({ message });
		}
	});
	return global.frappe.call;
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('chapter suggestion from the postal code', () => {
	let realDollar;

	beforeEach(() => {
		realDollar = global.$;
		global.$ = makeDomShim();
		renderTemplateMarkup();
		global.frappe.msgprint = jest.fn();
	});

	afterEach(() => {
		global.$ = realDollar;
		document.body.innerHTML = '';
	});

	it('renders the first suggestion into the template elements', async () => {
		const call = answerWith(MEASURED_OK);

		await proto.suggestChapterFromPostalCode.call(Object.create(proto), '1015CJ');

		expect(call).toHaveBeenCalledTimes(1);
		expect(call.mock.calls[0][0].method).toBe(METHOD);
		expect(global.$('#suggested-chapter-name').text()).toBe(MEASURED_OK.data.suggestions[0].chapter_name);
		expect(global.$('#suggested-chapter').css('display')).not.toBe('none');
	});

	it('normalises a spaced / lower-case postal code before calling the server', async () => {
		const call = answerWith(MEASURED_OK);

		await proto.suggestChapterFromPostalCode.call(Object.create(proto), ' 1015 cj ');

		expect(call.mock.calls[0][0].args).toEqual({ postal_code: '1015CJ' });
	});

	it('accepting the suggestion selects that chapter and hides the box', async () => {
		answerWith(MEASURED_OK);
		await proto.suggestChapterFromPostalCode.call(Object.create(proto), '1015CJ');

		global.$('#accept-suggestion').trigger('click');

		expect(global.$('#selected_chapter').val()).toBe('Test Amsterdam Chapter');
		expect(global.$('#suggested-chapter').css('display')).toBe('none');
	});

	it('hides a previously shown suggestion when the server refuses the code', async () => {
		global.$('#suggested-chapter').show();
		answerWith(MEASURED_FORMAT_REFUSAL);

		await proto.suggestChapterFromPostalCode.call(Object.create(proto), '1015CJ');

		expect(global.$('#suggested-chapter').css('display')).toBe('none');
		expect(global.frappe.msgprint).not.toHaveBeenCalled();
	});

	it('hides the box when there are no suggestions', async () => {
		global.$('#suggested-chapter').show();
		answerWith({ success: true, data: { postal_code: '9999ZZ', suggestions: [], total_suggestions: 0 }, meta: {} });

		await proto.suggestChapterFromPostalCode.call(Object.create(proto), '9999ZZ');

		expect(global.$('#suggested-chapter').css('display')).toBe('none');
	});

	it('hides the box and shows no dialog when the call itself fails', async () => {
		global.$('#suggested-chapter').show();
		const call = answerWith(new Error('403'));

		await proto.suggestChapterFromPostalCode.call(Object.create(proto), '1015CJ');

		// frappe.call raises its own error dialog unless told to stay silent
		expect(call.mock.calls[0][0].silent).toBe(true);
		expect(global.$('#suggested-chapter').css('display')).toBe('none');
		expect(global.frappe.msgprint).not.toHaveBeenCalled();
	});

	it('does not call the server for a code too short to match', async () => {
		const call = answerWith(MEASURED_OK);

		await proto.suggestChapterFromPostalCode.call(Object.create(proto), '10');

		expect(call).not.toHaveBeenCalled();
	});

	it('exactly ONE handler reacts to #postal_code, through the real bindings', async () => {
		const call = answerWith(MEASURED_OK);
		const page = Object.create(proto);
		page.validateEmail = jest.fn();
		page.validateIBAN = jest.fn();
		proto.bindCustomValidationEvents.call(page);
		proto.bindChapterSuggestion.call(page);

		global.$('#postal_code').val('1015 CJ').trigger('blur');
		await flush();

		expect(call).toHaveBeenCalledTimes(1);
		expect(call.mock.calls[0][0].args).toEqual({ postal_code: '1015CJ' });
		expect(global.$('#suggested-chapter-name').text()).toBe('Test Amsterdam Chapter');
	});
});
