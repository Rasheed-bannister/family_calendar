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
        
        close: closeModal
    };
})();

export default Modal;