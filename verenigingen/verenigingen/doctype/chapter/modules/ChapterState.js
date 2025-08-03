/**
 * @fileoverview ChapterState - Centralized state management for chapter functionality
 *
 * This module provides a centralized state management system for the Chapter DocType
 * and its associated modules. It implements a reactive state pattern with history
 * tracking, subscriptions, and efficient state updates for complex chapter operations.
 *
 * Business Context:
 * - Chapter forms have complex state with board members, members, and UI interactions
 * - Multiple modules need to share and react to state changes
 * - Undo functionality is needed for critical operations
 * - Loading states must be managed across async operations
 * - Cache management improves performance for expensive operations
 *
 * State Structure:
 * - chapter: Core chapter data (name, region, board members, members)
 * - ui: User interface state (dialogs, selections, loading states)
 * - cache: Cached data for performance (statistics, board history)
 *
 * Key Features:
 * - Reactive state updates with subscriber notifications
 * - History tracking for undo/redo functionality
 * - Nested state path access and updates
 * - Loading state management for async operations
 * - Cache invalidation and management
 * - Bulk action state tracking
 *
 * Usage Examples:
 * ```javascript
 * const state = new ChapterState();
 *
 * // Subscribe to state changes
 * state.subscribe(path => {
 *   console.log('State changed:', path);
 * });
 *
 * // Update nested state
 * state.update('ui.loadingStates.memberValidation', true);
 *
 * // Get state values
 * const isLoading = state.get('ui.loadingStates.memberValidation');
 *
 * // Manage loading states
 * state.setLoading('apiCall', true);
 * const loading = state.isLoading('apiCall');
 * ```
 *
 * @module verenigingen/doctype/chapter/modules/ChapterState
 * @version 1.0.0
 * @since 2024
 */

// verenigingen/verenigingen/doctype/chapter/modules/ChapterState.js

export class ChapterState {
	constructor() {
		this.state = {
			chapter: {
				name: null,
				region: null,
				boardMembers: [],
				members: [],
				postalCodes: null
			},
			ui: {
				bulkActionsVisible: false,
				selectedBoardMembers: new Set(),
				activeDialog: null,
				loadingStates: new Map()
			},
			cache: {
				boardHistory: null,
				statistics: null,
				lastUpdated: null
			}
		};

		this.subscribers = [];
		this.history = [];
		this.maxHistorySize = 10;
	}

	/**
	 * Get state value by path
	 * @param {string} path - Dot-separated path to state value (e.g., 'ui.loadingStates.memberValidation')
	 * @returns {any} The state value at the specified path
	 */
	get(path) {
		return this._getNestedValue(this.state, path);
	}

	/**
	 * Update state and notify subscribers
	 * @param {string} path - Dot-separated path to state value
	 * @param {any} value - New value to set
	 * @param {boolean} trackHistory - Whether to track this change in history (default: true)
	 */
	update(path, value, trackHistory = true) {
		const oldValue = this.get(path);

		// Store history for undo functionality
		if (trackHistory) {
			this.history.push({
				path,
				oldValue,
				newValue: value,
				timestamp: new Date()
			});

			if (this.history.length > this.maxHistorySize) {
				this.history.shift();
			}
		}

		// Update state
		this._setNestedValue(this.state, path, value);

		// Notify subscribers
		this.notify(path, value, oldValue);
	}

	// Subscribe to state changes
	subscribe(callback) {
		this.subscribers.push(callback);

		// Return unsubscribe function
		return () => {
			const index = this.subscribers.indexOf(callback);
			if (index > -1) {
				this.subscribers.splice(index, 1);
			}
		};
	}

	// Notify all subscribers of state change
	notify(path, newValue, oldValue) {
		this.subscribers.forEach(callback => {
			try {
				callback(path, newValue, oldValue);
			} catch (error) {
				console.error('Error in state subscriber:', error);
			}
		});
	}

	// Batch update multiple state values
	batchUpdate(updates) {
		const notifications = [];

		updates.forEach(({ path, value }) => {
			const oldValue = this.get(path);
			this._setNestedValue(this.state, path, value);
			notifications.push({ path, value, oldValue });
		});

		// Notify subscribers once for all changes
		notifications.forEach(({ path, value, oldValue }) => {
			this.notify(path, value, oldValue);
		});
	}

	// Get nested value from object using dot notation path
	_getNestedValue(obj, path) {
		return path.split('.').reduce((current, key) => current?.[key], obj);
	}

	// Set nested value in object using dot notation path
	_setNestedValue(obj, path, value) {
		const keys = path.split('.');
		const lastKey = keys.pop();
		const parent = keys.reduce((current, key) => {
			if (!current[key]) {
				current[key] = {};
			}
			return current[key];
		}, obj);

		parent[lastKey] = value;
	}

	// Undo last state change
	undo() {
		if (this.history.length === 0) { return false; }

		const lastChange = this.history.pop();
		this._setNestedValue(this.state, lastChange.path, lastChange.oldValue);
		this.notify(lastChange.path, lastChange.oldValue, lastChange.newValue);

		return true;
	}

	// Clear all state
	reset() {
		this.state = {
			chapter: {
				name: null,
				region: null,
				boardMembers: [],
				members: [],
				postalCodes: null
			},
			ui: {
				bulkActionsVisible: false,
				selectedBoardMembers: new Set(),
				activeDialog: null,
				loadingStates: new Map()
			},
			cache: {
				boardHistory: null,
				statistics: null,
				lastUpdated: null
			}
		};
		this.history = [];
		this.notify('*', this.state, null);
	}

	// Set loading state for a specific operation
	setLoading(operation, isLoading) {
		this.state.ui.loadingStates.set(operation, isLoading);
		this.notify(`ui.loadingStates.${operation}`, isLoading);
	}

	// Check if an operation is loading
	isLoading(operation) {
		return this.state.ui.loadingStates.get(operation) || false;
	}

	// Get current state snapshot
	getSnapshot() {
		return JSON.parse(JSON.stringify(this.state));
	}

	// Restore from snapshot
	restoreSnapshot(snapshot) {
		this.state = JSON.parse(JSON.stringify(snapshot));
		this.notify('*', this.state, null);
	}

	// Cleanup
	destroy() {
		this.subscribers = [];
		this.history = [];
		this.state = null;
	}
}
