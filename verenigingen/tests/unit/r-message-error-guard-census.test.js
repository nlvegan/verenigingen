/* eslint-env jest */
/**
 * @fileoverview Census guard: `r.message.error` must not be read unguarded (#1476)
 *
 * `frappe.call` hands the callback `r.message === undefined` whenever the backend
 * method returns None (and for some error responses). `if (r.message && r.message.success)
 * {...} else { ... r.message.error ... }` therefore throws
 * "TypeError: Cannot read properties of undefined (reading 'error')" in the else
 * branch, instead of showing the intended 'Unknown error' fallback (donor.js, #1454).
 *
 * This walks the AST of every client script and reports each `r.message.error` read
 * that is not dominated by a test that implies `r.message` is truthy:
 * `r.message ? ..`, `r.message && ..`, `if (r.message ..) {here}`, or the
 * consequent of `else if (r.message ..)`. The ELSE branch of `if (r.message && ..)`
 * is NOT guarded (that is exactly the bug).
 */

/* global describe, it, expect */

const fs = require('fs');
const os = require('os');
const path = require('path');
const acorn = require('acorn');

const APP_ROOT = path.resolve(__dirname, '..', '..');
const SKIP_DIRS = new Set(['node_modules', 'tests', 'lib', 'dist']);

function listJsFiles(dir, out = []) {
	for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
		if (entry.isDirectory()) {
			if (!SKIP_DIRS.has(entry.name)) {
				listJsFiles(path.join(dir, entry.name), out);
			}
		} else if (entry.name.endsWith('.js') && !entry.name.endsWith('.min.js')) {
			out.push(path.join(dir, entry.name));
		}
	}
	return out;
}

const isMessage = (n) =>
	n.type === 'MemberExpression' &&
	!n.computed &&
	n.property.name === 'message' &&
	n.object.type === 'Identifier' &&
	n.object.name === 'r';

// Does a truthy `test` prove r.message is truthy?
function impliesMessage(test) {
	if (!test) return false;
	if (isMessage(test)) return true;
	if (test.type === 'LogicalExpression' && test.operator === '&&') {
		return impliesMessage(test.left) || impliesMessage(test.right);
	}
	// `r.message.success` etc. dereference r.message, so reaching past them proves it
	return test.type === 'MemberExpression' && isMessage(test.object);
}

function isGuarded(node, ancestors) {
	let child = node;
	for (let i = ancestors.length - 1; i >= 0; i--) {
		const parent = ancestors[i];
		const inConsequent =
			(parent.type === 'IfStatement' || parent.type === 'ConditionalExpression') && parent.consequent === child;
		if (inConsequent && impliesMessage(parent.test)) return true;
		if (parent.type === 'LogicalExpression' && parent.operator === '&&' && parent.right === child) {
			if (impliesMessage(parent.left)) return true;
		}
		child = parent;
	}
	return false;
}

function walk(node, ancestors, visit) {
	if (!node || typeof node.type !== 'string') return;
	visit(node, ancestors);
	ancestors.push(node);
	for (const key of Object.keys(node)) {
		const value = node[key];
		if (Array.isArray(value)) value.forEach((v) => walk(v, ancestors, visit));
		else if (value && typeof value.type === 'string') walk(value, ancestors, visit);
	}
	ancestors.pop();
}

// Scope: only the receiver name `r` and the non-computed form `r.message.error` are checked
// (not `response.message.error`, `r['message']`, or an aliased `const m = r.message`).
function findUnguardedErrorReads(source, sourceType = 'script') {
	const ast = acorn.parse(source, { ecmaVersion: 'latest', sourceType, locations: true });
	const found = [];
	walk(ast, [], (node, ancestors) => {
		const isErrorRead =
			node.type === 'MemberExpression' &&
			!node.optional && // `r.message?.error` is already safe
			!node.computed &&
			node.property.name === 'error' &&
			isMessage(node.object);
		if (isErrorRead && !isGuarded(node, ancestors)) found.push(node.loc.start.line);
	});
	return found;
}

// Try script, retry as ES module, else record as unparsed (never silently skip a file).
function scanFiles(files) {
	const offenders = [];
	const unparsed = [];
	let parsed = 0;
	files.forEach((file) => {
		const source = fs.readFileSync(file, 'utf8');
		let lines;
		try {
			lines = findUnguardedErrorReads(source, 'script');
		} catch (scriptError) {
			try {
				lines = findUnguardedErrorReads(source, 'module');
			} catch (moduleError) {
				unparsed.push(`${path.relative(APP_ROOT, file)}: ${moduleError.message}`);
				return;
			}
		}
		parsed += 1;
		lines.forEach((line) => offenders.push(`${path.relative(APP_ROOT, file)}:${line}`));
	});
	return { offenders, unparsed, parsed };
}

describe('r.message.error census (#1476)', () => {
	it('the detector flags the donor.js crash shape and accepts the guarded shapes (control)', () => {
		const bad = `frappe.call({ callback(r) { if (r.message && r.message.success) { ok(); } else { x(r.message.error || 'u'); } } });`;
		expect(findUnguardedErrorReads(bad)).toEqual([1]);
		const good = [
			`f(r => { x((r.message && r.message.error) || 'u'); })`,
			`f(r => { if (r.message) { x(r.message.error); } })`,
			`f(r => { if (r.message && r.message.success) { a(); } else if (r.message) { x(r.message.error); } })`,
			`f(r => { x(r.message ? r.message.error : 'u'); })`,
			`f(r => { x(r.message?.error || 'u'); })`
		];
		good.forEach((src) => expect(findUnguardedErrorReads(src)).toEqual([]));
	});

	it('flags a file that cannot be parsed instead of silently passing it (control)', () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'census-'));
		const broken = path.join(dir, 'broken.js');
		fs.writeFileSync(broken, 'function ( {{ r.message.error');
		const esm = path.join(dir, 'esm.js');
		fs.writeFileSync(esm, "import x from './y.js';\nf(r => { x(r.message.error); });");
		const result = scanFiles([broken, esm]);
		expect(result.unparsed).toHaveLength(1);
		expect(result.unparsed[0]).toContain('broken.js');
		expect(result.parsed).toBe(1); // the ES module parsed on retry
		expect(result.offenders).toHaveLength(1); // ...and its unguarded read was found
	});

	it('every scanned client script parses and none reads r.message.error unguarded', () => {
		const files = listJsFiles(APP_ROOT);
		const result = scanFiles(files);
		expect(result.unparsed).toEqual([]);
		expect(result.parsed).toBe(files.length);
		expect(result.offenders).toEqual([]);
	});
});
