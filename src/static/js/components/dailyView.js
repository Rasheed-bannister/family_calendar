/**
 * DailyView Component
 * Handles the display and interactions with the daily event view
 */
import Modal from './modal.js';

const DailyView = (function() {
    // Private variables
    let dailyViewContainer;
    let initialDailyViewHTML; // Keep this to potentially reset later if needed
    let placeholderHTML = `<h2>Select a day</h2><p>Click on a day in the calendar to see its events.</p>`; // Define placeholder
    let updateTimer = null;
    let UPDATE_INTERVAL = 300000; // Default: 5 minutes, will be loaded from config
    
    // Private methods
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
    
    function setupEventListeners() {
        if (!dailyViewContainer) return;
        
        dailyViewContainer.addEventListener('click', function(event) {
            // Check if the click was on an event list item (li)
            // We need to reconstruct the event data slightly differently here
            const clickedListItem = event.target.closest('li');
            if (clickedListItem) {
                // Clicked on daily view event
                
                // Let's try to find the original event data if possible
                const title = clickedListItem.querySelector('strong').textContent;
                
                // Try to find the event in the calendar (this depends on the Calendar implementation)
                // Since we don't have direct access to selectedCell here, we'll use a simplified approach
                const eventElement = document.querySelector(`.event[data-title="${title}"]`);
                
                if (eventElement) {
                    const eventData = { ...eventElement.dataset };
                    Modal.show(eventData);
                } else {
                    // Fallback if original data can't be found
                    // Could not find original data for daily view event
                    const eventData = {
                        title: title,
                        // Extract other info from the LI if needed, though it's less structured
                        calendarName: clickedListItem.textContent.match(/\((.*?)\)/)?.[1] || 'N/A',
                        color: clickedListItem.style.borderLeftColor || '#ccc' // Get color from style
                    };
                    Modal.show(eventData); // Show with potentially limited data
                }
            }
        });
    }

    // Load configuration from server
    async function loadConfig() {
        try {
            const response = await fetch('/api/config');
            const config = await response.json();
            
            // Update sync interval from config
            const syncIntervalMinutes = config.google?.sync_interval_minutes || 5;
            UPDATE_INTERVAL = syncIntervalMinutes * 60 * 1000; // Convert to milliseconds
            
        } catch (error) {
            console.error("Failed to load DailyView config:", error);
            // Keep default values if config load fails
        }
    }

    // Public methods
    return {
        init: async function() {
            // Load configuration first
            await loadConfig();
            
            dailyViewContainer = document.querySelector('.daily-view-container');
            if (!dailyViewContainer) {
                console.error("DailyView component: daily-view-container element not found!");
                return false;
            }
            
            // Store the initial HTML (which might be today's events from server)
            initialDailyViewHTML = dailyViewContainer.innerHTML; 
            setupEventListeners();
            
            return true;
        },

        resetToPlaceholder: function() {
            if (dailyViewContainer) {
                dailyViewContainer.innerHTML = placeholderHTML;
            }
        },
        
        renderEvents: function(dayCell) {
            if (!dailyViewContainer) return;
            
            const day = dayCell.dataset.day;
            const month = dayCell.dataset.month;
            const year = dayCell.dataset.year;
            // Use UTC to avoid timezone issues when creating the date for formatting
            const clickedDate = new Date(Date.UTC(year, month - 1, day));
            const dateHeader = clickedDate.toLocaleDateString('en-US', { 
                weekday: 'long', 
                year: 'numeric', 
                month: 'long', 
                day: 'numeric', 
                timeZone: 'UTC' 
            });

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
                        // Skipping event element due to missing data attributes
                    }
                });
                eventsHTML += '</ul>';
            } else {
                eventsHTML = '<p>No events scheduled for this day.</p>';
            }

            dailyViewContainer.innerHTML = `<h2>${dateHeader}</h2>${eventsHTML}`;
        },
        
        reset: function() {
            // Reset to the initial HTML captured when the component was initialized.
            // This should be the server-rendered content (e.g., Today's Events).
            if (dailyViewContainer && initialDailyViewHTML) {
                dailyViewContainer.innerHTML = initialDailyViewHTML;
                // DailyView reset to initial server-rendered content
            }
        },
        
        pause: function() {
            if (updateTimer) {
                clearInterval(updateTimer);
                updateTimer = null;
            }
            // DailyView updates paused
        },
        
        resume: function() {
            // Clear any existing timer
            if (updateTimer) {
                clearInterval(updateTimer);
            }
            
            // Restart update timer if needed
            updateTimer = setInterval(() => {
                // If we have a valid day cell selected, refresh its events
                const selectedCell = document.querySelector('.calendar td.selected');
                if (selectedCell) {
                    this.renderEvents(selectedCell);
                }
            }, UPDATE_INTERVAL);
            
            // DailyView updates resumed
        }
    };
})();

export default DailyView;