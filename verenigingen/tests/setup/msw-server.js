/**
 * @fileoverview MSW (Mock Service Worker) Server Setup
 *
 * This module configures and exports the MSW server instance for use in
 * Jest tests. The server intercepts HTTP requests during testing and
 * returns mock responses, enabling reliable testing of API integration
 * code without requiring actual network connections.
 *
 * @author Verenigingen Development Team
 * @version 2025-08-26
 */

const { setupServer } = require('msw/node');
const { mollieHandlers, errorHandlers, networkHandlers } = require('./msw-handlers');

/**
 * MSW server instance with all Mollie API handlers
 *
 * This server is configured with:
 * - Standard Mollie API endpoints
 * - Error simulation handlers
 * - Network condition handlers
 */
const server = setupServer(
	...errorHandlers,
	...networkHandlers,
	...mollieHandlers
);

module.exports = { server };
