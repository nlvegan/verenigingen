/* eslint-disable no-new-func -- the shipped page script is plain browser JS inside a Jinja template; evaluating it is the only way to drive the real code. */
/**
 * @fileoverview dues-invoice-manager "Generation Failed" must show BOTH the server's
 * message and the per-member error list (issue #3230).
 *
 * The failure branch of generateMissingInvoices used `msg || 'Failed...' + errorList`,
 * where `+` binds tighter than `||`, so a server message made the list vanish and staff
 * never saw which members failed. This drives the REAL page script, extracted from the
 * template, through a stubbed frappe.call whose callback receives a failure payload.
 */

const fs = require('fs');
const path = require('path');

const PAGE = path.join(__dirname, '../../www/dues-invoice-manager.html');
const FALLBACK = 'Failed to queue invoice generation.';

function loadPage() {
	const blocks = [...fs.readFileSync(PAGE, 'utf8').matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\b[^>]*>/gi)].map(
		(m) => m[1]
	);
	const block = blocks.find((b) => b.includes('function generateMissingInvoices'));
	if (!block) throw new Error('page script not found');
	const script = block.replace(/\{\{[^}]*\}\}/g, "''").replace(/\{%[^%]*%\}/g, '');
	const factory = new Function(
		'frappe',
		'confirm',
		`${script}\n;return { run: generateMissingInvoices, allow: () => { workflowConfig = { can_generate_invoices: true }; } };`
	);
	return factory;
}

/** Run the failure branch with `payload`; returns the rendered results panel. */
function renderFailure(payload) {
	window.HTMLElement.prototype.scrollIntoView = () => {};
	document.body.innerHTML =
		'<div id="generation-spinner" class="hidden"></div><div id="results-panel" class="hidden"></div><div id="results-content"></div>';
	const frappe = { call: (opts) => opts.callback({ message: payload }) };
	const page = loadPage()(frappe, () => true);
	page.allow();
	page.run();
	const panel = document.getElementById('results-content');
	return { text: panel.textContent, items: [...panel.querySelectorAll('li')].map((li) => li.textContent) };
}

describe('dues-invoice-manager generateMissingInvoices failure (#3230)', () => {
	test('server message AND the per-member error list are both shown', () => {
		const out = renderFailure({
			success: false,
			message: 'Invoice generation failed for 2 members',
			errors: ['member-A: no dues schedule', 'member-B: no mandate']
		});
		expect(out.text).toContain('Generation Failed');
		expect(out.text).toContain('Invoice generation failed for 2 members');
		expect(out.items).toEqual(['member-A: no dues schedule', 'member-B: no mandate']);
	});

	test('no server message: fallback text plus the error list (unchanged behaviour)', () => {
		const out = renderFailure({ success: false, errors: ['member-C: boom'] });
		expect(out.text).toContain(FALLBACK);
		expect(out.items).toEqual(['member-C: boom']);
	});

	test('control: server message with no errors shows the message and no list', () => {
		const out = renderFailure({ success: false, message: 'Nothing to do' });
		expect(out.text).toContain('Nothing to do');
		expect(out.text).not.toContain(FALLBACK);
		expect(out.items).toEqual([]);
	});

	test('control: only the first five errors are listed', () => {
		const errors = ['e1', 'e2', 'e3', 'e4', 'e5', 'e6', 'e7'];
		const out = renderFailure({ success: false, message: 'Many failures', errors });
		expect(out.items).toEqual(errors.slice(0, 5));
	});
});
