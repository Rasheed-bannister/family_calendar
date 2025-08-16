/**
 * Calendar Component
 * Handles display and interactions with the calendar
 */
import Modal from './modal.js';
import DailyView from './dailyView.js';
import LoadingIndicator from './loadingIndicator.js';

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
    let UPDATE_CHECK_INTERVAL = 300000; // Default: Check every 5 minutes, will be loaded from config
    const INITIAL_CHECK_INTERVAL = 5000; // Check every 5 seconds initially until task completes
    let FORCE_REFRESH_INTERVAL = 600000; // Default: Force refresh every 10 minutes, will be loaded from config
    let updateCheckEnabled = true; // Control flag
    let initialLoadComplete = false; // Flag to track whether we've completed initial load
    let inDebounce = false; // Debounce flag
    let initialLoadTimeout = null; // Timeout to force refresh if initial load takes too long
    const INITIAL_LOAD_TIMEOUT = 15000; // Force refresh after 15 seconds if no update received
    let lastForceRefreshTime = Date.now(); // Track when we last forced a refresh
    
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
        // Inactivity timeout reached, reverting to today
        // No need to manually remove highlight here, the click handler will manage it.
        
        if (todayCell) {
            // Simulate a click on today's cell to reset state and view
            todayCell.click(); 
            // Triggered click on today's cell to reset
        } else {
            // If today is not visible (different month), reset to placeholder
            // Also clear selection state if something else was selected
            if (selectedCell) {
                removeHighlight(selectedCell);
                selectedCell = null;
            }
            DailyView.resetToPlaceholder();
            // Reset view to placeholder as today is not visible
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
            // Starting month inactivity timer
            monthInactivityTimer = setTimeout(resetToCurrentMonth, MONTH_INACTIVITY_TIMEOUT);
        }
    }

    function checkForGoogleUpdates() {
        if (!updateCheckEnabled) return;
        
        // Show loading indicator for initial sync operations
        if (!initialLoadComplete) {
            LoadingIndicator.show('google-sync', 'Syncing calendar events...', false);
        }

        // Check if it's time for a force refresh
        const now = Date.now();
        const timeSinceLastForceRefresh = now - lastForceRefreshTime;
        
        if (timeSinceLastForceRefresh > FORCE_REFRESH_INTERVAL) {
            // Triggering force refresh of calendar data
            LoadingIndicator.show('google-refresh', 'Refreshing calendar data...', false);
            lastForceRefreshTime = now;
            
            // Trigger manual refresh
            fetch(`/google/refresh-calendar/${currentDisplayedYear}/${currentDisplayedMonth}`, {
                method: 'GET'
            })
            .then(response => response.json())
            .then(() => {
                // Manual refresh triggered
                LoadingIndicator.hide('google-refresh');
                LoadingIndicator.showToast('Calendar refreshed', 'success', 2000);
                // Continue with normal update check after triggering refresh
                setTimeout(checkForGoogleUpdates, 2000); // Check again in 2 seconds
            })
            .catch(err => {
                console.error("Error triggering manual refresh:", err);
                LoadingIndicator.hide('google-refresh');
                LoadingIndicator.showToast('Refresh failed - using cached data', 'error', 3000);
            });
            return;
        }

        fetch(`/calendar/check-updates/${currentDisplayedYear}/${currentDisplayedMonth}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                // Update check response received
                
                // Handle first load differently from regular checks
                if (!initialLoadComplete) {
                    // If there are no calendar cells with events, we need to wait for data
                    const hasCalendarEvents = document.querySelectorAll('.calendar .event').length > 0;
                    
                    if (data.calendar_status === 'complete') {
                        // Clear any pending initial load timeout
                        if (initialLoadTimeout) {
                            clearTimeout(initialLoadTimeout);
                            initialLoadTimeout = null;
                        }
                        
                        // Hide loading indicator and show success
                        LoadingIndicator.hide('google-sync');
                        LoadingIndicator.showToast('Calendar sync complete', 'success', 2000);
                        
                        // Switch to regular interval - we're done with initial loading
                        clearInterval(googleUpdateTimer);
                        googleUpdateTimer = setInterval(checkForGoogleUpdates, UPDATE_CHECK_INTERVAL);
                        initialLoadComplete = true;
                        
                        // If updates were found or the page has no events yet but the fetch is complete,
                        // refresh the page to show the newly loaded events
                        if (data.events_changed || (!hasCalendarEvents && data.calendar_status === 'complete')) {
                            LoadingIndicator.showToast('Updates found! Refreshing...', 'info', 2000);
                            refreshPage();
                        }
                    }
                } else {
                    // Handle regular update checks
                    if (data.refresh_triggered) {
                        // Background refresh was triggered, checking again soon
                        // Check again in 3 seconds to see if the refresh found new data
                        setTimeout(checkForGoogleUpdates, 3000);
                    } else if (data.updates_available && !inDebounce) {
                        // Only refresh during regular checks if updates are available AND we're not in a debounce period
                        refreshPage();
                    } else if (data.calendar_status === 'complete' && data.events_changed) {
                        // Handle case where events changed but updates_available wasn't set
                        refreshPage();
                    }
                }
            })
            .catch(err => {
                // Log different messages based on the error type
                if (err instanceof TypeError && err.message === 'Failed to fetch') {
                    console.error("Error checking for Google Calendar updates: Could not connect to the server. Is the Flask server running?");
                } else {
                    console.error("Error checking for Google Calendar updates:", err);
                }
                
                // Stop the rapid initial checks if an error occurs
                if (!initialLoadComplete) {
                    LoadingIndicator.hide('google-sync');
                    LoadingIndicator.showToast('Sync error - using cached data', 'error', 3000);
                    clearInterval(googleUpdateTimer);
                    // Stopping rapid initial update checks due to error
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
        // Started initial Google Calendar update checker
        
        // Set timeout to force refresh if initial load takes too long
        if (initialLoadTimeout) {
            clearTimeout(initialLoadTimeout);
        }
        
        initialLoadTimeout = setTimeout(() => {
            // Initial load timeout reached, forcing refresh
            if (!initialLoadComplete) {
                refreshPage();
            }
        }, INITIAL_LOAD_TIMEOUT);
        
        // Do an immediate first check
        checkForGoogleUpdates();
    }

    function showUpdateNotification() {
        // Use the centralized LoadingIndicator component instead of custom notification
        LoadingIndicator.showToast('Calendar events loading... Please wait.', 'info', 3000);
    }

    // Swipe gesture variables
    let touchStartX = 0;
    let touchStartY = 0;
    let touchEndX = 0;
    let touchEndY = 0;
    const MIN_SWIPE_DISTANCE = 50;
    const MAX_VERTICAL_DRIFT = 100;

    function setupEventListeners() {
        if (!calendar) return;
        
        // Add swipe gesture support
        const calendarContainer = document.querySelector('.calendar-container');
        if (calendarContainer) {
            // Touch events for swipe gestures
            calendarContainer.addEventListener('touchstart', function(event) {
                touchStartX = event.changedTouches[0].screenX;
                touchStartY = event.changedTouches[0].screenY;
            }, { passive: true });

            calendarContainer.addEventListener('touchend', function(event) {
                touchEndX = event.changedTouches[0].screenX;
                touchEndY = event.changedTouches[0].screenY;
                handleSwipeGesture();
            }, { passive: true });

            // Mouse events for desktop swipe simulation
            let mouseDown = false;
            calendarContainer.addEventListener('mousedown', function(event) {
                mouseDown = true;
                touchStartX = event.screenX;
                touchStartY = event.screenY;
            });

            calendarContainer.addEventListener('mouseup', function(event) {
                if (mouseDown) {
                    touchEndX = event.screenX;
                    touchEndY = event.screenY;
                    handleSwipeGesture();
                    mouseDown = false;
                }
            });

            calendarContainer.addEventListener('mouseleave', function() {
                mouseDown = false;
            });
        }

        // Setup date picker and today button
        setupNavigationControls();
        
        calendar.addEventListener('click', function(event) {
            // Reset both inactivity timers on any calendar interaction
            startInactivityTimer();
            startMonthInactivityTimer();

            // Check if the click was on an event element
            const clickedEvent = event.target.closest('.event');
            if (clickedEvent) {
                // Clicked on calendar event
                const eventData = { ...clickedEvent.dataset }; // Clone dataset
                Modal.show(eventData);
                return; // Stop further processing for this click
            }

            // Find the closest parent TD element that has a data-day attribute
            const clickedCell = event.target.closest('td[data-day]');

            // Ensure we clicked a valid cell within the current month
            if (!clickedCell || !clickedCell.classList.contains('current-month')) {
                // Click ignored: Not a valid current-month day cell
                return; // Ignore clicks outside valid day cells or on other-month cells
            }

            // Clicked cell
            // No need to reset inactivity timer here, already done at the start

            // Remove selected class from the previous selection
            if (selectedCell && selectedCell !== clickedCell) {
                removeHighlight(selectedCell); // Now only removes 'selected'
                // Removed selected highlight from previously selected
            }
            
            // Highlight the new cell and update selection state
            // Ensure 'today' class is preserved if clicking today
            highlightToday(); // Re-apply today class just in case
            clickedCell.classList.add('selected');
            selectedCell = clickedCell;
            // Highlighted new cell

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
                // Page hidden, paused calendar update checks
            } else {
                // Page is visible again, resume update checks
                updateCheckEnabled = true;
                // Reset initial load status to check immediately
                initialLoadComplete = false;
                startGoogleUpdateTimer();
                // Page visible, resumed calendar update checks
            }
        });
    }

    // Load configuration from server
    async function loadConfig() {
        try {
            const response = await fetch('/api/config');
            const config = await response.json();
            
            // Update sync intervals from config
            const syncIntervalMinutes = config.google?.sync_interval_minutes || 5;
            UPDATE_CHECK_INTERVAL = syncIntervalMinutes * 60 * 1000; // Convert to milliseconds
            FORCE_REFRESH_INTERVAL = UPDATE_CHECK_INTERVAL * 2; // Force refresh at 2x sync interval
            
        } catch (error) {
            console.error("Failed to load calendar config:", error);
            // Keep default values if config load fails
        }
    }

    // Handle swipe gestures
    function handleSwipeGesture() {
        const deltaX = touchEndX - touchStartX;
        const deltaY = touchEndY - touchStartY;
        const absDeltaX = Math.abs(deltaX);
        const absDeltaY = Math.abs(deltaY);

        // Check if this is a horizontal swipe (more horizontal than vertical movement)
        if (absDeltaX > MIN_SWIPE_DISTANCE && absDeltaX > absDeltaY && absDeltaY < MAX_VERTICAL_DRIFT) {
            if (deltaX > 0) {
                // Swipe right - go to previous month
                navigateToPreviousMonth();
            } else {
                // Swipe left - go to next month
                navigateToNextMonth();
            }
        }
    }

    // Navigation functions
    function navigateToPreviousMonth() {
        let prevMonth = currentDisplayedMonth - 1;
        let prevYear = currentDisplayedYear;
        
        if (prevMonth < 1) {
            prevMonth = 12;
            prevYear--;
        }
        
        navigateToMonth(prevYear, prevMonth);
    }

    function navigateToNextMonth() {
        let nextMonth = currentDisplayedMonth + 1;
        let nextYear = currentDisplayedYear;
        
        if (nextMonth > 12) {
            nextMonth = 1;
            nextYear++;
        }
        
        navigateToMonth(nextYear, nextMonth);
    }

    function navigateToMonth(year, month) {
        // Add loading indicator
        LoadingIndicator.show('Loading calendar...');
        
        // Navigate to the new month
        window.location.href = `/calendar/${year}/${month}`;
    }

    function navigateToToday() {
        const today = new Date();
        const todayYear = today.getFullYear();
        const todayMonth = today.getMonth() + 1;
        
        navigateToMonth(todayYear, todayMonth);
    }

    // Setup navigation controls (date picker and today button)
    function setupNavigationControls() {
        const datePickerBtn = document.getElementById('date-picker-btn');
        const todayBtn = document.getElementById('today-btn');
        const qrBtn = document.getElementById('qr-btn');
        const datePickerModal = document.getElementById('date-picker-modal');
        const monthSelect = document.getElementById('month-select');
        const yearSelect = document.getElementById('year-select');
        const datePickerGo = document.getElementById('date-picker-go');
        const datePickerCancel = document.getElementById('date-picker-cancel');
        
        // QR Code Modal elements
        const qrModal = document.getElementById('qr-modal');
        const qrCloseBtn = document.querySelector('.qr-close-btn');
        const qrCodeContainer = document.getElementById('qr-code-container');
        const qrUrlDiv = document.getElementById('qr-url');

        if (datePickerBtn) {
            datePickerBtn.addEventListener('click', function() {
                if (datePickerModal) {
                    datePickerModal.style.display = 'block';
                }
            });
        }

        if (todayBtn) {
            todayBtn.addEventListener('click', function() {
                navigateToToday();
            });
        }
        
        // QR Code button handler
        if (qrBtn && qrModal) {
            qrBtn.addEventListener('click', function() {
                // Show the modal
                qrModal.style.display = 'flex';
                
                // Fetch and display the QR code
                fetch('/upload/qrcode')
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            qrCodeContainer.innerHTML = `<img src="${data.qrcode}" alt="QR Code">`;
                            // Show truncated URL (without token for display)
                            const displayUrl = data.url.split('?')[0] + '...';
                            qrUrlDiv.innerHTML = `
                                <div style="font-size: 0.85em; color: rgba(255,255,255,0.6);">
                                    ${displayUrl}
                                </div>
                                <div style="margin-top: 10px; color: rgba(255,193,7,0.9); font-weight: 600;">
                                    ⏱️ ${data.message || 'Valid for 60 minutes'}
                                </div>
                            `;
                        } else {
                            qrCodeContainer.innerHTML = '<div class="qr-error">Failed to generate QR code</div>';
                        }
                    })
                    .catch(error => {
                        console.error('Error generating QR code:', error);
                        qrCodeContainer.innerHTML = '<div class="qr-error">Error generating QR code</div>';
                    });
            });
            
            // Close button handler
            if (qrCloseBtn) {
                qrCloseBtn.addEventListener('click', function() {
                    qrModal.style.display = 'none';
                });
            }
            
            // Click outside to close
            qrModal.addEventListener('click', function(e) {
                if (e.target === qrModal) {
                    qrModal.style.display = 'none';
                }
            });
        }

        if (datePickerCancel) {
            datePickerCancel.addEventListener('click', function() {
                if (datePickerModal) {
                    datePickerModal.style.display = 'none';
                }
            });
        }

        if (datePickerGo && monthSelect && yearSelect) {
            datePickerGo.addEventListener('click', function() {
                const selectedMonth = parseInt(monthSelect.value);
                const selectedYear = parseInt(yearSelect.value);
                
                if (datePickerModal) {
                    datePickerModal.style.display = 'none';
                }
                
                navigateToMonth(selectedYear, selectedMonth);
            });
        }

        // Close modal when clicking outside
        if (datePickerModal) {
            datePickerModal.addEventListener('click', function(event) {
                if (event.target === datePickerModal) {
                    datePickerModal.style.display = 'none';
                }
            });
        }
    }

    // Public methods
    return {
        init: async function() {
            // Load configuration first
            await loadConfig();
            
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
                // Triggering initial click on today's cell
                todayCell.click(); // This will handle selection and rendering via the click listener
            } else {
                 // If today is not on this month view, clear the daily view initially.
                 DailyView.resetToPlaceholder(); 
                 // Today not visible, reset daily view to placeholder
            }
            
            // Check if we're viewing a different month than the current one
            const isCurrentMonth = currentDisplayedMonth === currentMonth && currentDisplayedYear === currentYear;
            
            // Always ensure we have events loaded when navigating to a different month
            const hasEvents = document.querySelectorAll('.calendar .event').length > 0;
            if (!isCurrentMonth && !hasEvents) {
                // Navigated to a new month with no events yet, ensuring data loads
                initialLoadComplete = false; // Force initial load behavior
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
            if (initialLoadTimeout) {
                clearTimeout(initialLoadTimeout);
                initialLoadTimeout = null;
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