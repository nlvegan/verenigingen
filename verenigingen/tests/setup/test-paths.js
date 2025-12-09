/**
 * @fileoverview Test Path Utilities for Verenigingen Controller Tests
 *
 * Provides helper functions for resolving controller paths in test files.
 * Works both in local development and GitHub Actions CI environment.
 *
 * Usage:
 * ```javascript
 * const { getControllerPath } = require('../../setup/test-paths');
 *
 * const config = {
 *   controllerPath: getControllerPath('membership_termination_request'),
 *   // ... rest of config
 * };
 * ```
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const path = require('path');
const { getProjectRoot, resolveControllerPath } = require('./controller-loader');

/**
 * Gets the path to a DocType controller by its snake_case name.
 * @param {string} doctypeName - The DocType name in snake_case (e.g., 'membership_termination_request')
 * @returns {string} Absolute path to the controller .js file
 */
function getControllerPath(doctypeName) {
	const relativePath = `verenigingen/verenigingen/doctype/${doctypeName}/${doctypeName}.js`;
	return resolveControllerPath(relativePath);
}

/**
 * Gets the path to a DocType controller from its display name.
 * Converts 'Membership Termination Request' to the proper file path.
 * @param {string} displayName - The DocType display name (e.g., 'Membership Termination Request')
 * @returns {string} Absolute path to the controller .js file
 */
function getControllerPathFromDisplayName(displayName) {
	const snakeCaseName = displayName.toLowerCase().replace(/ /g, '_');
	return getControllerPath(snakeCaseName);
}

/**
 * Gets a path relative to the project root.
 * @param {...string} pathSegments - Path segments to join
 * @returns {string} Absolute path
 */
function getProjectPath(...pathSegments) {
	return path.join(getProjectRoot(), ...pathSegments);
}

module.exports = {
	getControllerPath,
	getControllerPathFromDisplayName,
	getProjectPath,
	getProjectRoot
};
