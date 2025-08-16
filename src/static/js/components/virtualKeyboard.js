/**
 * Virtual Keyboard Component
 * Provides an enhanced on-screen keyboard for touchscreen devices
 */
const VirtualKeyboard = (function() {
    // Private variables
    let keyboardContainer;
    let currentInput = null;
    let isOpen = false;
    let keyPressTimeout = null;
    let longPressTimer = null;
    let config = null;
    let hapticFeedback = null;
    
    // Keyboard layouts
    const layouts = {
        standard: [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'Backspace'],
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
            ['Shift', 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '?'],
            ['Space', 'Enter']
        ],
        symbols: [
            ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')', 'Backspace'],
            ['-', '_', '=', '+', '[', ']', '{', '}', '\\', '|'],
            [';', ':', "'", '"', '<', '>', '/', '?'],
            ['123', '~', '`', ',', '.', '!', '?', 'Enter'],
            ['Space', 'ABC']
        ]
    };

    let shiftActive = false;
    let currentLayout = 'standard';
    
    // Configuration loading
    async function loadConfiguration() {
        try {
            const response = await fetch('/api/config');
            if (response.ok) {
                const fullConfig = await response.json();
                config = {
                    enhanced_virtual_keyboard: fullConfig.ui?.enhanced_virtual_keyboard ?? true,
                    animation_duration: fullConfig.ui?.animation_duration_ms ?? 300,
                    touch_optimized: fullConfig.ui?.touch_optimized ?? true
                };
            } else {
                config = {
                    enhanced_virtual_keyboard: true,
                    animation_duration: 300,
                    touch_optimized: true
                };
            }
        } catch (error) {
            console.warn('Could not load keyboard configuration, using defaults:', error);
            config = {
                enhanced_virtual_keyboard: true,
                animation_duration: 300,
                touch_optimized: true
            };
        }
        
        // Initialize haptic feedback if available
        if ('vibrate' in navigator && config.touch_optimized) {
            hapticFeedback = {
                light: () => navigator.vibrate(10),
                medium: () => navigator.vibrate(20),
                heavy: () => navigator.vibrate(50)
            };
        }
    }
    
    // Enhanced key press handling with haptic feedback
    function triggerHapticFeedback(type = 'light') {
        if (hapticFeedback && config.touch_optimized) {
            hapticFeedback[type]();
        }
    }
    
    // Create keyboard HTML structure
    function createKeyboard() {
        keyboardContainer = document.createElement('div');
        keyboardContainer.classList.add('virtual-keyboard');
        keyboardContainer.setAttribute('id', 'virtual-keyboard');
        
        // Build keyboard
        buildKeyboardLayout();
        
        // Add layout switcher if enhanced mode is enabled
        if (config?.enhanced_virtual_keyboard) {
            addLayoutSwitcher();
        }
        
        // Initially hide keyboard
        keyboardContainer.style.display = 'none';
        
        // Prevent clicks on the keyboard from closing modals
        keyboardContainer.addEventListener('click', function(e) {
            e.stopPropagation();
        });
        
        // Add keyboard to DOM
        document.body.appendChild(keyboardContainer);
    }
    
    function buildKeyboardLayout() {
        // Clear existing keys
        keyboardContainer.innerHTML = '';
        
        // Build keyboard rows and keys
        layouts[currentLayout].forEach(row => {
            const rowElement = document.createElement('div');
            rowElement.classList.add('keyboard-row');
            
            row.forEach(key => {
                const keyElement = createKeyElement(key);
                rowElement.appendChild(keyElement);
            });
            
            keyboardContainer.appendChild(rowElement);
        });
    }
    
    function createKeyElement(key) {
        const keyElement = document.createElement('button');
        keyElement.classList.add('keyboard-key');
        keyElement.setAttribute('type', 'button');
        
        // Special keys get special classes and content
        if (['Backspace', 'Enter', 'Space', 'Shift', 'ABC', '123'].includes(key)) {
            keyElement.classList.add('keyboard-key-wide');
            
            switch(key) {
                case 'Backspace':
                    keyElement.innerHTML = '⌫';
                    keyElement.classList.add('keyboard-key-backspace');
                    break;
                case 'Enter':
                    keyElement.innerHTML = 'Enter';
                    keyElement.classList.add('keyboard-key-enter');
                    break;
                case 'Space':
                    keyElement.innerHTML = '';
                    keyElement.classList.add('keyboard-key-space');
                    break;
                case 'Shift':
                    keyElement.innerHTML = '⇧';
                    keyElement.classList.add('keyboard-key-shift');
                    if (shiftActive) {
                        keyElement.classList.add('active');
                    }
                    break;
                case 'ABC':
                    keyElement.innerHTML = 'ABC';
                    keyElement.classList.add('keyboard-key-layout');
                    break;
                case '123':
                    keyElement.innerHTML = '123';
                    keyElement.classList.add('keyboard-key-layout');
                    break;
            }
        } else {
            let displayKey = key;
            if (shiftActive && key.match(/[a-z]/)) {
                displayKey = key.toUpperCase();
            }
            keyElement.textContent = displayKey;
            keyElement.classList.add('keyboard-key-char');
        }
        
        keyElement.dataset.key = key;
        
        // Enhanced touch event handling
        addTouchEventHandlers(keyElement, key);
        
        return keyElement;
    }
    
    function addTouchEventHandlers(keyElement, key) {
        // Standard click handler
        keyElement.addEventListener('click', (e) => handleKeyClick(e, key));
        
        // Enhanced touch handlers for better responsiveness
        if (config?.touch_optimized) {
            keyElement.addEventListener('touchstart', (e) => {
                e.preventDefault();
                keyElement.classList.add('pressed');
                triggerHapticFeedback('light');
                
                // Long press for backspace
                if (key === 'Backspace') {
                    longPressTimer = setTimeout(() => {
                        startBackspaceRepeat();
                    }, 500);
                }
            }, { passive: false });
            
            keyElement.addEventListener('touchend', (e) => {
                e.preventDefault();
                keyElement.classList.remove('pressed');
                
                if (longPressTimer) {
                    clearTimeout(longPressTimer);
                    longPressTimer = null;
                }
                
                stopBackspaceRepeat();
                handleKeyClick(e, key);
            }, { passive: false });
            
            keyElement.addEventListener('touchcancel', (e) => {
                keyElement.classList.remove('pressed');
                if (longPressTimer) {
                    clearTimeout(longPressTimer);
                    longPressTimer = null;
                }
                stopBackspaceRepeat();
            });
        }
        
        // Prevent context menu on long press
        keyElement.addEventListener('contextmenu', (e) => {
            e.preventDefault();
        });
    }
    
    function addLayoutSwitcher() {
        // This function can be called after buildKeyboardLayout
        // The layout switcher keys are already handled in the keyboard layout
    }
    
    let backspaceInterval = null;
    
    function startBackspaceRepeat() {
        if (backspaceInterval) return;
        
        triggerHapticFeedback('medium');
        backspaceInterval = setInterval(() => {
            performBackspace();
            triggerHapticFeedback('light');
        }, 100);
    }
    
    function stopBackspaceRepeat() {
        if (backspaceInterval) {
            clearInterval(backspaceInterval);
            backspaceInterval = null;
        }
    }
    
    function performBackspace() {
        if (!currentInput) return;
        
        const start = currentInput.selectionStart;
        const end = currentInput.selectionEnd;
        const value = currentInput.value;
        
        let newCursorPos = start;
        
        if (start !== end) {
            // Delete selection
            currentInput.value = value.slice(0, start) + value.slice(end);
            newCursorPos = start;
        } else if (start > 0) {
            // Delete one character before cursor
            currentInput.value = value.slice(0, start - 1) + value.slice(start);
            newCursorPos = start - 1;
        }
        
        // Set cursor position after a brief delay
        requestAnimationFrame(() => {
            try {
                if (currentInput && currentInput.setSelectionRange) {
                    currentInput.setSelectionRange(newCursorPos, newCursorPos);
                }
            } catch (e) {
                // Silently handle cursor positioning errors
            }
        });
        
        // Trigger input event
        currentInput.dispatchEvent(new Event('input', { bubbles: true }));
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
                performBackspace();
                triggerHapticFeedback('medium');
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
                updateShiftDisplay();
                triggerHapticFeedback('medium');
                break;
                
            case 'ABC':
                // Switch to standard layout
                currentLayout = 'standard';
                buildKeyboardLayout();
                triggerHapticFeedback('medium');
                break;
                
            case '123':
                // Switch to symbols layout
                currentLayout = 'symbols';
                buildKeyboardLayout();
                triggerHapticFeedback('medium');
                break;
                
            default:
                // Regular key - insert character
                let character = key;
                
                // Apply shift if active
                if (shiftActive) {
                    character = character.toUpperCase();
                    // Toggle shift off after one character
                    shiftActive = false;
                    updateShiftDisplay();
                }
                
                if (currentInput) {
                    insertCharacter(character);
                }
                triggerHapticFeedback('light');
                break;
        }
    }
    
    // Update shift display without rebuilding entire keyboard
    function updateShiftDisplay() {
        if (!keyboardContainer) return;
        
        // Update shift key appearance
        const shiftKey = keyboardContainer.querySelector('[data-key="Shift"]');
        if (shiftKey) {
            if (shiftActive) {
                shiftKey.classList.add('active');
            } else {
                shiftKey.classList.remove('active');
            }
        }
        
        // Update character keys to show uppercase/lowercase
        const charKeys = keyboardContainer.querySelectorAll('.keyboard-key-char');
        charKeys.forEach(key => {
            const keyData = key.dataset.key;
            if (keyData && keyData.match(/[a-z]/)) {
                key.textContent = shiftActive ? keyData.toUpperCase() : keyData;
            }
        });
    }

    // Insert character at cursor position
    function insertCharacter(character) {
        if (!currentInput) return;
        
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
                if (currentInput && currentInput.setSelectionRange) {
                    currentInput.setSelectionRange(newCursorPos, newCursorPos);
                }
            } catch (e) {
                // Silently handle cursor positioning errors on some input types
            }
        });
        
        // Trigger input event
        currentInput.dispatchEvent(new Event('input', { bubbles: true }));
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
                
                // Wait longer to see if focus moves to another input in the same modal
                // This gives time for keyboard rebuilds and other operations
                setTimeout(() => {
                    // Don't hide if keyboard is in use (recent interaction)
                    if (!isOpen) return;
                    
                    const activeElement = document.activeElement;
                    const modalContent = input.closest('.modal-content');
                    
                    // Don't hide if the active element is still an input or part of the keyboard
                    const isStillInput = activeElement && (
                        activeElement.matches('input[type="text"], input[type="email"], input[type="search"], input[type="tel"], textarea') ||
                        activeElement.getAttribute('data-needs-keyboard') === 'true'
                    );
                    
                    const isKeyboardElement = keyboardContainer && keyboardContainer.contains(activeElement);
                    
                    // Don't hide if focus is on body (which happens during keyboard interactions)
                    const isFocusOnBody = activeElement === document.body;
                    
                    // Only hide keyboard if focus truly moved outside the modal AND it's not a keyboard interaction
                    if (!modalContent || 
                        (!modalContent.contains(activeElement) && !isKeyboardElement && !isStillInput && !isFocusOnBody)) {
                        hideKeyboard();
                    }
                }, 300); // Further increased timeout
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
        init: async function() {
            // Load configuration first
            await loadConfiguration();
            
            createKeyboard();
            setupInputListeners();
            console.log("Enhanced virtual keyboard component initialized");
            
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
