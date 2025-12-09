function updateWrapperHeight() {
    const wrapper = document.querySelector('.admin-sections-wrapper');
    const activeSection = document.querySelector('.admin-section.active');
    if (wrapper && activeSection) {
        // Reset to auto to get natural height
        wrapper.style.minHeight = 'auto';
        // Set to the actual height of the active section
        const sectionHeight = activeSection.offsetHeight;
        wrapper.style.minHeight = Math.max(600, sectionHeight + 20) + 'px';
    }
}

function showSection(section) {
    // Hide all sections
    document.querySelectorAll('.admin-section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.admin-tab').forEach(t => t.classList.remove('active'));
    
    // Show selected section
    const targetSection = document.getElementById(section + '-section');
    targetSection.classList.add('active');
    event.target.classList.add('active');
    
    // Update wrapper height after a brief delay to allow rendering
    setTimeout(updateWrapperHeight, 10);
}

// Initialize wrapper height on page load
document.addEventListener('DOMContentLoaded', function() {
    updateWrapperHeight();
    // Also update when window resizes
    window.addEventListener('resize', updateWrapperHeight);
});

function toggleUserBlock(userId, isBlocked) {
    if (!confirm(`Are you sure you want to ${isBlocked ? 'unblock' : 'block'} this user?`)) {
        return;
    }

    fetch(`/admin/user/${userId}/toggle-block`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Error: ' + (data.error || 'Failed to update user'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred. Please try again.');
    });
}

function togglePostBlock(postId, isBlocked) {
    if (!confirm(`Are you sure you want to ${isBlocked ? 'unblock' : 'block'} this post?`)) {
        return;
    }

    fetch(`/admin/post/${postId}/toggle-block`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Error: ' + (data.error || 'Failed to update post'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred. Please try again.');
    });
}

function loadLanguages() {
    const display = document.getElementById('languages-display');
    display.innerHTML = '<p style="color: var(--color-text-muted);">Loading...</p>';

    fetch('/admin/languages')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                display.innerHTML = `
                    <h3 style="color: var(--color-text); margin-bottom: 1rem;">Available Languages: ${data.available_languages.join(', ')}</h3>
                    <p style="color: var(--color-text-muted); margin-bottom: 1rem;">Found ${Object.keys(data.languages).length} translation keys</p>
                    <pre>${JSON.stringify(data.languages, null, 2)}</pre>
                `;
            } else {
                display.innerHTML = `<p style="color: var(--color-error);">Error: ${data.error || 'Failed to load languages'}</p>`;
            }
        })
        .catch(error => {
            console.error('Error:', error);
            display.innerHTML = `<p style="color: var(--color-error);">An error occurred. Please check if Google Spreadsheet key is configured.</p>`;
        });
}

function loadDictionary() {
    const display = document.getElementById('languages-display');
    display.innerHTML = '<p style="color: var(--color-text-muted);">Loading...</p>';

    fetch('/admin/languages/dictionary')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Create a table for easy copying
                let tableHTML = `
                    <h3 style="color: var(--color-text); margin-bottom: 1rem;">Dictionary.json Contents (${data.total_keys} keys)</h3>
                    <p style="color: var(--color-text-muted); margin-bottom: 1rem; font-size: 0.9rem;">Copy this table into your Google Sheet. Format: key | english | danish | spanish</p>
                    <div style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse; background: var(--color-bg); border-radius: var(--radius-sm);">
                            <thead>
                                <tr style="background: var(--color-bg-secondary);">
                                    <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--color-bg); color: var(--color-text);">Key</th>
                                    <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--color-bg); color: var(--color-text);">English</th>
                                    <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--color-bg); color: var(--color-text);">Danish</th>
                                    <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--color-bg); color: var(--color-text);">Spanish</th>
                                </tr>
                            </thead>
                            <tbody>
                `;
                
                data.data.forEach((item, index) => {
                    const bgColor = index % 2 === 0 ? 'var(--color-bg)' : 'var(--color-bg-secondary)';
                    tableHTML += `
                        <tr style="background: ${bgColor};">
                            <td style="padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1); color: var(--color-text); font-weight: 600;">${escapeHtml(item.key)}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1); color: var(--color-text-muted);">${escapeHtml(item.english)}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1); color: var(--color-text-muted);">${escapeHtml(item.danish)}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1); color: var(--color-text-muted);">${escapeHtml(item.spanish)}</td>
                        </tr>
                    `;
                });
                
                tableHTML += `
                            </tbody>
                        </table>
                    </div>
                    <div style="margin-top: 1rem; padding: 1rem; background: var(--color-bg-secondary); border-radius: var(--radius-sm);">
                        <p style="color: var(--color-text-muted); margin: 0; font-size: 0.9rem;">
                            <strong>Tip:</strong> You can select and copy the table above, then paste it directly into Google Sheets. 
                            Make sure your sheet has columns: key, english, danish, spanish
                        </p>
                    </div>
                `;
                
                display.innerHTML = tableHTML;
            } else {
                display.innerHTML = `<p style="color: var(--color-error);">Error: ${data.error || 'Failed to load dictionary'}</p>`;
            }
        })
        .catch(error => {
            console.error('Error:', error);
            display.innerHTML = `<p style="color: var(--color-error);">An error occurred while loading dictionary.json.</p>`;
        });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function syncLanguages() {
    if (!confirm('This will overwrite dictionary.json with data from Google Sheets. Make sure your sheet has data before syncing! Continue?')) {
        return;
    }

    const display = document.getElementById('languages-display');
    display.innerHTML = '<p style="color: var(--color-text-muted);">Syncing...</p>';

    fetch('/admin/languages/sync', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                display.innerHTML = `
                    <div style="background: var(--color-success); color: white; padding: 1rem; border-radius: var(--radius-sm); margin-bottom: 1rem;">
                        <strong>✓ Success!</strong> ${data.message}
                    </div>
                    <p style="color: var(--color-text-muted); margin-top: 1rem;">The dictionary.json file has been updated. The application will use these translations immediately.</p>
                `;
            } else {
                display.innerHTML = `
                    <div style="background: var(--color-error); color: white; padding: 1rem; border-radius: var(--radius-sm); margin-bottom: 1rem;">
                        <strong>⚠ Error:</strong> ${data.error || 'Failed to sync languages'}
                    </div>
                    <p style="color: var(--color-text-muted);">Your dictionary.json file was NOT modified. Please add data to your Google Sheet and try again.</p>
                `;
            }
        })
        .catch(error => {
            console.error('Error:', error);
            display.innerHTML = `
                <div style="background: var(--color-error); color: white; padding: 1rem; border-radius: var(--radius-sm); margin-bottom: 1rem;">
                    <strong>⚠ Error:</strong> An error occurred while syncing.
                </div>
                <p style="color: var(--color-text-muted);">Your dictionary.json file was NOT modified. Please check the console for details.</p>
            `;
        });
}

