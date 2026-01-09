let currentJobId = null;
let pollInterval = null;
let autoMode = false; // Auto-mode state
let aiAutoSelectMode = false; // AI auto-selection mode state

document.addEventListener('DOMContentLoaded', () => {
    initializeEventListeners();
    startPolling();
    initializePage();
    initializeAutoMode();
});

function initializeAutoMode() {
    // Load auto-mode state from localStorage
    const savedAutoMode = localStorage.getItem('autoMode') === 'true';
    autoMode = savedAutoMode;
    
    const checkbox = document.getElementById('auto-mode-checkbox');
    if (checkbox) {
        checkbox.checked = autoMode;
        checkbox.addEventListener('change', (e) => {
            autoMode = e.target.checked;
            localStorage.setItem('autoMode', autoMode.toString());
            if (autoMode) {
                showStatus('Auto mode enabled. Will automatically find URLs after email scraping.', 'success');
            } else {
                showStatus('Auto mode disabled. Manual mode active.', 'info');
            }
        });
    }
    
    // Initialize AI auto-select mode
    const savedAiAutoSelect = localStorage.getItem('aiAutoSelectMode') === 'true';
    aiAutoSelectMode = savedAiAutoSelect;
    
    const aiAutoSelectCheckbox = document.getElementById('ai-auto-select-checkbox');
    if (aiAutoSelectCheckbox) {
        aiAutoSelectCheckbox.checked = aiAutoSelectMode;
        aiAutoSelectCheckbox.addEventListener('change', (e) => {
            aiAutoSelectMode = e.target.checked;
            localStorage.setItem('aiAutoSelectMode', aiAutoSelectMode.toString());
            if (aiAutoSelectMode) {
                showStatus('AI auto-selection enabled. AI will automatically select URLs without approval.', 'success');
            } else {
                showStatus('AI auto-selection disabled. Manual approval required.', 'info');
            }
        });
    }
}

async function initializePage() {
    // Check if there are pending stores and load the first one
    try {
        const response = await fetch('/api/stores/next');
        const data = await response.json();
        
        if (data.store) {
            // There are pending stores, load the first one
            await loadNextStore();
        } else {
            // Check if there are any active jobs that might have stores
            try {
                const jobsResponse = await fetch('/api/jobs');
                if (jobsResponse.ok) {
                    const jobs = await jobsResponse.json();
                    // Find the most recent job that's in 'finding_urls' or 'scraping_reviews' status
                    const activeJob = jobs.find(job => 
                        job.status === 'finding_urls' || job.status === 'scraping_reviews'
                    );
                    if (activeJob) {
                        currentJobId = activeJob.id;
                        // If status is finding_urls, try to load stores
                        if (activeJob.status === 'finding_urls') {
                            await loadNextStore();
                        }
                    }
                }
            } catch (jobsError) {
                console.error('Error fetching jobs:', jobsError);
            }
        }
    } catch (error) {
        console.error('Error initializing page:', error);
    }
}

function initializeEventListeners() {
    document.getElementById('start-scraping').addEventListener('click', startScraping);
    document.getElementById('export-json').addEventListener('click', exportJSON);
    document.getElementById('export-csv').addEventListener('click', exportCSV);
    document.querySelector('.close').addEventListener('click', closeModal);
    
    window.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) {
            closeModal();
        }
    });
}

async function startScraping() {
    const appUrl = document.getElementById('app-url').value.trim();
    if (!appUrl) {
        showStatus('Please enter an app URL', 'error');
        return;
    }
    
    // Get limits from inputs
    const maxReviewsInput = document.getElementById('max-reviews');
    const maxPagesInput = document.getElementById('max-pages');
    const maxReviews = maxReviewsInput.value ? parseInt(maxReviewsInput.value) : 0;
    const maxPages = maxPagesInput.value ? parseInt(maxPagesInput.value) : 0;
    
    if (maxReviews < 0 || maxPages < 0) {
        showStatus('Limits must be positive numbers', 'error');
        return;
    }
    
    const btn = document.getElementById('start-scraping');
    btn.disabled = true;
    btn.textContent = 'Starting...';
    
    try {
        const response = await fetch('/api/jobs', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                app_url: appUrl,
                max_reviews: maxReviews,
                max_pages: maxPages
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            currentJobId = data.job_id;
            if (data.resumed) {
                let message = data.message || 'Resuming from where we left off...';
                if (data.remaining_reviews !== undefined || data.remaining_pages !== undefined) {
                    const parts = [];
                    if (data.remaining_reviews !== 'unlimited') {
                        parts.push(`${data.remaining_reviews} reviews remaining`);
                    }
                    if (data.remaining_pages !== 'unlimited') {
                        parts.push(`${data.remaining_pages} pages remaining`);
                    }
                    if (parts.length > 0) {
                        message += ` (${parts.join(', ')})`;
                    }
                }
                showStatus(`Job resumed! ${message}`, 'success');
            } else {
                let message = `Job started! App: ${data.app_name}`;
                const limits = [];
                if (maxReviews > 0) limits.push(`max ${maxReviews} reviews`);
                if (maxPages > 0) limits.push(`max ${maxPages} pages`);
                if (limits.length > 0) {
                    message += ` [${limits.join(', ')}]`;
                }
                showStatus(message, 'success');
            }
            loadPendingStores();
            pollJobStatus();
        } else {
            if (data.job_id && data.message) {
                showStatus(`${data.error}: ${data.message}`, 'info');
            } else {
                showStatus(`Error: ${data.error}`, 'error');
            }
        }
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Start Scraping';
    }
}

function pollJobStatus() {
    if (pollInterval) clearInterval(pollInterval);
    
    pollInterval = setInterval(async () => {
        if (!currentJobId) return;
        
        try {
            const response = await fetch(`/api/jobs/${currentJobId}`);
            const job = await response.json();
            
            updateProgress(job);
            
            if (job.status === 'finding_urls') {
                loadNextStore(); // Load first store when reviews are done
            } else if (job.status === 'completed' || job.status === 'error') {
                clearInterval(pollInterval);
                if (job.status === 'completed') {
                    showStatus('Job completed successfully!', 'success');
                } else {
                    showStatus(`Job failed: ${job.progress_message || 'Unknown error'}`, 'error');
                }
            }
            
            updateStatistics();
        } catch (error) {
            console.error('Error polling job status:', error);
        }
    }, 2000);
}

function updateProgress(job) {
    const progressSection = document.getElementById('progress-section');
    const progressBar = document.getElementById('progress-bar');
    const progressMessage = document.getElementById('progress-message');
    const progressDetails = document.getElementById('progress-details');
    
    if (!progressSection || !progressBar || !progressMessage || !progressDetails) return;
    
    if (job.status === 'scraping_reviews' || job.status === 'finding_urls' || job.status === 'scraping_emails') {
        progressSection.style.display = 'block';
        
        // Update progress message
        if (job.progress_message) {
            progressMessage.textContent = job.progress_message;
        } else {
            progressMessage.textContent = `Status: ${job.status.replace('_', ' ')}`;
        }
        
        // Calculate progress percentage
        let progressPercent = 0;
        if (job.status === 'scraping_reviews') {
            const currentPage = job.current_page || 0;
            const totalPages = job.total_pages || 0;
            const reviewsScraped = job.reviews_scraped || 0;
            const maxReviewsLimit = job.max_reviews_limit || 0;
            const maxPagesLimit = job.max_pages_limit || 0;
            
            let detailsParts = [];
            
            // Page progress
            if (maxPagesLimit > 0) {
                const pagesRemaining = Math.max(0, maxPagesLimit - currentPage);
                progressPercent = Math.min(50, (currentPage / maxPagesLimit) * 50);
                detailsParts.push(`<strong>Page Progress:</strong> Page ${currentPage} / ${maxPagesLimit} (${pagesRemaining} remaining)`);
            } else if (totalPages > 0) {
                progressPercent = Math.min(50, (currentPage / totalPages) * 50);
                const pagesRemaining = Math.max(0, totalPages - currentPage);
                detailsParts.push(`<strong>Page Progress:</strong> Page ${currentPage} / ${totalPages} (${pagesRemaining} remaining)`);
            } else if (currentPage > 0) {
                progressPercent = Math.min(50, (currentPage * 5)); // Estimate
                detailsParts.push(`<strong>Current Page:</strong> ${currentPage}`);
            }
            
            // Reviews progress
            if (maxReviewsLimit > 0) {
                const reviewsRemaining = Math.max(0, maxReviewsLimit - reviewsScraped);
                const reviewsPercent = (reviewsScraped / maxReviewsLimit) * 50;
                if (progressPercent < reviewsPercent) {
                    progressPercent = reviewsPercent;
                }
                detailsParts.push(`<strong>Reviews Progress:</strong> ${reviewsScraped} / ${maxReviewsLimit} (${reviewsRemaining} remaining)`);
            } else {
                detailsParts.push(`<strong>Reviews Scraped:</strong> ${reviewsScraped}`);
                if (currentPage === 0 && reviewsScraped === 0) {
                    progressPercent = 0;
                } else if (progressPercent === 0) {
                    progressPercent = Math.min(50, (reviewsScraped / 100) * 50);
                }
            }
            
            if (detailsParts.length > 0) {
                progressDetails.innerHTML = detailsParts.join('<br>');
            } else {
                progressDetails.textContent = 'Starting review scraping...';
            }
        } else if (job.status === 'finding_urls') {
            if (job.total_stores > 0) {
                progressPercent = 50 + (job.stores_processed / job.total_stores) * 25;
            } else {
                progressPercent = 50;
            }
            progressDetails.textContent = `Stores processed: ${job.stores_processed || 0} / ${job.total_stores || 0}`;
        } else if (job.status === 'scraping_emails') {
            if (job.total_stores > 0) {
                progressPercent = 75 + (job.stores_processed / job.total_stores) * 25;
            } else {
                progressPercent = 75;
            }
            progressDetails.textContent = `Emails scraped for: ${job.stores_processed || 0} / ${job.total_stores || 0} stores`;
        }
        
        progressBar.style.width = `${progressPercent}%`;
        progressBar.textContent = `${Math.round(progressPercent)}%`;
    } else {
        progressSection.style.display = 'none';
    }
}

let currentStore = null;
let emailCheckInterval = null;
let isFindingUrl = false; // Guard to prevent concurrent findStoreUrl calls
let isAutoTriggering = false; // Guard to prevent multiple auto-triggers
let isEmailScrapingInProgress = false; // Track if email scraping is in progress

async function loadNextStore() {
    try {
        const response = await fetch('/api/stores/next');
        const data = await response.json();
        
        const container = document.getElementById('stores-container');
        
        if (!data.store) {
            container.innerHTML = '<p>No more stores pending. All reviews have been processed!</p>';
            if (emailCheckInterval) {
                clearInterval(emailCheckInterval);
                emailCheckInterval = null;
            }
            return;
        }
        
        currentStore = data.store;
        
        // Escape strings for use in onclick attributes
        const escapedStoreName = (currentStore.store_name || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        const escapedCountry = (currentStore.country || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        
        container.innerHTML = `
            <div class="store-item">
                <h4>${currentStore.store_name}</h4>
                <p><strong>Country:</strong> ${currentStore.country || 'N/A'}</p>
                ${currentStore.rating ? `<p><strong>Rating:</strong> ${'★'.repeat(currentStore.rating)}${'☆'.repeat(5 - currentStore.rating)} (${currentStore.rating} stars)</p>` : ''}
                <p><strong>Review:</strong> ${currentStore.review_text ? (currentStore.review_text.substring(0, 100) + '...') : 'N/A'}</p>
                <p><strong>Status:</strong> ${currentStore.status}</p>
                ${currentStore.base_url ? `<p><strong>URL:</strong> ${currentStore.base_url}</p>` : ''}
                ${currentStore.emails && currentStore.emails.length > 0 ? `<p><strong>Emails:</strong> ${currentStore.emails.join(', ')}</p>` : ''}
                ${autoMode && !currentStore.base_url ? `<p class="info-message" style="color: #3498db; font-weight: 500;">🤖 Auto mode: Finding URL automatically...</p>` : ''}
                <div class="store-actions">
                    ${!currentStore.base_url ? `
                        <button class="btn-small" onclick="findStoreUrl(${currentStore.id}, '${escapedStoreName}', '${escapedCountry}')">Find URL</button>
                        <button class="btn-small btn-skip" onclick="skipStore(${currentStore.id})">Skip</button>
                    ` : ''}
                    ${currentStore.base_url && 
                      (currentStore.status === 'url_verified' || currentStore.status === 'url_found') &&
                      (!currentStore.emails || currentStore.emails.length === 0) &&
                      currentStore.status !== 'emails_found' ? `
                        <p class="info-message">Email scraping in progress... Please wait.</p>
                    ` : ''}
                </div>
            </div>
        `;
        
        // If URL is set but emails are not found yet, start checking for completion
        // Only start checking if status is NOT already 'emails_found' (email scraping might still be in progress)
        const isEmailScrapingComplete = currentStore.status === 'emails_found' || currentStore.status === 'no_emails_found';
        if (currentStore.base_url && !isEmailScrapingComplete && (!currentStore.emails || currentStore.emails.length === 0)) {
            // Mark email scraping as in progress
            isEmailScrapingInProgress = true;
            startEmailStatusCheck();
            // DO NOT proceed to auto-mode - wait for emails to complete
            return;
        }
        
        // If store already has emails found status but we're checking again, refresh display and move on
        if (currentStore.base_url && isEmailScrapingComplete && autoMode) {
            // Store is complete, move to next store
            setTimeout(async () => {
                if (!isEmailScrapingInProgress && !isFindingUrl) {
                    await loadNextStore();
                    updateStatistics();
                }
            }, 1000);
            return;
        }
        
        // If store already has emails, it's complete - move to next store if auto-mode is enabled
        if (autoMode && currentStore.base_url && currentStore.emails && currentStore.emails.length > 0) {
            // Store is already complete, move to next store
            setTimeout(async () => {
                if (!isEmailScrapingInProgress && !isFindingUrl) {
                    await loadNextStore();
                    updateStatistics();
                }
            }, 1000);
            return;
        }
        
        // Auto-mode: automatically trigger Find URL ONLY if:
        // 1. Store has no URL
        // 2. Email scraping is NOT in progress
        // 3. Not already finding URL
        // 4. Auto-mode is enabled
        if (autoMode && !currentStore.base_url && !isEmailScrapingInProgress && !isFindingUrl) {
            // Ensure clean state
            closeModal();
            
            // Set flag to prevent multiple triggers
            isAutoTriggering = true;
            
            // Small delay to ensure UI is rendered before triggering
            setTimeout(() => {
                // Double-check conditions before triggering (ensure currentStore hasn't changed)
                // CRITICAL: Also check that email scraping is not in progress
                if (autoMode && 
                    currentStore && 
                    currentStore.id === data.store.id && 
                    !currentStore.base_url && 
                    !isFindingUrl && 
                    !isEmailScrapingInProgress) {
                    
                    console.log('🤖 Auto-mode: Triggering Find URL', {
                        storeId: currentStore.id,
                        storeName: currentStore.store_name,
                        hasBaseUrl: !!currentStore.base_url,
                        isFindingUrl,
                        isAutoTriggering,
                        isEmailScrapingInProgress
                    });
                    showStatus('🤖 Auto mode: Automatically finding URL...', 'info');
                    findStoreUrl(currentStore.id, currentStore.store_name, currentStore.country || '');
                } else {
                    // Reset flag if conditions not met
                    isAutoTriggering = false;
                    console.log('🤖 Auto-mode: Conditions changed, skipping Find URL', {
                        autoMode,
                        hasCurrentStore: !!currentStore,
                        storeIdMatch: currentStore?.id === data.store.id,
                        hasBaseUrl: !!currentStore?.base_url,
                        isFindingUrl,
                        isEmailScrapingInProgress
                    });
                }
            }, 500);
        }
    } catch (error) {
        console.error('Error loading next store:', error);
    }
}

async function skipStore(storeId) {
    try {
        // Reset all flags before skipping
        isFindingUrl = false;
        isAutoTriggering = false;
        isEmailScrapingInProgress = false;
        closeModal();
        
        if (emailCheckInterval) {
            clearInterval(emailCheckInterval);
            emailCheckInterval = null;
        }
        
        const response = await fetch(`/api/stores/${storeId}/skip`, {
            method: 'POST'
        });
        
        if (response.ok) {
            showStatus('Store skipped', 'info');
            await loadNextStore();
            updateStatistics();
        } else {
            showStatus('Error skipping store', 'error');
        }
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    }
}

function startEmailStatusCheck() {
    if (emailCheckInterval) {
        clearInterval(emailCheckInterval);
    }
    
    // Mark email scraping as in progress
    isEmailScrapingInProgress = true;
    
    let checkCount = 0;
    const maxChecks = 60; // Check for up to 3 minutes (60 * 3 seconds)
    const startTime = Date.now();
    const maxWaitTime = 5 * 60 * 1000; // 5 minutes maximum wait time
    
    emailCheckInterval = setInterval(async () => {
        if (!currentStore) {
            clearInterval(emailCheckInterval);
            emailCheckInterval = null;
            isEmailScrapingInProgress = false;
            return;
        }
        
        checkCount++;
        const elapsedTime = Date.now() - startTime;
        
        // Check if we've exceeded max wait time
        if (elapsedTime > maxWaitTime) {
            clearInterval(emailCheckInterval);
            emailCheckInterval = null;
            isEmailScrapingInProgress = false; // Mark as no longer in progress
            console.warn(`Email scraping timeout for store ${currentStore.id} after ${Math.round(elapsedTime / 1000)}s`);
            
            // If store has URL but status is still url_verified, mark as complete with no emails
            if (currentStore.base_url && (currentStore.status === 'url_verified' || currentStore.status === 'url_found')) {
                console.log(`Marking store ${currentStore.id} as complete (timeout, no emails found)`);
                showStatus('Email scraping timed out. Moving to next store.', 'info');
                
                // Reset flags - IMPORTANT: Mark email scraping as complete before moving to next
                isAutoTriggering = false;
                isFindingUrl = false;
                isEmailScrapingInProgress = false;
                closeModal();
                
                setTimeout(async () => {
                    await loadNextStore();
                    updateStatistics();
                }, 1000);
                return;
            }
            
            showStatus('Email scraping is taking longer than expected. You can manually proceed.', 'info');
            return;
        }
        
        if (checkCount > maxChecks) {
            clearInterval(emailCheckInterval);
            emailCheckInterval = null;
            isEmailScrapingInProgress = false; // Mark as no longer in progress
            showStatus('Email scraping is taking longer than expected. You can manually proceed.', 'info');
            return;
        }
        
        try {
            const response = await fetch(`/api/stores/${currentStore.id}`);
            const store = await response.json();
            
            // Update the current store
            currentStore = store;
            
            // Refresh the display to show updated status
            // But skip if we're in the process of auto-triggering to avoid flickering
            if (!isAutoTriggering && !isFindingUrl) {
                await refreshCurrentStoreDisplay();
            }
            
            // Check if emails are found (status is 'emails_found')
            if (store.status === 'emails_found') {
                // Emails found (or scraping completed with 0 emails), mark as complete
                clearInterval(emailCheckInterval);
                emailCheckInterval = null;
                isEmailScrapingInProgress = false; // CRITICAL: Mark email scraping as complete
                
                // Update currentStore with the latest data (including emails)
                currentStore = store;
                
                // Immediately refresh the display to show emails (not "in progress" message)
                await refreshCurrentStoreDisplay();
                
                // CRITICAL: Reset ALL flags BEFORE checking auto-mode and moving to next store
                // This ensures we're in a clean state regardless of previous operations
                closeModal();
                isFindingUrl = false;
                isAutoTriggering = false;
                
                const emailList = store.emails && store.emails.length > 0 
                    ? store.emails.join(', ') 
                    : 'No emails found';
                showStatus(`Email scraping completed. ${emailList}`, 'success');
                
                // IMPORTANT: Re-read autoMode from localStorage to ensure we have the latest value
                // This handles cases where the user might have toggled it while scraping was in progress
                const currentAutoMode = localStorage.getItem('autoMode') === 'true';
                
                console.log('Email scraping completed. Auto-mode status:', currentAutoMode, {
                    storeId: store.id,
                    storeName: store.store_name,
                    hasEmails: store.emails && store.emails.length > 0,
                    isEmailScrapingInProgress,
                    isFindingUrl,
                    isAutoTriggering
                });
                
                // Only move to next store if auto-mode is enabled
                if (currentAutoMode) {
                    // Wait a moment to ensure all state is cleared before loading next store
                    setTimeout(async () => {
                        // Final safety check: ensure we're in a clean state
                        if (!isEmailScrapingInProgress && !isFindingUrl && !isAutoTriggering) {
                            console.log('Auto-mode: Moving to next store after email scraping completion');
                            await loadNextStore();
                            updateStatistics();
                        } else {
                            console.warn('Auto-mode: Skipping move to next store due to active flags', {
                                isEmailScrapingInProgress,
                                isFindingUrl,
                                isAutoTriggering
                            });
                        }
                    }, 1500);
                } else {
                    // If auto-mode is off, just update statistics and stop
                    console.log('Auto-mode is OFF. Stopping after email scraping completion.');
                    updateStatistics();
                }
            }
        } catch (error) {
            console.error('Error checking email status:', error);
        }
    }, 3000); // Check every 3 seconds
}

async function refreshCurrentStoreDisplay() {
    if (!currentStore) return;
    
    try {
        const response = await fetch(`/api/stores/${currentStore.id}`);
        const store = await response.json();
        currentStore = store;
        
        // Escape strings for use in onclick attributes
        const escapedStoreName = (currentStore.store_name || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        const escapedCountry = (currentStore.country || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        
        const container = document.getElementById('stores-container');
        
        // Determine if email scraping is complete based on status
        const isEmailScrapingComplete = currentStore.status === 'emails_found' || currentStore.status === 'no_emails_found';
        const hasEmails = currentStore.emails && currentStore.emails.length > 0;
        // Only show "in progress" if URL exists, status is NOT complete, and emails are not yet found
        const isScrapingInProgress = currentStore.base_url && 
                                     !isEmailScrapingComplete && 
                                     (!hasEmails) &&
                                     (currentStore.status === 'url_verified' || currentStore.status === 'url_found');
        
        container.innerHTML = `
            <div class="store-item">
                <h4>${currentStore.store_name}</h4>
                <p><strong>Country:</strong> ${currentStore.country || 'N/A'}</p>
                ${currentStore.rating ? `<p><strong>Rating:</strong> ${'★'.repeat(currentStore.rating)}${'☆'.repeat(5 - currentStore.rating)} (${currentStore.rating} stars)</p>` : ''}
                <p><strong>Review:</strong> ${currentStore.review_text ? (currentStore.review_text.substring(0, 100) + '...') : 'N/A'}</p>
                <p><strong>Status:</strong> ${currentStore.status}</p>
                ${currentStore.base_url ? `<p><strong>URL:</strong> ${currentStore.base_url}</p>` : ''}
                ${hasEmails ? `<p><strong>Emails:</strong> ${currentStore.emails.join(', ')}</p>` : ''}
                ${isEmailScrapingComplete && !hasEmails ? `<p class="info-message" style="color: #666;">No emails found for this store.</p>` : ''}
                <div class="store-actions">
                    ${!currentStore.base_url ? `
                        <button class="btn-small" onclick="findStoreUrl(${currentStore.id}, '${escapedStoreName}', '${escapedCountry}')">Find URL</button>
                        <button class="btn-small btn-skip" onclick="skipStore(${currentStore.id})">Skip</button>
                    ` : ''}
                    ${isScrapingInProgress ? `
                        <p class="info-message">Email scraping in progress... Please wait.</p>
                    ` : ''}
                </div>
            </div>
        `;
    } catch (error) {
        console.error('Error refreshing store display:', error);
    }
}

async function loadPendingStores() {
    // This function is kept for backward compatibility but now loads one store
    await loadNextStore();
}

async function findStoreUrl(storeId, storeName, country) {
    // Prevent concurrent calls
    if (isFindingUrl) {
        console.log('findStoreUrl already in progress, skipping...', {storeId, storeName});
        return;
    }
    
    // CRITICAL: Do not proceed if email scraping is in progress
    if (isEmailScrapingInProgress) {
        console.log('Cannot start Find URL - email scraping is still in progress', {storeId, storeName});
        showStatus('Please wait for email scraping to complete before finding next URL', 'info');
        return;
    }
    
    // Validate that storeId matches currentStore (if available)
    if (currentStore && currentStore.id !== storeId) {
        console.warn(`Store ID mismatch: currentStore.id=${currentStore.id}, requested storeId=${storeId}`);
        // Still proceed, but log the warning
    }
    
    // Ensure modal is closed and flags are reset before starting
    closeModal();
    isFindingUrl = true;
    isAutoTriggering = false; // Reset auto-trigger flag when starting findStoreUrl
    
    console.log('Starting findStoreUrl', {storeId, storeName, country, isFindingUrl});
    
    const modal = document.getElementById('modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    
    // Close any existing modal first to avoid conflicts
    if (modal.style.display === 'block') {
        closeModal();
        // Small delay to ensure modal is fully closed
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    
    modalTitle.textContent = `Find URL for ${storeName}`;
    modalBody.innerHTML = '<div class="loading">Requesting search from Chrome extension...</div>';
    modal.style.display = 'block';
    
    // Clean store name
    let cleanName = storeName;
    cleanName = cleanName.replace(/\s*shopify\s*store\s*/gi, ' ');
    cleanName = cleanName.replace(/\s*\|\s*[A-Z]{2}\s*/g, ' ');
    cleanName = cleanName.replace(/\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}/gi, '');
    cleanName = cleanName.replace(/\s+\d{1,2}\/\d{1,2}\/\d{4}/g, '');
    cleanName = cleanName.split(/\s+/).filter(w => w).join(' ').trim();
    
    // Try direct extension communication first (if extension is installed)
    if (window.extensionSearch) {
        try {
            modalBody.innerHTML = '<div class="loading">Extension is searching Google...</div>';
            const result = await window.extensionSearch(cleanName);
            
            if (result.success && result.urls && result.urls.length > 0) {
                await displayExtractedUrls(result.urls, storeId, storeName);
                isFindingUrl = false; // Reset flag when URLs are displayed
                return;
            }
        } catch (error) {
            console.log('Direct extension call failed, using polling:', error);
        }
    }
    
    // Fallback to polling method
    try {
        // Request search from extension via Flask
        const response = await fetch('/api/search/request', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({store_name: cleanName, country: country})
        });
        
        const result = await response.json();
        
        if (result.error) {
            if (result.extension_required) {
                modalBody.innerHTML = `
                    <div class="manual-url-entry">
                        <p class="error"><strong>Chrome Extension Required</strong></p>
                        <p>Please install the Chrome extension to use automatic URL extraction.</p>
                        <p style="margin-top: 15px;">Installation instructions:</p>
                        <ol style="font-size: 12px; margin-left: 20px;">
                            <li>Open Chrome and go to chrome://extensions/</li>
                            <li>Enable "Developer mode"</li>
                            <li>Click "Load unpacked"</li>
                            <li>Select the google_search_extension folder</li>
                        </ol>
                        <p style="margin-top: 15px;">You can still enter the URL manually:</p>
                        <div class="input-group" style="margin-top: 10px;">
                            <input type="text" id="manual-url-input" placeholder="Paste store URL here" style="width: 100%; padding: 10px;">
                        </div>
                        <button class="btn-small" onclick="confirmManualUrl(${storeId})" style="margin-top: 10px; width: 100%;">Confirm URL</button>
                    </div>
                `;
            } else {
                modalBody.innerHTML = `<p class="error">Error: ${result.error}</p>`;
            }
            return;
        }
        
        const searchId = result.search_id;
        
        // Poll for results
        modalBody.innerHTML = `
            <div class="loading">
                <p>Extension is searching Google...</p>
                <p style="font-size: 12px; color: #666; margin-top: 10px;">
                    Search ID: ${searchId}<br>
                    Query: ${result.query}<br>
                    <small>If nothing happens, check Chrome extension console (chrome://extensions → Extension details → Service worker)</small>
                </p>
            </div>
        `;
        
        pollForResults(searchId, storeId, storeName);
        
    } catch (error) {
        console.error('Error in findStoreUrl:', error);
        modalBody.innerHTML = `
            <p class="error">Error: ${error.message}</p>
            <div style="margin-top: 20px;">
                <p>You can still enter the URL manually:</p>
                <div class="input-group" style="margin-top: 10px;">
                    <input type="text" id="manual-url-input" placeholder="Paste store URL here" style="width: 100%; padding: 10px;">
                </div>
                <button class="btn-small" onclick="confirmManualUrl(${storeId})" style="margin-top: 10px; width: 100%;">Confirm URL</button>
            </div>
        `;
        isFindingUrl = false; // Reset flag on error
    }
}

async function pollForResults(searchId, storeId, storeName) {
    const modalBody = document.getElementById('modal-body');
    let attempts = 0;
    const maxAttempts = 30; // 30 seconds max
    
    const poll = async () => {
        attempts++;
        
        try {
            const response = await fetch(`/api/search/poll/${searchId}`);
            const result = await response.json();
            
            if (result.status === 'complete' && result.urls && result.urls.length > 0) {
                // Show extracted URLs (with AI analysis)
                await displayExtractedUrls(result.urls, storeId, storeName);
                isFindingUrl = false; // Reset flag when URLs are displayed
            } else if (result.status === 'pending' && attempts < maxAttempts) {
                // Keep polling
                setTimeout(poll, 1000);
            } else {
                // Timeout or no results
                isFindingUrl = false; // Reset flag on timeout
                modalBody.innerHTML = `
                    <div class="manual-url-entry">
                        <p><strong>No URLs extracted.</strong> This might be because:</p>
                        <ul>
                            <li>Extension is not installed or not active</li>
                            <li>CAPTCHA appeared on Google</li>
                            <li>Search results didn't load in time</li>
                        </ul>
                        <p style="margin-top: 15px;">You can enter the URL manually:</p>
                        <div class="input-group" style="margin-top: 10px;">
                            <input type="text" id="manual-url-input" placeholder="Paste store URL here" style="width: 100%; padding: 10px;">
                        </div>
                        <button class="btn-small" onclick="confirmManualUrl(${storeId})" style="margin-top: 10px; width: 100%;">Confirm URL</button>
                    </div>
                `;
            }
        } catch (error) {
            console.error('Polling error:', error);
            if (attempts < maxAttempts) {
                setTimeout(poll, 1000);
            } else {
                isFindingUrl = false; // Reset flag on error
                modalBody.innerHTML = `<p class="error">Error polling for results: ${error.message}</p>`;
            }
        }
    };
    
    poll();
}

async function displayExtractedUrls(urls, storeId, storeName) {
    const modalBody = document.getElementById('modal-body');
    
    // Show loading state while AI analyzes
    modalBody.innerHTML = `
        <div class="loading">
            <p>🤖 AI is analyzing search results to find the best match...</p>
        </div>
    `;
    
    // Get store information for AI context
    let country = '';
    let reviewText = '';
    if (currentStore) {
        country = currentStore.country || '';
        reviewText = currentStore.review_text || '';
    } else {
        // Fetch store info if not available
        try {
            const storeResponse = await fetch(`/api/stores/${storeId}`);
            const storeData = await storeResponse.json();
            country = storeData.country || '';
            reviewText = storeData.review_text || '';
        } catch (e) {
            console.warn('Could not fetch store info for AI:', e);
        }
    }
    
    // Call AI endpoint to select best URL
    let aiSelectedIndex = -1;
    let aiConfidence = 0;
    let aiReasoning = '';
    
    try {
        const aiResponse = await fetch('/api/ai/select-url', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                store_name: storeName,
                country: country,
                review_text: reviewText,
                search_results: urls
            })
        });
        
        if (aiResponse.ok) {
            const aiResult = await aiResponse.json();
            if (aiResult.success) {
                aiSelectedIndex = aiResult.selected_index;
                aiConfidence = aiResult.confidence;
                aiReasoning = aiResult.reasoning;
                console.log('AI selected URL:', aiResult.selected_url, 'Confidence:', aiConfidence);
                
                // Auto-select if AI auto-select mode is ON and confidence is high enough (>= 0.7)
                if (aiAutoSelectMode && aiSelectedIndex >= 0 && aiSelectedIndex < urls.length && aiConfidence >= 0.7) {
                    const selectedUrl = urls[aiSelectedIndex].url;
                    showStatus(`🤖 AI auto-selected URL with ${Math.round(aiConfidence * 100)}% confidence. Processing...`, 'success');
                    
                    // Ensure modal is closed and flag is reset
                    closeModal();
                    isFindingUrl = false;
                    
                    // Small delay to ensure modal is fully closed before proceeding
                    await new Promise(resolve => setTimeout(resolve, 200));
                    
                    // Automatically select the AI-chosen URL
                    await selectExtractedUrl(storeId, selectedUrl);
                    return; // Exit early, don't show the selection UI
                }
            }
        } else {
            console.warn('AI selection failed, showing all results');
        }
    } catch (error) {
        console.error('Error calling AI endpoint:', error);
        // Continue to show results even if AI fails
    }
    
    // Build URLs HTML
    let urlsHtml = '<div class="extracted-urls">';
    urlsHtml += `<p><strong>Found ${urls.length} URLs. Select the correct store URL:</strong></p>`;
    
    if (aiSelectedIndex >= 0 && aiSelectedIndex < urls.length) {
        const autoSelectNote = aiAutoSelectMode && aiConfidence >= 0.7 
            ? '<br><small style="color: #666; font-style: italic;">(Auto-selection skipped due to low confidence or mode disabled)</small>'
            : '';
        urlsHtml += `<div style="background: #e8f5e9; border-left: 4px solid #4caf50; padding: 10px; margin-bottom: 15px; border-radius: 4px;">
            <p style="margin: 0; font-size: 13px; color: #2e7d32;">
                <strong>🤖 AI Recommendation:</strong> The AI selected result #${aiSelectedIndex + 1} with ${Math.round(aiConfidence * 100)}% confidence.
                <br><small style="color: #666;">${aiReasoning}</small>
                ${autoSelectNote}
            </p>
        </div>`;
    }
    
    urlsHtml += '<div class="url-buttons-container" style="max-height: 400px; overflow-y: auto; margin-top: 15px;">';
    
    urls.forEach((urlData, index) => {
        try {
            const urlObj = new URL(urlData.url);
            const domain = urlObj.hostname.replace('www.', '');
            const shopifyBadge = urlData.is_shopify ? '<span class="shopify-badge" style="background: #95BF47; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px; margin-left: 8px;">Shopify</span>' : '';
            
            // Properly escape URL for use in onclick attribute
            // Need to escape: single quotes, backslashes, and newlines
            const escapedUrl = urlData.url
                .replace(/\\/g, '\\\\')  // Escape backslashes first
                .replace(/'/g, "\\'")     // Escape single quotes
                .replace(/"/g, '&quot;')  // Escape double quotes
                .replace(/\n/g, '\\n')    // Escape newlines
                .replace(/\r/g, '\\r');   // Escape carriage returns
            
            const escapedTitle = (urlData.title || domain)
                .replace(/\\/g, '\\\\')
                .replace(/'/g, "\\'")
                .replace(/"/g, '&quot;')
                .replace(/\n/g, '\\n')
                .replace(/\r/g, '\\r');
            
            const escapedSnippet = (urlData.snippet || '')
                .replace(/\\/g, '\\\\')
                .replace(/'/g, "\\'")
                .replace(/"/g, '&quot;')
                .replace(/\n/g, '\\n')
                .replace(/\r/g, '\\r');
            
            // Highlight AI-selected result
            const isAISelected = index === aiSelectedIndex;
            const borderColor = isAISelected ? '#4caf50' : '#ddd';
            const borderWidth = isAISelected ? '3px' : '1px';
            const backgroundColor = isAISelected ? '#f1f8e9' : 'white';
            const aiBadge = isAISelected ? '<span style="background: #4caf50; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px; margin-left: 8px; font-weight: bold;">🤖 AI SELECTED</span>' : '';
            
            urlsHtml += `
                <div class="url-button-item" style="margin-bottom: 10px; border: ${borderWidth} solid ${borderColor}; border-radius: 5px; padding: 12px; cursor: pointer; transition: all 0.2s; background: ${backgroundColor}; box-shadow: ${isAISelected ? '0 2px 8px rgba(76, 175, 80, 0.3)' : 'none'};" 
                     onclick="selectExtractedUrl(${storeId}, '${escapedUrl}')"
                     onmouseover="this.style.background='${isAISelected ? '#e8f5e9' : '#f5f5f5'}'; this.style.transform='translateY(-1px)'" 
                     onmouseout="this.style.background='${backgroundColor}'; this.style.transform='translateY(0)'">
                    <div style="font-weight: bold; color: #0066cc; margin-bottom: 4px; display: flex; align-items: center; justify-content: space-between;">
                        <span>${escapedTitle}</span>
                        <span>${shopifyBadge}${aiBadge}</span>
                    </div>
                    <div style="font-size: 12px; color: #666; margin-bottom: 4px;">
                        ${domain}
                    </div>
                    ${escapedSnippet ? `<div style="font-size: 11px; color: #888; margin-top: 4px;">${escapedSnippet}</div>` : ''}
                </div>
            `;
        } catch (e) {
            console.error('Error processing URL:', e);
        }
    });
    
    urlsHtml += '</div>';
    urlsHtml += '<div style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #ddd;">';
    urlsHtml += '<p style="font-size: 12px; color: #666; margin-bottom: 10px;">Or enter URL manually:</p>';
    urlsHtml += '<div class="input-group">';
    urlsHtml += '<input type="text" id="manual-url-input" placeholder="Paste store URL here" style="width: 100%; padding: 10px; font-size: 14px;">';
    urlsHtml += '</div>';
    urlsHtml += '<button class="btn-small" onclick="confirmManualUrl(' + storeId + ')" style="margin-top: 10px; width: 100%;">Confirm Manual URL</button>';
    urlsHtml += '</div>';
    urlsHtml += '</div>';
    
    modalBody.innerHTML = urlsHtml;
}

async function selectExtractedUrl(storeId, url) {
    if (!url) {
        showStatus('Invalid URL', 'error');
        isFindingUrl = false; // Reset flag on error
        isEmailScrapingInProgress = false; // Ensure flag is reset
        return;
    }
    
    try {
        // Ensure modal is closed and flag is reset
        closeModal();
        isFindingUrl = false;
        
        const response = await fetch(`/api/stores/${storeId}/url`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: url})
        });
        
        if (response.ok) {
            showStatus('URL saved! Email scraping started...', 'success');
            
            // Refresh the current store to get updated URL
            const data = await response.json();
            if (currentStore && currentStore.id === storeId) {
                currentStore.base_url = data.url;
                // Update the display for current store
                await refreshCurrentStoreDisplay();
            }
            
            // CRITICAL: Start checking for email completion
            // This will mark isEmailScrapingInProgress = true
            // and prevent auto-mode from triggering next store until emails are done
            startEmailStatusCheck();
            updateStatistics();
        } else {
            const error = await response.json();
            showStatus(`Error: ${error.error || 'Failed to save URL'}`, 'error');
            isFindingUrl = false; // Reset flag on error
            isEmailScrapingInProgress = false; // Ensure flag is reset
        }
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
        isFindingUrl = false; // Reset flag on error
        isEmailScrapingInProgress = false; // Ensure flag is reset
    }
}

async function confirmManualUrl(storeId) {
    const urlInput = document.getElementById('manual-url-input');
    const url = urlInput.value.trim();
    
    if (!url) {
        showStatus('Please enter a URL', 'error');
        return;
    }
    
    // Basic URL validation
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        showStatus('Please enter a valid URL starting with http:// or https://', 'error');
        return;
    }
    
    // Reset finding URL flag since we're manually confirming
    isFindingUrl = false;
    await selectExtractedUrl(storeId, url);
}

async function selectUrl(storeId, url) {
    try {
        const response = await fetch(`/api/stores/${storeId}/url`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: url})
        });
        
        if (response.ok) {
            showStatus('URL saved! Emails are being scraped...', 'success');
            closeModal();
            loadPendingStores();
            updateStatistics();
        } else {
            const data = await response.json();
            showStatus(`Error: ${data.error}`, 'error');
        }
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    }
}

async function scrapeEmails(storeId, url) {
    try {
        const response = await fetch(`/api/stores/${storeId}/url`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: url})
        });
        
        if (response.ok) {
            showStatus('Email scraping started...', 'info');
            setTimeout(() => {
                loadPendingStores();
                updateStatistics();
            }, 5000);
        }
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    }
}

async function updateStatistics() {
    try {
        const url = currentJobId ? `/api/statistics?job_id=${currentJobId}` : '/api/statistics';
        const response = await fetch(url);
        const stats = await response.json();
        
        document.getElementById('total-stores').textContent = stats.total || 0;
        document.getElementById('pending-url').textContent = stats.pending_url || 0;
        document.getElementById('url-verified').textContent = stats.url_verified || 0;
        // Show total emails count instead of stores with emails
        const totalEmails = stats.total_emails || stats.emails_found || 0;
        document.getElementById('emails-found').textContent = totalEmails;
    } catch (error) {
        console.error('Error updating statistics:', error);
    }
}

async function exportJSON() {
    try {
        const response = await fetch('/api/stores');
        const stores = await response.json();
        
        const blob = new Blob([JSON.stringify(stores, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'shopify_stores.json';
        a.click();
        URL.revokeObjectURL(url);
    } catch (error) {
        showStatus(`Error exporting: ${error.message}`, 'error');
    }
}

async function exportCSV() {
    try {
        const response = await fetch('/api/stores');
        const stores = await response.json();
        
        const headers = ['ID', 'Store Name', 'Country', 'Base URL', 'Emails', 'Status'];
        const rows = stores.map(store => [
            store.id,
            store.store_name,
            store.country || '',
            store.base_url || '',
            (store.emails || []).join('; '),
            store.status
        ]);
        
        const csv = [headers.join(','), ...rows.map(r => r.map(c => `"${c}"`).join(','))].join('\n');
        
        const blob = new Blob([csv], {type: 'text/csv'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'shopify_stores.csv';
        a.click();
        URL.revokeObjectURL(url);
    } catch (error) {
        showStatus(`Error exporting: ${error.message}`, 'error');
    }
}

function showStatus(message, type) {
    const statusDiv = document.getElementById('job-status');
    statusDiv.textContent = message;
    statusDiv.className = `status ${type}`;
    setTimeout(() => {
        statusDiv.textContent = '';
        statusDiv.className = 'status';
    }, 5000);
}

function closeModal() {
    const modal = document.getElementById('modal');
    if (modal) {
        modal.style.display = 'none';
    }
    // Reset flag when modal is closed (safety measure)
    // Individual functions will also reset it explicitly when needed
    isFindingUrl = false;
}

function startPolling() {
    setInterval(() => {
        updateStatistics();
        // Don't auto-reload stores, user controls navigation with skip/next
    }, 5000);
}

