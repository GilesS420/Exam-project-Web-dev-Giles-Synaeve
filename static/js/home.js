// Toggle comments section visibility
function toggleComments(postId) {
    const commentsSection = document.getElementById('comments-' + postId);
    commentsSection.style.display = commentsSection.style.display === 'none' ? 'block' : 'none';
}

// Toggle edit mode for posts
function toggleEdit(postId) {
    const postView = document.getElementById('post-view-' + postId);
    const postEdit = document.getElementById('post-edit-' + postId);
    
    if (postView && postEdit) {
        postView.style.display = postView.style.display === 'none' ? 'block' : 'none';
        postEdit.style.display = postEdit.style.display === 'none' ? 'block' : 'none';
    }
}

// Cancel edit mode and reset form
function cancelEdit(postId) {
    const postView = document.getElementById('post-view-' + postId);
    const postEdit = document.getElementById('post-edit-' + postId);
    
    if (postView && postEdit) {
        postView.style.display = 'block';
        postEdit.style.display = 'none';
        // Reset form
        const form = postEdit.querySelector('form');
        if (form) {
            form.reset();
        }
    }
}

// Toggle like on a post using AJAX (no page reload)
async function toggleLike(postId) {
    try {
        const response = await fetch(`/like/${postId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin'
        });
        
        if (response.ok) {
            const data = await response.json();
            const likeBtn = document.getElementById('like-btn-' + postId);
            const likeCount = document.getElementById('like-count-' + postId);
            
            if (data.liked) {
                likeBtn.classList.add('liked');
            } else {
                likeBtn.classList.remove('liked');
            }
            likeCount.textContent = data.total_likes;
        } else {
            console.error('Failed to toggle like');
        }
    } catch (error) {
        console.error('Error toggling like:', error);
    }
}

// Add comment using AJAX (no page reload)
async function addComment(event, postId) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const content = formData.get('content').trim();
    
    if (!content || content.length < 1) {
        alert('Comment cannot be empty');
        return false;
    }
    
    try {
        const response = await fetch(`/comment/${postId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams(formData),
            credentials: 'same-origin'
        });
        
        if (response.ok) {
            // Reload comments section
            location.reload();
        } else {
            alert('Failed to add comment');
        }
    } catch (error) {
        console.error('Error adding comment:', error);
        alert('Error adding comment');
    }
    return false;
}

// Delete post using AJAX
async function deletePost(postId) {
    if (!confirm('Are you sure you want to delete this post?')) {
        return;
    }
    
    try {
        const response = await fetch(`/post/${postId}/delete`, {
            method: 'POST',
            credentials: 'same-origin'
        });
        
        if (response.ok) {
            // Remove post from DOM
            const postElement = document.getElementById('post-' + postId);
            if (postElement) {
                postElement.remove();
            }
        } else {
            alert('Failed to delete post');
        }
    } catch (error) {
        console.error('Error deleting post:', error);
        alert('Error deleting post');
    }
}

// Submit post using AJAX (no page reload)
document.addEventListener('DOMContentLoaded', function() {
    const postForm = document.getElementById('post-form');
    if (postForm) {
        postForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const form = e.target;
            const formData = new FormData(form);
            const content = formData.get('content')?.trim() || '';
            const audioFile = formData.get('audio_file');
            
            // Front-end validation: at least content or audio file required
            if (!content && !audioFile?.name) {
                const errorDiv = document.getElementById('post-error');
                errorDiv.textContent = 'Please enter content or upload an audio file';
                errorDiv.style.display = 'block';
                return false;
            }
            
            // Validate content length
            if (content && content.length > 500) {
                const errorDiv = document.getElementById('post-error');
                errorDiv.textContent = 'Content must be 500 characters or less';
                errorDiv.style.display = 'block';
                return false;
            }
            
            try {
                const response = await fetch('/post', {
                    method: 'POST',
                    body: formData,
                    credentials: 'same-origin'
                });
                
                if (response.ok) {
                    // Reload page to show new post
                    location.reload();
                } else {
                    const errorDiv = document.getElementById('post-error');
                    errorDiv.textContent = 'Failed to create post';
                    errorDiv.style.display = 'block';
                }
            } catch (error) {
                console.error('Error creating post:', error);
                const errorDiv = document.getElementById('post-error');
                errorDiv.textContent = 'Error creating post';
                errorDiv.style.display = 'block';
            }
            return false;
        });
    }
});

// Live search functionality
let searchTimeout;

function handleLiveSearch(query) {
    const resultsDiv = document.getElementById('live-search-results');
    
    // Clear previous timeout
    clearTimeout(searchTimeout);
    
    // Hide results if query is empty
    if (!query || query.trim().length === 0) {
        if (resultsDiv) {
            resultsDiv.style.display = 'none';
        }
        return;
    }
    
    // Debounce search - wait 300ms after user stops typing
    searchTimeout = setTimeout(() => {
        performLiveSearch(query.trim());
    }, 300);
}

async function performLiveSearch(query) {
    const resultsDiv = document.getElementById('live-search-results');
    if (!resultsDiv) return;
    
    resultsDiv.style.display = 'block';
    resultsDiv.innerHTML = '<p style="color: var(--color-text-muted); text-align: center; padding: var(--space-3);">Searching...</p>';

    try {
        const response = await fetch(`/search?q=${encodeURIComponent(query)}`, {
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin'
        });

        if (!response.ok) {
            throw new Error('Search failed');
        }

        const data = await response.json();
        displayLiveSearchResults(data, query);
    } catch (error) {
        console.error('Search error:', error);
        resultsDiv.innerHTML = '<p style="color: var(--color-error); text-align: center; padding: var(--space-3);">Error performing search</p>';
    }
}

function displayLiveSearchResults(data, query) {
    const resultsDiv = document.getElementById('live-search-results');
    if (!resultsDiv) return;
    
    let html = '';
    let hasResults = false;

    if (data.users && data.users.length > 0) {
        hasResults = true;
        html += '<div class="live-search-section"><h3 style="color: var(--color-text); margin: 0 0 var(--space-3) 0; font-size: 1rem;">Users</h3>';
        data.users.forEach(user => {
            const avatarUrl = user.avatar 
                ? (user.avatar.startsWith('http') ? user.avatar : `/static/${user.avatar}`)
                : '/static/images/default-avatar.svg';
            html += `
                <div class="live-search-item">
                    <img src="${avatarUrl}" alt="${user.name}" class="avatar-small" onerror="this.src='/static/images/default-avatar.svg'">
                    <div style="flex: 1;">
                        <a href="/profile/${user.id}" style="color: var(--color-text); text-decoration: none; font-weight: 600; display: block; font-size: 0.95rem;">${escapeHtml(user.name)}</a>
                        <p style="color: var(--color-text-muted); font-size: 0.85rem; margin: 0;">${escapeHtml(user.email)}</p>
                    </div>
                    ${user.id !== data.current_user_id ? `
                        <form method="POST" action="/follow/${user.id}" style="display: inline;" onsubmit="event.preventDefault(); toggleFollowInSearch(${user.id}, this); return false;">
                            <button type="submit" class="btn btn-small" style="font-size: 0.8rem; padding: 0.4rem 0.8rem;">
                                ${user.is_following ? 'Unfollow' : 'Follow'}
                            </button>
                        </form>
                    ` : ''}
                </div>
            `;
        });
        html += '</div>';
    }

    if (data.posts && data.posts.length > 0) {
        hasResults = true;
        html += '<div class="live-search-section"><h3 style="color: var(--color-text); margin: var(--space-4) 0 var(--space-3) 0; font-size: 1rem;">Posts</h3>';
        data.posts.forEach(post => {
            const avatarUrl = post.user_avatar 
                ? (post.user_avatar.startsWith('http') ? post.user_avatar : `/static/${post.user_avatar}`)
                : '/static/images/default-avatar.svg';
            const audioHtml = post.media_type === 'audio' && post.media_path 
                ? `<div class="post-audio" style="margin: var(--space-2) 0;"><audio controls class="audio-player" style="width: 100%; height: 35px;"><source src="/static/uploads/${post.media_path}" type="audio/mpeg"></audio></div>`
                : '';
            html += `
                <article class="post-card" style="margin-bottom: var(--space-3);">
                    <div class="post-header">
                        <img src="${avatarUrl}" alt="${escapeHtml(post.user_name)}" class="avatar-small" onerror="this.src='/static/images/default-avatar.svg'">
                        <div class="post-author">
                            <a href="/profile/${post.user_id}" class="author-name" style="font-size: 0.9rem;">${escapeHtml(post.user_name)}</a>
                            <span class="post-time" style="font-size: 0.75rem;">${formatDate(post.created_at)}</span>
                        </div>
                    </div>
                    ${post.content ? `<div class="post-content" style="font-size: 0.9rem; margin-bottom: var(--space-2);">${escapeHtml(post.content)}</div>` : ''}
                    ${audioHtml}
                    <div class="post-actions" style="padding-top: var(--space-2); border-top: 1px solid rgba(255,255,255,0.1);">
                        <span class="action-btn" style="font-size: 0.85rem;">❤️ ${post.total_likes || 0}</span>
                    </div>
                </article>
            `;
        });
        html += '</div>';
    }

    if (!hasResults) {
        html = '<p style="color: var(--color-text-muted); text-align: center; padding: var(--space-4);">No results found for "' + escapeHtml(query) + '"</p>';
    }

    resultsDiv.innerHTML = html;
}

function clearSearch() {
    const searchInput = document.getElementById('search-input');
    const resultsDiv = document.getElementById('live-search-results');
    if (searchInput) {
        searchInput.value = '';
    }
    if (resultsDiv) {
        resultsDiv.style.display = 'none';
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateString) {
    if (!dateString) return '';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

async function toggleFollowInSearch(userId, form) {
    try {
        const response = await fetch(`/follow/${userId}`, {
            method: 'POST',
            credentials: 'same-origin'
        });
        if (response.ok) {
            const button = form.querySelector('button');
            const isFollowing = button.textContent.trim() === 'Unfollow';
            button.textContent = isFollowing ? 'Follow' : 'Unfollow';
        }
    } catch (error) {
        console.error('Error toggling follow:', error);
    }
}

