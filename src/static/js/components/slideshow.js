/**
 * Slideshow Component
 * Manages background photo slideshow functionality
 */
const Slideshow = (function() {
    // Private variables
    let slideshowInterval = null;
    const SLIDESHOW_INTERVAL_MS = 30000; // Change photo every 30 seconds
    
    // Private methods
    function fetchAndSetBackgroundPhoto() {
        console.log("Fetching new background photo...");
        fetch('/api/random-photo')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.url) {
                    document.body.style.backgroundImage = `url(${data.url})`;
                } else if (data.error) {
                    console.error("Error fetching photo URL:", data.error);
                    // Optionally clear background or set a default
                    document.body.style.backgroundImage = 'none';
                }
            })
            .catch(error => {
                console.error('Could not fetch or set background photo:', error);
                // Optionally clear background or set a default
                document.body.style.backgroundImage = 'none';
            });
    }

    // Public methods
    return {
        init: function() {
            this.start(); // Start slideshow immediately on init
            return true;
        },
        
        start: function() {
            if (slideshowInterval) {
                clearInterval(slideshowInterval);
            }
            fetchAndSetBackgroundPhoto(); // Fetch first photo immediately
            // Set interval to fetch new photos
            slideshowInterval = setInterval(fetchAndSetBackgroundPhoto, SLIDESHOW_INTERVAL_MS);
            console.log(`Started background slideshow (interval: ${SLIDESHOW_INTERVAL_MS / 1000}s)`);
        },
        
        stop: function() {
            if (slideshowInterval) {
                clearInterval(slideshowInterval);
                slideshowInterval = null;
                console.log("Slideshow stopped");
            }
        },
        
        changePhoto: function() {
            fetchAndSetBackgroundPhoto();
        }
    };
})();

export default Slideshow;