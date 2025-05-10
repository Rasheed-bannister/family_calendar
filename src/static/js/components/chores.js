/**
 * Chores Component
 * Handles the display and interactions with the chores section
 */
const Chores = (function() {
    // Private variables
    let choresContainer;
    let touchStartX = 0;
    let touchEndX = 0;
    let mouseStartX = 0;
    let mouseEndX = 0;
    let isMouseDown = false;
    let activeChoreItem = null;
    const swipeThreshold = 60; // Minimum swipe distance to reveal delete button (matches button width)
    let isPaused = false;
    let activeSwipedChore = null; // Track which chore is currently swiped

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
    
    // Helper function to check if a chore is completed and can be swiped
    function canBeDeleted(choreItem) {
        return choreItem && choreItem.classList.contains('completed');
    }
    
    // Touch event handlers
    function handleTouchStart(event) {
        if (isPaused) {
            return;
        }
        
        const choreItem = event.target.closest('.chore-item');
        if (!choreItem) {
            // If tapping elsewhere and we have an active swiped chore, reset it
            if (activeSwipedChore) {
                resetSwipedChore();
            }
            return;
        }
        
        // If tapping on a different chore than the currently swiped one, reset the swiped one
        if (activeSwipedChore && activeSwipedChore !== choreItem) {
            resetSwipedChore();
        }
        
        // Always store the initial touch position so we can detect taps for toggling
        touchStartX = event.touches[0].clientX;
        touchEndX = touchStartX; // Initialize end position to start
    }
    
    function handleTouchMove(event) {
        if (isPaused) {
            return;
        }
        
        const choreItem = event.target.closest('.chore-item');
        if (!choreItem || !canBeDeleted(choreItem)) {
            return;
        }
        
        const choreTextContent = choreItem.querySelector('.chore-text-content');
        if (!choreTextContent) return;

        touchEndX = event.touches[0].clientX;
        const diffX = touchStartX - touchEndX;
        
        // If swiping left and within reasonable bounds
        if (diffX > 0) {
            // Apply transform based on swipe distance (capped at threshold)
            const translateX = Math.min(diffX, swipeThreshold);
            choreTextContent.style.transform = `translateX(-${translateX}px)`; // Apply to text content
            
            // Show delete button when swipe reaches threshold
            if (translateX >= swipeThreshold - 5) { // Small buffer to make it easier to activate
                if (!choreItem.classList.contains('swiping')) {
                    choreItem.classList.add('swiping');
                    activeSwipedChore = choreItem;
                    console.log('Chore item swiped - showing delete button'); // Debugging
                }
            } else {
                if (choreItem.classList.contains('swiping')) {
                    choreItem.classList.remove('swiping');
                    activeSwipedChore = null;
                }
            }
        } else { // Swiping right or not enough left swipe
            choreTextContent.style.transform = ''; // Reset transform if swiping back right
            if (choreItem.classList.contains('swiping')) {
                choreItem.classList.remove('swiping');
                activeSwipedChore = null;
            }
        }
    }
    
    function handleTouchEnd(event) {
        if (isPaused) {
            return;
        }
        
        const choreItem = event.target.closest('.chore-item');
        if (!choreItem) {
            return;
        }
        const choreTextContent = choreItem.querySelector('.chore-text-content');
        if (!choreTextContent) return;
        
        // Always allow toggling status via tap regardless of completion state
        const diffX = touchStartX - touchEndX;
        
        // If it's a short touch/tap (not a significant swipe)
        if (Math.abs(diffX) < 30) {
            // If we're tapping on a swiped item, don't toggle it
            if (choreItem.classList.contains('swiping')) {
                return;
            }
            toggleChoreStatus(choreItem);
            resetSwipedChore();
            return;
        }
        
        // Only handle swipe actions for completed chores
        if (!canBeDeleted(choreItem)) {
            choreTextContent.style.transform = ''; // Ensure non-deletable items don't stay transformed
            return;
        }
        
        // If it's a significant swipe left but not enough to fully reveal
        if (diffX > 30 && diffX < swipeThreshold) {
            // Reset the transform
            choreTextContent.style.transform = '';
            choreItem.classList.remove('swiping');
            activeSwipedChore = null;
        }
        // If it's a full swipe left (past threshold), keep it open showing the delete button
        else if (diffX >= swipeThreshold) {
            choreTextContent.style.transform = `translateX(-${swipeThreshold}px)`;
            choreItem.classList.add('swiping');
            activeSwipedChore = choreItem;
        } else { // Swiped right or not enough
            choreTextContent.style.transform = '';
            choreItem.classList.remove('swiping');
            activeSwipedChore = null;
        }
        
        // Reset touch coordinates
        touchStartX = 0;
        touchEndX = 0;
    }
    
    // Mouse event handlers
    function handleMouseDown(event) {
        if (isPaused || event.button !== 0) { // Only handle left mouse button (0)
            return;
        }
        
        const choreItem = event.target.closest('.chore-item');
        
        // If clicking on the delete button of a swiped chore
        if (event.target.closest('.chore-delete-button')) {
            // Handle delete action
            if (choreItem) {
                hideChore(choreItem);
            }
            return;
        }
        
        // If clicking elsewhere and we have an active swiped chore, reset it
        if (!choreItem && activeSwipedChore) {
            resetSwipedChore();
            return;
        }
        
        if (!choreItem) {
            return;
        }
        
        // If clicking on a different chore than the currently swiped one, reset the swiped one
        if (activeSwipedChore && activeSwipedChore !== choreItem) {
            resetSwipedChore();
        }
        
        // Always allow mousedown for potential clicking
        isMouseDown = true;
        activeChoreItem = choreItem;
        mouseStartX = event.clientX;
        mouseEndX = mouseStartX; // Initialize end position to start
        
        // Add mousemove and mouseup listeners to document to track outside element
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
    }
    
    function handleMouseMove(event) {
        if (isPaused || !isMouseDown || !activeChoreItem || !canBeDeleted(activeChoreItem)) {
            return;
        }
        
        const choreTextContent = activeChoreItem.querySelector('.chore-text-content');
        if (!choreTextContent) return;

        mouseEndX = event.clientX;
        const diffX = mouseStartX - mouseEndX;
        
        // If swiping left and within reasonable bounds
        if (diffX > 0) {
            // Apply transform based on swipe distance (capped at threshold)
            const translateX = Math.min(diffX, swipeThreshold);
            choreTextContent.style.transform = `translateX(-${translateX}px)`; // Apply to text content
            
            // Show delete button when swipe reaches threshold
            if (translateX >= swipeThreshold - 5) {
                if (!activeChoreItem.classList.contains('swiping')) {
                    activeChoreItem.classList.add('swiping');
                    activeSwipedChore = activeChoreItem;
                }
            } else {
                if (activeChoreItem.classList.contains('swiping')) {
                    activeChoreItem.classList.remove('swiping');
                    activeSwipedChore = null;
                }
            }
        } else { // Swiping right or not enough left swipe
            choreTextContent.style.transform = ''; // Reset transform if swiping back right
            if (activeChoreItem.classList.contains('swiping')) {
                activeChoreItem.classList.remove('swiping');
                activeSwipedChore = null;
            }
        }
    }
    
    function handleMouseUp(event) {
        if (isPaused || !isMouseDown || !activeChoreItem) {
            return;
        }
        
        const choreTextContent = activeChoreItem.querySelector('.chore-text-content');
        if (!choreTextContent) {
            return;
        }

        // Calculate swipe distance
        const diffX = mouseStartX - mouseEndX;
        
        // If it's just a click (not a significant drag)
        if (Math.abs(diffX) < 30) {
            // If we're clicking on a swiped item, don't toggle it
            if (!activeChoreItem.classList.contains('swiping')) {
                toggleChoreStatus(activeChoreItem);
            }
        } 
        // Only process swipe actions for completed chores
        else if (canBeDeleted(activeChoreItem)) {
            // If it's a significant drag left but not enough to fully reveal
            if (diffX > 30 && diffX < swipeThreshold) {
                // Reset the transform
                choreTextContent.style.transform = '';
                activeChoreItem.classList.remove('swiping');
                activeSwipedChore = null;
            }
            // If it's a full drag left (past threshold), keep it open showing the delete button
            else if (diffX >= swipeThreshold) {
                choreTextContent.style.transform = `translateX(-${swipeThreshold}px)`;
                activeChoreItem.classList.add('swiping');
                activeSwipedChore = activeChoreItem;
            } else { // Swiped right or not enough
                choreTextContent.style.transform = '';
                activeChoreItem.classList.remove('swiping');
                activeSwipedChore = null;
            }
        } else if (!canBeDeleted(activeChoreItem) && Math.abs(diffX) >= 30) {
            // If dragged a non-deletable item, ensure it resets
            choreTextContent.style.transform = '';
        }
        
        // Clean up
        isMouseDown = false;
        mouseStartX = 0;
        mouseEndX = 0;
        activeChoreItem = null; // Reset activeChoreItem after processing
        
        // Remove document-level event listeners
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
    }
    
    // Reset any currently swiped chore
    function resetSwipedChore() {
        if (activeSwipedChore) {
            const choreTextContent = activeSwipedChore.querySelector('.chore-text-content');
            if (choreTextContent) {
                choreTextContent.style.transform = '';
            }
            activeSwipedChore.classList.remove('swiping');
            activeSwipedChore = null;
        }
    }
    
    // Handle clicks on document to close swiped items when clicking elsewhere
    function handleDocumentClick(event) {
        if (isPaused) return;
        
        // If clicking anywhere except on a chore item or its delete button
        if (!event.target.closest('.chore-item') && activeSwipedChore) {
            resetSwipedChore();
        }
    }
    
    // Prevent default behavior on drag to avoid text selection
    function handleDragStart(event) {
        if (event.target.closest('.chore-item')) {
            event.preventDefault();
        }
    }
    
    async function toggleChoreStatus(choreItem) {
        const choreId = choreItem.dataset.choreId;
        const isCurrentlyCompleted = choreItem.classList.contains('completed');
        const newStatus = isCurrentlyCompleted ? 'needsAction' : 'completed';
        
        const success = await updateChoreStatus(choreId, newStatus);
        if (success) {
            choreItem.classList.toggle('completed');
            choreItem.classList.toggle('needsAction');
        }
    }
    
    async function hideChore(choreItem) {
        const choreId = choreItem.dataset.choreId;
        const success = await updateChoreStatus(choreId, 'invisible');
        
        if (success) {
            // Animate removal
            choreItem.style.opacity = '0';
            choreItem.style.height = '0';
            choreItem.style.margin = '0';
            choreItem.style.padding = '0';
            choreItem.style.transition = 'opacity 0.3s, height 0.3s, margin 0.3s, padding 0.3s';
            
            // Remove from DOM after animation completes
            setTimeout(() => {
                choreItem.remove();
                activeSwipedChore = null;
            }, 300);
        }
    }

    function setupEventListeners() {
        if (!choresContainer) return;

        // Add touch event listeners for swipe functionality
        choresContainer.addEventListener('touchstart', handleTouchStart, { passive: true });
        choresContainer.addEventListener('touchmove', handleTouchMove, { passive: true });
        choresContainer.addEventListener('touchend', handleTouchEnd);
        
        // Add mouse event listeners for click-and-drag functionality
        choresContainer.addEventListener('mousedown', handleMouseDown);
        // Prevent default drag behavior
        choresContainer.addEventListener('dragstart', handleDragStart);
        
        // Add event listener for clicks on delete buttons
        choresContainer.addEventListener('click', (event) => {
            if (isPaused) return;
            
            // If clicking on delete button
            if (event.target.closest('.chore-delete-button')) {
                console.log('Delete button clicked'); // Debugging
                const choreItem = event.target.closest('.chore-item');
                if (choreItem) {
                    hideChore(choreItem);
                    event.stopPropagation(); // Prevent the click from bubbling up
                }
            }
        });
        
        // Add document-level click handler to close swiped items when clicking elsewhere
        document.addEventListener('click', handleDocumentClick);
        
        // Log that we've initialized
        console.log('Chores component initialized with trash button functionality');
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
            console.log("Chores component initialized with touch and mouse gesture support");
            return true;
        },
        pause: function() {
            isPaused = true;
            console.log("Chores component paused");
        },
        resume: function() {
            isPaused = false;
            console.log("Chores component resumed");
        }
    };
})();

export default Chores;