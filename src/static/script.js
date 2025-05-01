document.addEventListener('DOMContentLoaded', function() {
    console.log("Calendar script loaded.");

    const calendar = document.querySelector('.calendar');
    const dailyViewContainer = document.querySelector('.daily-view-container');
    const today = new Date();
    const currentDay = today.getDate();
    const currentMonth = today.getMonth() + 1; // JS months are 0-indexed
    const currentYear = today.getFullYear();
    const todayCellSelector = `.calendar td[data-year="${currentYear}"][data-month="${currentMonth}"][data-day="${currentDay}"]`;
    const todayCell = document.querySelector(todayCellSelector);
    const initialDailyViewHTML = dailyViewContainer.innerHTML; // Store initial state

    let selectedCell = null;
    let inactivityTimer = null;
    let monthInactivityTimer = null; // New timer for month navigation
    const INACTIVITY_TIMEOUT = 60 * 1000; // 1 minute
    const MONTH_INACTIVITY_TIMEOUT = 300 * 1000; // 5 minutes for month navigation
    
    // Variables for Google Calendar update checking
    let googleUpdateTimer = null;
    const UPDATE_CHECK_INTERVAL = 300000; // Check every 5 minutes (300000ms)
    const INITIAL_CHECK_INTERVAL = 1000; // Check every 1 second initially until task completes
    const currentDisplayedMonth = parseInt(document.querySelector('.calendar').dataset.month || currentMonth);
    const currentDisplayedYear = parseInt(document.querySelector('.calendar').dataset.year || currentYear);
    let updateCheckEnabled = true; // Control flag
    let initialLoadComplete = false; // Flag to track whether we've completed initial load
    let inDebounce = false; // Debounce flag

    // Slideshow variables
    let slideshowInterval = null;
    const SLIDESHOW_INTERVAL_MS = 30000; // Change photo every 30 seconds

    // Modal variables
    const eventModal = document.getElementById('event-modal');
    const modalCloseButton = eventModal.querySelector('.close-button');
    const modalTitle = document.getElementById('modal-title');
    const modalCalendar = document.getElementById('modal-calendar');
    const modalTime = document.getElementById('modal-time');
    const modalLocation = document.getElementById('modal-location');
    const modalDescription = document.getElementById('modal-description');
    let modalCloseTimer = null;
    const MODAL_TIMEOUT = 15000; // 15 seconds

    // --- Helper Functions ---

    function applyWeatherGradient() {
        const currentWeatherDiv = document.querySelector('.current-weather');
        if (currentWeatherDiv && currentWeatherDiv.dataset.isDay !== undefined) {
            const isDay = currentWeatherDiv.dataset.isDay === '1' || currentWeatherDiv.dataset.isDay.toLowerCase() === 'true'; // Handle '1' or 'true'
            currentWeatherDiv.classList.remove('day-gradient', 'night-gradient'); // Remove existing
            if (isDay) {
                currentWeatherDiv.classList.add('day-gradient');
                console.log("Applied day gradient.");
            } else {
                currentWeatherDiv.classList.add('night-gradient');
                console.log("Applied night gradient.");
            }
        } else {
            console.warn("Could not find .current-weather div or data-is-day attribute.");
        }
    }

    function highlightToday() {
        if (todayCell) {
            // Ensure 'today' class isn't removed if it's also selected
            if (!todayCell.classList.contains('selected')) {
                 todayCell.classList.add('today');
            }
        }
    }

    function removeHighlight(cell) {
        if (cell) {
            cell.classList.remove('today'); // Remove today highlight if present
            cell.classList.remove('selected'); // Remove selected highlight
        }
    }

    function formatEventHTML(eventData) {
        let timeString = eventData.allDay === 'true'
            ? 'All Day'
            : `${eventData.startTime} - ${eventData.endTime}`;
        // Handle cases where start/end time might be missing for non-all-day events
        if (eventData.allDay !== 'true' && (!eventData.startTime || !eventData.endTime)) {
            timeString = eventData.startTime || eventData.endTime || 'Time not specified';
        }

        let locationString = eventData.location ? `<small>Location: ${eventData.location}</small><br>` : '';
        let descriptionString = eventData.description ? `<small>Notes: ${eventData.description}</small>` : '';

        return `
            <li style="border-left: 5px solid ${eventData.color || '#ccc'}; padding-left: 10px; margin-bottom: 10px;">
                <strong>${eventData.title}</strong> (${eventData.calendarName})<br>
                ${timeString}<br>
                ${locationString}
                ${descriptionString}
            </li>
        `;
    }

    function renderEvents(dayCell) {
        const day = dayCell.dataset.day;
        const month = dayCell.dataset.month;
        const year = dayCell.dataset.year;
        // Use UTC to avoid timezone issues when creating the date for formatting
        const clickedDate = new Date(Date.UTC(year, month - 1, day));
        const dateHeader = clickedDate.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' });

        const eventElements = dayCell.querySelectorAll('.events .event');
        let eventsHTML = '';

        if (eventElements.length > 0) {
            eventsHTML = '<ul>';
            eventElements.forEach(eventEl => {
                // Check if the element has the necessary data attributes
                if (eventEl.dataset.title && eventEl.dataset.calendarName) {
                    const eventData = {
                        title: eventEl.dataset.title,
                        calendarName: eventEl.dataset.calendarName,
                        allDay: eventEl.dataset.allDay,
                        startTime: eventEl.dataset.startTime,
                        endTime: eventEl.dataset.endTime,
                        location: eventEl.dataset.location,
                        description: eventEl.dataset.description,
                        color: eventEl.dataset.color
                    };
                    eventsHTML += formatEventHTML(eventData);
                } else {
                    console.warn("Skipping event element due to missing data attributes:", eventEl);
                }
            });
            eventsHTML += '</ul>';
        } else {
            eventsHTML = '<p>No events scheduled for this day.</p>';
        }

        dailyViewContainer.innerHTML = `<h2>${dateHeader}</h2>${eventsHTML}`;
    }

    function resetToToday() {
        console.log("Inactivity timeout reached. Reverting to today.");
        if (selectedCell) {
            removeHighlight(selectedCell); // Remove highlight from previously selected
            selectedCell = null;
        }
        highlightToday(); // Re-apply today's highlight
        dailyViewContainer.innerHTML = initialDailyViewHTML; // Restore initial right panel
        clearTimeout(inactivityTimer);
        inactivityTimer = null;
    }

    function startInactivityTimer() {
        clearTimeout(inactivityTimer); // Clear existing timer
        console.log(`Starting inactivity timer (${INACTIVITY_TIMEOUT / 1000}s)`);
        inactivityTimer = setTimeout(resetToToday, INACTIVITY_TIMEOUT);
    }

    function isCurrentMonthDisplayed() {
        // Check if the month/year being viewed is the current month/year
        return (currentDisplayedMonth === currentMonth && currentDisplayedYear === currentYear);
    }

    function resetToCurrentMonth() {
        console.log("Month inactivity timeout reached. Navigating back to current month.");
        if (!isCurrentMonthDisplayed()) {
            // Only navigate if we're not already on the current month
            window.location.href = `/calendar/${currentYear}/${currentMonth}`;
        }
    }

    function startMonthInactivityTimer() {
        clearTimeout(monthInactivityTimer); // Clear existing timer
        
        // Only start the timer if we're not on the current month
        if (!isCurrentMonthDisplayed()) {
            console.log(`Starting month inactivity timer (${MONTH_INACTIVITY_TIMEOUT / 1000}s)`);
            monthInactivityTimer = setTimeout(resetToCurrentMonth, MONTH_INACTIVITY_TIMEOUT);
        }
    }

    function checkForGoogleUpdates() {
        if (!updateCheckEnabled) return;
        
        fetch(`/check-updates/${currentDisplayedYear}/${currentDisplayedMonth}`)
            .then(response => response.json())
            .then(data => {
                console.log(`Update check: status=${data.status}, updates=${data.updates_available}`);
                
                // Handle first load differently from regular checks
                if (!initialLoadComplete) {
                    // If the task is complete, switch to regular interval
                    if (data.status === 'complete') {
                        console.log("Initial Google Calendar task completed.");
                        clearInterval(googleUpdateTimer);
                        googleUpdateTimer = setInterval(checkForGoogleUpdates, UPDATE_CHECK_INTERVAL);
                        console.log(`Switched to regular update interval (${UPDATE_CHECK_INTERVAL/1000}s)`);
                        initialLoadComplete = true;
                        
                        // If updates were found during initial load, refresh the page
                        if (data.updates_available) {
                            console.log("✅ Found new events during initial load, refreshing page");
                            refreshPage();
                        }
                    }
                    // Continue checking frequently until task completes
                } else {
                    // Only refresh during regular checks if updates are available AND we're not in a debounce period
                    if (data.updates_available && !inDebounce) {
                        console.log("✅ New Google Calendar events found during regular check");
                        refreshPage();
                    }
                }
            })
            .catch(err => {
                console.error("Error checking for Google Calendar updates:", err);
            });
    }

    function refreshPage() {
        // Show notification
        showUpdateNotification();
        
        // Temporarily disable further checks
        updateCheckEnabled = false;
        
        // Use a more reliable reload method
        setTimeout(() => {
            // Add cache busting parameter to prevent browser caching
            const cacheBuster = new Date().getTime();
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('_', cacheBuster);
            window.location.href = currentUrl.toString();
        }, 1500);
    }

    function startGoogleUpdateTimer() {
        // Clear any existing timer
        if (googleUpdateTimer) {
            clearInterval(googleUpdateTimer);
        }
        
        // Start with frequent checks until initial load completes
        googleUpdateTimer = setInterval(checkForGoogleUpdates, INITIAL_CHECK_INTERVAL);
        console.log(`Started initial Google Calendar update checker (checking every ${INITIAL_CHECK_INTERVAL/1000}s)`);
        
        // Do an immediate first check
        checkForGoogleUpdates();
    }

    function showUpdateNotification() {
        // Create a notification element
        const notification = document.createElement('div');
        notification.classList.add('update-notification');
        notification.textContent = 'New calendar events found! Refreshing...';
        
        // Style the notification
        Object.assign(notification.style, {
            position: 'fixed',
            top: '10px',
            left: '50%',
            transform: 'translateX(-50%)',
            backgroundColor: '#4CAF50',
            color: 'white',
            padding: '10px 20px',
            borderRadius: '4px',
            boxShadow: '0 2px 5px rgba(0,0,0,0.2)',
            zIndex: '1000',
            transition: 'opacity 0.3s ease'
        });
        
        // Add to the page
        document.body.appendChild(notification);
        
        // Remove after the page refreshes or 3 seconds (whichever comes first)
        setTimeout(() => {
            notification.style.opacity = '0';
            setTimeout(() => {
                if (document.body.contains(notification)) {
                    document.body.removeChild(notification);
                }
            }, 300);
        }, 3000);
    }

    // --- Modal Functions ---

    function showModal(eventData) {
        modalTitle.textContent = eventData.title || 'Event Details';
        modalCalendar.textContent = `Calendar: ${eventData.calendarName || 'N/A'}`;

        let timeString = 'N/A';
        if (eventData.allDay === 'true') {
            timeString = 'All Day';
        } else if (eventData.startTime && eventData.endTime) {
            timeString = `${eventData.startTime} - ${eventData.endTime}`;
        } else if (eventData.startTime) {
            timeString = `Starts at ${eventData.startTime}`;
        } else if (eventData.endTime) {
            timeString = `Ends at ${eventData.endTime}`;
        }
        modalTime.textContent = `Time: ${timeString}`;

        modalLocation.textContent = `Location: ${eventData.location || 'Not specified'}`;
        modalDescription.textContent = `Description: ${eventData.description || 'None'}`;

        // Set color border based on event color
        eventModal.querySelector('.modal-content').style.borderLeft = `5px solid ${eventData.color || '#ccc'}`;

        eventModal.style.display = 'block';

        // Start auto-close timer
        clearTimeout(modalCloseTimer); // Clear any existing timer
        modalCloseTimer = setTimeout(closeModal, MODAL_TIMEOUT);
        console.log(`Modal opened. Auto-closing in ${MODAL_TIMEOUT / 1000}s.`);
    }

    function closeModal() {
        eventModal.style.display = 'none';
        clearTimeout(modalCloseTimer); // Clear timer if closed manually
        modalCloseTimer = null;
        console.log("Modal closed.");
    }

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

    function startSlideshow() {
        // Clear any existing interval
        if (slideshowInterval) {
            clearInterval(slideshowInterval);
        }
        // Fetch the first photo immediately
        fetchAndSetBackgroundPhoto();
        // Set interval to fetch new photos
        slideshowInterval = setInterval(fetchAndSetBackgroundPhoto, SLIDESHOW_INTERVAL_MS);
        console.log(`Started background slideshow (interval: ${SLIDESHOW_INTERVAL_MS / 1000}s)`);
    }

    // --- Initialization ---

    highlightToday(); // Highlight today on load
    startGoogleUpdateTimer(); // Start checking for Google updates
    startSlideshow(); // Start the background photo slideshow
    applyWeatherGradient(); // Apply initial weather gradient

    // Add data attributes to the calendar for the current displayed month/year
    if (calendar) {
        calendar.dataset.month = currentDisplayedMonth;
        calendar.dataset.year = currentDisplayedYear;
    }
    
    // Start the month inactivity timer on page load
    startMonthInactivityTimer();

    // --- Event Listeners ---

    if (calendar) {
        calendar.addEventListener('click', function(event) {
            // Reset both inactivity timers on any calendar interaction
            startInactivityTimer();
            startMonthInactivityTimer();

            // Check if the click was on an event element
            const clickedEvent = event.target.closest('.event');
            if (clickedEvent) {
                console.log("Clicked on calendar event:", clickedEvent.dataset.title);
                const eventData = { ...clickedEvent.dataset }; // Clone dataset
                showModal(eventData);
                return; // Stop further processing for this click
            }

            // Find the closest parent TD element that has a data-day attribute
            const clickedCell = event.target.closest('td[data-day]');

            // Ensure we clicked a valid cell within the current month
            if (!clickedCell || !clickedCell.classList.contains('current-month')) {
                console.log("Click ignored: Not a valid current-month day cell.");
                return; // Ignore clicks outside valid day cells or on other-month cells
            }

            console.log("Clicked cell:", clickedCell.dataset.year, clickedCell.dataset.month, clickedCell.dataset.day);
            startInactivityTimer(); // Reset timer on interaction

            // If clicking the already selected cell, do nothing extra
            if (clickedCell === selectedCell) {
                console.log("Clicked the already selected cell.");
                return;
            }

            // Remove highlights from previous selection AND today (if it's not the clicked cell)
            if (selectedCell) {
                removeHighlight(selectedCell);
                console.log("Removed highlight from previously selected:", selectedCell);
            }
             // Only remove today's highlight if it's not the cell being clicked
            if (todayCell && todayCell !== clickedCell) {
                 removeHighlight(todayCell);
                 console.log("Removed highlight from today cell.");
            }

            // Highlight the new cell and update selection state
            clickedCell.classList.add('selected');
            selectedCell = clickedCell;
            console.log("Highlighted new cell:", selectedCell);

            // Render events for the clicked day
            renderEvents(clickedCell);
        });
    } else {
        console.error("Calendar element not found!");
    }

    // Add event listener for clicks within the daily view
    if (dailyViewContainer) {
        dailyViewContainer.addEventListener('click', function(event) {
            // Reset inactivity timer on interaction
            startInactivityTimer();

            // Check if the click was on an event list item (li)
            // We need to reconstruct the event data slightly differently here
            const clickedListItem = event.target.closest('li');
            if (clickedListItem) {
                console.log("Clicked on daily view event:", clickedListItem.querySelector('strong').textContent);
                // Attempt to find the corresponding event in the main calendar data
                // This is a bit tricky as the daily view has slightly different structure
                // A better approach might be to add data attributes to the daily view LI elements too
                // For now, we'll show a simplified modal or indicate data might be missing

                // Let's try to find the original event data if possible
                // This requires searching the DOM, which isn't ideal but works for now
                const title = clickedListItem.querySelector('strong').textContent;
                let originalEventElement = null;

                // Search within the selected cell first (if one exists)
                if (selectedCell) {
                    originalEventElement = selectedCell.querySelector(`.event[data-title="${title}"]`);
                }
                // If not found in selected cell, search today's cell (if applicable)
                if (!originalEventElement && todayCell) {
                     originalEventElement = todayCell.querySelector(`.event[data-title="${title}"]`);
                }

                if (originalEventElement) {
                     const eventData = { ...originalEventElement.dataset };
                     showModal(eventData);
                } else {
                    // Fallback if original data can't be easily found
                    console.warn("Could not find original data for daily view event. Showing basic info.");
                    const eventData = {
                        title: title,
                        // Extract other info from the LI if needed, though it's less structured
                        calendarName: clickedListItem.textContent.match(/\((.*?)\)/)?.[1] || 'N/A',
                        // ... other fields would need parsing from the text content ...
                        color: clickedListItem.style.borderLeftColor || '#ccc' // Get color from style
                    };
                    showModal(eventData); // Show with potentially limited data
                }
                return; // Stop further processing
            }
        });
    }

    // Modal Close Button Listener
    if (modalCloseButton) {
        modalCloseButton.addEventListener('click', closeModal);
    }

    // Close modal if clicked outside the content area
    window.addEventListener('click', function(event) {
        if (event.target == eventModal) {
            closeModal();
        }
    });

    // Reset both inactivity timers when user interacts with the page
    document.addEventListener('click', function() {
        startMonthInactivityTimer();
    });

    document.addEventListener('keydown', function() {
        startMonthInactivityTimer();
    });

    // Also reset the month timer when clicking month navigation links
    const navArrows = document.querySelectorAll('.nav-arrow');
    if (navArrows.length) {
        navArrows.forEach(arrow => {
            arrow.addEventListener('click', function() {
                // When navigating months, don't immediately start the timer
                // It will be started on the new page load
                clearTimeout(monthInactivityTimer);
            });
        });
    }

    // Handle page visibility changes to manage update checks
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            // Page is hidden, pause update checks
            updateCheckEnabled = false;
            if (googleUpdateTimer) {
                clearInterval(googleUpdateTimer);
                googleUpdateTimer = null;
            }
            console.log("Page hidden, paused Google Calendar update checks");
        } else {
            // Page is visible again, resume update checks
            updateCheckEnabled = true;
            // Reset initial load status to check immediately
            initialLoadComplete = false;
            startGoogleUpdateTimer();
            console.log("Page visible, resumed Google Calendar update checks");
        }
    });
});