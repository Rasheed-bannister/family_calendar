/**
 * Virtual Keyboard Component
 * Provides an on-screen keyboard for touchscreen devices
 */
const VirtualKeyboard = (function() {
    // Private variables
    let keyboardContainer;
    let currentInput = null;
    let isOpen = false;
    
    // Keyboard layouts
    const layouts = {
        standard: [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'Backspace'],
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
            ['Shift', 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '?'],
            ['Space', 'Enter']
        ]
    };

    let shiftActive = false;
    
    // Create keyboard HTML structure
    function createKeyboard() {
        keyboardContainer = document.createElement('div');
        keyboardContainer.classList.add('virtual-keyboard');
        keyboardContainer.setAttribute('id', 'virtual-keyboard');
        
        // Build keyboard rows and keys
        layouts.standard.forEach(row => {
            const rowElement = document.createElement('div');
            rowElement.classList.add('keyboard-row');
            
            row.forEach(key => {
                const keyElement = document.createElement('button');
                keyElement.classList.add('keyboard-key');
                
                // Special keys get special classes
                if (key === 'Backspace' || key === 'Enter' || key === 'Space' || key === 'Shift') {
                    keyElement.classList.add('keyboard-key-wide');
                    
                    switch(key) {
                        case 'Backspace':
                            keyElement.innerHTML = '&larr;';
                            keyElement.dataset.key = key;
                            break;
                        case 'Enter':
                            keyElement.innerHTML = 'Enter';
                            keyElement.dataset.key = key;
                            break;
                        case 'Space':
                            keyElement.innerHTML = '&nbsp;';
                            keyElement.dataset.key = key;
                            break;
                        case 'Shift':
                            keyElement.innerHTML = '&uarr;';
                            keyElement.dataset.key = key;
                            break;
                    }
                } else {
                    keyElement.textContent = key;
                    keyElement.dataset.key = key;
                }
                
                // Add click handler to each key
                keyElement.addEventListener('click', (e) => handleKeyClick(e, keyElement.dataset.key));
                rowElement.appendChild(keyElement);
            });
            
            keyboardContainer.appendChild(rowElement);
        });
        
        // Initially hide keyboard
        keyboardContainer.style.display = 'none';
        
        // Prevent clicks on the keyboard from closing modals
        keyboardContainer.addEventListener('click', function(e) {
            e.stopPropagation();
        });
        
        // Add keyboard to DOM
        document.body.appendChild(keyboardContainer);
    }
    
    // Handle key clicks
    function handleKeyClick(e, key) {
        console.log('Virtual keyboard: key clicked', key);
        
        if (!currentInput) {
            console.warn('Virtual keyboard: no current input selected');
            return;
        }
        
        e.preventDefault();
        e.stopPropagation(); // Prevent event from bubbling up to modal
        
        switch(key) {
            case 'Backspace':
                // Remove last character
                if (currentInput.tagName.toLowerCase() === 'textarea') {
                    const start = currentInput.selectionStart;
                    const end = currentInput.selectionEnd;
                    
                    if (start === end && start > 0) {
                        currentInput.value = currentInput.value.slice(0, start - 1) + currentInput.value.slice(end);
                        currentInput.selectionStart = start - 1;
                        currentInput.selectionEnd = start - 1;
                    } else if (start !== end) {
                        // Delete selected text
                        currentInput.value = currentInput.value.slice(0, start) + currentInput.value.slice(end);
                        currentInput.selectionStart = start;
                        currentInput.selectionEnd = start;
                    }
                } else {
                    currentInput.value = currentInput.value.slice(0, -1);
                }
                break;
                
            case 'Enter':
                if (currentInput.tagName.toLowerCase() === 'textarea') {
                    // Insert newline in textarea
                    const start = currentInput.selectionStart;
                    const end = currentInput.selectionEnd;
                    currentInput.value = currentInput.value.slice(0, start) + '\n' + currentInput.value.slice(end);
                    currentInput.selectionStart = start + 1;
                    currentInput.selectionEnd = start + 1;
                } else {
                    // Submit the form if this is the last input
                    const form = currentInput.closest('form');
                    if (form) {
                        const inputs = Array.from(form.querySelectorAll('input, textarea'));
                        const currentIndex = inputs.indexOf(currentInput);
                        
                        if (currentIndex === inputs.length - 1) {
                            form.dispatchEvent(new Event('submit'));
                        } else if (currentIndex !== -1 && currentIndex < inputs.length - 1) {
                            // Move focus to the next input
                            inputs[currentIndex + 1].focus();
                        }
                    }
                }
                break;
                
            case 'Space':
                // Insert space
                if (currentInput) {
                    const start = currentInput.selectionStart;
                    const end = currentInput.selectionEnd;
                    
                    currentInput.value = currentInput.value.slice(0, start) + ' ' + currentInput.value.slice(end);
                    currentInput.selectionStart = start + 1;
                    currentInput.selectionEnd = start + 1;
                }
                break;
                
            case 'Shift':
                // Toggle shift state
                shiftActive = !shiftActive;
                toggleShift();
                break;
                
            default:
                // Regular key - insert character
                let character = key;
                
                // Apply shift if active
                if (shiftActive) {
                    character = character.toUpperCase();
                    // Toggle shift off after one character
                    shiftActive = false;
                    toggleShift();
                }
                
                if (currentInput) {
                    // Focus the input to ensure proper state
                    currentInput.focus();
                    
                    // Get current cursor position, defaulting to end of text if not available
                    let start = currentInput.selectionStart;
                    let end = currentInput.selectionEnd;
                    
                    // If cursor position is not available, place at end
                    if (start === null || start === undefined) {
                        start = currentInput.value.length;
                    }
                    if (end === null || end === undefined) {
                        end = currentInput.value.length;
                    }
                    
                    // Build new value by inserting character at cursor position
                    const beforeText = currentInput.value.substring(0, start);
                    const afterText = currentInput.value.substring(end);
                    const newValue = beforeText + character + afterText;
                    
                    // Set the new value
                    currentInput.value = newValue;
                    
                    // Calculate new cursor position (after the inserted character)
                    const newCursorPos = start + character.length;
                    
                    // Set cursor position after a brief delay to ensure value is set
                    requestAnimationFrame(() => {
                        try {
                            currentInput.selectionStart = newCursorPos;
                            currentInput.selectionEnd = newCursorPos;
                        } catch (e) {
                            // Silently handle cursor positioning errors on some input types
                        }
                    });
                }
        }
        
        // Trigger input event for validation and reactivity
        currentInput.dispatchEvent(new Event('input', { bubbles: true }));
    }
    
    // Toggle shift state
    function toggleShift() {
        const keys = document.querySelectorAll('.keyboard-key:not(.keyboard-key-wide)');
        keys.forEach(key => {
            if (shiftActive) {
                key.textContent = key.textContent.toUpperCase();
                document.querySelector('[data-key="Shift"]').classList.add('active');
            } else {
                key.textContent = key.textContent.toLowerCase();
                document.querySelector('[data-key="Shift"]').classList.remove('active');
            }
        });
    }
    
    // Show the keyboard and link it to the input that has focus
    function showKeyboard(input) {
        if (!keyboardContainer) {
            console.warn('Virtual keyboard: keyboard container not found');
            return;
        }
        
        if (!input) {
            console.warn('Virtual keyboard: no input element provided');
            return;
        }
        
        console.log('Virtual keyboard: showing keyboard for input', input.id || input.tagName);
        
        currentInput = input;
        keyboardContainer.style.display = 'block';
        
        // Animate in from bottom
        keyboardContainer.classList.add('keyboard-visible');
        
        // Add class to body
        document.body.classList.add('keyboard-open');
        
        // Add class to modal content if input is inside a modal
        const modalContent = input.closest('.modal-content');
        if (modalContent) {
            modalContent.classList.add('keyboard-open');
            modalContent.classList.add('keyboard-visible');
            
            // Also add class to the modal itself
            const modal = input.closest('.modal');
            if (modal) {
                modal.classList.add('keyboard-active');
            }
            
            console.log('Virtual keyboard: added keyboard classes to modal content');
        }
        
        // Try to trigger native keyboard on mobile devices
        if ('virtualKeyboard' in navigator && typeof navigator.virtualKeyboard.show === 'function') {
            navigator.virtualKeyboard.show();
        }
        
        // Scroll to ensure input is visible above keyboard
        setTimeout(() => {
            input.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 300);
        
        isOpen = true;
        console.log('Virtual keyboard: successfully shown');
    }
    
    // Hide the keyboard
    function hideKeyboard() {
        if (!keyboardContainer || !isOpen) {
            console.log('Virtual keyboard: hide called but keyboard not open or not found');
            return;
        }
        
        console.log('Virtual keyboard: hiding keyboard');
        
        keyboardContainer.classList.remove('keyboard-visible');
        
        // Remove class from body
        document.body.classList.remove('keyboard-open');
        
        // Remove class from any modal content
        const modalContents = document.querySelectorAll('.modal-content.keyboard-open');
        modalContents.forEach(modalContent => {
            modalContent.classList.remove('keyboard-open');
            modalContent.classList.remove('keyboard-visible');
        });
        
        // Remove class from any modal
        const modals = document.querySelectorAll('.modal.keyboard-active');
        modals.forEach(modal => {
            modal.classList.remove('keyboard-active');
        });
        
        // Try to hide native keyboard
        if ('virtualKeyboard' in navigator && typeof navigator.virtualKeyboard.hide === 'function') {
            navigator.virtualKeyboard.hide();
        }
        
        // Wait for animation to complete before hiding
        setTimeout(() => {
            keyboardContainer.style.display = 'none';
            currentInput = null;
            isOpen = false;
            console.log('Virtual keyboard: successfully hidden');
        }, 300);
    }
    
    // Setup event listeners for inputs
    function setupInputListeners() {
        // We'll use a dynamic approach to catch inputs that are added later
        document.addEventListener('focusin', (event) => {
            const input = event.target;
            
            if (input.matches('input[type="text"], input[type="email"], input[type="search"], input[type="tel"], textarea') || 
                input.getAttribute('data-needs-keyboard') === 'true') {
                // Add a small delay to ensure the input is properly focused
                setTimeout(() => {
                    showKeyboard(input);
                }, 50);
            }
        });
        
        // Handle focus out events - but only hide if focus moves completely outside modal
        document.addEventListener('focusout', (event) => {
            const input = event.target;
            
            if (isOpen && (input.matches('input[type="text"], input[type="email"], input[type="search"], input[type="tel"], textarea') || 
                input.getAttribute('data-needs-keyboard') === 'true')) {
                
                // Wait a bit to see if focus moves to another input in the same modal
                setTimeout(() => {
                    const activeElement = document.activeElement;
                    const modalContent = input.closest('.modal-content');
                    
                    // Only hide keyboard if focus moved outside the modal or to a non-input element
                    if (!modalContent || 
                        !modalContent.contains(activeElement) || 
                        (!activeElement.matches('input[type="text"], input[type="email"], input[type="search"], input[type="tel"], textarea') &&
                         activeElement.getAttribute('data-needs-keyboard') !== 'true')) {
                        hideKeyboard();
                    }
                }, 100);
            }
        });
        
        // Handle clicks outside the keyboard to close it
        document.addEventListener('click', (event) => {
            // Don't hide keyboard if clicking within modal content or on the keyboard itself
            const isModalContent = event.target.closest('.modal-content');
            const isKeyboard = keyboardContainer && keyboardContainer.contains(event.target);
            const isInput = event.target.matches('input[type="text"], input[type="email"], input[type="search"], input[type="tel"], textarea') ||
                          event.target.getAttribute('data-needs-keyboard') === 'true';
            
            if (isOpen && !isKeyboard && !isInput && !isModalContent) {
                hideKeyboard();
            }
        });
        
        // Add touch detection
        document.addEventListener('touchstart', () => {
            document.body.classList.add('touch-device');
        }, { once: true });
    }
    
    // Public methods
    const publicAPI = {
        init: function() {
            createKeyboard();
            setupInputListeners();
            console.log("Virtual keyboard component initialized");
            
            // Make the keyboard available globally
            window.VirtualKeyboard = publicAPI;
            
            return true;
        },
        
        // Method to manually show keyboard for an input
        showFor: function(inputElement) {
            if (inputElement && (inputElement.tagName === 'INPUT' || inputElement.tagName === 'TEXTAREA' || 
                inputElement.getAttribute('data-needs-keyboard') === 'true')) {
                showKeyboard(inputElement);
            }
        },
        
        // Method to manually hide keyboard
        hide: function() {
            hideKeyboard();
        },
        
        // Method to check if keyboard is currently open
        isOpen: function() {
            return isOpen;
        }
    };
    
    return publicAPI;
})();

export default VirtualKeyboard;
