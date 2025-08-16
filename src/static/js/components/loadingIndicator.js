/**
 * Loading Indicator Component
 * Manages loading states and visual feedback during async operations
 */

const LoadingIndicator = (function() {
    let loadingOverlay = null;
    let loadingSpinner = null;
    let loadingText = null;
    let activeOperations = new Set();
    let config = {
        show_loading_indicators: false
    };
    
    /**
     * Load configuration from server
     */
    async function loadConfig() {
        try {
            const response = await fetch('/api/config');
            const fullConfig = await response.json();
            config = {
                show_loading_indicators: fullConfig.ui?.show_loading_indicators ?? false
            };
        } catch (error) {
            console.error("Failed to load loading indicator config:", error);
            // Keep default values if config load fails
        }
    }

    /**
     * Initialize the loading indicator component
     */
    async function init() {
        await loadConfig();
        createLoadingElements();
        return true;
    }
    
    /**
     * Create the loading indicator DOM elements
     */
    function createLoadingElements() {
        // Create overlay
        loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'loading-overlay';
        loadingOverlay.style.display = 'none';
        
        // Create spinner container
        const spinnerContainer = document.createElement('div');
        spinnerContainer.className = 'loading-spinner-container';
        
        // Create spinner
        loadingSpinner = document.createElement('div');
        loadingSpinner.className = 'loading-spinner';
        
        // Create loading text
        loadingText = document.createElement('div');
        loadingText.className = 'loading-text';
        loadingText.textContent = 'Loading...';
        
        // Assemble elements
        spinnerContainer.appendChild(loadingSpinner);
        spinnerContainer.appendChild(loadingText);
        loadingOverlay.appendChild(spinnerContainer);
        document.body.appendChild(loadingOverlay);
        
        // Add inline loading indicator for non-blocking operations
        const inlineIndicator = document.createElement('div');
        inlineIndicator.className = 'inline-loading-indicator';
        inlineIndicator.id = 'inline-loading';
        inlineIndicator.innerHTML = '<span class="sync-icon">⟳</span> <span class="sync-text">Syncing...</span>';
        inlineIndicator.style.display = 'none';
        document.body.appendChild(inlineIndicator);
    }
    
    /**
     * Show loading indicator
     * @param {string} operationId - Unique ID for the operation
     * @param {string} message - Optional message to display
     * @param {boolean} blocking - Whether to show blocking overlay (default: false)
     */
    function show(operationId, message = 'Loading...', blocking = false) {
        if (!config.show_loading_indicators) {
            return; // Don't show loading indicators if disabled in config
        }
        
        activeOperations.add(operationId);
        
        if (blocking && loadingOverlay) {
            loadingText.textContent = message;
            loadingOverlay.style.display = 'flex';
            loadingOverlay.classList.add('fade-in');
        } else {
            // Show inline indicator
            const inlineIndicator = document.getElementById('inline-loading');
            if (inlineIndicator) {
                const syncText = inlineIndicator.querySelector('.sync-text');
                if (syncText) {
                    syncText.textContent = message;
                }
                inlineIndicator.style.display = 'block';
                inlineIndicator.classList.add('pulse');
            }
        }
    }
    
    /**
     * Hide loading indicator
     * @param {string} operationId - Unique ID for the operation
     */
    function hide(operationId) {
        activeOperations.delete(operationId);
        
        // Only hide if no active operations remain
        if (activeOperations.size === 0) {
            if (loadingOverlay) {
                loadingOverlay.classList.remove('fade-in');
                loadingOverlay.classList.add('fade-out');
                setTimeout(() => {
                    loadingOverlay.style.display = 'none';
                    loadingOverlay.classList.remove('fade-out');
                }, 300);
            }
            
            // Hide inline indicator
            const inlineIndicator = document.getElementById('inline-loading');
            if (inlineIndicator) {
                inlineIndicator.classList.remove('pulse');
                setTimeout(() => {
                    inlineIndicator.style.display = 'none';
                }, 300);
            }
        }
    }
    
    /**
     * Show quick toast notification
     * @param {string} message - Message to display
     * @param {string} type - Type of notification (success, error, info)
     * @param {number} duration - Duration in milliseconds
     */
    function showToast(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        
        // Add icon based on type
        const icon = document.createElement('span');
        icon.className = 'toast-icon';
        switch(type) {
            case 'success':
                icon.textContent = '✓';
                break;
            case 'error':
                icon.textContent = '✗';
                break;
            case 'info':
                icon.textContent = 'ℹ';
                break;
        }
        toast.prepend(icon);
        
        document.body.appendChild(toast);
        
        // Trigger animation
        setTimeout(() => {
            toast.classList.add('toast-show');
        }, 10);
        
        // Remove after duration
        setTimeout(() => {
            toast.classList.remove('toast-show');
            toast.classList.add('toast-hide');
            setTimeout(() => {
                document.body.removeChild(toast);
            }, 300);
        }, duration);
    }
    
    /**
     * Show progress indicator for long operations
     * @param {string} operationId - Unique ID for the operation
     * @param {number} progress - Progress percentage (0-100)
     * @param {string} message - Optional progress message
     */
    function updateProgress(operationId, progress, message = '') {
        if (!activeOperations.has(operationId)) {
            show(operationId, message, false);
        }
        
        // Update inline indicator with progress
        const inlineIndicator = document.getElementById('inline-loading');
        if (inlineIndicator) {
            const syncText = inlineIndicator.querySelector('.sync-text');
            if (syncText) {
                syncText.textContent = message || `Syncing... ${progress}%`;
            }
        }
    }
    
    /**
     * Check if any operations are active
     * @returns {boolean}
     */
    function isActive() {
        return activeOperations.size > 0;
    }
    
    // Public API
    return {
        init,
        show,
        hide,
        showToast,
        updateProgress,
        isActive
    };
})();

export default LoadingIndicator;