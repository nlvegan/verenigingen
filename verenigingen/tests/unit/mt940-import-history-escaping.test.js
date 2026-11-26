/**
 * @fileoverview displayMollieHistory (mt940_import page) must escape every value it
 * puts into innerHTML (issue #3307).
 *
 * `descriptive_name` is built server-side from the Bank Account name (whose account_name is
 * free text), so markup in it reaches the history table. The REAL shipped function is
 * extracted from the template and run against a jsdom table; the produced DOM is parsed,
 * and no element the payload carries may exist.
 */

const fs = require('fs');
const path = require('path');

const TEMPLATE = path.join(__dirname, '../../templates/pages/mt940_import.html');
const PAYLOAD = '"\'><img src=x onerror=alert(1)>';

function extractFunction(source, name) {
	const start = source.indexOf(`function ${name}(`);
	if (start < 0) throw new Error(`${name} not found in the template`);
	const open = source.indexOf('{', start);
	let depth = 0;
	for (let i = open; i < source.length; i++) {
		if (source[i] === '{') depth++;
		else if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
	}
	throw new Error(`unbalanced braces in ${name}`);
}

function loadHistoryRenderer() {
	const source = fs.readFileSync(TEMPLATE, 'utf8');
	const helper = extractFunction(source, 'escapeHtml');
	const renderer = extractFunction(source, 'displayMollieHistory');
	// eslint-disable-next-line no-new-func
	return new Function('document', `${helper}\n${renderer}\nreturn displayMollieHistory;`)(document);
}

function render(imports) {
	document.body.innerHTML =
		'<div id="mollie-history-section" style="display:none"><table><tbody id="mollie-history-body"></tbody></table></div>';
	loadHistoryRenderer()(imports);
	return document.getElementById('mollie-history-body');
}

const tainted = (overrides) => ({
	name: 'MT940-IMP-0001',
	descriptive_name: 'Bank - 01-01-2026',
	import_status: 'Completed',
	mollie_from_date: '2026-01-01',
	mollie_to_date: '2026-01-31',
	transactions_created: 3,
	transactions_skipped: 1,
	...overrides
});

describe('displayMollieHistory escaping (#3307)', () => {
	test('control: a benign row renders its name, status and link', () => {
		const body = render([tainted()]);
		expect(body.textContent).toContain('Bank - 01-01-2026');
		expect(body.querySelector('span.label-success').textContent).toBe('Completed');
		expect(body.querySelector('a').getAttribute('href')).toBe('/app/mt940-import/MT940-IMP-0001');
	});

	test.each([
		'descriptive_name',
		'import_status',
		'mollie_from_date',
		'mollie_to_date',
		'transactions_created',
		'transactions_skipped'
	])('markup in %s is rendered as text, not as elements', (field) => {
		const body = render([tainted({ [field]: PAYLOAD })]);
		expect(body.querySelector('img')).toBeNull();
		expect(body.innerHTML).not.toMatch(/<img/i);
		expect(body.textContent).toContain(PAYLOAD);
	});

	test('the name falls back to imp.name, escaped, when there is no descriptive_name', () => {
		const body = render([tainted({ descriptive_name: '', name: PAYLOAD })]);
		expect(body.querySelector('img')).toBeNull();
		expect(body.textContent).toContain(PAYLOAD);
	});

	test('a name cannot break out of the href attribute', () => {
		const body = render([tainted({ name: PAYLOAD })]);
		const link = body.querySelector('a');
		expect(body.querySelector('img')).toBeNull();
		expect(link.hasAttribute('onerror')).toBe(false);
		expect(link.getAttribute('href')).toBe(`/app/mt940-import/${encodeURIComponent(PAYLOAD)}`);
	});
});
