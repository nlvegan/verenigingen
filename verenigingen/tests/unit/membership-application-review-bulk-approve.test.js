/**
 * @fileoverview The review page's BULK approve buckets each approve_application response (#2560).
 * Bulk approve is a client loop over the same server call the single approve uses, so every
 * response already carries `invoice_failed` / `dues_schedule_failed` (#1774, #1930); the loop must
 * count each apart from a clean approval. The real page class runs in a vm context; only the
 * framework edge (frappe.call, msgprint, confirm) is stubbed.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const PAGE = path.join(
	__dirname,
	'../../verenigingen/page/membership_application_review/membership_application_review.js'
);

function loadPage(responses) {
	const shown = [];
	let pending;
	const sandbox = {
		frappe: {
			pages: { 'membership-application-review': {} },
			route_options: null,
			confirm: (_msg, yes) => {
				pending = yes();
			},
			call: async ({ args }) => responses[args.application_name],
			msgprint: (opts) => shown.push(opts),
			utils: { escape_html: (s) => String(s).replace(/</g, '&lt;') }
		},
		__: (s) => s,
		window: { location: { search: '' } },
		document: { addEventListener() {} },
		URL,
		URLSearchParams,
		$: () => ({ html() {}, val: () => '', on() {} })
	};
	vm.createContext(sandbox);
	vm.runInContext(`${fs.readFileSync(PAGE, 'utf8')}\n;this.__Cls = MembershipApplicationReview;`, sandbox);
	const page = new sandbox.__Cls({});
	page.applications = Object.keys(responses).map((name) => ({ name }));
	page.selected_application_names = () => Object.keys(responses);
	page.load_applications = () => {};
	page.load_statistics = () => {};
	return { page, shown, done: () => pending };
}

const ok = (message) => ({ message: { success: true, message } });

describe('bulk approve buckets', () => {
	test('an approval without a dues schedule is listed apart, not counted as a clean approval', async () => {
		const { page, shown, done } = loadPage({
			'APP-CLEAN': ok('fine'),
			'APP-NODUES': { message: { success: true, dues_schedule_failed: true, message: 'schedule missing' } }
		});
		page.bulk_approve();
		await done();
		const html = shown[0].message;
		expect(html).toContain('Approved: 1');
		expect(html).toContain('Approved, but the dues schedule could NOT be created: 1');
		expect(html).toContain('APP-NODUES: schedule missing');
		expect(html).not.toContain('APP-CLEAN:');
		expect(shown[0].indicator).toBe('orange');
	});

	test('both flags on one item: it is listed once, under the invoice bucket, with the dues note kept', async () => {
		const { page, shown, done } = loadPage({
			'APP-BOTH': {
				message: { success: true, invoice_failed: true, dues_schedule_failed: true, message: 'both' }
			}
		});
		page.bulk_approve();
		await done();
		const html = shown[0].message;
		expect(html).toContain('Approved: 0');
		expect(html.match(/APP-BOTH/g)).toHaveLength(1);
		expect(html).toContain('Approved, but the invoice could NOT be created: 1');
	});

	test('control: all clean approvals stay green with no failure sections', async () => {
		const { page, shown, done } = loadPage({ 'APP-A': ok('a'), 'APP-B': ok('b') });
		page.bulk_approve();
		await done();
		expect(shown[0].message).toContain('Approved: 2');
		expect(shown[0].message).not.toContain('could NOT');
		expect(shown[0].indicator).toBe('green');
	});

	test('control: a refused approval is still under Failed', async () => {
		const { page, shown, done } = loadPage({ 'APP-X': { message: { success: false, message: 'nope' } } });
		page.bulk_approve();
		await done();
		expect(shown[0].message).toContain('Failed: 1');
		expect(shown[0].message).toContain('APP-X: nope');
	});
});
