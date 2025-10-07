/**
 * Progress Tracking System untuk VPS Production
 * Compatible dengan multiple Gunicorn workers
 * 
 * Features:
 * - Auto-stop polling ketika tidak ada progress aktif
 * - Error handling yang robust
 * - Cleanup otomatis untuk mencegah memory leaks
 * - Fallback mechanism jika server error
 */

class ProgressTracker {
    constructor(userId, progressContainer, options = {}) {
        this.userId = userId;
        this.progressContainer = progressContainer;
        this.pollingInterval = null;
        this.isActive = false;
        this.retryCount = 0;
        this.maxRetries = options.maxRetries || 10;
        this.pollIntervalMs = options.pollIntervalMs || 500;
        this.timeoutMs = options.timeoutMs || 30000; // 30 seconds timeout
        
        // Bind methods
        this.pollProgress = this.pollProgress.bind(this);
        this.stopPolling = this.stopPolling.bind(this);
        
        // Auto-cleanup on page unload
        window.addEventListener('beforeunload', () => {
            this.cleanup();
        });
    }

    startPolling() {
        if (this.isActive) {
            console.log('Progress polling already active');
            return;
        }

        this.isActive = true;
        this.retryCount = 0;
        
        console.log(`Starting progress polling for user ${this.userId}`);
        
        // Start immediate poll
        this.pollProgress();
        
        // Set up interval polling
        this.pollingInterval = setInterval(this.pollProgress, this.pollIntervalMs);
        
        // Set timeout to auto-stop polling
        setTimeout(() => {
            if (this.isActive) {
                console.log('Progress polling timeout reached, stopping...');
                this.stopPolling();
            }
        }, this.timeoutMs);
    }

    async pollProgress() {
        if (!this.isActive) return;

        try {
            const response = await fetch(`/api/progress/${this.userId}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                },
                timeout: 5000 // 5 second timeout per request
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            
            // Reset retry count on successful response
            this.retryCount = 0;
            
            if (data.success && data.progress) {
                this.updateProgressUI(data.progress);
            } else {
                // No active progress, stop polling
                console.log('No active progress, stopping polling');
                this.stopPolling();
            }

        } catch (error) {
            console.error('Progress polling error:', error);
            this.handlePollingError(error);
        }
    }

    handlePollingError(error) {
        this.retryCount++;
        
        if (this.retryCount >= this.maxRetries) {
            console.error(`Max retries (${this.maxRetries}) reached, stopping progress polling`);
            this.stopPolling();
            this.showErrorMessage('Koneksi ke server terputus. Silakan refresh halaman.');
            return;
        }
        
        // Exponential backoff
        const backoffMs = Math.min(1000 * Math.pow(2, this.retryCount), 10000);
        console.log(`Retry ${this.retryCount}/${this.maxRetries} in ${backoffMs}ms`);
        
        setTimeout(() => {
            if (this.isActive) {
                this.pollProgress();
            }
        }, backoffMs);
    }

    updateProgressUI(progress) {
        if (!this.progressContainer) return;

        const currentStep = progress.current_step || 1;
        const steps = progress.steps || {};

        // Update progress bar
        const progressBar = this.progressContainer.querySelector('.progress-bar');
        if (progressBar) {
            const percentage = (currentStep / 5) * 100;
            progressBar.style.width = `${percentage}%`;
            progressBar.setAttribute('aria-valuenow', percentage);
        }

        // Update step indicators
        for (let i = 1; i <= 5; i++) {
            const stepElement = this.progressContainer.querySelector(`#step-${i}`);
            if (!stepElement) continue;

            const stepData = steps[i] || {};
            const status = stepData.status || 'pending';
            const message = stepData.message || `Step ${i}`;

            // Remove all status classes
            stepElement.classList.remove('pending', 'active', 'completed');
            
            // Add current status class
            stepElement.classList.add(status);

            // Update step message
            const messageElement = stepElement.querySelector('.step-message');
            if (messageElement) {
                messageElement.textContent = message;
            }

            // Update step icon
            const iconElement = stepElement.querySelector('.step-icon');
            if (iconElement) {
                if (status === 'completed') {
                    iconElement.innerHTML = '<i class="bi bi-check-circle-fill text-success"></i>';
                } else if (status === 'active') {
                    iconElement.innerHTML = '<i class="bi bi-arrow-right-circle-fill text-primary"></i>';
                } else {
                    iconElement.innerHTML = '<i class="bi bi-circle text-muted"></i>';
                }
            }
        }

        // Check if all steps completed
        const allCompleted = Object.values(steps).every(step => step.status === 'completed');
        if (allCompleted) {
            console.log('All progress steps completed, stopping polling');
            setTimeout(() => {
                this.stopPolling();
            }, 2000); // Give user time to see completion
        }
    }

    stopPolling() {
        if (!this.isActive) return;

        this.isActive = false;
        
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }

        console.log(`Progress polling stopped for user ${this.userId}`);
        
        // Notify server to cleanup progress tracking
        this.cleanup();
    }

    async cleanup() {
        try {
            await fetch(`/api/progress/stop/${this.userId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            console.log('Progress tracking cleaned up on server');
        } catch (error) {
            console.warn('Failed to cleanup progress tracking:', error);
        }
    }

    showErrorMessage(message) {
        if (this.progressContainer) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'alert alert-warning mt-3';
            errorDiv.innerHTML = `
                <i class="bi bi-exclamation-triangle"></i>
                ${message}
            `;
            this.progressContainer.appendChild(errorDiv);
        }
    }
}

// Global instance untuk backward compatibility
window.ProgressTracker = ProgressTracker;

// Auto-initialize jika ada elemen progress di halaman
document.addEventListener('DOMContentLoaded', function() {
    const progressContainer = document.getElementById('progress-container');
    if (progressContainer && window.currentUserId) {
        window.progressTracker = new ProgressTracker(window.currentUserId, progressContainer);
    }
});

// Fungsi helper untuk memulai progress tracking (backward compatibility)
function startProgressTracking(userId) {
    const progressContainer = document.getElementById('progress-container');
    if (progressContainer) {
        if (window.progressTracker) {
            window.progressTracker.stopPolling();
        }
        window.progressTracker = new ProgressTracker(userId, progressContainer);
        window.progressTracker.startPolling();
    }
}

function stopProgressTracking() {
    if (window.progressTracker) {
        window.progressTracker.stopPolling();
        window.progressTracker = null;
    }
}