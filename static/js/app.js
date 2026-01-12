let currentJobId = null;
let pollInterval = null;
let autoMode = false; // Auto-mode state
let aiAutoSelectMode = false; // AI auto-selection mode state
let urlFindingActive = false; // Track if URL finding is actively running

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
            updateUrlFindingButtons();
            if (autoMode) {
                showStatus('Auto mode enabled. Click "Start URL Finding" to begin.', 'success');
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
    // Check if email scraping is in progress
    try {
        const batchStatusResponse = await fetch('/api/email-scraping/batch/status');
        if (batchStatusResponse.ok) {
            const batchStatus = await batchStatusResponse.json();
            if (batchStatus.is_processing || batchStatus.pending_count > 0) {
                // Email scraping is active, show that phase
                startBatchEmailScrapingMonitor();
                return;
            }
        }
    } catch (error) {
        console.error('Error checking batch status:', error);
    }
    
    // Check URL finding status (but don't auto-start)
    try {
        const urlStatusResponse = await fetch('/api/stores/url-finding-status');
        if (urlStatusResponse.ok) {
            const urlStatus = await urlStatusResponse.json();
            
            if (urlStatus.is_complete && urlStatus.stores_with_urls > 0) {
                // All URLs found, start email scraping
                await startBatchEmailScraping();
                return;
            } else if (urlStatus.pending_count > 0) {
                // Show status but don't start automatically
                await displayUrlFindingStatus(urlStatus);
                updateUrlFindingButtons();
                // Start monitoring to keep status updated
                if (!urlFindingStatusInterval) {
                    startUrlFindingStatusMonitor();
                }
                return;
            } else {
                // No pending stores, but show status anyway
                await displayUrlFindingStatus(urlStatus);
                updateUrlFindingButtons();
                return;
            }
        }
    } catch (error) {
        console.error('Error checking URL status:', error);
    }
    
    // Just show status, don't auto-start
    updateUrlFindingButtons();
    
    // Also check button state periodically
    setInterval(() => {
        if (!urlFindingActive && !urlFindingStatusInterval) {
            updateUrlFindingButtons();
        }
    }, 5000);
}

function initializeEventListeners() {
    document.getElementById('start-scraping').addEventListener('click', startScraping);
    document.getElementById('export-json').addEventListener('click', exportJSON);
    document.getElementById('export-csv').addEventListener('click', exportCSV);
    document.querySelector('.close').addEventListener('click', closeModal);
    
    const startUrlFindingBtn = document.getElementById('start-url-finding');
    const stopUrlFindingBtn = document.getElementById('stop-url-finding');
    
    if (startUrlFindingBtn) {
        startUrlFindingBtn.addEventListener('click', startUrlFinding);
    }
    if (stopUrlFindingBtn) {
        stopUrlFindingBtn.addEventListener('click', stopUrlFinding);
    }
    
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
                // Reviews are done, update buttons but don't auto-start
                updateUrlFindingButtons();
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
let batchEmailScrapingInterval = null; // Interval for monitoring batch email scraping
let isFindingUrl = false; // Guard to prevent concurrent findStoreUrl calls
let isAutoTriggering = false; // Guard to prevent multiple auto-triggers
let isEmailScrapingInProgress = false; // Track if email scraping is in progress

let urlFindingStatusInterval = null;

async function displayUrlFindingStatus(statusData) {
    const container = document.getElementById('stores-container');
    
    const total = statusData.total_stores || 0;
    const found = statusData.stores_with_urls || 0;
    const pending = statusData.pending_count || 0;
    const progressPercent = statusData.progress_percent || 0;
    
    let html = '<div style="margin-bottom: 20px;">';
    html += '<h3>🔍 URL Finding Phase</h3>';
    html += '<p style="color: #666; font-size: 14px; margin-top: 5px;">Finding store URLs for all reviews. Email scraping will start after all URLs are found.</p>';
    html += '</div>';
    
    // Progress summary card
    html += '<div style="margin-bottom: 20px; padding: 15px; background: linear-gradient(135deg, #3498db 0%, #2980b9 100%); border-radius: 8px; color: white;">';
    html += '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 15px;">';
    html += `<div><div style="font-size: 24px; font-weight: bold;">${found}</div><div style="font-size: 12px; opacity: 0.9;">URLs Found</div></div>`;
    html += `<div><div style="font-size: 24px; font-weight: bold;">${pending}</div><div style="font-size: 12px; opacity: 0.9;">Pending</div></div>`;
    html += `<div><div style="font-size: 24px; font-weight: bold;">${total}</div><div style="font-size: 12px; opacity: 0.9;">Total Stores</div></div>`;
    html += '</div>';
    
    // Progress bar
    html += '<div style="background: rgba(255,255,255,0.2); border-radius: 10px; height: 20px; overflow: hidden; margin-top: 10px;">';
    html += `<div style="background: white; height: 100%; width: ${progressPercent}%; transition: width 0.3s; display: flex; align-items: center; justify-content: center; color: #3498db; font-size: 11px; font-weight: bold;">${progressPercent}%</div>`;
    html += '</div>';
    html += '</div>';
    
    // Current store being processed
    if (currentStore && !currentStore.base_url) {
        const escapedStoreName = (currentStore.store_name || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        const escapedCountry = (currentStore.country || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        
        html += '<div style="margin-bottom: 20px;">';
        html += '<h4 style="margin: 0 0 15px 0; color: #3498db; font-size: 16px;">🔍 Currently Finding URL</h4>';
        html += '<div class="store-item" style="border: 2px solid #3498db; border-radius: 8px; padding: 15px; background: #fff; box-shadow: 0 2px 4px rgba(52,152,219,0.2);">';
        html += `<h4 style="margin: 0 0 10px 0;">${currentStore.store_name}</h4>`;
        html += `<p style="margin: 5px 0; font-size: 13px; color: #666;"><strong>Country:</strong> ${currentStore.country || 'N/A'}</p>`;
        if (currentStore.rating) {
            html += `<p style="margin: 5px 0;"><strong>Rating:</strong> ${'★'.repeat(currentStore.rating)}${'☆'.repeat(5 - currentStore.rating)} (${currentStore.rating} stars)</p>`;
        }
        html += `<p style="margin: 5px 0; font-size: 13px; color: #666;"><strong>Review:</strong> ${currentStore.review_text ? (currentStore.review_text.substring(0, 100) + '...') : 'N/A'}</p>`;
        html += `<div style="margin-top: 15px;">`;
        if (!isFindingUrl) {
            html += `<button class="btn-small" onclick="findStoreUrl(${currentStore.id}, '${escapedStoreName}', '${escapedCountry}')">Find URL</button>`;
            html += `<button class="btn-small btn-skip" onclick="skipStore(${currentStore.id})" style="margin-left: 10px;">Skip</button>`;
        } else {
            html += `<p class="info-message" style="color: #3498db; font-weight: 500;">🔍 Finding URL...</p>`;
        }
        html += `</div></div></div>`;
    }
    
    // Pending stores section - always show if there are pending stores
    if (pending > 0) {
        html += '<div style="margin-bottom: 20px;">';
        html += '<h4 style="margin: 0 0 15px 0; color: #95a5a6; font-size: 16px;">⏳ Waiting for URL Finding</h4>';
        
        if (!urlFindingActive && !currentStore) {
            html += '<p style="color: #e74c3c; font-size: 14px; margin-bottom: 15px; padding: 10px; background: #ffe6e6; border-radius: 4px; border-left: 4px solid #e74c3c;">';
            html += '⚠️ URL finding is not active. Click "Start URL Finding" button above to begin processing these stores.';
            html += '</p>';
        }
        
        html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px;">';
        
        // Show pending stores from statusData
        if (statusData.pending_stores && statusData.pending_stores.length > 0) {
            const pendingToShow = Math.min(statusData.pending_stores.length, 20); // Show up to 20
            for (let i = 0; i < pendingToShow; i++) {
                const store = statusData.pending_stores[i];
                html += `
                    <div class="store-item" style="border: 2px solid #95a5a6; border-radius: 8px; padding: 15px; background: #f8f9fa;">
                        <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px;">
                            <h4 style="margin: 0; flex: 1; font-size: 15px;">${store.store_name || 'N/A'}</h4>
                            <span style="background: #95a5a6; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;">⏳ #${i + 1}</span>
                        </div>
                        <p style="margin: 5px 0; font-size: 13px; color: #666;"><strong>Country:</strong> ${store.country || 'N/A'}</p>
                        ${store.rating ? `<p style="margin: 5px 0;"><strong>Rating:</strong> ${'★'.repeat(store.rating)}${'☆'.repeat(5 - store.rating)} (${store.rating} stars)</p>` : ''}
                    </div>
                `;
            }
            
            if (pending > pendingToShow) {
                html += `
                    <div class="store-item" style="border: 2px solid #e0e0e0; border-radius: 8px; padding: 15px; background: #f5f5f5; text-align: center;">
                        <p style="margin: 0; color: #666; font-size: 13px; font-weight: 500;">+ ${pending - pendingToShow} more stores pending</p>
                    </div>
                `;
            }
        } else {
            // If no pending stores in response but pending count > 0, show a message
            html += `
                <div class="store-item" style="border: 2px solid #95a5a6; border-radius: 8px; padding: 15px; background: #f8f9fa; text-align: center;">
                    <p style="margin: 0; color: #666; font-size: 13px;">${pending} stores pending URL finding</p>
                </div>
            `;
        }
        
        html += '</div></div>';
    }
    
    // Recently found URLs section
    if (statusData.recently_found && statusData.recently_found.length > 0) {
        html += '<div style="margin-bottom: 20px;">';
        html += '<h4 style="margin: 0 0 15px 0; color: #27ae60; font-size: 16px;">✅ Recently Found URLs</h4>';
        html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px;">';
        
        for (const store of statusData.recently_found) {
            html += `
                <div class="store-item" style="border: 2px solid #27ae60; border-radius: 8px; padding: 15px; background: #f0f9f4;">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px;">
                        <h4 style="margin: 0; flex: 1; font-size: 15px;">${store.store_name || 'N/A'}</h4>
                        <span style="background: #27ae60; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;">✅ Found</span>
                    </div>
                    <p style="margin: 5px 0; font-size: 13px; color: #666;"><strong>Country:</strong> ${store.country || 'N/A'}</p>
                    ${store.base_url ? `<p style="margin: 5px 0; font-size: 12px; color: #0066cc; word-break: break-all;"><strong>URL:</strong> ${store.base_url}</p>` : ''}
                </div>
            `;
        }
        
        html += '</div></div>';
    }
    
    container.innerHTML = html;
    updateStatistics();
}

function startUrlFindingStatusMonitor() {
    if (urlFindingStatusInterval) {
        clearInterval(urlFindingStatusInterval);
    }
    
    urlFindingStatusInterval = setInterval(async () => {
        if (!urlFindingActive) {
            clearInterval(urlFindingStatusInterval);
            urlFindingStatusInterval = null;
            return;
        }
        
        try {
            const response = await fetch('/api/stores/url-finding-status');
            if (response.ok) {
                const statusData = await response.json();
                await displayUrlFindingStatus(statusData);
                updateUrlFindingButtons();
                
                // If all URLs are found, stop monitoring and start email scraping
                if (statusData.is_complete && statusData.stores_with_urls > 0) {
                    urlFindingActive = false;
                    clearInterval(urlFindingStatusInterval);
                    urlFindingStatusInterval = null;
                    updateUrlFindingButtons();
                    showStatus('All URLs found! Starting email scraping...', 'success');
                    setTimeout(async () => {
                        await startBatchEmailScraping();
                    }, 1000);
                } else if (statusData.pending_count === 0 && statusData.stores_with_urls === 0) {
                    // No more stores to process
                    urlFindingActive = false;
                    clearInterval(urlFindingStatusInterval);
                    urlFindingStatusInterval = null;
                    updateUrlFindingButtons();
                    showStatus('No more stores to process.', 'info');
                }
            }
        } catch (error) {
            console.error('Error checking URL finding status:', error);
        }
    }, 3000);
}

async function loadNextStore() {
    try {
        const response = await fetch('/api/stores/next');
        const data = await response.json();
        
        const container = document.getElementById('stores-container');
        
        if (!data.store) {
            // Check if we're in URL finding phase
            const urlStatusResponse = await fetch('/api/stores/url-finding-status');
            if (urlStatusResponse.ok) {
                const urlStatus = await urlStatusResponse.json();
                if (!urlStatus.is_complete) {
                    // Still finding URLs, show status
                    startUrlFindingStatusMonitor();
                    return;
                }
            }
            
            container.innerHTML = '<p>No more stores pending. All reviews have been processed!</p>';
            if (emailCheckInterval) {
                clearInterval(emailCheckInterval);
                emailCheckInterval = null;
            }
            return;
        }
        
        currentStore = data.store;
        
        // Start URL finding status monitor if not already running
        if (!urlFindingStatusInterval) {
            startUrlFindingStatusMonitor();
        }
        
        // Escape strings for use in onclick attributes
        const escapedStoreName = (currentStore.store_name || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        const escapedCountry = (currentStore.country || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        
        // Show current store in context of URL finding status
        const urlStatusResponse = await fetch('/api/stores/url-finding-status');
        if (urlStatusResponse.ok) {
            const urlStatus = await urlStatusResponse.json();
            await displayUrlFindingStatus(urlStatus);
            // Don't return here - continue to auto-trigger logic below
        } else {
            // Fallback to simple display if status fetch fails
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
                        ${currentStore.base_url && (!currentStore.emails || currentStore.emails.length === 0) ? `
                            <p class="info-message" style="color: #27ae60;">✓ URL found. Email scraping will start after all URLs are found.</p>
                        ` : ''}
                    </div>
                </div>
            `;
        }
        
        // If store has URL but no emails, it's in the URL finding phase
        // Email scraping will happen later in batch mode
        // Just move to next store if auto-mode is enabled and URL finding is active
        if (urlFindingActive && autoMode && currentStore.base_url && (!currentStore.emails || currentStore.emails.length === 0)) {
            // URL found, move to next store to find more URLs
            setTimeout(async () => {
                if (!isFindingUrl && urlFindingActive) {
                    await loadNextStore();
                    updateStatistics();
                }
            }, 1000);
            return;
        }
        
        // If store already has emails, it's complete - move to next store if auto-mode is enabled and URL finding is active
        if (urlFindingActive && autoMode && currentStore.base_url && currentStore.emails && currentStore.emails.length > 0) {
            // Store is complete, move to next store
            setTimeout(async () => {
                if (!isFindingUrl && urlFindingActive) {
                    await loadNextStore();
                    updateStatistics();
                }
            }, 1000);
            return;
        }
        
        // Auto-mode: automatically trigger Find URL ONLY if:
        // 1. Store has no URL
        // 2. Not already finding URL
        // 3. Auto-mode is enabled
        // 4. URL finding is actively running
        if (urlFindingActive && autoMode && !currentStore.base_url && !isFindingUrl) {
            // Ensure clean state
            closeModal();
            
            // Set flag to prevent multiple triggers
            isAutoTriggering = true;
            
            // Small delay to ensure UI is rendered before triggering
            setTimeout(() => {
                // Double-check conditions before triggering (ensure currentStore hasn't changed)
                // CRITICAL: Also check that email scraping is not in progress
                if (urlFindingActive && autoMode && 
                    currentStore && 
                    currentStore.id === data.store.id && 
                    !currentStore.base_url && 
                    !isFindingUrl) {
                    
                    console.log('🤖 Auto-mode: Triggering Find URL', {
                        storeId: currentStore.id,
                        storeName: currentStore.store_name,
                        hasBaseUrl: !!currentStore.base_url,
                        isFindingUrl,
                        isAutoTriggering,
                        urlFindingActive
                    });
                    showStatus('🤖 Auto mode: Automatically finding URL...', 'info');
                    findStoreUrl(currentStore.id, currentStore.store_name, currentStore.country || '');
                } else {
                    // Reset flag if conditions not met
                    isAutoTriggering = false;
                    console.log('🤖 Auto-mode: Conditions changed, skipping Find URL', {
                        autoMode,
                        urlFindingActive,
                        hasCurrentStore: !!currentStore,
                        storeIdMatch: currentStore?.id === data.store.id,
                        hasBaseUrl: !!currentStore?.base_url,
                        isFindingUrl
                    });
                }
            }, 500);
        }
    } catch (error) {
        console.error('Error loading next store:', error);
    }
}

async function skipStoreFromUrlSelection(storeId) {
    // Skip store from URL selection modal - closes modal and skips
    closeModal();
    isFindingUrl = false;
    await skipStore(storeId);
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
        
        const hasEmails = currentStore.emails && currentStore.emails.length > 0;
        const isEmailScrapingComplete = currentStore.status === 'emails_found' || currentStore.status === 'no_emails_found';
        
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
                    ${currentStore.base_url && (!hasEmails) ? `
                        <p class="info-message" style="color: #27ae60;">✓ URL found. Email scraping will start after all URLs are found.</p>
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

async function startUrlFinding() {
    if (urlFindingActive) {
        showStatus('URL finding is already running.', 'info');
        return;
    }
    
    // Check if auto mode is enabled (warn but don't block)
    if (!autoMode) {
        showStatus('Auto Mode is not enabled. URL finding will work but may require manual intervention.', 'warning');
    }
    
    // Reset state to ensure clean restart
    currentStore = null;
    isFindingUrl = false;
    isAutoTriggering = false;
    
    urlFindingActive = true;
    updateUrlFindingButtons();
    showStatus('Starting URL finding...', 'info');
    
    // Check if email scraping is in progress first
    try {
        const batchStatusResponse = await fetch('/api/email-scraping/batch/status');
        if (batchStatusResponse.ok) {
            const batchStatus = await batchStatusResponse.json();
            if (batchStatus.is_processing || batchStatus.pending_count > 0) {
                showStatus('Email scraping is in progress. URL finding will start after email scraping completes.', 'info');
                urlFindingActive = false;
                updateUrlFindingButtons();
                return;
            }
        }
    } catch (error) {
        console.error('Error checking batch status:', error);
    }
    
    // Check URL finding status
    try {
        const urlStatusResponse = await fetch('/api/stores/url-finding-status');
        if (urlStatusResponse.ok) {
            const urlStatus = await urlStatusResponse.json();
            
            // Priority: Check for pending URLs first - URL finding must complete before email scraping
            if (urlStatus.pending_count > 0) {
                // Start URL finding - there are still pending URLs to find
                startUrlFindingStatusMonitor();
                // Load the first store to start processing
                await loadNextStore();
                showStatus('URL finding started!', 'success');
                return;
            } else if (urlStatus.is_complete && urlStatus.stores_with_urls > 0) {
                // All URLs found (no pending), now start email scraping
                urlFindingActive = false;
                updateUrlFindingButtons();
                await startBatchEmailScraping();
                return;
            } else {
                // No pending URLs and no stores with URLs
                showStatus('No stores pending URL finding.', 'info');
                urlFindingActive = false;
                updateUrlFindingButtons();
                // Still show the status
                await displayUrlFindingStatus(urlStatus);
                return;
            }
        }
    } catch (error) {
        console.error('Error starting URL finding:', error);
        showStatus('Error starting URL finding.', 'error');
        urlFindingActive = false;
        updateUrlFindingButtons();
    }
}

function stopUrlFinding() {
    if (!urlFindingActive) {
        showStatus('URL finding is not running.', 'info');
        return;
    }
    
    urlFindingActive = false;
    
    // Stop the status monitor
    if (urlFindingStatusInterval) {
        clearInterval(urlFindingStatusInterval);
        urlFindingStatusInterval = null;
    }
    
    // Reset flags and state
    isFindingUrl = false;
    isAutoTriggering = false;
    currentStore = null; // Clear current store so restart works properly
    closeModal();
    
    updateUrlFindingButtons();
    showStatus('URL finding stopped.', 'info');
    
    // Show current status without auto-loading next store
    fetch('/api/stores/url-finding-status')
        .then(response => response.json())
        .then(statusData => displayUrlFindingStatus(statusData))
        .catch(error => console.error('Error fetching URL status:', error));
}

function updateUrlFindingButtons() {
    const startBtn = document.getElementById('start-url-finding');
    const stopBtn = document.getElementById('stop-url-finding');
    
    if (!startBtn || !stopBtn) return;
    
    // Check if there are pending stores
    fetch('/api/stores/url-finding-status')
        .then(response => response.json())
        .then(statusData => {
            const hasPending = statusData.pending_count > 0 && !statusData.is_complete;
            
            // Show buttons if there are pending stores (regardless of auto mode)
            // Auto mode is only required to actually start automatically
            if (hasPending) {
                if (urlFindingActive) {
                    startBtn.style.display = 'none';
                    stopBtn.style.display = 'block';
                } else {
                    startBtn.style.display = 'block';
                    stopBtn.style.display = 'none';
                }
            } else {
                startBtn.style.display = 'none';
                stopBtn.style.display = 'none';
            }
        })
        .catch(error => {
            console.error('Error checking URL status for buttons:', error);
            startBtn.style.display = 'none';
            stopBtn.style.display = 'none';
        });
}

async function startBatchEmailScraping() {
    try {
        showStatus('Starting batch email scraping...', 'info');
        const response = await fetch('/api/email-scraping/batch/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        
        if (response.ok) {
            const data = await response.json();
            showStatus(`Batch email scraping started. ${data.active_count} stores processing concurrently.`, 'success');
            startBatchEmailScrapingMonitor();
        } else {
            const error = await response.json();
            showStatus(`Error: ${error.message || 'Failed to start batch email scraping'}`, 'error');
        }
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    }
}

function startBatchEmailScrapingMonitor() {
    if (batchEmailScrapingInterval) {
        clearInterval(batchEmailScrapingInterval);
    }
    
    batchEmailScrapingInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/email-scraping/batch/status');
            if (response.ok) {
                const data = await response.json();
                await displayBatchEmailScrapingStatus(data);
                
                // Continuously fill available slots to maintain 10 active jobs
                if (data.available_slots > 0 && data.pending_count > 0) {
                    // Start jobs to fill available slots - do them in parallel, not sequentially
                    const jobsToStart = Math.min(data.available_slots, data.pending_count);
                    const startPromises = [];
                    
                    for (let i = 0; i < jobsToStart; i++) {
                        startPromises.push(
                            fetch('/api/email-scraping/start-next-job', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'}
                            }).then(async (startResponse) => {
                                if (startResponse.ok) {
                                    const startData = await startResponse.json();
                                    if (startData.success) {
                                        console.log(`Started email scraping for store ${startData.store_id}. Active: ${startData.active_count}/${startData.max_concurrent}`);
                                    } else {
                                        console.log(`Could not start job: ${startData.message || 'Unknown reason'}`);
                                    }
                                    return startData;
                                } else {
                                    const errorData = await startResponse.json().catch(() => ({}));
                                    console.log(`Failed to start job: ${errorData.message || 'HTTP error'}`);
                                    return null;
                                }
                            }).catch(error => {
                                console.error('Error starting next email scraping job:', error);
                                return null;
                            })
                        );
                    }
                    
                    // Wait for all to complete (but they're running in parallel)
                    const results = await Promise.all(startPromises);
                    const successful = results.filter(r => r && r.success).length;
                    if (successful > 0) {
                        console.log(`Successfully started ${successful} out of ${jobsToStart} requested jobs`);
                    }
                }
                
                // Check if all done
                if (!data.is_processing && data.pending_count === 0 && data.active_count === 0) {
                    // All done
                    clearInterval(batchEmailScrapingInterval);
                    batchEmailScrapingInterval = null;
                    showStatus('All email scraping completed!', 'success');
                    updateStatistics();
                    
                    // Check for more stores that need URL finding
                    const nextStoreResponse = await fetch('/api/stores/next');
                    if (nextStoreResponse.ok) {
                        const nextStoreData = await nextStoreResponse.json();
                        if (nextStoreData.store) {
                            await loadNextStore();
                        }
                    }
                }
            }
        } catch (error) {
            console.error('Error checking batch email scraping status:', error);
        }
    }, 3000); // Check every 3 seconds
}

async function displayBatchEmailScrapingStatus(statusData) {
    const container = document.getElementById('stores-container');
    
    // Progress calculation
    const total = statusData.total_with_urls || 0;
    const completed = statusData.total_completed || 0;
    const active = statusData.active_count || 0;
    const pending = statusData.pending_count || 0;
    const progressPercent = statusData.progress_percent || 0;
    
    // Debug logging
    if (active > 0) {
        console.log(`Email scraping status: ${active} active, ${statusData.active_stores?.length || 0} active stores in response`, {
            active_count: active,
            active_stores_length: statusData.active_stores?.length || 0,
            active_store_ids: statusData.active_store_ids?.length || 0,
            active_stores: statusData.active_stores
        });
    }
    
    let html = '<div style="margin-bottom: 20px;">';
    html += '<h3>📧 Email Scraping Phase (Continuous Processing)</h3>';
    html += '<p style="color: #666; font-size: 14px; margin-top: 5px;">Always maintaining 10 active stores. When one completes, the next automatically starts.</p>';
    html += '</div>';
    
    // Progress summary card
    html += '<div style="margin-bottom: 20px; padding: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px; color: white;">';
    html += '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 15px;">';
    html += `<div><div style="font-size: 24px; font-weight: bold;">${completed}</div><div style="font-size: 12px; opacity: 0.9;">Completed</div></div>`;
    html += `<div><div style="font-size: 24px; font-weight: bold;">${active}</div><div style="font-size: 12px; opacity: 0.9;">Active Now</div></div>`;
    html += `<div><div style="font-size: 24px; font-weight: bold;">${pending}</div><div style="font-size: 12px; opacity: 0.9;">In Queue</div></div>`;
    html += `<div><div style="font-size: 24px; font-weight: bold;">${total}</div><div style="font-size: 12px; opacity: 0.9;">Total with URLs</div></div>`;
    html += '</div>';
    
    // Progress bar
    html += '<div style="background: rgba(255,255,255,0.2); border-radius: 10px; height: 20px; overflow: hidden; margin-top: 10px;">';
    html += `<div style="background: white; height: 100%; width: ${progressPercent}%; transition: width 0.3s; display: flex; align-items: center; justify-content: center; color: #667eea; font-size: 11px; font-weight: bold;">${progressPercent}%</div>`;
    html += '</div>';
    html += '</div>';
    
    // Status details
    html += '<div style="margin-bottom: 20px; padding: 12px; background: #f8f9fa; border-radius: 6px; border-left: 4px solid #3498db;">';
    html += `<p style="margin: 0; font-size: 13px;"><strong>Status:</strong> ${statusData.is_processing ? '🟢 Processing' : '⏸️ Waiting'}</p>`;
    html += `<p style="margin: 5px 0; font-size: 13px;"><strong>Active Slots:</strong> ${active}/${statusData.max_concurrent} | <strong>Available:</strong> ${statusData.available_slots}</p>`;
    html += '</div>';
    
    // Active stores section - show all active stores
    if (active > 0) {
        html += '<div style="margin-bottom: 20px;">';
        html += `<h4 style="margin: 0 0 15px 0; color: #f39c12; font-size: 16px;">📧 Currently Scraping (${active} Active)</h4>`;
        html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px;">';
        
        if (statusData.active_stores && statusData.active_stores.length > 0) {
            // Show all active stores from the response
            for (const store of statusData.active_stores) {
                html += `
                    <div class="store-item" style="border: 2px solid #f39c12; border-radius: 8px; padding: 15px; background: #fff; box-shadow: 0 2px 4px rgba(243,156,18,0.2);">
                        <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px;">
                            <h4 style="margin: 0; flex: 1; font-size: 15px;">${store.store_name || 'N/A'}</h4>
                            <span style="background: #f39c12; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; animation: pulse 2s infinite;">📧 Scraping...</span>
                        </div>
                        <p style="margin: 5px 0; font-size: 13px; color: #666;"><strong>Country:</strong> ${store.country || 'N/A'}</p>
                        ${store.base_url ? `<p style="margin: 5px 0; font-size: 12px; color: #0066cc; word-break: break-all;"><strong>URL:</strong> ${store.base_url}</p>` : ''}
                    </div>
                `;
            }
        } else if (statusData.active_store_ids && statusData.active_store_ids.length > 0) {
            // Fallback: if active_stores array is empty but we have active_store_ids, show them
            for (const storeId of statusData.active_store_ids) {
                html += `
                    <div class="store-item" style="border: 2px solid #f39c12; border-radius: 8px; padding: 15px; background: #fff; box-shadow: 0 2px 4px rgba(243,156,18,0.2);">
                        <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px;">
                            <h4 style="margin: 0; flex: 1; font-size: 15px;">Store ID: ${storeId}</h4>
                            <span style="background: #f39c12; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; animation: pulse 2s infinite;">📧 Scraping...</span>
                        </div>
                        <p style="margin: 5px 0; font-size: 13px; color: #666;">Loading store details...</p>
                    </div>
                `;
            }
        } else {
            // No active stores data but active_count > 0 - show a message
            html += `
                <div class="store-item" style="border: 2px solid #f39c12; border-radius: 8px; padding: 15px; background: #fff; box-shadow: 0 2px 4px rgba(243,156,18,0.2);">
                    <p style="margin: 0; color: #666; font-size: 13px;">${active} stores are being scraped (details loading...)</p>
                </div>
            `;
        }
        
        html += '</div></div>';
    }
    
    // Pending stores section
    if (statusData.pending_stores && statusData.pending_stores.length > 0) {
        html += '<div style="margin-bottom: 20px;">';
        html += '<h4 style="margin: 0 0 15px 0; color: #95a5a6; font-size: 16px;">⏳ Waiting in Queue</h4>';
        html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px;">';
        
        const pendingToShow = Math.min(statusData.pending_stores.length, 10);
        for (let i = 0; i < pendingToShow; i++) {
            const store = statusData.pending_stores[i];
            html += `
                <div class="store-item" style="border: 2px solid #95a5a6; border-radius: 8px; padding: 15px; background: #f8f9fa;">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px;">
                        <h4 style="margin: 0; flex: 1; font-size: 15px;">${store.store_name || 'N/A'}</h4>
                        <span style="background: #95a5a6; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;">⏳ #${i + 1}</span>
                    </div>
                    <p style="margin: 5px 0; font-size: 13px; color: #666;"><strong>Country:</strong> ${store.country || 'N/A'}</p>
                    ${store.base_url ? `<p style="margin: 5px 0; font-size: 12px; color: #0066cc; word-break: break-all;"><strong>URL:</strong> ${store.base_url}</p>` : ''}
                </div>
            `;
        }
        
        if (statusData.pending_count > pendingToShow) {
            html += `
                <div class="store-item" style="border: 2px solid #e0e0e0; border-radius: 8px; padding: 15px; background: #f5f5f5; text-align: center;">
                    <p style="margin: 0; color: #666; font-size: 13px; font-weight: 500;">+ ${statusData.pending_count - pendingToShow} more stores in queue</p>
                </div>
            `;
        }
        
        html += '</div></div>';
    }
    
    // Recently completed stores section
    if (statusData.completed_stores && statusData.completed_stores.length > 0) {
        html += '<div style="margin-bottom: 20px;">';
        html += '<h4 style="margin: 0 0 15px 0; color: #27ae60; font-size: 16px;">✅ Recently Completed</h4>';
        html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px;">';
        
        for (const store of statusData.completed_stores) {
            const hasEmails = store.emails && store.emails.length > 0;
            html += `
                <div class="store-item" style="border: 2px solid #27ae60; border-radius: 8px; padding: 15px; background: #f0f9f4;">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px;">
                        <h4 style="margin: 0; flex: 1; font-size: 15px;">${store.store_name || 'N/A'}</h4>
                        <span style="background: #27ae60; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;">✅ ${hasEmails ? 'Done' : 'No Emails'}</span>
                    </div>
                    <p style="margin: 5px 0; font-size: 13px; color: #666;"><strong>Country:</strong> ${store.country || 'N/A'}</p>
                    ${store.base_url ? `<p style="margin: 5px 0; font-size: 12px; color: #0066cc; word-break: break-all;"><strong>URL:</strong> ${store.base_url}</p>` : ''}
                    ${hasEmails ? `<p style="margin: 5px 0; font-size: 12px; color: #27ae60;"><strong>Emails:</strong> ${store.emails.join(', ')}</p>` : '<p style="margin: 5px 0; font-size: 12px; color: #95a5a6;">No emails found</p>'}
                </div>
            `;
        }
        
        html += '</div></div>';
    }
    
    // Add CSS animation for pulsing effect
    html += '<style>@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }</style>';
    
    container.innerHTML = html;
    updateStatistics();
}

async function findStoreUrl(storeId, storeName, country) {
    // Prevent concurrent calls
    if (isFindingUrl) {
        console.log('findStoreUrl already in progress, skipping...', {storeId, storeName});
        return;
    }
    
    // Note: Email scraping is now separate, so we don't need to check if it's in progress
    
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
                
                // Auto-fallback: If AI confidence is low (< 0.7) and auto-mode is ON, automatically select first result
                if (autoMode && urlFindingActive && aiConfidence < 0.7 && urls.length > 0) {
                    const fallbackUrl = urls[0].url;
                    showStatus(`⚠️ AI confidence low (${Math.round(aiConfidence * 100)}%). Auto-selecting first result to continue...`, 'info');
                    
                    // Ensure modal is closed and flag is reset
                    closeModal();
                    isFindingUrl = false;
                    
                    // Small delay to ensure modal is fully closed before proceeding
                    await new Promise(resolve => setTimeout(resolve, 200));
                    
                    // Automatically select the first URL as fallback
                    await selectExtractedUrl(storeId, fallbackUrl);
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
    
    // Add quick action buttons
    urlsHtml += '<div style="margin-top: 20px; padding-top: 15px; border-top: 2px solid #ddd; background: #f9f9f9; padding: 15px; border-radius: 5px;">';
    urlsHtml += '<p style="font-size: 13px; color: #666; margin-bottom: 12px; font-weight: 500;">Quick Actions (if AI can\'t decide):</p>';
    urlsHtml += '<div style="display: flex; gap: 10px; flex-wrap: wrap;">';
    
    // Select first result button
    if (urls.length > 0) {
        const firstUrl = urls[0].url.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        urlsHtml += `<button class="btn-small" onclick="selectExtractedUrl(${storeId}, '${firstUrl}')" style="flex: 1; min-width: 120px; background: #2196F3; color: white; border: none; padding: 10px; border-radius: 4px; cursor: pointer; font-weight: 500;">✓ Select First</button>`;
    }
    
    // Select last result button
    if (urls.length > 1) {
        const lastUrl = urls[urls.length - 1].url.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        urlsHtml += `<button class="btn-small" onclick="selectExtractedUrl(${storeId}, '${lastUrl}')" style="flex: 1; min-width: 120px; background: #2196F3; color: white; border: none; padding: 10px; border-radius: 4px; cursor: pointer; font-weight: 500;">✓ Select Last</button>`;
    }
    
    // Skip store button
    urlsHtml += `<button class="btn-small" onclick="skipStoreFromUrlSelection(${storeId})" style="flex: 1; min-width: 120px; background: #ff9800; color: white; border: none; padding: 10px; border-radius: 4px; cursor: pointer; font-weight: 500;">⊘ Skip Store</button>`;
    
    urlsHtml += '</div>';
    urlsHtml += '<p style="font-size: 11px; color: #999; margin-top: 10px; margin-bottom: 0;">These actions will automatically proceed without waiting for manual selection.</p>';
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
            const data = await response.json();
            showStatus(data.message || 'URL saved!', 'success');
            
            // Refresh the current store to get updated URL
            if (currentStore && currentStore.id === storeId) {
                currentStore.base_url = data.url;
                // Update the display for current store
                await refreshCurrentStoreDisplay();
            }
            
            // Reset flags
            isFindingUrl = false;
            isAutoTriggering = false;
            
            // Check if all URLs are found (pending_url_count === 0)
            if (data.pending_url_count === 0) {
                // All URLs found! Stop URL finding and start batch email scraping
                urlFindingActive = false;
                updateUrlFindingButtons();
                showStatus('All URLs found! Starting batch email scraping...', 'success');
                setTimeout(async () => {
                    await startBatchEmailScraping();
                }, 1000);
            } else {
                // Not all URLs found yet - if URL finding is active and auto-mode is on, move to next store
                if (urlFindingActive && autoMode) {
                    setTimeout(async () => {
                        if (!isFindingUrl && !isAutoTriggering && urlFindingActive) {
                            await loadNextStore();
                            updateStatistics();
                        }
                    }, 1500);
                }
            }
            
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

