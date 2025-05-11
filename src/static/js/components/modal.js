/**
 * Modal Component
 * Handles displaying event details in a popup modal
 */
const Modal = (function() {
    // Private variables
    let eventModal;
    let modalCloseButton;
    let modalTitle;
    let modalCalendar;
    let modalTime;
    let modalLocation;
    let modalDescription;
    let modalCloseTimer = null;
    const MODAL_TIMEOUT = 15000; // 15 seconds

    // Private methods
    function closeModal() {
        eventModal.style.display = 'none';
        clearTimeout(modalCloseTimer); // Clear timer if closed manually
        modalCloseTimer = null;
        console.log("Modal closed.");
    }

    // Public methods
    return {
        init: function() {
            // Initialize modal DOM elements
            eventModal = document.getElementById('event-modal');
            if (!eventModal) {
                console.error("Modal component: event-modal element not found!");
                return false;
            }
            
            modalCloseButton = eventModal.querySelector('.close-button');
            modalTitle = document.getElementById('modal-title');
            modalCalendar = document.getElementById('modal-calendar');
            modalTime = document.getElementById('modal-time');
            modalLocation = document.getElementById('modal-location');
            modalDescription = document.getElementById('modal-description');
            
            // Set up event listeners
            if (modalCloseButton) {
                modalCloseButton.addEventListener('click', closeModal);
            }
            
            // Close modal if clicked outside the content area
            window.addEventListener('click', function(event) {
                if (event.target == eventModal) {
                    closeModal();
                }
            });
            
            return true;
        },
        
        show: function(eventData) {
            if (!eventModal) return;
            
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
        },
        
        close: closeModal,

        // Add Chore Modal Specific Logic
        initAddChoreModal: function() {
            const addChoreModal = document.getElementById('add-chore-modal');
            const addChoreButton = document.getElementById('add-chore-button'); // The '+' button
            const closeButton = document.querySelector('#add-chore-modal .close-button');
            const addChoreForm = document.getElementById('add-chore-form');

            if (!addChoreModal || !addChoreButton || !closeButton || !addChoreForm) {
                console.error('Add Chore Modal: One or more required elements not found.');
                return false;
            }

            const openModal = () => {
                addChoreModal.style.display = 'block';
                // Focus the first input field when the modal opens
                setTimeout(() => {
                    document.getElementById('chore-title').focus();
                }, 300);
            };
            
            const closeModal = () => {
                addChoreModal.style.display = 'none';
                // When closing modal, hide virtual keyboard
                if (window.VirtualKeyboard && typeof window.VirtualKeyboard.hide === 'function') {
                    window.VirtualKeyboard.hide();
                }
            };

            addChoreButton.addEventListener('click', openModal);
            closeButton.addEventListener('click', closeModal);
            
            window.addEventListener('click', (event) => {
                if (event.target === addChoreModal) {
                    closeModal();
                }
            });
            
            // Handle modal content positioning when virtual keyboard appears
            const modalContent = addChoreModal.querySelector('.modal-content');
            
            // Add listeners for focusing input fields
            document.getElementById('chore-title').addEventListener('focus', () => {
                setTimeout(() => {
                    if (modalContent && window.VirtualKeyboard && window.VirtualKeyboard.isOpen()) {
                        modalContent.classList.add('keyboard-open');
                    }
                }, 300);
            });
            
            document.getElementById('chore-notes').addEventListener('focus', () => {
                setTimeout(() => {
                    if (modalContent && window.VirtualKeyboard && window.VirtualKeyboard.isOpen()) {
                        modalContent.classList.add('keyboard-open');
                    }
                }, 300);
            });
            
            // Additional handler for when keyboard is closed
            window.addEventListener('click', () => {
                setTimeout(() => {
                    if (modalContent && window.VirtualKeyboard && !window.VirtualKeyboard.isOpen()) {
                        modalContent.classList.remove('keyboard-open');
                    }
                }, 100);
            });

            addChoreForm.addEventListener('submit', async (event) => {
                event.preventDefault();
                const formData = new FormData(addChoreForm);
                const data = Object.fromEntries(formData.entries());

                try {
                    const response = await fetch('/chores/add', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(data),
                    });

                    if (response.ok) {
                        closeModal();
                        addChoreForm.reset();
                        location.reload(); // Refresh to see the new chore
                    } else {
                        const errorData = await response.json();
                        alert(`Error adding chore: ${errorData.message || 'Unknown error'}`);
                    }
                } catch (error) {
                    console.error('Error submitting chore:', error);
                    alert('An error occurred while adding the chore.');
                }
            });
            return true;
        }
    };
})();

export default Modal;