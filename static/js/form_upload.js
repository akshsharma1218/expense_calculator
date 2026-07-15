// ============================================================
// File Handling
// ============================================================

function showExportModal() {
    const modal = new bootstrap.Modal(document.getElementById('UploadModal'));
    modal.show();
    // Trigger the download tab
    const downloadTab = document.getElementById('download-tab');
    if (downloadTab) {
        downloadTab.click();
    }
}

const uploadZone = document.getElementById('uploadZone');
const csvFileInput = document.getElementById('csvFileInput');
const receiptUploadZone = document.getElementById('receiptUploadZone');
const receiptFileInput = document.getElementById('receiptFileInput');

// CSV Drag & Drop
uploadZone?.addEventListener('click', () => csvFileInput?.click());
uploadZone?.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('dragover');
});
uploadZone?.addEventListener('dragleave', () => {
    uploadZone.classList.remove('dragover');
});
uploadZone?.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        csvFileInput.files = e.dataTransfer.files;
        updateFileInfo(e.dataTransfer.files[0]);
    }
});

csvFileInput?.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        updateFileInfo(e.target.files[0]);
    }
});

// Receipt Drag & Drop
receiptUploadZone?.addEventListener('click', () => receiptFileInput?.click());
receiptUploadZone?.addEventListener('dragover', (e) => {
    e.preventDefault();
    receiptUploadZone.classList.add('dragover');
});
receiptUploadZone?.addEventListener('dragleave', () => {
    receiptUploadZone.classList.remove('dragover');
});
receiptUploadZone?.addEventListener('drop', (e) => {
    e.preventDefault();
    receiptUploadZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        receiptFileInput.files = e.dataTransfer.files;
        updateReceiptFileInfo(e.dataTransfer.files[0]);
    }
});

receiptFileInput?.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        updateReceiptFileInfo(e.target.files[0]);
    }
});

function updateFileInfo(file) {
    const fileInfo = document.getElementById('fileInfo');
    const fileName = document.getElementById('fileName');
    const fileSize = document.getElementById('fileSize');
    const uploadBtn = document.getElementById('uploadBtn');
    const validationInfo = document.getElementById('validationInfo');

    fileName.textContent = file.name;
    fileSize.textContent = (file.size / 1024).toFixed(2) + ' KB';
    fileInfo.classList.remove('d-none');
    validationInfo.style.display = 'block';
    uploadBtn.disabled = false;
}

function updateReceiptFileInfo(file) {
    const fileInfo = document.getElementById('receiptFileInfo');
    const fileName = document.getElementById('receiptFileName');
    const fileSize = document.getElementById('receiptFileSize');
    const uploadBtn = document.getElementById('uploadBtn');

    fileName.textContent = file.name;
    fileSize.textContent = (file.size / 1024).toFixed(2) + ' KB';
    fileInfo.classList.remove('d-none');
    uploadBtn.disabled = false;
}

function resetFileInput() {
    csvFileInput.value = '';
    document.getElementById('fileInfo').classList.add('d-none');
    document.getElementById('uploadBtn').disabled = true;
}

function resetReceiptInput() {
    receiptFileInput.value = '';
    document.getElementById('receiptFileInfo').classList.add('d-none');
    document.getElementById('uploadBtn').disabled = true;
}

// ============================================================
// Upload Handler
// ============================================================

function handleUpload() {
    const csvFile = csvFileInput?.files[0];
    const receiptFile = receiptFileInput?.files[0];

    if (!csvFile && !receiptFile) {
        alert('Please select a file to upload.');
        return;
    }

    if (csvFile) {
        uploadCSV(csvFile);
    } else if (receiptFile) {
        uploadReceipt(receiptFile);
    }
}

function uploadWithProgress(url, formData, onProgress, onServerProcessing) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url, true);
        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

        xhr.upload.onprogress = (event) => {
            if (!event.lengthComputable) return;
            const percent = Math.min(95, Math.round((event.loaded / event.total) * 95));
            onProgress(percent);
        };

        xhr.upload.onloadend = () => {
            onServerProcessing();
        };

        xhr.onload = () => {
            let data = {};
            try {
                data = xhr.responseText ? JSON.parse(xhr.responseText) : {};
            } catch (error) {
                data = {
                    success: xhr.status >= 200 && xhr.status < 300,
                    detail: 'Invalid JSON response from server.'
                };
            }

            resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, data });
        };

        xhr.onerror = () => {
            reject(new Error('Network error during upload'));
        };

        xhr.send(formData);
    });
}

async function uploadCSV(file) {
    const formData = new FormData();
    formData.append('csv_file', file);
    formData.append('csrfmiddlewaretoken', document.querySelector('[name=csrfmiddlewaretoken]').value);

    // Show progress modal
    const uploadModal = bootstrap.Modal.getInstance(document.getElementById('UploadModal'));
    if (uploadModal) uploadModal.hide();
    
    const progressModal = new bootstrap.Modal(document.getElementById('UploadProgressModal'));
    progressModal.show();
    const progressBar = document.getElementById('uploadProgress');
    const progressText = document.getElementById('progressText');
    progressBar.style.width = '0%';
    progressText.textContent = 'Uploading file...';

    // Disable button
    const uploadBtn = document.getElementById('uploadBtn');
    uploadBtn.disabled = true;

    try {
        // Use URL from data attribute (set in template)
        const uploadUrl = document.getElementById('uploadZone').dataset.uploadUrl;
        const response = await uploadWithProgress(
            uploadUrl,
            formData,
            (percent) => {
                progressBar.style.width = `${percent}%`;
            },
            () => {
                progressBar.style.width = '95%';
                progressText.textContent = 'Processing transactions...';
            }
        );
        
        // Complete progress bar
        progressBar.style.width = '100%';
        progressText.textContent = 'Done';
        
        // Wait a bit before showing result
        setTimeout(() => {
            progressModal.hide();
            showUploadResult(response.data);
        }, 500);

    } catch (error) {
        progressModal.hide();
        uploadBtn.disabled = false;
        showUploadResult({
            success: false,
            created: 0,
            failed: 0,
            errors: ['Network error: ' + error.message]
        });
    }
}

async function uploadReceipt(file) {
    const formData = new FormData();
    formData.append('receipt', file);
    formData.append('csrfmiddlewaretoken', document.querySelector('[name=csrfmiddlewaretoken]').value);

    const uploadModal = bootstrap.Modal.getInstance(document.getElementById('UploadModal'));
    if (uploadModal) uploadModal.hide();

    const progressModal = new bootstrap.Modal(document.getElementById('UploadProgressModal'));
    progressModal.show();
    const progressBar = document.getElementById('uploadProgress');
    const progressText = document.getElementById('progressText');
    progressBar.style.width = '0%';
    progressText.textContent = 'Uploading receipt...';

    const uploadBtn = document.getElementById('uploadBtn');
    uploadBtn.disabled = true;

    try {
        // Use URL from data attribute (set in template)
        const receiptUrl = document.getElementById('receiptUploadZone').dataset.receiptUrl;
        const response = await uploadWithProgress(
            receiptUrl,
            formData,
            (percent) => {
                progressBar.style.width = `${percent}%`;
            },
            () => {
                progressBar.style.width = '95%';
                progressText.textContent = 'Extracting receipt details...';
            }
        );

        progressBar.style.width = '100%';
        progressText.textContent = 'Done';

        setTimeout(() => {
            progressModal.hide();
            showUploadResult({
                success: response.ok && response.data.success !== false,
                created: response.ok ? 1 : 0,
                failed: response.ok ? 0 : 1,
                message: response.data.message || (response.ok ? 'Receipt processed successfully' : 'Receipt processing failed'),
                errors: response.data.errors || (response.ok ? [] : [response.data.detail || 'Receipt processing failed'])
            });

            if (response.ok && response.data.redirect_url) {
                setTimeout(() => {
                    window.location.href = response.data.redirect_url;
                }, 800);
            }
        }, 500);

    } catch (error) {
        progressModal.hide();
        uploadBtn.disabled = false;
        showUploadResult({
            success: false,
            created: 0,
            failed: 0,
            errors: ['Network error: ' + error.message]
        });
    }
}

function showUploadResult(result) {
    const resultModal = new bootstrap.Modal(document.getElementById('UploadResultModal'));
    const resultIcon = document.getElementById('resultIcon');
    const resultMessage = document.getElementById('resultMessage');
    const createdCount = document.getElementById('createdCount');
    const failedCount = document.getElementById('failedCount');
    const errorsList = document.getElementById('errorsList');
    const errorsListItems = document.getElementById('errorsListItems');
    const uploadBtn = document.getElementById('uploadBtn');

    // Parse result
    const isSuccess = result.success === true;
    const created = result.created || 0;
    const failed = result.failed || 0;
    const detailMessage = result.detail || '';
    const errors = (Array.isArray(result.errors) && result.errors.length > 0)
        ? result.errors
        : (detailMessage ? [detailMessage] : []);

    if (isSuccess) {
        resultIcon.innerHTML = '<i class="bi bi-check-circle-fill text-success"></i>';
        resultMessage.textContent = 'All transactions uploaded successfully! ';
        createdCount.textContent = created;
        failedCount.textContent = 0;
        errorsList.classList.add('d-none');
    } else {
        resultIcon.innerHTML = '<i class="bi bi-exclamation-circle-fill text-warning"></i>';
        const firstError = errors.length > 0 ? errors[0] : null;
        
        if (created > 0 && failed > 0) {
            resultMessage.textContent = firstError
                ? `Partial success. ${created} transaction(s) created with ${failed} error(s). First issue: ${firstError}`
                : `Partial success. ${created} transaction(s) created with ${failed} error(s).`;
        } else if (failed > 0) {
            resultMessage.textContent = firstError
                ? firstError
                : `Upload failed with ${failed} error(s). Please review and try again.`;
        } else {
            resultMessage.textContent = firstError || result.message || 'Upload completed with issues.';
        }
        
        createdCount.textContent = created;
        failedCount.textContent = failed;

        if (errors && errors.length > 0) {
            errorsListItems.innerHTML = errors
                .slice(0, 5)
                .map(err => `<li class="small">${err}</li>`)
                .join('');
            
            if (errors.length > 5) {
                errorsListItems.innerHTML += `<li class="small text-muted">... and ${errors.length - 5} more errors</li>`;
            }
            
            errorsList.classList.remove('d-none');
        } else {
            errorsList.classList.add('d-none');
        }
    }

    // Reset upload button
    uploadBtn.disabled = false;

    resultModal.show();

    // Reset forms after modal closes
    resultModal._element.addEventListener('hidden.bs.modal', () => {
        resetFileInput();
        resetReceiptInput();
        
        // Reload page if successful
        if (isSuccess) {
            setTimeout(() => location.reload(), 500);
        }
    }, { once: true });
}

function downloadTemplate() {
    const csv = `account,category,merchant,amount,transaction_date,description
Checking Account,Groceries,Walmart,125.50,2026-07-11,Weekly shopping
Credit Card,Gas,Shell,45.00,2026-07-10,Gas fill-up
Savings,Dining,Restaurant,89.99,2026-07-09,Dinner`;

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'transactions-template.csv';
    a.click();
}

async function downloadTransactions() {
    try {
        window.location.href = '/transactions/export/';
    } catch (error) {
        alert('Error downloading transactions: ' + error.message);
    }
}

async function downloadTransactionsByDate() {
    const today = new Date().toISOString().split('T')[0];
    const lastMonth = new Date(new Date().setMonth(new Date().getMonth() - 1)).toISOString().split('T')[0];
    
    const startDate = prompt('Enter start date (YYYY-MM-DD):', lastMonth);
    if (!startDate) return;

    const endDate = prompt('Enter end date (YYYY-MM-DD):', today);
    if (!endDate) return;

    try {
        window.location.href = `/transactions/export/?start_date=${startDate}&end_date=${endDate}`;
    } catch (error) {
        alert('Error downloading transactions: ' + error.message);
    }
}

async function downloadTransactionsByAccount() {
    try {
        const response = await fetch('/accounts/json/');
        const accounts = await response.json();
        
        if (!accounts || accounts.length === 0) {
            alert('No accounts found');
            return;
        }

        const accountList = accounts.map((acc, idx) => `${idx + 1}. ${acc.name}`).join('\n');
        const accountIdx = prompt(`Select account to export:\n\n${accountList}\n\nEnter number:`, '1');
        
        if (!accountIdx || isNaN(accountIdx)) return;

        const selectedAccount = accounts[parseInt(accountIdx) - 1];
        if (!selectedAccount) {
            alert('Invalid selection');
            return;
        }

        window.location.href = `/transactions/export/?account=${selectedAccount.id}`;
    } catch (error) {
        alert('Error downloading transactions: ' + error.message);
    }
}
