/**
 * Storage Service for Membership Application
 * Handles local storage, session storage, and draft saving functionality
 */

class StorageService {
    constructor(apiService, options = {}) {
        this.api = apiService;
        this.options = {
            autoSaveInterval: 30000, // 30 seconds
            maxDrafts: 5,
            storagePrefix: 'membership_app_',
            encryptSensitive: true,
            ...options
        };

        this.autoSaveTimer = null;
        this.isDirty = false;
        this.lastSaved = null;
        this.currentDraftId = null;

        this._initializeStorage();
    }

    /**
     * Initialize storage and check browser compatibility
     */
    _initializeStorage() {
        this.storageAvailable = {
            localStorage: this._storageAvailable('localStorage'),
            sessionStorage: this._storageAvailable('sessionStorage'),
            indexedDB: this._storageAvailable('indexedDB')
        };

        // Clean up old drafts on initialization
        this._cleanupOldDrafts();

        // Set up beforeunload handler to save draft
        window.addEventListener('beforeunload', (event) => {
            if (this.isDirty) {
                this._saveToLocalStorage();
            }
        });
    }

    /**
     * Check if storage type is available
     */
    _storageAvailable(type) {
        try {
            const storage = window[type];
            const test = '__storage_test__';
            storage.setItem(test, test);
            storage.removeItem(test);
            return true;
        } catch (e) {
            return false;
        }
    }

    /**
     * Start auto-save functionality
     */
    startAutoSave(getData) {
        this.getDataCallback = getData;

        if (this.autoSaveTimer) {
            clearInterval(this.autoSaveTimer);
        }

        this.autoSaveTimer = setInterval(async () => {
            if (this.isDirty) {
                await this.saveDraft();
            }
        }, this.options.autoSaveInterval);

        console.log('Auto-save started with interval:', this.options.autoSaveInterval);
    }

    /**
     * Stop auto-save functionality
     */
    stopAutoSave() {
        if (this.autoSaveTimer) {
            clearInterval(this.autoSaveTimer);
            this.autoSaveTimer = null;
        }
    }

    /**
     * Mark data as dirty (changed)
     */
    markDirty() {
        this.isDirty = true;
    }

    /**
     * Mark data as clean (saved)
     */
    markClean() {
        this.isDirty = false;
        this.lastSaved = new Date();
    }

    /**
     * Save draft to local storage and optionally to server
     */
    async saveDraft(data = null, saveToServer = true) {
        try {
            const draftData = data || (this.getDataCallback ? this.getDataCallback() : {});

            if (!draftData || Object.keys(draftData).length === 0) {
                return { success: false, message: 'No data to save' };
            }

            // Save to local storage first (instant)
            const localResult = this._saveToLocalStorage(draftData);

            let serverResult = { success: true };

            // Save to server if requested and API is available
            if (saveToServer && this.api) {
                try {
                    serverResult = await this.api.saveDraft(draftData);
                    if (serverResult.success && serverResult.draft_id) {
                        this.currentDraftId = serverResult.draft_id;
                        this._saveMetadata('currentDraftId', this.currentDraftId);
                    }
                } catch (error) {
                    console.warn('Server draft save failed, using local storage only:', error);
                    serverResult = { success: false, error: error.message };
                }
            }

            this.markClean();

            return {
                success: localResult.success || serverResult.success,
                local: localResult,
                server: serverResult,
                timestamp: new Date(),
                draftId: this.currentDraftId
            };

        } catch (error) {
            console.error('Draft save failed:', error);
            return {
                success: false,
                error: error.message,
                timestamp: new Date()
            };
        }
    }

    /**
     * Load draft from local storage or server
     */
    async loadDraft(draftId = null) {
        try {
            // Try to load from server first if draft ID is provided
            if (draftId && this.api) {
                try {
                    const serverResult = await this.api.loadDraft(draftId);
                    if (serverResult.success) {
                        this.currentDraftId = draftId;
                        this._saveMetadata('currentDraftId', draftId);
                        return {
                            success: true,
                            data: serverResult.data,
                            source: 'server',
                            draftId: draftId
                        };
                    }
                } catch (error) {
                    console.warn('Server draft load failed, trying local storage:', error);
                }
            }

            // Fall back to local storage
            const localResult = this._loadFromLocalStorage();
            if (localResult.success) {
                return {
                    success: true,
                    data: localResult.data,
                    source: 'local',
                    timestamp: localResult.timestamp
                };
            }

            return { success: false, message: 'No draft found' };

        } catch (error) {
            console.error('Draft load failed:', error);
            return {
                success: false,
                error: error.message
            };
        }
    }

    /**
     * Get all available draft versions
     */
    getAllDrafts() {
        const drafts = [];

        // Get local drafts
        if (this.storageAvailable.localStorage) {
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key.startsWith(this.options.storagePrefix + 'draft_')) {
                    try {
                        const data = JSON.parse(localStorage.getItem(key));
                        drafts.push({
                            id: key.replace(this.options.storagePrefix + 'draft_', ''),
                            timestamp: new Date(data.timestamp),
                            source: 'local',
                            size: JSON.stringify(data).length
                        });
                    } catch (error) {
                        console.warn('Invalid draft data in localStorage:', key);
                    }
                }
            }
        }

        // Sort by timestamp (newest first)
        return drafts.sort((a, b) => b.timestamp - a.timestamp);
    }

    /**
     * Delete a specific draft
     */
    deleteDraft(draftId) {
        if (this.storageAvailable.localStorage) {
            const key = this.options.storagePrefix + 'draft_' + draftId;
            localStorage.removeItem(key);
        }

        // If this was the current draft, clear the reference
        if (this.currentDraftId === draftId) {
            this.currentDraftId = null;
            this._saveMetadata('currentDraftId', null);
        }
    }

    /**
     * Clear all drafts
     */
    clearAllDrafts() {
        if (this.storageAvailable.localStorage) {
            const keysToRemove = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key.startsWith(this.options.storagePrefix)) {
                    keysToRemove.push(key);
                }
            }
            keysToRemove.forEach(key => localStorage.removeItem(key));
        }

        this.currentDraftId = null;
    }

    /**
     * Save to local storage
     */
    _saveToLocalStorage(data = null) {
        if (!this.storageAvailable.localStorage) {
            return { success: false, message: 'localStorage not available' };
        }

        try {
            const draftData = data || (this.getDataCallback ? this.getDataCallback() : {});
            const timestamp = new Date().toISOString();
            const draftId = this._generateDraftId();

            const saveData = {
                data: this._sanitizeData(draftData),
                timestamp: timestamp,
                version: '1.0',
                userAgent: navigator.userAgent.substring(0, 100)
            };

            const key = this.options.storagePrefix + 'draft_' + draftId;
            localStorage.setItem(key, JSON.stringify(saveData));

            // Update current draft reference
            this._saveMetadata('currentDraftId', draftId);
            this._saveMetadata('lastSaved', timestamp);

            return {
                success: true,
                draftId: draftId,
                timestamp: timestamp,
                size: JSON.stringify(saveData).length
            };

        } catch (error) {
            console.error('Local storage save failed:', error);
            return {
                success: false,
                error: error.message
            };
        }
    }

    /**
     * Load from local storage
     */
    _loadFromLocalStorage() {
        if (!this.storageAvailable.localStorage) {
            return { success: false, message: 'localStorage not available' };
        }

        try {
            const currentDraftId = this._loadMetadata('currentDraftId');
            if (!currentDraftId) {
                return { success: false, message: 'No current draft ID' };
            }

            const key = this.options.storagePrefix + 'draft_' + currentDraftId;
            const savedData = localStorage.getItem(key);

            if (!savedData) {
                return { success: false, message: 'Draft not found in localStorage' };
            }

            const parsedData = JSON.parse(savedData);
            return {
                success: true,
                data: parsedData.data,
                timestamp: parsedData.timestamp,
                draftId: currentDraftId
            };

        } catch (error) {
            console.error('Local storage load failed:', error);
            return {
                success: false,
                error: error.message
            };
        }
    }

    /**
     * Save/load metadata
     */
    _saveMetadata(key, value) {
        if (this.storageAvailable.localStorage) {
            const metaKey = this.options.storagePrefix + 'meta_' + key;
            localStorage.setItem(metaKey, JSON.stringify(value));
        }
    }

    _loadMetadata(key) {
        if (this.storageAvailable.localStorage) {
            const metaKey = this.options.storagePrefix + 'meta_' + key;
            const value = localStorage.getItem(metaKey);
            return value ? JSON.parse(value) : null;
        }
        return null;
    }

    /**
     * Utility functions
     */
    _generateDraftId() {
        return 'local_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    _sanitizeData(data) {
        // Remove sensitive data before storing locally
        const sanitized = { ...data };

        if (this.options.encryptSensitive) {
            // Remove or encrypt sensitive fields
            delete sanitized.bankAccount;
            delete sanitized.ssn;
        }

        return sanitized;
    }

    _cleanupOldDrafts() {
        if (!this.storageAvailable.localStorage) return;

        const drafts = this.getAllDrafts();
        if (drafts.length > this.options.maxDrafts) {
            // Remove oldest drafts
            const draftsToRemove = drafts.slice(this.options.maxDrafts);
            draftsToRemove.forEach(draft => {
                this.deleteDraft(draft.id);
            });

            console.log(`Cleaned up ${draftsToRemove.length} old drafts`);
        }
    }

    /**
     * Storage statistics and debugging
     */
    getStorageStats() {
        let usedSpace = 0;
        let draftCount = 0;

        if (this.storageAvailable.localStorage) {
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key.startsWith(this.options.storagePrefix)) {
                    const value = localStorage.getItem(key);
                    usedSpace += key.length + value.length;
                    if (key.includes('draft_')) {
                        draftCount++;
                    }
                }
            }
        }

        return {
            available: this.storageAvailable,
            usedSpace: usedSpace,
            draftCount: draftCount,
            lastSaved: this.lastSaved,
            currentDraftId: this.currentDraftId,
            isDirty: this.isDirty,
            autoSaveActive: !!this.autoSaveTimer
        };
    }

    /**
     * Session storage methods for temporary data
     */
    setSessionData(key, value) {
        if (this.storageAvailable.sessionStorage) {
            const fullKey = this.options.storagePrefix + 'session_' + key;
            sessionStorage.setItem(fullKey, JSON.stringify(value));
        }
    }

    getSessionData(key) {
        if (this.storageAvailable.sessionStorage) {
            const fullKey = this.options.storagePrefix + 'session_' + key;
            const value = sessionStorage.getItem(fullKey);
            return value ? JSON.parse(value) : null;
        }
        return null;
    }

    clearSessionData(key = null) {
        if (!this.storageAvailable.sessionStorage) return;

        if (key) {
            const fullKey = this.options.storagePrefix + 'session_' + key;
            sessionStorage.removeItem(fullKey);
        } else {
            // Clear all session data for this app
            const keysToRemove = [];
            for (let i = 0; i < sessionStorage.length; i++) {
                const storageKey = sessionStorage.key(i);
                if (storageKey.startsWith(this.options.storagePrefix + 'session_')) {
                    keysToRemove.push(storageKey);
                }
            }
            keysToRemove.forEach(storageKey => sessionStorage.removeItem(storageKey));
        }
    }
}

// Export for use in other modules
window.StorageService = StorageService;
