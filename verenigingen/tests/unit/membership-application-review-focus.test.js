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

function loadClass(listHtml) {
	const sandbox = {
		frappe: { pages: { 'membership-application-review': {} }, route_options: null },
		__: (s) => s,
		window: { location: { search: '?application=APP-1' } },
		URLSearchParams,
		$: () => ({ html: (h) => listHtml.push(h) })
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
});
