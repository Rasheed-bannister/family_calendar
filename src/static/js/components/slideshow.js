/**
 * Slideshow Component
 * Manages background photo slideshow functionality with preloading
 */
const Slideshow = (function() {
    // Private variables
    let slideshowInterval = null;
    const SLIDESHOW_INTERVAL_MS = 30000; // Change photo every 30 seconds
    let currentPhotoUrl = null;
    let nextPhotoUrl = null;
    let isPreloading = false;

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

    function preloadAndSwitchBackground(url) {
        if (!url || isPreloading) return;
        
        // Preloading image
        isPreloading = true;
        const img = new Image();
        img.onload = () => {
            // Image preloaded, setting as background
            document.body.style.backgroundImage = `url(${url})`;
            currentPhotoUrl = url;
            isPreloading = false;
            // Fetch the *next* photo's URL immediately after switching
            fetchNextPhotoUrl().then(fetchedUrl => {
                nextPhotoUrl = fetchedUrl;
            });
        };
        img.onerror = () => {
            console.error("Error preloading image:", url);
            isPreloading = false;
            // Attempt to fetch a different photo URL for the next cycle
            fetchNextPhotoUrl().then(fetchedUrl => {
                nextPhotoUrl = fetchedUrl;
            });
        };
        img.src = url;
    }

    function cyclePhoto() {
        if (nextPhotoUrl && !isPreloading) {
            preloadAndSwitchBackground(nextPhotoUrl);
        } else if (!isPreloading) {
            // If nextPhotoUrl isn't ready, try fetching one now and maybe use it next cycle
            // Next photo URL not available for cycle, fetching again
            fetchNextPhotoUrl().then(fetchedUrl => {
                nextPhotoUrl = fetchedUrl;
                // Optionally, try preloading immediately if needed, 
                // but be cautious of race conditions or rapid retries.
                // preloadAndSwitchBackground(nextPhotoUrl);
            });
        }
    }

    // Public methods
    return {
        init: function() {
            // Initializing slideshow
            // Fetch the first two photo URLs
            fetchNextPhotoUrl().then(firstUrl => {
                if (firstUrl) {
                    // Preload and set the first image
                    preloadAndSwitchBackground(firstUrl);
                    // The onload handler for the first image will fetch the second URL
                    this.start(); // Start the interval timer after the first image is initiated
                } else {
                    console.error("Failed to fetch initial photo for slideshow.");
                }
            });
            return true;
        },

        start: function() {
            if (slideshowInterval) {
                clearInterval(slideshowInterval);
            }
            // Don't fetch immediately, rely on init and the cycle
            slideshowInterval = setInterval(cyclePhoto, SLIDESHOW_INTERVAL_MS);
            // Started background slideshow interval
        },

        stop: function() {
            if (slideshowInterval) {
                clearInterval(slideshowInterval);
                slideshowInterval = null;
                // Slideshow interval stopped
            }
            isPreloading = false; // Reset preloading state
        },

        // Optional: force change might need adjustment based on preloading state
        changePhoto: function() {
             // Manual photo change requested
             cyclePhoto(); // Trigger the cycle logic immediately
        }
    };
})();

export default Slideshow;