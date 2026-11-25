/**
 * Guard: Member mock docs may only carry fields that exist on Member.
 *
 * Mock forms are plain objects with no schema enforcement, so a test that
 * assigns `frm.doc.some_invented_field` can never fail. #1149 and #1186 found
 * test fixtures assigning names that are not in member.json (primary_chapter,
 * phone, member_number, is_volunteer, ...). This scans test sources for such
 * names so the next invented one is caught at review time.
 */
const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '../../..');
const MEMBER_JSON = path.join(REPO_ROOT, 'verenigingen/verenigingen/doctype/member/member.json');

// Keys Frappe puts on every doc; not declared in a DocType's `fields`.
const STANDARD_DOC_KEYS = [
	'name',
	'doctype',
	'docstatus',
	'owner',
	'creation',
	'modified',
	'modified_by',
	'idx',
	'__islocal',
	'__unsaved'
];

function memberFieldnames() {
	const meta = JSON.parse(fs.readFileSync(MEMBER_JSON, 'utf8'));
	return new Set([...meta.fields.map((f) => f.fieldname), ...STANDARD_DOC_KEYS]);
}

// Returns the text between the braces that open at `openIdx` (a '{').
function balancedBlock(src, openIdx) {
	let depth = 0;
	for (let i = openIdx; i < src.length; i++) {
		if (src[i] === '{') depth++;
		else if (src[i] === '}' && --depth === 0) return src.slice(openIdx + 1, i);
	}
	return src.slice(openIdx + 1);
}

// Top-level `key:` names of an object-literal body (nested objects skipped).
function topLevelKeys(body) {
	const keys = [];
	let depth = 0;
	body.split('\n').forEach((line) => {
		const m = depth === 0 && line.match(/^\s*(\w+)\s*:/);
		if (m) keys.push(m[1]);
		for (const ch of line) {
			if ('{[('.includes(ch)) depth++;
			else if ('}])'.includes(ch)) depth--;
		}
	});
	return keys;
}

function lineOf(src, idx) {
	return src.slice(0, idx).split('\n').length;
}

/** Field names a test source puts on a Member doc: [{field, line, via}] */
function memberDocFieldRefs(src) {
	const refs = [];
	const add = (field, idx, via) => refs.push({ field, line: lineOf(src, idx), via });

	for (const m of src.matchAll(/\b(?:frm|mockForm)\.doc\.(\w+)/g)) add(m[1], m.index, 'doc.<field>');
	for (const m of src.matchAll(/\bfill_frappe_field\(\s*['"](\w+)['"]/g)) add(m[1], m.index, 'fill_frappe_field');
	for (const m of src.matchAll(/\b(?:doc|defaultDoc)\s*:\s*\{/g)) {
		const open = m.index + m[0].length - 1;
		topLevelKeys(balancedBlock(src, open)).forEach((k) => add(k, open, 'doc literal'));
	}
	return refs;
}

function phantomMemberFields(src, fieldnames = memberFieldnames()) {
	return memberDocFieldRefs(src).filter((r) => !fieldnames.has(r.field));
}

module.exports = { REPO_ROOT, memberFieldnames, memberDocFieldRefs, phantomMemberFields };
