/**
 * Slideshow Component
 * Manages background photo slideshow functionality with preloading and smooth transitions
 */
const Slideshow = (function() {
    // Private variables
    let slideshowInterval = null;
    const SLIDESHOW_INTERVAL_MS = 30000; // Change photo every 30 seconds
    let currentPhotoUrl = null;
    let nextPhotoUrl = null;
    let isPreloading = false;
    let isRunning = false;
    let backgroundElement = null;
    let nextBackgroundElement = null;

    // Private methods
    function fetchNextPhotoUrl() {
        // Fetching next background photo URL
        return fetch('/api/random-photo')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.url) {
                    // Next photo URL fetched
                    return data.url;
                } else if (data.error) {
                    console.error("Error fetching photo URL:", data.error);
                    return null;
                }
                return null;
            })
            .catch(error => {
                console.error('Could not fetch next photo URL:', error);
                return null;
            });
    }

    function createBackgroundElements() {
        // Create main background element
        if (!backgroundElement) {
            backgroundElement = document.createElement('div');
            backgroundElement.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-size: cover;
                background-position: center;
                background-repeat: no-repeat;
                z-index: -2;
                opacity: 1;
                transition: opacity 2s ease-in-out;
            `;
            document.body.appendChild(backgroundElement);
        }
        
        // Create next background element for smooth transitions
        if (!nextBackgroundElement) {
            nextBackgroundElement = document.createElement('div');
            nextBackgroundElement.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-size: cover;
                background-position: center;
                background-repeat: no-repeat;
                z-index: -1;
                opacity: 0;
                transition: opacity 2s ease-in-out;
            `;
            document.body.appendChild(nextBackgroundElement);
        }
    }

    function preloadAndSwitchBackground(url) {
        if (!url || isPreloading || !isRunning) return;
        
        // Preloading image
        isPreloading = true;
        const img = new Image();
        img.onload = () => {
            if (!isRunning) {
                // Clear image reference to prevent memory leak
                img.onload = null;
                img.onerror = null;
                img.src = '';
                isPreloading = false;
                return;
            }
            
            // Set image on the next background element
            nextBackgroundElement.style.backgroundImage = `url(${url})`;
            nextBackgroundElement.style.opacity = '0';
            
            // Force a reflow to ensure the opacity is set
            nextBackgroundElement.offsetHeight;
            
            // Fade in the new image
            nextBackgroundElement.style.opacity = '1';
            
            // After transition completes, swap elements
            setTimeout(() => {
                if (!isRunning) {
                    // Clear image reference to prevent memory leak
                    img.onload = null;
                    img.onerror = null;
                    img.src = '';
                    return;
                }
                
                // Swap the elements
                const temp = backgroundElement;
                backgroundElement = nextBackgroundElement;
                nextBackgroundElement = temp;
                
                // Reset the now-hidden element
                nextBackgroundElement.style.opacity = '0';
                nextBackgroundElement.style.backgroundImage = '';
                
                currentPhotoUrl = url;
                isPreloading = false;
                
                // Clear image reference to prevent memory leak
                img.onload = null;
                img.onerror = null;
                img.src = '';
                
                // Fetch the *next* photo's URL for next cycle
                if (isRunning) {
                    fetchNextPhotoUrl().then(fetchedUrl => {
                        nextPhotoUrl = fetchedUrl;
                    });
                }
            }, 2000); // Match transition duration
        };
        img.onerror = () => {
            console.error("Error preloading image:", url);
            // Clear image reference to prevent memory leak
            img.onload = null;
            img.onerror = null;
            img.src = '';
            isPreloading = false;
            // Attempt to fetch a different photo URL for the next cycle
            if (isRunning) {
                fetchNextPhotoUrl().then(fetchedUrl => {
                    nextPhotoUrl = fetchedUrl;
                });
            }
        };
        img.src = url;
    }

    function cyclePhoto() {
        if (!isRunning) return;
        
        if (nextPhotoUrl && !isPreloading) {
            preloadAndSwitchBackground(nextPhotoUrl);
        } else if (!isPreloading) {
            // If nextPhotoUrl isn't ready, try fetching one now
            fetchNextPhotoUrl().then(fetchedUrl => {
                if (isRunning && fetchedUrl) {
                    nextPhotoUrl = fetchedUrl;
                    // Don't preload immediately to avoid rapid changes
                }
            });
        }
    }
    
    function cleanup() {
        // Clean up resources to prevent memory leaks
        if (slideshowInterval) {
            clearInterval(slideshowInterval);
            slideshowInterval = null;
        }
        
        if (backgroundElement && backgroundElement.parentNode) {
            backgroundElement.parentNode.removeChild(backgroundElement);
            backgroundElement = null;
        }
        
        if (nextBackgroundElement && nextBackgroundElement.parentNode) {
            nextBackgroundElement.parentNode.removeChild(nextBackgroundElement);
            nextBackgroundElement = null;
        }
        
        // Clear body background image as fallback
        document.body.style.backgroundImage = '';
        
        isRunning = false;
        isPreloading = false;
        currentPhotoUrl = null;
        nextPhotoUrl = null;
    }

    // Public methods
    return {
        init: function() {
            // Initializing slideshow
            createBackgroundElements();
            isRunning = true;
            
            // Fetch the first two photo URLs
            fetchNextPhotoUrl().then(firstUrl => {
                if (firstUrl) {
                    currentPhotoUrl = firstUrl;
                    // Set the first image directly without transition
                    if (backgroundElement) {
                        backgroundElement.style.backgroundImage = `url(${firstUrl})`;
                    }
                    // Fetch the next photo URL for the first cycle
                    fetchNextPhotoUrl().then(secondUrl => {
                        nextPhotoUrl = secondUrl;
                    });
                } else {
                    console.error("Failed to fetch initial photo for slideshow.");
                }
            });
            return true;
        },

        start: function() {
            if (!isRunning) {
                isRunning = true;
                createBackgroundElements();
            }
            
            if (slideshowInterval) {
                clearInterval(slideshowInterval);
            }
            
            slideshowInterval = setInterval(cyclePhoto, SLIDESHOW_INTERVAL_MS);
            // Started background slideshow interval
        },

        stop: function() {
            if (slideshowInterval) {
                clearInterval(slideshowInterval);
                slideshowInterval = null;
                // Slideshow interval stopped
            }
            isRunning = false;
            isPreloading = false;
        },

        // Optional: force change might need adjustment based on preloading state
        changePhoto: function() {
             // Manual photo change requested
             cyclePhoto(); // Trigger the cycle logic immediately
        },
        
        cleanup: function() {
            cleanup();
        },
        
        isRunning: function() {
            return isRunning;
        }
    };
})();

export default Slideshow;