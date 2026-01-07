let currentJobId = null;
let pollInterval = null;

document.addEventListener('DOMContentLoaded', () => {
    initializeEventListeners();
    startPolling();
    initializePage();
});

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
    
    const btn = document.getElementById('start-scraping');
    btn.disabled = true;
    btn.textContent = 'Starting...';
    
    try {
        const response = await fetch('/api/jobs', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({app_url: appUrl})
        });
        
        const data = await response.json();
        
        if (response.ok) {
            currentJobId = data.job_id;
            showStatus(`Job started! App: ${data.app_name}`, 'success');
            loadPendingStores();
            pollJobStatus();
        } else {
            showStatus(`Error: ${data.error}`, 'error');
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
            if (job.total_pages > 0) {
                progressPercent = Math.min(100, (job.current_page / job.total_pages) * 100);
            } else if (job.reviews_scraped > 0) {
                progressPercent = Math.min(50, (job.reviews_scraped / 100) * 50);
            }
            progressDetails.textContent = `Page ${job.current_page || 0} | Reviews scraped: ${job.reviews_scraped || 0}`;
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
        
        container.innerHTML = `
            <div class="store-item">
                <h4>${currentStore.store_name}</h4>
                <p><strong>Country:</strong> ${currentStore.country || 'N/A'}</p>
                <p><strong>Review:</strong> ${currentStore.review_text ? (currentStore.review_text.substring(0, 100) + '...') : 'N/A'}</p>
                <p><strong>Status:</strong> ${currentStore.status}</p>
                ${currentStore.base_url ? `<p><strong>URL:</strong> ${currentStore.base_url}</p>` : ''}
                ${currentStore.emails && currentStore.emails.length > 0 ? `<p><strong>Emails:</strong> ${currentStore.emails.join(', ')}</p>` : ''}
                <div class="store-actions">
                    ${!currentStore.base_url ? `
                        <button class="btn-small" onclick="findStoreUrl(${currentStore.id}, '${currentStore.store_name}', '${currentStore.country || ''}')">Find URL</button>
                        <button class="btn-small btn-skip" onclick="skipStore(${currentStore.id})">Skip</button>
                    ` : ''}
                    ${currentStore.base_url && (!currentStore.emails || currentStore.emails.length === 0) ? `
                        <p class="info-message">Email scraping in progress... Please wait.</p>
                    ` : ''}
                </div>
            </div>
        `;
        
        // If URL is set but emails are not found yet, start checking for completion
        if (currentStore.base_url && (!currentStore.emails || currentStore.emails.length === 0)) {
            startEmailStatusCheck();
        }
    } catch (error) {
        console.error('Error loading next store:', error);
    }
}

async function skipStore(storeId) {
    try {
        const response = await fetch(`/api/stores/${storeId}/skip`, {
            method: 'POST'
        });
        
        if (response.ok) {
            showStatus('Store skipped', 'info');
            loadNextStore();
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
    
    let checkCount = 0;
    const maxChecks = 60; // Check for up to 3 minutes (60 * 3 seconds)
    
    emailCheckInterval = setInterval(async () => {
        if (!currentStore) {
            clearInterval(emailCheckInterval);
            emailCheckInterval = null;
            return;
        }
        
        checkCount++;
        if (checkCount > maxChecks) {
            clearInterval(emailCheckInterval);
            emailCheckInterval = null;
            showStatus('Email scraping is taking longer than expected. You can manually proceed.', 'info');
            return;
        }
        
        try {
            const response = await fetch(`/api/stores/${currentStore.id}`);
            const store = await response.json();
            
            // Update the current store
            currentStore = store;
            
            // Refresh the display to show updated status
            await refreshCurrentStoreDisplay();
            
            if (store.status === 'emails_found') {
                // Emails found, move to next store
                clearInterval(emailCheckInterval);
                emailCheckInterval = null;
                const emailList = store.emails && store.emails.length > 0 
                    ? store.emails.join(', ') 
                    : 'No emails found';
                showStatus(`Email scraping completed. ${emailList}`, 'success');
                setTimeout(() => {
                    loadNextStore();
                    updateStatistics();
                }, 2000);
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
        
        const container = document.getElementById('stores-container');
        container.innerHTML = `
            <div class="store-item">
                <h4>${currentStore.store_name}</h4>
                <p><strong>Country:</strong> ${currentStore.country || 'N/A'}</p>
                <p><strong>Review:</strong> ${currentStore.review_text ? (currentStore.review_text.substring(0, 100) + '...') : 'N/A'}</p>
                <p><strong>Status:</strong> ${currentStore.status}</p>
                ${currentStore.base_url ? `<p><strong>URL:</strong> ${currentStore.base_url}</p>` : ''}
                ${currentStore.emails && currentStore.emails.length > 0 ? `<p><strong>Emails:</strong> ${currentStore.emails.join(', ')}</p>` : ''}
                <div class="store-actions">
                    ${!currentStore.base_url ? `
                        <button class="btn-small" onclick="findStoreUrl(${currentStore.id}, '${currentStore.store_name}', '${currentStore.country || ''}')">Find URL</button>
                        <button class="btn-small btn-skip" onclick="skipStore(${currentStore.id})">Skip</button>
                    ` : ''}
                    ${currentStore.base_url && (!currentStore.emails || currentStore.emails.length === 0) ? `
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
    const modal = document.getElementById('modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    
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
                displayExtractedUrls(result.urls, storeId, storeName);
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
                // Show extracted URLs
                displayExtractedUrls(result.urls, storeId, storeName);
            } else if (result.status === 'pending' && attempts < maxAttempts) {
                // Keep polling
                setTimeout(poll, 1000);
            } else {
                // Timeout or no results
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
                modalBody.innerHTML = `<p class="error">Error polling for results: ${error.message}</p>`;
            }
        }
    };
    
    poll();
}

function displayExtractedUrls(urls, storeId, storeName) {
    const modalBody = document.getElementById('modal-body');
    
    let urlsHtml = '<div class="extracted-urls">';
    urlsHtml += `<p><strong>Found ${urls.length} URLs. Select the correct store URL:</strong></p>`;
    urlsHtml += '<div class="url-buttons-container" style="max-height: 400px; overflow-y: auto; margin-top: 15px;">';
    
    urls.forEach((urlData) => {
        try {
            const urlObj = new URL(urlData.url);
            const domain = urlObj.hostname.replace('www.', '');
            const shopifyBadge = urlData.is_shopify ? '<span class="shopify-badge" style="background: #95BF47; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px; margin-left: 8px;">Shopify</span>' : '';
            
            const escapedUrl = urlData.url.replace(/'/g, "\\'").replace(/"/g, '&quot;');
            const escapedTitle = (urlData.title || domain).replace(/'/g, "\\'").replace(/"/g, '&quot;');
            const escapedSnippet = (urlData.snippet || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
            
            urlsHtml += `
                <div class="url-button-item" style="margin-bottom: 10px; border: 1px solid #ddd; border-radius: 5px; padding: 12px; cursor: pointer; transition: background 0.2s; background: white;" 
                     onclick="selectExtractedUrl(${storeId}, '${escapedUrl}')"
                     onmouseover="this.style.background='#f5f5f5'" 
                     onmouseout="this.style.background='white'">
                    <div style="font-weight: bold; color: #0066cc; margin-bottom: 4px;">
                        ${escapedTitle}
                        ${shopifyBadge}
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
        return;
    }
    
    try {
        const response = await fetch(`/api/stores/${storeId}/url`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: url})
        });
        
        if (response.ok) {
            showStatus('URL saved! Email scraping started...', 'success');
            closeModal();
            const data = await response.json();
            if (currentStore && currentStore.id === storeId) {
                currentStore.url = data.url;
                currentStore.status = 'url_verified';
            }
            startEmailStatusCheck(storeId);
        } else {
            const error = await response.json();
            showStatus(`Error: ${error.error || 'Failed to save URL'}`, 'error');
        }
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
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
    
    try {
        const response = await fetch(`/api/stores/${storeId}/url`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: url})
        });
        
        if (response.ok) {
            showStatus('URL saved! Email scraping started...', 'success');
            closeModal();
            // Refresh the current store to get updated URL
            const data = await response.json();
            if (currentStore && currentStore.id === storeId) {
                currentStore.base_url = data.url;
                // Update the display for current store
                await refreshCurrentStoreDisplay();
            }
            // Start checking for email completion
            startEmailStatusCheck();
            updateStatistics();
        } else {
            const data = await response.json();
            showStatus(`Error: ${data.error}`, 'error');
        }
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    }
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
    document.getElementById('modal').style.display = 'none';
}

function startPolling() {
    setInterval(() => {
        updateStatistics();
        // Don't auto-reload stores, user controls navigation with skip/next
    }, 5000);
}

