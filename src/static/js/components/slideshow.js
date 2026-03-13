/**
 * Slideshow Component
 * Manages background photo slideshow functionality with preloading and smooth transitions
 */
const Slideshow = (function () {
  // Private variables
  let slideshowInterval = null;
  const SLIDESHOW_INTERVAL_MS = 30000; // Change photo every 30 seconds
  const EMPTY_RECHECK_INTERVAL_MS = 5 * 60 * 1000; // Recheck for photos every 5 minutes when none exist
  let nextPhotoUrl = null;
  let currentPhotoUrl = null;
  let isPreloading = false;
  let isRunning = false;
  let photosAvailable = true; // Assume available until proven otherwise
  let emptyRecheckTimer = null;
  let backgroundElement = null;
  let nextBackgroundElement = null;
  let preloadTimer = null;
  let transitionTimer = null; // Track the post-transition cleanup timeout
  let prepareNextTimer = null; // Track the prepareNextImage timeout
  let activeImage = null; // Track current Image object for cleanup
  const PRELOAD_DELAY_MS = 20000; // Start preloading 10 seconds before transition

  // Private methods
  async function fetchNextPhotoUrl(maxAttempts = 3) {
    // If we know there are no photos, don't bother fetching
    if (!photosAvailable) {
      return null;
    }

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        const response = await fetch("/api/random-photo");
        if (!response.ok) {
          console.error("Error fetching photo URL: HTTP", response.status);
          return null;
        }

        const data = await response.json();

        // Server told us the photo library is empty — this is not an error
        if (data.empty) {
          photosAvailable = false;
          scheduleEmptyRecheck();
          return null;
        }

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

  function scheduleEmptyRecheck() {
    // Don't stack multiple recheck timers
    if (emptyRecheckTimer) return;

    emptyRecheckTimer = setTimeout(async () => {
      emptyRecheckTimer = null;
      try {
        const response = await fetch("/api/random-photo");
        if (response.ok) {
          const data = await response.json();
          if (data.url) {
            // Photos are now available — resume the slideshow
            photosAvailable = true;
            if (isRunning) {
              cyclePhoto();
            }
            return;
          }
        }
      } catch (error) {
        // Ignore — we'll retry later
      }
      // Still no photos, schedule another recheck
      if (isRunning || backgroundElement) {
        scheduleEmptyRecheck();
      }
    }, EMPTY_RECHECK_INTERVAL_MS);
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

    // Clean up any previous in-flight Image object
    if (activeImage) {
      activeImage.onload = null;
      activeImage.onerror = null;
      activeImage.src = "";
      activeImage = null;
    }

    // Cancel any pending transition cleanup from a previous cycle
    if (transitionTimer) {
      clearTimeout(transitionTimer);
      transitionTimer = null;
    }

    // Critical: Wait for image to be fully decoded before starting transition
    const testImg = new Image();
    activeImage = testImg;

    function applyTransition() {
      if (!isRunning) return;

      // Set the new image on the front element AFTER it's decoded
      nextBackgroundElement.style.backgroundImage = `url(${url})`;
      nextBackgroundElement.style.opacity = "0";

      // Single-step crossfade: fade out current, then fade in new
      requestAnimationFrame(() => {
        backgroundElement.style.opacity = "0";
        setTimeout(() => {
          if (!isRunning) return;
          nextBackgroundElement.style.opacity = "1";
        }, 50);
      });
    }

    testImg.onload = () => {
      // Clear the reference since loading is complete
      if (activeImage === testImg) activeImage = null;
      testImg.onload = null;
      testImg.onerror = null;

      if (!isRunning) return;

      // Force browser to decode the image completely
      testImg
        .decode()
        .then(() => applyTransition())
        .catch(() => applyTransition()); // Fallback if decode() not supported
    };

    testImg.onerror = () => {
      if (activeImage === testImg) activeImage = null;
      testImg.onload = null;
      testImg.onerror = null;
      console.error("Failed to load image for transition:", url);
    };

    testImg.src = url;

    // After transition completes, clean up and swap references
    transitionTimer = setTimeout(() => {
      transitionTimer = null;
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
    if (!isRunning || isPreloading || !photosAvailable) return;

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
    // Cancel any pending prepare timer
    if (prepareNextTimer) {
      clearTimeout(prepareNextTimer);
      prepareNextTimer = null;
    }

    // Non-blocking preparation of next image
    prepareNextTimer = setTimeout(async () => {
      prepareNextTimer = null;
      if (!isRunning || nextPhotoUrl || !photosAvailable) return;

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

  function applyDefaultBackground() {
    // Show a simple dark background when no photos are available
    if (backgroundElement) {
      backgroundElement.style.backgroundImage = "none";
      backgroundElement.style.backgroundColor = "#1a1a2e";
      backgroundElement.style.opacity = "1";
    }
    if (nextBackgroundElement) {
      nextBackgroundElement.style.backgroundImage = "none";
      nextBackgroundElement.style.opacity = "0";
    }
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

    if (transitionTimer) {
      clearTimeout(transitionTimer);
      transitionTimer = null;
    }

    if (prepareNextTimer) {
      clearTimeout(prepareNextTimer);
      prepareNextTimer = null;
    }

    if (emptyRecheckTimer) {
      clearTimeout(emptyRecheckTimer);
      emptyRecheckTimer = null;
    }

    // Clean up any in-flight Image object
    if (activeImage) {
      activeImage.onload = null;
      activeImage.onerror = null;
      activeImage.src = "";
      activeImage = null;
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
    photosAvailable = true;
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
        } else if (!photosAvailable) {
          // No photos exist — show default background and wait for photos to appear
          applyDefaultBackground();
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

      // Only start the cycling interval if photos are available
      if (photosAvailable) {
        slideshowInterval = setInterval(cyclePhoto, SLIDESHOW_INTERVAL_MS);
      }
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
