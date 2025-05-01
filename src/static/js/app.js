/**
 * Main Application
 * Initializes and coordinates all components
 */
import Calendar from './components/calendar.js';
import DailyView from './components/dailyView.js';
import Weather from './components/weather.js';
import Slideshow from './components/slideshow.js';
import Chores from './components/chores.js';
import Modal from './components/modal.js';

document.addEventListener('DOMContentLoaded', function() {
    console.log("Calendar application initializing...");
    
    // Initialize all components
    const componentsStatus = {
        modal: Modal.init(),
        calendar: Calendar.init(),
        dailyView: DailyView.init(),
        weather: Weather.init(),
        slideshow: Slideshow.init(),
        chores: Chores.init()
    };
    
    // Check if all components initialized successfully
    const failedComponents = Object.entries(componentsStatus)
        .filter(([name, status]) => !status)
        .map(([name]) => name);
    
    if (failedComponents.length > 0) {
        console.error(`Failed to initialize components: ${failedComponents.join(', ')}`);
    } else {
        console.log("All components initialized successfully");
    }
    
    // Handle page visibility for global application state
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            console.log("Page hidden, pausing components");
            // Pause components that need to be paused when page is hidden
            Calendar.pause();
            Weather.pause();
            // We don't need to pause the slideshow as it's just cosmetic
        } else {
            console.log("Page visible, resuming components");
            // Resume components when page becomes visible again
            Calendar.resume();
            Weather.resume();
        }
    });
    
    console.log("Calendar application initialized");
});