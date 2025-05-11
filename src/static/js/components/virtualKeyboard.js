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
        
        // Add keyboard to DOM
        document.body.appendChild(keyboardContainer);
    }
    
    // Handle key clicks
    function handleKeyClick(e, key) {
        if (!currentInput) return;
        
        e.preventDefault();
        
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
                    const start = currentInput.selectionStart;
                    const end = currentInput.selectionEnd;
                    
                    if (start !== undefined && end !== undefined) {
                        currentInput.value = currentInput.value.slice(0, start) + character + currentInput.value.slice(end);
                        currentInput.selectionStart = start + 1;
                        currentInput.selectionEnd = start + 1;
                    } else {
                        // Fallback for browsers that don't support selection
                        currentInput.value += character;
                    }
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
        if (!keyboardContainer) return;
        
        currentInput = input;
        keyboardContainer.style.display = 'block';
        
        // Animate in from bottom
        keyboardContainer.classList.add('keyboard-visible');
        
        // Scroll to ensure input is visible above keyboard
        setTimeout(() => {
            input.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 300);
        
        isOpen = true;
    }
    
    // Hide the keyboard
    function hideKeyboard() {
        if (!keyboardContainer || !isOpen) return;
        
        keyboardContainer.classList.remove('keyboard-visible');
        
        // Wait for animation to complete before hiding
        setTimeout(() => {
            keyboardContainer.style.display = 'none';
            currentInput = null;
            isOpen = false;
        }, 300);
    }
    
    // Setup event listeners for inputs
    function setupInputListeners() {
        // Find all text inputs and textareas
        const inputs = document.querySelectorAll('input[type="text"], input[type="email"], input[type="search"], input[type="tel"], textarea');
        
        inputs.forEach(input => {
            // Show keyboard on focus
            input.addEventListener('focus', () => {
                showKeyboard(input);
            });
            
            // Don't hide immediately on blur as it might be due to clicking on keyboard
            input.addEventListener('blur', (event) => {
                // Check if the new focus is outside the keyboard
                setTimeout(() => {
                    const activeElement = document.activeElement;
                    if (!keyboardContainer.contains(activeElement) && 
                        !activeElement.matches('input[type="text"], input[type="email"], input[type="search"], input[type="tel"], textarea')) {
                        hideKeyboard();
                    }
                }, 100);
            });
        });
        
        // Handle clicks outside the keyboard and inputs to close keyboard
        document.addEventListener('click', (event) => {
            if (isOpen && 
                !keyboardContainer.contains(event.target) && 
                !event.target.matches('input[type="text"], input[type="email"], input[type="search"], input[type="tel"], textarea')) {
                hideKeyboard();
            }
        });
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
            if (inputElement && (inputElement.tagName === 'INPUT' || inputElement.tagName === 'TEXTAREA')) {
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
