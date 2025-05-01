/**
 * Chores Component
 * Handles the display and interactions with the chores section
 */
const Chores = (function() {
    // Private variables
    let choresContainer;
    let choresUpdateTimer = null;
    const CHORES_UPDATE_INTERVAL = 600000; // Check for chores updates every 10 minutes (600000ms)
    
    // Private methods
    function setupEventListeners() {
        if (!choresContainer) return;
        
        // Add event listeners for chore interactions, if any
        choresContainer.addEventListener('click', function(event) {
            const choreItem = event.target.closest('.chore-item');
            if (choreItem) {
                // If we implement toggling of chore completion status, it would go here
                console.log("Clicked on chore:", choreItem.textContent.trim());
            }
        });
    }
    
    function updateChoresList() {
        // This function would be used to refresh chores list via AJAX
        console.log("Updating chores list...");
        fetch('/api/chores/list')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.text();
            })
            .then(html => {
                // Replace the chores container with new HTML
                if (choresContainer) {
                    choresContainer.outerHTML = html;
                    // Re-get the container since we just replaced it
                    choresContainer = document.querySelector('.chores-list');
                    // Re-setup event listeners on the new elements
                    setupEventListeners();
                    console.log("Chores list updated successfully");
                }
            })
            .catch(error => {
                console.error("Error updating chores list:", error);
            });
    }
    
    function startChoresUpdateTimer() {
        // Clear any existing timer
        if (choresUpdateTimer) {
            clearInterval(choresUpdateTimer);
        }
        
        // Set interval to check for chores updates
        choresUpdateTimer = setInterval(updateChoresList, CHORES_UPDATE_INTERVAL);
        console.log(`Started chores update timer (checking every ${CHORES_UPDATE_INTERVAL/60000} minutes)`);
    }

    // Public methods
    return {
        init: function() {
            choresContainer = document.querySelector('.chores-list');
            if (!choresContainer) {
                console.error("Chores component: chores-list element not found!");
                return false;
            }
            
            setupEventListeners();
            startChoresUpdateTimer(); // Start the update timer
            
            return true;
        },
        
        refresh: function() {
            updateChoresList();
        },
        
        pause: function() {
            if (choresUpdateTimer) {
                clearInterval(choresUpdateTimer);
                choresUpdateTimer = null;
            }
            console.log("Chores updates paused");
        },
        
        resume: function() {
            updateChoresList(); // Immediately update the chores list
            startChoresUpdateTimer(); // Restart the update timer
            console.log("Chores updates resumed");
        }
    };
})();

export default Chores;