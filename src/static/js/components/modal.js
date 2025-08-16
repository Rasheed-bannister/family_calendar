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
        // Modal closed
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
            // Modal opened with auto-close timer
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
                // Hide the virtual keyboard if it's visible
                if (window.VirtualKeyboard && typeof window.VirtualKeyboard.hide === 'function') {
                    window.VirtualKeyboard.hide();
                }
                
                if (document.activeElement) {
                    document.activeElement.blur();
                }
                
                // Remove keyboard-related classes
                const modalContent = addChoreModal.querySelector('.modal-content');
                if (modalContent) {
                    modalContent.classList.remove('keyboard-visible');
                }
                document.body.classList.remove('keyboard-focus-active', 'keyboard-active');
            };

            addChoreButton.addEventListener('click', openModal);
            closeButton.addEventListener('click', closeModal);
            
            window.addEventListener('click', (event) => {
                // Only close if the click is directly on the modal background (not its content)
                // and not on the virtual keyboard
                const isVirtualKeyboard = event.target.closest('#virtual-keyboard') || 
                                        event.target.closest('.virtual-keyboard');
                
                if (event.target === addChoreModal && !isVirtualKeyboard) {
                    closeModal();
                }
            });
            
            // Get reference to modal content for potential later use
            const modalContent = addChoreModal.querySelector('.modal-content');
            
            // Prevent clicks within modal content from bubbling up and potentially hiding keyboard
            if (modalContent) {
                modalContent.addEventListener('click', (event) => {
                    event.stopPropagation();
                });
            }
            
            // Enhance inputs in the modal for better keyboard experience
            const enhanceInputsForMobile = () => {
                const inputs = addChoreModal.querySelectorAll('input, textarea');
                inputs.forEach(input => {
                    // Make sure inputs have appropriate attributes
                    if (!input.hasAttribute('inputmode')) {
                        input.setAttribute('inputmode', 'text');
                    }
                    
                    // For iOS to prevent zooming when focusing on inputs
                    if (parseInt(window.getComputedStyle(input).fontSize) < 16) {
                        input.style.fontSize = '16px';
                    }
                    
                    // For better accessibility
                    if (!input.hasAttribute('autocorrect')) {
                        input.setAttribute('autocorrect', 'off');
                    }
                    
                    // Add touch-specific attribute
                    input.setAttribute('data-needs-keyboard', 'true');
                    
                    // Add focus/blur events for keyboard management
                    input.addEventListener('focus', () => {
                        // Add class to modal content for styling
                        modalContent.classList.add('keyboard-visible');
                        
                        // Try to use our custom virtual keyboard first
                        if (window.VirtualKeyboard && typeof window.VirtualKeyboard.showFor === 'function') {
                            window.VirtualKeyboard.showFor(input);
                        }
                        // Fall back to native virtual keyboard API if available
                        else if ('virtualKeyboard' in navigator && typeof navigator.virtualKeyboard.show === 'function') {
                            navigator.virtualKeyboard.show();
                        }
                        
                        // Add class to body to help with styling
                        document.body.classList.add('keyboard-focus-active');
                    });
                    
                    input.addEventListener('blur', () => {
                        // Remove class if no other inputs are focused
                        setTimeout(() => {
                            if (!modalContent.contains(document.activeElement) || 
                                !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
                                modalContent.classList.remove('keyboard-visible');
                                document.body.classList.remove('keyboard-focus-active');
                            }
                        }, 100);
                    });
                    
                    // Add touch event to explicitly trigger virtual keyboard on mobile
                    input.addEventListener('touchstart', (e) => {
                        // Add class for styling
                        document.body.classList.add('touch-device');
                        
                        if (window.VirtualKeyboard && typeof window.VirtualKeyboard.showFor === 'function') {
                            // Allow the default focus first
                            setTimeout(() => {
                                window.VirtualKeyboard.showFor(input);
                            }, 10);
                        }
                    });
                });
            };
            
            // Call the enhancement function
            enhanceInputsForMobile();
            
            // Set up native virtual keyboard behavior if available
            if ('virtualKeyboard' in navigator) {
                // Tell browser to overlay keyboard without resizing viewport
                navigator.virtualKeyboard.overlaysContent = true;
                
                // Listen for keyboard geometry changes
                if (typeof navigator.virtualKeyboard.addEventListener === 'function') {
                    navigator.virtualKeyboard.addEventListener('geometrychange', (event) => {
                        const keyboardHeight = event.target.boundingRect.height;
                        if (keyboardHeight > 0) {
                            modalContent.classList.add('keyboard-visible');
                            document.body.classList.add('keyboard-active');
                        } else {
                            modalContent.classList.remove('keyboard-visible');
                            document.body.classList.remove('keyboard-active');
                        }
                    });
                }
            }

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