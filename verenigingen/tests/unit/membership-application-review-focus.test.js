/**
 * @fileoverview Focus-mode (?application=<name>) handling of the membership application
 * review page (#1963). The page file is a vm-style Frappe page script with no exports, so it
 * is evaluated in a vm context with frappe/$ stubbed; the class itself is the system under test.
 *
 * Verified here: "Clear filters" leaves focus mode, and a focused application that is not in
 * the listed set still renders a visible "Show all applications" link.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const PAGE = path.join(
	__dirname,
	'../../verenigingen/page/membership_application_review/membership_application_review.js'
);

function loadClass(listHtml, handlers = {}, win = null) {
	const sandbox = {
		frappe: { pages: { 'membership-application-review': {} }, route_options: null },
		__: (s) => s,
		window: win || { location: { search: '?application=APP-1' } },
		document: { addEventListener() {} },
		URL,
		URLSearchParams,
		$: () => ({
			html: (h) => listHtml.push(h),
			val: () => '',
			on: (event, selector, handler) => {
				handlers[`${event} ${selector}`] = handler;
			}
		})
	};
	vm.createContext(sandbox);
	vm.runInContext(`${fs.readFileSync(PAGE, 'utf8')}\n;this.__Cls = MembershipApplicationReview;`, sandbox);
	return sandbox.__Cls;
}

describe('membership application review focus mode', () => {
	let rendered;
	let page;

	beforeEach(() => {
		rendered = [];
		const Cls = loadClass(rendered);
		page = new Cls({});
	});

	test('constructor enters focus mode from ?application=', () => {
		expect(page.focus_application).toBe('APP-1');
	});

	test('clear_filters leaves focus mode and reloads the unfiltered list', () => {
		page.filters = { chapter: 'X', days_overdue: '3' };
		page.load_applications = jest.fn();
		page.clear_filters();
		expect(page.focus_application).toBeNull();
		expect(page.filters).toEqual({ chapter: null, days_overdue: null });
		expect(page.load_applications).toHaveBeenCalledTimes(1);
	});

	test('focused application missing from the list still offers Show all applications', () => {
		page.applications = [];
		page.render_applications();
		expect(rendered[0]).toContain('show-all-applications');
		expect(rendered[0]).toContain('Show all applications');
	});

	test('control: empty list without focus mode has no Show-all link', () => {
		page.focus_application = null;
		page.applications = [];
		page.render_applications();
		expect(rendered[0]).not.toContain('show-all-applications');
	});

	describe('event wiring', () => {
		let handlers;
		let win;
		let wired;

		beforeEach(() => {
			handlers = {};
			win = {
				location: {
					search: '?application=APP-1&x=1',
					href: 'http://h/app/membership-application-review?application=APP-1&x=1#top'
				},
				history: { state: { s: 1 }, replaceState: jest.fn() }
			};
			const Cls = loadClass(rendered, handlers, win);
			wired = new Cls({});
			wired.wrapper = {};
			wired.load_applications = jest.fn();
			wired.setup_event_handlers();
		});

		test('Clear filters button leaves focus mode and drops ?application= from the URL', () => {
			expect(wired.focus_application).toBe('APP-1');
			handlers['click #btn-clear-filters']();
			expect(wired.focus_application).toBeNull();
			expect(wired.load_applications).toHaveBeenCalled();
			const url = win.history.replaceState.mock.calls[0][2];
			expect(url).toBe('/app/membership-application-review?x=1#top');
		});

		test('Show all link leaves focus mode and drops ?application= from the URL', () => {
			handlers['click .show-all-applications']({ preventDefault() {} });
			expect(wired.focus_application).toBeNull();
			expect(win.history.replaceState.mock.calls[0][2]).not.toContain('application=');
		});

		test('exit_focus_mode tolerates a missing window.history', () => {
			delete win.history;
			wired.exit_focus_mode();
			expect(wired.focus_application).toBeNull();
		});
	});
});
