/**
 * Slideshow Component
 * Manages background photo slideshow functionality with preloading and smooth transitions
 */
const Slideshow = (function () {
  // Private variables
  let slideshowInterval = null;
  let SLIDESHOW_INTERVAL_MS = 30000; // Default: Change photo every 30 seconds
  let PRELOAD_DELAY_MS = 20000; // Default: Start preloading 20 seconds before transition
  let NETWORK_TIMEOUT_MS = 5000; // Default: Network timeout for photo fetching
  let currentPhotoUrl = null;
  let isPreloading = false;
  let isRunning = false;
  let backgroundElement = null;
  let nextBackgroundElement = null;
  let preloadTimer = null;

  // Private methods
  async function fetchNextPhotoUrl(maxAttempts = 5) {
    // Fetching next background photo URL with duplicate prevention
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      let timeoutId; // Declare outside try block for proper scope
      try {
        // Add timeout to prevent slideshow from being affected by server network issues
        const timeoutController = new AbortController();
        timeoutId = setTimeout(() => timeoutController.abort(), NETWORK_TIMEOUT_MS);

        const response = await fetch("/api/random-photo", {
          signal: timeoutController.signal,
        });
        clearTimeout(timeoutId);

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
          // On last attempt, return it anyway to prevent infinite loop
          if (attempt < maxAttempts - 1) {
            continue;
          } else {
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
        if (timeoutId) clearTimeout(timeoutId);
        if (error.name === "AbortError") {
          console.error(
            `Slideshow photo fetch timed out after ${NETWORK_TIMEOUT_MS / 1000} seconds (attempt`,
            attempt + 1 + ")"
          );
        } else {
          console.error("Could not fetch next photo URL (attempt", attempt + 1 + "):", error);
        }
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

  function setupPortraitDisplay(element, imageUrl, imgWidth, imgHeight) {
    // Remove any existing overlays
    const existingBlur = element.querySelector(".portrait-blur-bg");
    const existingSharp = element.querySelector(".portrait-sharp");
    if (existingBlur) existingBlur.remove();
    if (existingSharp) existingSharp.remove();

    // Calculate the width needed to fit the image height to viewport
    const viewportHeight = window.innerHeight;
    const imageAspectRatio = imgWidth / imgHeight;
    const displayedWidth = imageAspectRatio * viewportHeight * (1 / 0.75);

    // Create blurred background layer (fills entire viewport)
    const blurBg = document.createElement("div");
    blurBg.className = "portrait-blur-bg";
    blurBg.style.cssText = `
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background-image: url(${imageUrl});
      background-size: cover;
      background-position: center;
      background-repeat: no-repeat;
      filter: blur(20px) brightness(0.6);
      transform: scale(1.1);
      z-index: 0;
    `;
    element.appendChild(blurBg);

    // Create sharp center overlay element
    const sharpOverlay = document.createElement("div");
    sharpOverlay.className = "portrait-sharp";
    sharpOverlay.style.cssText = `
      position: absolute;
      top: 0;
      left: 50%;
      transform: translateX(-50%);
      width: ${displayedWidth}px;
      height: 100%;
      background-image: url(${imageUrl});
      background-size: 100% 133.33%;
      background-position: center top;
      background-repeat: no-repeat;
      z-index: 1;
    `;
    element.appendChild(sharpOverlay);

    return { blurBg, sharpOverlay };
  }

  function preloadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        img.onload = null;
        img.onerror = null;
        // Return both URL and dimensions for aspect ratio calculation
        resolve({ url, width: img.width, height: img.height });
      };
      img.onerror = () => {
        img.onload = null;
        img.onerror = null;
        reject(new Error(`Failed to load image: ${url}`));
      };
      img.src = url;
    });
  }

  function getOptimalBackgroundStyle(imgWidth, imgHeight) {
    const viewportRatio = window.innerWidth / window.innerHeight;
    const imageRatio = imgWidth / imgHeight;

    // Check if viewport is landscape (wider than tall)
    const isViewportLandscape = viewportRatio > 1.2;
    // Check if image is portrait (height is 10% larger than width)
    // This means width/height < 1/1.1 = 0.909...
    const isImagePortrait = imageRatio < 1 / 1.1;

    // For portrait images on landscape screens, use special handling
    if (isViewportLandscape && isImagePortrait) {
      return {
        size: "auto 100%", // Fit to viewport height, auto width
        position: "center top", // Center horizontally, align to top
        needsBlurredBackground: true, // Use blurred background fill
        isPortraitOptimized: true,
        cropTop75Percent: true, // Flag to indicate top 75% cropping
      };
    }

    // For landscape images or matching aspect ratios, use cover
    return {
      size: "cover",
      position: "center",
      needsBlurredBackground: false,
      isPortraitOptimized: false,
    };
  }

  // Calculate intelligent focus point based on image aspect ratio
  function getIntelligentFocusPoint(imgWidth, imgHeight) {
    const imageRatio = imgWidth / imgHeight;

    // Default focus points based on common photo compositions
    const focusPresets = {
      extremePortrait: "center 25%", // Focus on upper quarter (faces)
      tallPortrait: "center 30%", // Focus on upper third
      portrait: "center 35%", // Focus on upper-middle
      square: "center", // Center for square images
      landscape: "center", // Center for landscape
      panoramic: "center", // Center for panoramic
    };

    // Determine image type
    if (imageRatio < 0.5) return focusPresets.extremePortrait;
    if (imageRatio < 0.7) return focusPresets.tallPortrait;
    if (imageRatio < 0.9) return focusPresets.portrait;
    if (imageRatio < 1.1) return focusPresets.square;
    if (imageRatio < 2.0) return focusPresets.landscape;
    return focusPresets.panoramic;
  }

  function switchBackground(url, imgWidth, imgHeight) {
    if (!url || !isRunning) return;

    // Skip transition if it's the same as current image
    if (url === currentPhotoUrl) {
      return;
    }

    // Update current photo URL tracking
    currentPhotoUrl = url;

    // Determine optimal display style based on image and viewport aspect ratios
    const displayStyle = getOptimalBackgroundStyle(
      imgWidth || window.innerWidth,
      imgHeight || window.innerHeight
    );

    // Critical: Wait for image to be fully decoded before starting transition
    const testImg = new Image();
    testImg.onload = () => {
      if (!isRunning) return;

      // Force browser to decode the image completely
      testImg
        .decode()
        .then(() => {
          if (!isRunning) return;

          // Apply appropriate background style based on aspect ratio
          if (displayStyle.needsBlurredBackground && displayStyle.cropTop75Percent) {
            // Portrait image - clear main background and use layers
            nextBackgroundElement.style.backgroundImage = "";
            nextBackgroundElement.style.filter = "none";
            nextBackgroundElement.style.transform = "translateZ(0)";

            // Setup portrait display with blurred background and sharp center
            setupPortraitDisplay(nextBackgroundElement, url, imgWidth, imgHeight);
          } else {
            // Standard landscape image - remove any portrait layers
            const existingBlur = nextBackgroundElement.querySelector(".portrait-blur-bg");
            const existingSharp = nextBackgroundElement.querySelector(".portrait-sharp");
            if (existingBlur) existingBlur.remove();
            if (existingSharp) existingSharp.remove();

            // Apply standard background
            nextBackgroundElement.style.backgroundImage = `url(${url})`;
            nextBackgroundElement.style.backgroundSize = displayStyle.size;
            nextBackgroundElement.style.backgroundPosition = displayStyle.position;
            nextBackgroundElement.style.backgroundRepeat = "no-repeat";
            nextBackgroundElement.style.filter = "none";
            nextBackgroundElement.style.transform = "translateZ(0) scale(1.0)";
          }

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

          // Apply same styling without decode (fallback path)
          if (displayStyle.needsBlurredBackground && displayStyle.cropTop75Percent) {
            // Portrait image - clear main background and use layers
            nextBackgroundElement.style.backgroundImage = "";
            nextBackgroundElement.style.filter = "none";
            nextBackgroundElement.style.transform = "translateZ(0)";

            // Setup portrait display with blurred background and sharp center
            setupPortraitDisplay(nextBackgroundElement, url, imgWidth, imgHeight);
          } else {
            // Standard landscape image - remove any portrait layers
            const existingBlur = nextBackgroundElement.querySelector(".portrait-blur-bg");
            const existingSharp = nextBackgroundElement.querySelector(".portrait-sharp");
            if (existingBlur) existingBlur.remove();
            if (existingSharp) existingSharp.remove();

            // Apply standard background
            nextBackgroundElement.style.backgroundImage = `url(${url})`;
            nextBackgroundElement.style.backgroundSize = displayStyle.size;
            nextBackgroundElement.style.backgroundPosition = displayStyle.position;
            nextBackgroundElement.style.backgroundRepeat = "no-repeat";
            nextBackgroundElement.style.filter = "none";
            nextBackgroundElement.style.transform = "translateZ(0) scale(1.0)";
          }

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

  // Store preloaded image data including dimensions
  let nextPhotoData = null;

  async function cyclePhoto() {
    if (!isRunning || isPreloading) return;

    isPreloading = true;

    try {
      // If we have a preloaded image ready, use it
      if (nextPhotoData) {
        const imageData = nextPhotoData;
        nextPhotoData = null;

        // Display the preloaded image with dimension info
        switchBackground(imageData.url, imageData.width, imageData.height);

        // Start preparing next image immediately but asynchronously
        prepareNextImage();
      } else {
        // No preloaded image ready, fetch and load one now
        const url = await fetchNextPhotoUrl();
        if (url && isRunning) {
          const imageData = await preloadImage(url);
          if (isRunning) {
            // Check again after async operation
            switchBackground(imageData.url, imageData.width, imageData.height);

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
      if (!isRunning || nextPhotoData) return; // Already have one prepared

      try {
        const url = await fetchNextPhotoUrl();
        if (url && isRunning && !nextPhotoData) {
          // Double-check we still need it
          const imageData = await preloadImage(url);
          if (isRunning) {
            // Final check after async operation
            nextPhotoData = imageData;
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

    // Clean up portrait overlay DOM elements
    [backgroundElement, nextBackgroundElement].forEach((element) => {
      if (element) {
        const existingBlur = element.querySelector(".portrait-blur-bg");
        const existingSharp = element.querySelector(".portrait-sharp");
        if (existingBlur) existingBlur.remove();
        if (existingSharp) existingSharp.remove();
      }
    });

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
    nextPhotoData = null;
    currentPhotoUrl = null;
  }

  // Load slideshow configuration from server
  async function loadSlideshowConfig() {
    try {
      const response = await fetch("/api/config");
      const config = await response.json();

      // Update slideshow timing from config
      SLIDESHOW_INTERVAL_MS = (config.slideshow?.interval_seconds || 30) * 1000;
      PRELOAD_DELAY_MS = (config.slideshow?.preload_seconds || 20) * 1000;
      NETWORK_TIMEOUT_MS = (config.slideshow?.network_timeout_seconds || 5) * 1000;
    } catch (error) {
      console.error("Failed to load slideshow config:", error);
      // Keep default values if config load fails
    }
  }

  // Public methods
  return {
    init: async function () {
      // Load configuration from server first
      await loadSlideshowConfig();

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
          // Preload first image with dimensions
          const imageData = await preloadImage(firstUrl);

          // Set the first image directly without transition only after elements are verified
          if (backgroundElement && isRunning) {
            // Determine optimal display style for first image
            const displayStyle = getOptimalBackgroundStyle(imageData.width, imageData.height);

            // Apply the same styling logic as switchBackground
            if (displayStyle.needsBlurredBackground && displayStyle.cropTop75Percent) {
              // Portrait image - clear main background and use layers
              backgroundElement.style.backgroundImage = "";
              backgroundElement.style.filter = "none";
              backgroundElement.style.transform = "translateZ(0)";

              // Setup portrait display with blurred background and sharp center
              setupPortraitDisplay(
                backgroundElement,
                imageData.url,
                imageData.width,
                imageData.height
              );
            } else {
              // Standard landscape image
              backgroundElement.style.backgroundImage = `url(${imageData.url})`;
              backgroundElement.style.backgroundSize = displayStyle.size;
              backgroundElement.style.backgroundPosition = displayStyle.position;
              backgroundElement.style.backgroundRepeat = "no-repeat";
              backgroundElement.style.filter = "none";
              backgroundElement.style.transform = "translateZ(0) scale(1.0)";
            }

            backgroundElement.style.opacity = "1";
            currentPhotoUrl = imageData.url; // Track the first image
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
