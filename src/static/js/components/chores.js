/**
 * Chores Component
 * Handles the display and interactions with the chores section
 */
const Chores = (function() {
    // Private variables
    let choresContainer;

    // Private methods
    async function updateChoreStatus(choreId, newStatus) {
        try {
            const response = await fetch(`/chores/update_status/${choreId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ status: newStatus }),
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            if (!result.success) {
                console.error(`Failed to update chore ${choreId} status to ${newStatus}:`, result.error);
                return false;
            }
            console.log(`Chore ${choreId} status updated to ${newStatus}`);
            return true;
        } catch (error) {
            console.error(`Error updating chore ${choreId} status to ${newStatus}:`, error);
            return false;
        }
    }

    function setupEventListeners() {
        if (!choresContainer) return;

        // Listener for checkbox changes (completion status)
        choresContainer.addEventListener('change', async (event) => {
            if (event.target.classList.contains('chore-complete-checkbox')) {
                const choreItem = event.target.closest('.chore-item');
                const choreId = choreItem.dataset.choreId;
                const isCompleted = event.target.checked;
                const newStatus = isCompleted ? 'completed' : 'needsAction';

                const success = await updateChoreStatus(choreId, newStatus);
                if (success) {
                    choreItem.classList.toggle('completed', isCompleted);
                } else {
                    // Revert checkbox state on failure
                    event.target.checked = !isCompleted;
                }
            }
        });

        // Listener for clearing chores (setting status to invisible)
        choresContainer.addEventListener('click', async (event) => {
            // Example: Using a specific button class for clearing
            if (event.target.classList.contains('chore-clear-button')) { 
                const choreItem = event.target.closest('.chore-item');
                const choreId = choreItem.dataset.choreId;
                const newStatus = 'invisible';

                if (!confirm('Are you sure you want to clear this chore?')) {
                    return;
                }

                const success = await updateChoreStatus(choreId, newStatus);
                if (success) {
                    choreItem.remove(); // Remove the item from the list visually
                } else {
                    // Handle failure - maybe show an error message to the user
                    alert('Failed to clear the chore. Please try again.');
                }
            }
        });
    }

    // Public methods
    return {
        init: function() {
            choresContainer = document.querySelector('.chores-list');
            if (!choresContainer) {
                console.warn("Chores component: .chores-list element not found during init!");
                return false;
            }
            setupEventListeners();
            return true;
        },
        // ... potentially other public methods like refresh, pause, resume ...
    };
})();

export default Chores;