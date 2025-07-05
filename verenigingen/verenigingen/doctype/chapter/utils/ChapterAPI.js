// verenigingen/verenigingen/doctype/chapter/utils/ChapterAPI.js

import { ChapterConfig } from '../config/ChapterConfig.js';

export class ChapterAPI {
    constructor() {
        this.requestQueue = [];
        this.cache = new Map();
        this.activeRequests = new Map();
    }

    /**
     * Make a Frappe API call with error handling and retries
     * @param {String} method - Method name
     * @param {Object} args - Method arguments
     * @param {Object} options - Additional options
     * @returns {Promise} API response
     */
    async call(method, args = {}, options = {}) {
        const {
            freeze = true,
            freeze_message = __('Processing...'),
            cache = false,
            cacheKey = null,
            cacheDuration = ChapterConfig.statistics.cacheDuration,
            retry = true,
            retryAttempts = ChapterConfig.api.retryAttempts,
            retryDelay = ChapterConfig.api.retryDelay,
            showError = true
        } = options;

        // Check cache first
        const finalCacheKey = cacheKey || this.generateCacheKey(method, args);
        if (cache && this.cache.has(finalCacheKey)) {
            const cachedData = this.cache.get(finalCacheKey);
            if (Date.now() - cachedData.timestamp < cacheDuration * 1000) {
                return cachedData.data;
            }
            this.cache.delete(finalCacheKey);
        }

        // Check if request is already in progress
        if (this.activeRequests.has(finalCacheKey)) {
            return this.activeRequests.get(finalCacheKey);
        }

        // Create the promise
        const promise = this._makeCall(method, args, {
            freeze,
            freeze_message,
            retry,
            retryAttempts,
            retryDelay,
            showError
        });

        // Store active request
        this.activeRequests.set(finalCacheKey, promise);

        try {
            const result = await promise;

            // Cache the result if requested
            if (cache) {
                this.cache.set(finalCacheKey, {
                    data: result,
                    timestamp: Date.now()
                });
            }

            return result;
        } finally {
            // Remove from active requests
            this.activeRequests.delete(finalCacheKey);
        }
    }

    /**
     * Internal method to make the actual API call
     */
    async _makeCall(method, args, options, attemptNumber = 1) {
        try {
            const response = await frappe.call({
                method: method,
                args: args,
                freeze: options.freeze,
                freeze_message: options.freeze_message
            });

            if (response.exc) {
                throw new Error(response.exc);
            }

            return response.message;
        } catch (error) {
            // Handle retry logic
            if (options.retry && attemptNumber < options.retryAttempts) {
                await this.sleep(options.retryDelay * attemptNumber);
                return this._makeCall(method, args, options, attemptNumber + 1);
            }

            // Handle error
            if (options.showError) {
                this.handleError(error, method);
            }

            throw error;
        }
    }

    /**
     * Get a document
     * @param {String} doctype - Document type
     * @param {String} name - Document name
     * @param {Object} options - Additional options
     * @returns {Promise} Document data
     */
    async getDoc(doctype, name, options = {}) {
        return this.call('frappe.client.get', {
            doctype: doctype,
            name: name
        }, {
            ...options,
            cache: options.cache !== false, // Cache by default
            cacheKey: `doc-${doctype}-${name}`
        });
    }

    /**
     * Get list of documents
     * @param {String} doctype - Document type
     * @param {Object} params - List parameters
     * @param {Object} options - Additional options
     * @returns {Promise} List of documents
     */
    async getList(doctype, params = {}, options = {}) {
        const defaultParams = {
            doctype: doctype,
            fields: params.fields || ['name'],
            filters: params.filters || {},
            order_by: params.order_by || 'modified desc',
            limit: params.limit || 20,
            start: params.start || 0
        };

        return this.call('frappe.client.get_list', defaultParams, options);
    }

    /**
     * Get document count
     * @param {String} doctype - Document type
     * @param {Object} filters - Filters
     * @param {Object} options - Additional options
     * @returns {Promise} Document count
     */
    async getCount(doctype, filters = {}, options = {}) {
        return this.call('frappe.client.get_count', {
            doctype: doctype,
            filters: filters
        }, options);
    }

    /**
     * Get single value from document
     * @param {String} doctype - Document type
     * @param {String} name - Document name
     * @param {String} fieldname - Field name
     * @param {Object} options - Additional options
     * @returns {Promise} Field value
     */
    async getValue(doctype, name, fieldname, options = {}) {
        return this.call('frappe.client.get_value', {
            doctype: doctype,
            filters: { name: name },
            fieldname: fieldname
        }, {
            ...options,
            cache: true,
            cacheKey: `value-${doctype}-${name}-${fieldname}`
        });
    }

    /**
     * Set value in document
     * @param {String} doctype - Document type
     * @param {String} name - Document name
     * @param {String} fieldname - Field name
     * @param {*} value - New value
     * @param {Object} options - Additional options
     * @returns {Promise} Update result
     */
    async setValue(doctype, name, fieldname, value, options = {}) {
        // Clear cache for this document
        this.clearDocCache(doctype, name);

        return this.call('frappe.client.set_value', {
            doctype: doctype,
            name: name,
            fieldname: fieldname,
            value: value
        }, options);
    }

    /**
     * Insert new document
     * @param {Object} doc - Document data
     * @param {Object} options - Additional options
     * @returns {Promise} Created document
     */
    async insert(doc, options = {}) {
        return this.call('frappe.client.insert', {
            doc: doc
        }, options);
    }

    /**
     * Update existing document
     * @param {Object} doc - Document data with name
     * @param {Object} options - Additional options
     * @returns {Promise} Updated document
     */
    async update(doc, options = {}) {
        // Clear cache for this document
        this.clearDocCache(doc.doctype, doc.name);

        return this.call('frappe.client.save', {
            doc: doc
        }, options);
    }

    /**
     * Delete document
     * @param {String} doctype - Document type
     * @param {String} name - Document name
     * @param {Object} options - Additional options
     * @returns {Promise} Deletion result
     */
    async delete(doctype, name, options = {}) {
        // Clear cache for this document
        this.clearDocCache(doctype, name);

        return this.call('frappe.client.delete', {
            doctype: doctype,
            name: name
        }, options);
    }

    /**
     * Bulk update documents
     * @param {String} doctype - Document type
     * @param {Array} names - Document names
     * @param {Object} updates - Field updates
     * @param {Object} options - Additional options
     * @returns {Promise} Update result
     */
    async bulkUpdate(doctype, names, updates, options = {}) {
        // Clear cache for all documents
        names.forEach(name => this.clearDocCache(doctype, name));

        return this.call('frappe.client.bulk_update', {
            doctype: doctype,
            names: names,
            updates: updates
        }, options);
    }

    /**
     * Run report
     * @param {String} report - Report name
     * @param {Object} filters - Report filters
     * @param {Object} options - Additional options
     * @returns {Promise} Report data
     */
    async runReport(report, filters = {}, options = {}) {
        return this.call('frappe.desk.query_report.run', {
            report_name: report,
            filters: filters
        }, options);
    }

    /**
     * Send email
     * @param {Object} emailData - Email parameters
     * @param {Object} options - Additional options
     * @returns {Promise} Email result
     */
    async sendEmail(emailData, options = {}) {
        return this.call('frappe.core.doctype.communication.email.make', {
            recipients: emailData.recipients,
            subject: emailData.subject,
            content: emailData.content,
            doctype: emailData.doctype,
            name: emailData.name,
            send_email: 1,
            attachments: emailData.attachments || []
        }, options);
    }

    /**
     * Get print format
     * @param {String} doctype - Document type
     * @param {String} name - Document name
     * @param {String} format - Print format name
     * @param {Object} options - Additional options
     * @returns {Promise} Print HTML
     */
    async getPrintFormat(doctype, name, format, options = {}) {
        return this.call('frappe.www.printview.get_print_format', {
            doctype: doctype,
            name: name,
            format: format
        }, options);
    }

    /**
     * Upload file
     * @param {File} file - File object
     * @param {Object} params - Upload parameters
     * @param {Object} options - Additional options
     * @returns {Promise} Upload result
     */
    async uploadFile(file, params = {}, options = {}) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('is_private', params.is_private || 0);
        formData.append('doctype', params.doctype || '');
        formData.append('docname', params.docname || '');
        formData.append('fieldname', params.fieldname || '');

        return new Promise((resolve, reject) => {
            frappe.upload.make({
                args: formData,
                callback: (response) => {
                    if (response.exc) {
                        reject(new Error(response.exc));
                    } else {
                        resolve(response.message);
                    }
                },
                error: (error) => {
                    reject(error);
                }
            });
        });
    }

    /**
     * Batch API calls
     * @param {Array} calls - Array of API call definitions
     * @param {Object} options - Additional options
     * @returns {Promise} Array of results
     */
    async batch(calls, options = {}) {
        const {
            parallel = true,
            batchSize = ChapterConfig.api.batchSize,
            continueOnError = false
        } = options;

        if (parallel) {
            // Process in parallel batches
            const results = [];
            for (let i = 0; i < calls.length; i += batchSize) {
                const batch = calls.slice(i, i + batchSize);
                const batchResults = await Promise.allSettled(
                    batch.map(call => this.call(call.method, call.args, call.options))
                );

                batchResults.forEach((result, index) => {
                    if (result.status === 'fulfilled') {
                        results.push(result.value);
                    } else if (!continueOnError) {
                        throw result.reason;
                    } else {
                        results.push({ error: result.reason });
                    }
                });
            }
            return results;
        } else {
            // Process sequentially
            const results = [];
            for (const call of calls) {
                try {
                    const result = await this.call(call.method, call.args, call.options);
                    results.push(result);
                } catch (error) {
                    if (!continueOnError) {
                        throw error;
                    }
                    results.push({ error });
                }
            }
            return results;
        }
    }

    /**
     * Clear cache for a specific document
     * @param {String} doctype - Document type
     * @param {String} name - Document name
     */
    clearDocCache(doctype, name) {
        const keysToDelete = [];

        this.cache.forEach((value, key) => {
            if (key.includes(`${doctype}-${name}`)) {
                keysToDelete.push(key);
            }
        });

        keysToDelete.forEach(key => this.cache.delete(key));
    }

    /**
     * Clear all cache
     */
    clearCache() {
        this.cache.clear();
    }

    /**
     * Generate cache key
     * @param {String} method - Method name
     * @param {Object} args - Method arguments
     * @returns {String} Cache key
     */
    generateCacheKey(method, args) {
        return `${method}-${JSON.stringify(args)}`;
    }

    /**
     * Handle API errors
     * @param {Error} error - Error object
     * @param {String} context - Error context
     */
    handleError(error, context) {
        console.error(`API Error in ${context}:`, error);

        let message = ChapterConfig.messages.errors.generic;
        let title = __('Error');
        let indicator = 'red';

        // Parse error message
        if (error.message) {
            if (error.message.includes('PermissionError')) {
                message = ChapterConfig.messages.errors.permission;
                title = __('Permission Denied');
            } else if (error.message.includes('ValidationError')) {
                message = ChapterConfig.messages.errors.validation;
                title = __('Validation Error');
            } else if (error.message.includes('DoesNotExistError')) {
                message = __('The requested item does not exist');
                title = __('Not Found');
            } else if (error.message.includes('DuplicateEntryError')) {
                message = __('This item already exists');
                title = __('Duplicate Entry');
            } else if (error.message.includes('timeout')) {
                message = ChapterConfig.messages.errors.timeout;
                title = __('Timeout');
            } else if (error.message.includes('Network')) {
                message = ChapterConfig.messages.errors.network;
                title = __('Network Error');
            } else {
                // Use the actual error message if it's user-friendly
                message = error.message;
            }
        }

        // Show error to user
        frappe.msgprint({
            title: title,
            indicator: indicator,
            message: message
        });

        // Log to server if critical
        if (this.shouldLogError(error)) {
            this.logError(error, context);
        }
    }

    /**
     * Check if error should be logged to server
     * @param {Error} error - Error object
     * @returns {Boolean} Whether to log error
     */
    shouldLogError(error) {
        // Don't log expected errors
        const expectedErrors = [
            'PermissionError',
            'ValidationError',
            'DoesNotExistError',
            'DuplicateEntryError'
        ];

        return !expectedErrors.some(e => error.message?.includes(e));
    }

    /**
     * Log error to server
     * @param {Error} error - Error object
     * @param {String} context - Error context
     */
    async logError(error, context) {
        try {
            await this.call('frappe.utils.error.log_error', {
                title: `Chapter API Error: ${context}`,
                error: error.stack || error.message
            }, {
                showError: false,
                retry: false
            });
        } catch (logError) {
            console.error('Failed to log error:', logError);
        }
    }

    /**
     * Sleep for specified milliseconds
     * @param {Number} ms - Milliseconds to sleep
     * @returns {Promise} Promise that resolves after sleep
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Check API rate limits
     * @returns {Boolean} Whether rate limit is exceeded
     */
    checkRateLimit() {
        // This would need actual implementation based on your rate limiting strategy
        return false;
    }

    /**
     * Get API statistics
     * @returns {Object} API usage statistics
     */
    getStatistics() {
        return {
            cacheSize: this.cache.size,
            activeRequests: this.activeRequests.size,
            queuedRequests: this.requestQueue.length
        };
    }
}

// Create singleton instance
export const chapterAPI = new ChapterAPI();
