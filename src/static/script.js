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
    const INACTIVITY_TIMEOUT = 60 * 1000; // 1 minute

    // --- Helper Functions ---

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

    // --- Initialization ---

    highlightToday(); // Highlight today on load

    // --- Event Listeners ---

    if (calendar) {
        calendar.addEventListener('click', function(event) {
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

    // Start the timer initially only if today is visible and selected by default
    // We only want the timer active after the user *first* clicks away from today.
    // So, no need to start it here initially.

    // Add other interactive features here if needed
});

// Example: Slideshow activation/deactivation logic would go here
// Example: Event handling for adding events would go here