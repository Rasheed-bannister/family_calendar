/**
 * Calendar Component
 * Handles display and interactions with the calendar
 */
import Modal from './modal.js';
import DailyView from './dailyView.js';

const Calendar = (function() {
    // Private variables
    let calendar;
    let today;
    let currentDay;
    let currentMonth;
    let currentYear;
    let todayCell;
    let selectedCell = null;
    let inactivityTimer = null;
    let monthInactivityTimer = null;
    const INACTIVITY_TIMEOUT = 60 * 1000; // 1 minute
    const MONTH_INACTIVITY_TIMEOUT = 300 * 1000; // 5 minutes for month navigation
    let currentDisplayedMonth;
    let currentDisplayedYear;
    
    // Google Calendar update checking
    let googleUpdateTimer = null;
    const UPDATE_CHECK_INTERVAL = 300000; // Check every 5 minutes (300000ms)
    const INITIAL_CHECK_INTERVAL = 1000; // Check every 1 second initially until task completes
    let updateCheckEnabled = true; // Control flag
    let initialLoadComplete = false; // Flag to track whether we've completed initial load
    let inDebounce = false; // Debounce flag
    
    // Private methods
    function highlightToday() {
        if (todayCell) {
            todayCell.classList.add('today');
        }
    }

    function removeHighlight(cell) {
        // Only remove 'selected', keep 'today' if present
        if (cell) {
            cell.classList.remove('selected');
        }
    }

    function resetToToday() {
        console.log("Inactivity timeout reached. Reverting to today.");
        // No need to manually remove highlight here, the click handler will manage it.
        
        if (todayCell) {
            // Simulate a click on today's cell to reset state and view
            todayCell.click(); 
            console.log("Triggered click on today's cell to reset.");
        } else {
            // If today is not visible (different month), reset to placeholder
            // Also clear selection state if something else was selected
            if (selectedCell) {
                removeHighlight(selectedCell);
                selectedCell = null;
            }
            DailyView.resetToPlaceholder();
            console.log("Reset view to placeholder as today is not visible.");
        }

        clearTimeout(inactivityTimer);
        inactivityTimer = null;
    }

    function startInactivityTimer() {
        clearTimeout(inactivityTimer); 
        inactivityTimer = setTimeout(resetToToday, INACTIVITY_TIMEOUT);
    }

    function isCurrentMonthDisplayed() {
        return (currentDisplayedMonth === currentMonth && currentDisplayedYear === currentYear);
    }

    function resetToCurrentMonth() {
        if (!isCurrentMonthDisplayed()) {
            // Only navigate if we're not already on the current month
            window.location.href = `/calendar/${currentYear}/${currentMonth}`;
        }
    }

    function startMonthInactivityTimer() {
        clearTimeout(monthInactivityTimer); 
        
        // Only start the timer if we're not on the current month
        if (!isCurrentMonthDisplayed()) {
            console.log(`Starting month inactivity timer (${MONTH_INACTIVITY_TIMEOUT / 1000}s)`);
            monthInactivityTimer = setTimeout(resetToCurrentMonth, MONTH_INACTIVITY_TIMEOUT);
        }
    }

    function checkForGoogleUpdates() {
        if (!updateCheckEnabled) return;

        fetch(`/calendar/check-updates/${currentDisplayedYear}/${currentDisplayedMonth}`)
            .then(response => {
                if (!response.ok) {
                    // Handle HTTP errors like 404, 500 etc.
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                // Handle first load differently from regular checks
                if (!initialLoadComplete) {
                    // If the task is complete, switch to regular interval
                    if (data.status === 'complete') {
                        clearInterval(googleUpdateTimer);
                        googleUpdateTimer = setInterval(checkForGoogleUpdates, UPDATE_CHECK_INTERVAL);
                        initialLoadComplete = true;
                        
                        // If updates were found during initial load, refresh the page
                        if (data.updates_available) {
                            refreshPage();
                        }
                    }
                } else {
                    // Only refresh during regular checks if updates are available AND we're not in a debounce period
                    if (data.updates_available && !inDebounce) {
                        refreshPage();
                    }
                }
            })
            .catch(err => {
                // Log different messages based on the error type
                if (err instanceof TypeError && err.message === 'Failed to fetch') {
                    // This is often a network/connection error
                    console.error("Error checking for Google Calendar updates: Could not connect to the server (ERR_CONNECTION_REFUSED or similar). Is the Flask server running?");
                    // Optionally, you could try to disable further checks or implement a retry
                    // updateCheckEnabled = false; // Stop checking if connection fails
                } else {
                    // Other errors (e.g., JSON parsing, HTTP errors)
                    console.error("Error checking for Google Calendar updates:", err);
                }
                // Stop the rapid initial checks if an error occurs
                if (!initialLoadComplete) {
                    clearInterval(googleUpdateTimer);
                    // Optionally switch to the slower interval even on error, or stop completely
                    // googleUpdateTimer = setInterval(checkForGoogleUpdates, UPDATE_CHECK_INTERVAL);
                    console.warn("Stopping rapid initial update checks due to error.");
                    initialLoadComplete = true; // Mark initial phase as done (even if failed)
                }
            });
    }

    function refreshPage() {
        showUpdateNotification();

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

    function setupEventListeners() {
        if (!calendar) return;
        
        calendar.addEventListener('click', function(event) {
            // Reset both inactivity timers on any calendar interaction
            startInactivityTimer();
            startMonthInactivityTimer();

            // Check if the click was on an event element
            const clickedEvent = event.target.closest('.event');
            if (clickedEvent) {
                console.log("Clicked on calendar event:", clickedEvent.dataset.title);
                const eventData = { ...clickedEvent.dataset }; // Clone dataset
                Modal.show(eventData);
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
            // No need to reset inactivity timer here, already done at the start

            // Remove selected class from the previous selection
            if (selectedCell && selectedCell !== clickedCell) {
                removeHighlight(selectedCell); // Now only removes 'selected'
                console.log("Removed selected highlight from previously selected:", selectedCell);
            }
            
            // Highlight the new cell and update selection state
            // Ensure 'today' class is preserved if clicking today
            highlightToday(); // Re-apply today class just in case
            clickedCell.classList.add('selected');
            selectedCell = clickedCell;
            console.log("Highlighted new cell:", selectedCell);

            // Render events for the clicked day
            DailyView.renderEvents(clickedCell);
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
        
        // Reset month timer when user interacts with the page
        document.addEventListener('click', function() {
            startMonthInactivityTimer();
        });

        document.addEventListener('keydown', function() {
            startMonthInactivityTimer();
        });
        
        // Handle page visibility changes to manage update checks
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                // Page is hidden, pause update checks
                updateCheckEnabled = false;
                if (googleUpdateTimer) {
                    clearInterval(googleUpdateTimer);
                    googleUpdateTimer = null;
                }
                console.log("Page hidden, paused calendar update checks");
            } else {
                // Page is visible again, resume update checks
                updateCheckEnabled = true;
                // Reset initial load status to check immediately
                initialLoadComplete = false;
                startGoogleUpdateTimer();
                console.log("Page visible, resumed calendar update checks");
            }
        });
    }

    // Public methods
    return {
        init: function() {
            calendar = document.querySelector('.calendar');
            if (!calendar) {
                console.error("Calendar component: Calendar element not found!");
                return false;
            }
            
            today = new Date();
            currentDay = today.getDate();
            currentMonth = today.getMonth() + 1; // JS months are 0-indexed
            currentYear = today.getFullYear();
            
            const todayCellSelector = `.calendar td[data-year="${currentYear}"][data-month="${currentMonth}"][data-day="${currentDay}"]`;
            todayCell = document.querySelector(todayCellSelector);
            
            currentDisplayedMonth = parseInt(calendar.dataset.month || currentMonth);
            currentDisplayedYear = parseInt(calendar.dataset.year || currentYear);
            
            // Add data attributes to the calendar for the current displayed month/year if missing
            if (calendar) {
                if (!calendar.dataset.month) calendar.dataset.month = currentDisplayedMonth;
                if (!calendar.dataset.year) calendar.dataset.year = currentDisplayedYear;
            }
            
            // Initialize DailyView first to capture initial HTML
            DailyView.init();

            // Setup listeners before triggering the initial click
            setupEventListeners();
            
            // Apply base 'today' styling
            highlightToday(); 

            // Simulate a click on today's cell if it exists on the current view
            if (todayCell) {
                console.log("Triggering initial click on today's cell.");
                todayCell.click(); // This will handle selection and rendering via the click listener
            } else {
                 // If today is not on this month view, clear the daily view initially.
                 DailyView.resetToPlaceholder(); 
                 console.log("Today not visible, reset daily view to placeholder.");
            }
            
            startGoogleUpdateTimer(); // Start checking for Google updates
            startMonthInactivityTimer(); // Start the month inactivity timer
            
            return true;
        },
        
        pause: function() {
            updateCheckEnabled = false;
            if (googleUpdateTimer) {
                clearInterval(googleUpdateTimer);
                googleUpdateTimer = null;
            }
        },
        
        resume: function() {
            updateCheckEnabled = true;
            initialLoadComplete = false;
            startGoogleUpdateTimer();
        },
        
        getTodayCell: function() {
            return todayCell;
        },
        
        getCurrentDate: function() {
            return {
                day: currentDay,
                month: currentMonth,
                year: currentYear
            };
        }
    };
})();

export default Calendar;