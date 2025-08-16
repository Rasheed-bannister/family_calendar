#!/bin/bash

# Family Calendar Health Monitor Script
# This script monitors the application health and restarts it if necessary

# Configuration
APP_DIR="/home/pi/family_calendar"
HEALTH_ENDPOINT="http://localhost:5000/health/"
SERVICE_NAME="family-calendar"
LOG_FILE="/var/log/family-calendar-monitor.log"
CHECK_INTERVAL=60  # Check every 60 seconds
MAX_FAILED_CHECKS=3
RESTART_COOLDOWN=300  # 5 minutes between restarts

# State variables
failed_checks=0
last_restart_time=0

# Logging function
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Check if application is responding
check_health() {
    local response
    local status_code
    
    # Try to get health status
    response=$(curl -s -w "%{http_code}" "$HEALTH_ENDPOINT" --max-time 10 2>/dev/null)
    status_code="${response: -3}"
    
    if [[ "$status_code" == "200" ]]; then
        # Parse the response to check if status is healthy or warning
        local health_status
        health_status=$(echo "${response%???}" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('status', 'unknown'))" 2>/dev/null)
        
        if [[ "$health_status" == "healthy" || "$health_status" == "warning" ]]; then
            return 0  # Healthy
        else
            log_message "Health check returned unhealthy status: $health_status"
            return 1  # Unhealthy
        fi
    elif [[ "$status_code" == "503" ]]; then
        log_message "Health check returned service unavailable (503)"
        return 1  # Service unavailable
    else
        log_message "Health check failed with status code: $status_code"
        return 1  # Failed
    fi
}

# Check system resources
check_resources() {
    local cpu_usage
    local memory_usage
    local disk_usage
    
    # Get CPU usage (5 second average)
    cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
    
    # Get memory usage percentage
    memory_usage=$(free | grep Mem | awk '{printf "%.1f", $3/$2 * 100.0}')
    
    # Get disk usage percentage for root
    disk_usage=$(df / | tail -1 | awk '{print $5}' | cut -d'%' -f1)
    
    # Check thresholds
    if (( $(echo "$cpu_usage > 95" | bc -l) )); then
        log_message "WARNING: High CPU usage: ${cpu_usage}%"
    fi
    
    if (( $(echo "$memory_usage > 90" | bc -l) )); then
        log_message "WARNING: High memory usage: ${memory_usage}%"
    fi
    
    if [[ "$disk_usage" -gt 90 ]]; then
        log_message "WARNING: High disk usage: ${disk_usage}%"
    fi
}

# Restart the application service
restart_application() {
    local current_time
    current_time=$(date +%s)
    
    # Check restart cooldown
    if [[ $((current_time - last_restart_time)) -lt $RESTART_COOLDOWN ]]; then
        log_message "Restart cooldown active. Skipping restart."
        return 1
    fi
    
    log_message "Attempting to restart $SERVICE_NAME service..."
    
    if systemctl restart "$SERVICE_NAME"; then
        log_message "Successfully restarted $SERVICE_NAME service"
        last_restart_time=$current_time
        failed_checks=0
        return 0
    else
        log_message "CRITICAL: Failed to restart $SERVICE_NAME service"
        return 1
    fi
}

# Main monitoring loop
main() {
    log_message "Family Calendar health monitor started"
    
    while true; do
        if check_health; then
            # Health check passed
            if [[ $failed_checks -gt 0 ]]; then
                log_message "Health check recovered after $failed_checks failed attempts"
                failed_checks=0
            fi
        else
            # Health check failed
            ((failed_checks++))
            log_message "Health check failed ($failed_checks/$MAX_FAILED_CHECKS)"
            
            if [[ $failed_checks -ge $MAX_FAILED_CHECKS ]]; then
                log_message "Maximum failed health checks reached. Attempting restart..."
                if restart_application; then
                    # Wait longer after restart to let application stabilize
                    sleep 30
                else
                    log_message "CRITICAL: Application restart failed. Manual intervention required."
                    # Could send alerts here (email, webhook, etc.)
                fi
            fi
        fi
        
        # Check system resources periodically
        check_resources
        
        # Wait before next check
        sleep $CHECK_INTERVAL
    done
}

# Handle signals for graceful shutdown
trap 'log_message "Health monitor shutting down"; exit 0' SIGTERM SIGINT

# Ensure we have required commands
for cmd in curl systemctl bc; do
    if ! command -v "$cmd" &> /dev/null; then
        log_message "CRITICAL: Required command '$cmd' not found"
        exit 1
    fi
done

# Start monitoring
main