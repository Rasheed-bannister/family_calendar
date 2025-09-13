/**
 * Slideshow Component
 * Manages background photo slideshow functionality with preloading and smooth transitions
 */
const Slideshow = (function () {
  // Private variables
  let slideshowInterval = null;
  const SLIDESHOW_INTERVAL_MS = 30000; // Change photo every 30 seconds
  let nextPhotoUrl = null;
  let currentPhotoUrl = null;
  let isPreloading = false;
  let isRunning = false;
  let backgroundElement = null;
  let nextBackgroundElement = null;
  let preloadTimer = null;
  const PRELOAD_DELAY_MS = 20000; // Start preloading 10 seconds before transition

  // Private methods
  async function fetchNextPhotoUrl(maxAttempts = 5) {
    // Fetching next background photo URL with duplicate prevention
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        const response = await fetch("/api/random-photo");
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        if (data.url) {
          // Check if this URL is different from the current one
          if (data.url !== currentPhotoUrl) {
            return data.url;
          }
          // If it's the same, try again (unless it's our last attempt)
          if (attempt < maxAttempts - 1) {
            continue;
          } else {
            // On last attempt, return it anyway to prevent infinite loop
            console.warn(
              "Could not find different image after",
              maxAttempts,
              "attempts, using duplicate"
            );
            return data.url;
          }
        } else if (data.error) {
          console.error("Error fetching photo URL:", data.error);
          return null;
        }
        return null;
      } catch (error) {
        console.error("Could not fetch next photo URL (attempt", attempt + 1 + "):", error);
        if (attempt === maxAttempts - 1) {
          return null;
        }
      }
    }
    return null;
  }

  function createBackgroundElements() {
    // Create main background element
    if (!backgroundElement) {
      backgroundElement = document.createElement("div");
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
                will-change: opacity;
                transform: translateZ(0);
                backface-visibility: hidden;
                isolation: isolate;
                contain: layout paint;
            `;
      document.body.appendChild(backgroundElement);
    }

    // Create next background element for smooth transitions
    if (!nextBackgroundElement) {
      nextBackgroundElement = document.createElement("div");
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
                will-change: opacity;
                transform: translateZ(0);
                backface-visibility: hidden;
                isolation: isolate;
                contain: layout paint;
            `;
      document.body.appendChild(nextBackgroundElement);
    }
  }

  function preloadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        img.onload = null;
        img.onerror = null;
        resolve(url);
      };
      img.onerror = () => {
        img.onload = null;
        img.onerror = null;
        reject(new Error(`Failed to load image: ${url}`));
      };
      img.src = url;
    });
  }

  function switchBackground(url) {
    if (!url || !isRunning) return;

    // Skip transition if it's the same as current image
    if (url === currentPhotoUrl) {
      return;
    }

    // Update current photo URL tracking
    currentPhotoUrl = url;

    // Critical: Wait for image to be fully decoded before starting transition
    const testImg = new Image();
    testImg.onload = () => {
      if (!isRunning) return;

      // Force browser to decode the image completely
      testImg
        .decode()
        .then(() => {
          if (!isRunning) return;

          // Set the new image on the front element AFTER it's decoded
          nextBackgroundElement.style.backgroundImage = `url(${url})`;
          nextBackgroundElement.style.opacity = "0";

          // Single-step crossfade: fade out current, then fade in new
          // This eliminates compositor conflicts from simultaneous transitions
          requestAnimationFrame(() => {
            // First: fade out the current image completely
            backgroundElement.style.opacity = "0";

            // Then: after a brief moment, start fading in the new image
            setTimeout(() => {
              if (!isRunning) return;
              nextBackgroundElement.style.opacity = "1";
            }, 50); // Very brief delay to ensure clean transition
          });
        })
        .catch(() => {
          // Fallback if decode() not supported
          if (!isRunning) return;
          nextBackgroundElement.style.backgroundImage = `url(${url})`;
          nextBackgroundElement.style.opacity = "0";

          requestAnimationFrame(() => {
            backgroundElement.style.opacity = "0";
            setTimeout(() => {
              if (!isRunning) return;
              nextBackgroundElement.style.opacity = "1";
            }, 50);
          });
        });
    };

    testImg.onerror = () => {
      console.error("Failed to load image for transition:", url);
    };

    testImg.src = url;

    // After transition completes, clean up and swap references
    setTimeout(() => {
      if (!isRunning) return;

      // Clear the old background image and reset its opacity
      backgroundElement.style.backgroundImage = "";
      backgroundElement.style.opacity = "1";

      // Swap the element references for next transition
      const temp = backgroundElement;
      backgroundElement = nextBackgroundElement;
      nextBackgroundElement = temp;
    }, 2050); // Slightly longer to account for the 50ms delay
  }

  async function cyclePhoto() {
    if (!isRunning || isPreloading) return;

    isPreloading = true;

    try {
      // If we have a preloaded URL ready, use it
      if (nextPhotoUrl) {
        const urlToDisplay = nextPhotoUrl;
        nextPhotoUrl = null;

        // Display the preloaded image
        switchBackground(urlToDisplay);

        // Start preparing next image immediately but asynchronously
        prepareNextImage();
      } else {
        // No preloaded image ready, fetch and load one now
        const url = await fetchNextPhotoUrl();
        if (url && isRunning) {
          await preloadImage(url);
          if (isRunning) {
            // Check again after async operation
            switchBackground(url);

            // Start preparing next image
            prepareNextImage();
          }
        }
      }
    } catch (error) {
      console.error("Error in cyclePhoto:", error);
    } finally {
      isPreloading = false;
    }
  }

  async function prepareNextImage() {
    // Non-blocking preparation of next image
    setTimeout(async () => {
      if (!isRunning || nextPhotoUrl) return; // Already have one prepared

      try {
        const url = await fetchNextPhotoUrl();
        if (url && isRunning && !nextPhotoUrl) {
          // Double-check we still need it
          await preloadImage(url);
          if (isRunning) {
            // Final check after async operation
            nextPhotoUrl = url;
          }
        }
      } catch (error) {
        console.error("Error preparing next image:", error);
      }
    }, PRELOAD_DELAY_MS);
  }

  function cleanup() {
    // Clean up resources to prevent memory leaks
    if (slideshowInterval) {
      clearInterval(slideshowInterval);
      slideshowInterval = null;
    }

    if (preloadTimer) {
      clearTimeout(preloadTimer);
      preloadTimer = null;
    }

    if (backgroundElement && backgroundElement.parentNode) {
      backgroundElement.parentNode.removeChild(backgroundElement);
      backgroundElement = null;
    }

    if (nextBackgroundElement && nextBackgroundElement.parentNode) {
      nextBackgroundElement.parentNode.removeChild(nextBackgroundElement);
      nextBackgroundElement = null;
    }

    // Clear any body background styles that might conflict
    document.body.style.background = "none";
    document.body.style.backgroundImage = "";
    document.body.style.backgroundSize = "";
    document.body.style.backgroundPosition = "";
    document.body.style.backgroundRepeat = "";

    isRunning = false;
    isPreloading = false;
    nextPhotoUrl = null;
    currentPhotoUrl = null;
  }

  // Public methods
  return {
    init: async function () {
      // Ensure elements are created before setting running state
      createBackgroundElements();

      // Set running state after elements are ready
      isRunning = true;

      // Add slideshow-active class immediately after elements are ready
      document.body.classList.add("slideshow-active");

      try {
        // Fetch and load the first image
        const firstUrl = await fetchNextPhotoUrl();
        if (firstUrl) {
          // Preload first image
          await preloadImage(firstUrl);

          // Set the first image directly without transition only after elements are verified
          if (backgroundElement && isRunning) {
            backgroundElement.style.backgroundImage = `url(${firstUrl})`;
            backgroundElement.style.opacity = "1";
            currentPhotoUrl = firstUrl; // Track the first image
          }

          // Start preparing the second image using the coordinated function
          prepareNextImage();
        } else {
          console.error("Failed to fetch initial photo for slideshow.");
        }
      } catch (error) {
        console.error("Error initializing slideshow:", error);
      }

      return true;
    },

    start: function () {
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

    stop: function () {
      if (slideshowInterval) {
        clearInterval(slideshowInterval);
        slideshowInterval = null;
        // Slideshow interval stopped
      }
      isRunning = false;
      isPreloading = false;
    },

    // Optional: force change might need adjustment based on preloading state
    changePhoto: function () {
      // Manual photo change requested
      cyclePhoto(); // Trigger the cycle logic immediately
    },

    cleanup: function () {
      cleanup();
    },

    isRunning: function () {
      return isRunning;
    },
  };
})();

export default Slideshow;
