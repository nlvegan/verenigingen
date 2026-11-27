/* eslint-disable no-eval -- drives the real inline page script extracted from the template. */
/**
 * @fileoverview Issue #3097: dues-coverage-manager.html read the brand CSS from
 * `r.message.data.css`, but get_brand_css_inline returns `{success, css, timestamp}` with
 * `css` at the top level (pinned server-side by
 * brand_settings/test_brand_settings_endpoints.py::test_get_brand_css_inline_success_envelope),
 * so the page never applied the brand CSS. This drives the REAL page script with the
 * endpoint's real response shape.
 */
const fs = require('fs');
const path = require('path');

const REL = 'verenigingen/www/dues-coverage-manager.html';
const METHOD = 'verenigingen.verenigingen.doctype.brand_settings.brand_settings.get_brand_css_inline';
const BRAND = ':root{--brand-primary:#123456}';

function brandScript() {
	const html = fs.readFileSync(path.join(__dirname, '../../..', REL), 'utf8');
	const blocks = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\b[^>]*>/gi)].map((m) => m[1]);
	const block = blocks.find((b) => b.includes('get_brand_css_inline'));
	if (!block) throw new Error('brand CSS script not found');
	return block;
}

/** Run the page script; the endpoint answers with `message`. Returns the injected <style> texts. */
function runWith(message) {
	document.head.innerHTML = '';
	window.frappe = {
		ready: (fn) => fn(),
		call: jest.fn((opts) => opts.callback({ message }))
	};
	window.eval(brandScript());
	expect(window.frappe.call.mock.calls[0][0].method).toBe(METHOD);
	return [...document.head.querySelectorAll('style')].map((s) => s.innerHTML);
}

describe('dues-coverage-manager brand CSS (#3097)', () => {
	test('applies the css the endpoint returns at the top level', () => {
		// Exact shape get_brand_css_inline returns.
		const styles = runWith({ success: true, css: BRAND, timestamp: '2026-11-23 10:00:00' });
		expect(styles).toEqual([BRAND]);
	});

	test('control: a failed response injects nothing', () => {
		expect(runWith({ success: false, error: 'boom' })).toEqual([]);
	});
});
