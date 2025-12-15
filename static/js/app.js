// Enhanced Odnix Application JavaScript
console.log('Odnix messaging platform loaded - Enhanced version');

document.addEventListener('DOMContentLoaded', function() {
    // Initialize Lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    
    initializeAuth();
    initializeTweets();
    initializeNavigation();
    initializeUserInteractions();
});

// Function to re-initialize Lucide icons after dynamic content changes
function refreshLucideIcons() {
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function initializeAuth() {
    // Handle login form
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', function(e) {
            const username = this.querySelector('input[name="username"]').value;
            if (!username.trim()) {
                e.preventDefault();
                showNotification('Please enter a username', 'error');
                return;
            }
            showNotification('Logging in...', 'info');
        });
    }

    // Handle register form
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.addEventListener('submit', function(e) {
            const inputs = this.querySelectorAll('input[required]');
            for (let input of inputs) {
                if (!input.value.trim()) {
                    e.preventDefault();
                    showNotification('Please fill in all required fields', 'error');
                    return;
                }
            }

            // Basic email validation
            const email = this.querySelector('input[type="email"]').value;
            if (email && !isValidEmail(email)) {
                e.preventDefault();
                showNotification('Please enter a valid email address', 'error');
                return;
            }

            showNotification('Creating account...', 'info');
        });
    }
}

function initializeTweets() {
    console.log('initializeTweets called');
    
    // Handle tweet posting - only attach submit listener if not on profile page
    const tweetForm = document.getElementById('tweetForm');
    console.log('tweetForm element:', tweetForm);
    
    if (tweetForm && !window.location.pathname.includes('/profile')) {
        console.log('Attaching submit event listener to tweetForm (not profile page)');
        tweetForm.addEventListener('submit', function(e) {
            console.log('Form submit event triggered');
            e.preventDefault();
            console.log('Default prevented');
            
            const tweetContent = document.getElementById('tweetContent');
            console.log('tweetContent element:', tweetContent);
            console.log('tweetContent value:', tweetContent ? tweetContent.value : 'null');
            
            const content = tweetContent.value.trim();
            console.log('Trimmed content:', content);
            console.log('Content length:', content.length);

            if (!content) {
                console.log('Content is empty, showing error');
                showNotification('Please enter some content for your tweet', 'error');
                return;
            }

            if (content.length > 280) {
                console.log('Content too long, showing error');
                showNotification('Tweet must be 280 characters or less', 'error');
                return;
            }

            console.log('Calling postTweet with content');
            postTweet(content, tweetContent);
        });
    } else if (tweetForm && window.location.pathname.includes('/profile')) {
        console.log('On profile page - using onclick handler instead of submit listener');
    } else {
        console.log('tweetForm not found on this page');
    }

        // Enhanced character counter for tweets
        const tweetContent = document.getElementById('tweetContent');
        if (tweetContent) {
            console.log('Setting up character counter for tweetContent');
            tweetContent.addEventListener('input', function() {
                const remaining = 280 - this.value.length;
                const charCounter = document.getElementById('charCounter');

                if (charCounter) {
                    charCounter.textContent = remaining + ' characters remaining';

                    // Change color based on remaining characters
                    charCounter.className = 'char-counter';
                    if (remaining < 0) {
                        charCounter.className += ' danger';
                        charCounter.textContent = Math.abs(remaining) + ' characters over limit';
                    } else if (remaining < 20) {
                        charCounter.className += ' danger';
                    } else if (remaining < 50) {
                        charCounter.className += ' warning';
                    }
                }
            });
        }
}

function initializeNavigation() {
    // Smooth scrolling for internal links
    document.querySelectorAll('a[href^="#"]').forEach(link => {
        link.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            // Skip if href is just "#" or empty
            if (!href || href === '#' || href.length < 2) {
                return;
            }
            e.preventDefault();
            try {
                const target = document.querySelector(href);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth' });
                }
            } catch (err) {
                // Invalid selector, ignore
                console.warn('Invalid selector:', href);
            }
        });
    });

    // Active navigation highlighting
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-item').forEach(item => {
        if (item.getAttribute('href') === currentPath) {
            item.classList.add('active');
        }
    });
}

function initializeUserInteractions() {
    // Add click handlers for user items that don't have specific onclick handlers
    document.querySelectorAll('.user-item').forEach(item => {
        if (!item.onclick) {
            const username = item.querySelector('.user-username')?.textContent?.replace('@', '');
            if (username) {
                item.style.cursor = 'pointer';
                item.addEventListener('click', function(e) {
                    // Don't trigger if clicking on buttons
                    if (e.target.tagName !== 'BUTTON' && e.target.tagName !== 'A') {
                        window.location.href = `/profile/${username}/`;
                    }
                });
            }
        }
    });

    // Profile link hover effects
    document.querySelectorAll('.profile-link').forEach(link => {
        link.addEventListener('mouseenter', function() {
            this.style.transform = 'translateX(3px)';
            this.style.transition = 'transform 0.2s';
        });

        link.addEventListener('mouseleave', function() {
            this.style.transform = 'translateX(0)';
        });
    });
}

// API Functions with enhanced error handling
function postTweet(content, inputElement) {
    console.log('postTweet called with content:', content);
    console.log('Content length:', content.length);
    console.log('Content trimmed:', content.trim());
    
    const submitBtn = document.querySelector('#tweetForm button[type="submit"]');
    const originalText = submitBtn.textContent;

    submitBtn.textContent = 'Posting...';
    submitBtn.disabled = true;

    // Use same CSRF approach as dashboard
    const csrfToken = getCSRFToken();
    console.log('CSRF Token:', csrfToken);

    // Use FormData like dashboard for consistency
    const formData = new FormData();
    formData.append('content', content);
    console.log('FormData created with content:', content);

    console.log('Sending fetch request to /api/post-tweet/');
    fetch('/api/post-tweet/', {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
        },
        body: formData
    })
    .then(response => {
        console.log('Response status:', response.status);
        console.log('Response headers:', response.headers);
        if (!response.ok) {
            console.error('Response not ok:', response.status, response.statusText);
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        console.log('Response data:', data);
        if (data.success) {
            console.log('Tweet posted successfully');
            inputElement.value = '';
            // Trigger input event to update character counter
            inputElement.dispatchEvent(new Event('input'));
            showNotification('Tweet posted successfully!', 'success');

            // Add the new tweet to the page dynamically if we're on the profile page
            const tweetsContainer = document.getElementById('tweets-container');
            if (tweetsContainer) {
                addTweetToPage(data.tweet);
                
                // Update tweet count if on profile page
                const tweetCountEl = document.getElementById('tweetCount');
                if (tweetCountEl) {
                    const currentCount = parseInt(tweetCountEl.textContent.replace(/[()]/g, '')) || 0;
                    tweetCountEl.textContent = `(${currentCount + 1})`;
                }
            }
        } else {
            console.error('Server returned error:', data.error);
            showNotification('Failed to post tweet: ' + (data.error || 'Unknown error'), 'error');
        }
    })
    .catch(error => {
        console.error('Error posting tweet:', error);
        showNotification('Network error. Please check your connection and try again.', 'error');
    })
    .finally(() => {
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
        inputElement.focus();
    });
}

function postTweetFromProfile() {
    console.log('postTweetFromProfile called');
    
    const tweetContent = document.getElementById('tweetContent');
    const tweetBtn = document.getElementById('tweetBtn');
    
    if (!tweetContent || !tweetBtn) {
        console.error('Form elements not found');
        showNotification('Form elements not found. Please refresh the page.', 'error');
        return;
    }
    
    const content = tweetContent.value.trim();
    console.log('Content to post:', content);
    
    // Validation
    if (!content) {
        console.log('Content is empty');
        showNotification('Please enter some content for your tweet', 'error');
        return;
    }
    
    if (content.length > 280) {
        console.log('Content too long');
        showNotification('Tweet must be 280 characters or less', 'error');
        return;
    }
    
    // Set posting state
    tweetBtn.disabled = true;
    tweetBtn.textContent = 'Posting...';
    
    console.log('Preparing form data...');
    
    try {
        // Prepare form data
        const formData = new FormData();
        formData.append('content', content);
        
        // Get CSRF token
        const csrfToken = getCSRFToken();
        if (!csrfToken) {
            throw new Error('No CSRF token found');
        }
        
        console.log('Sending request to /api/post-tweet/');
        
        // Make request
        fetch('/api/post-tweet/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken,
            },
            body: formData
        })
        .then(response => {
            console.log('Response status:', response.status);
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            console.log('Response data:', data);
            if (data.success) {
                // Clear form
                tweetContent.value = '';
                document.getElementById('charCounter').textContent = '280 characters remaining';
                document.getElementById('charCounter').className = 'char-counter';
                showNotification('Tweet posted successfully!', 'success');

                // Add the new tweet to the page dynamically
                const tweetsContainer = document.getElementById('my-tweets-content');
                if (tweetsContainer) {
                    addTweetToPage(data.tweet);
                    
                    // Update tweet count
                    const tweetCountEl = document.getElementById('tweetCount');
                    if (tweetCountEl) {
                        const currentCount = parseInt(tweetCountEl.textContent.replace(/[()]/g, '')) || 0;
                        tweetCountEl.textContent = `(${currentCount + 1})`;
                    }
                }
            } else {
                showNotification('Failed to post tweet: ' + (data.error || 'Unknown error'), 'error');
            }
        })
        .catch(error => {
            console.error('Error posting tweet:', error);
            showNotification('Network error. Please check your connection and try again.', 'error');
        })
        .finally(() => {
            tweetBtn.textContent = 'Tweet';
            tweetBtn.disabled = false;
            tweetContent.focus();
        });
        
    } catch (error) {
        console.error('Error in postTweetFromProfile:', error);
        showNotification('An error occurred. Please try again.', 'error');
        tweetBtn.textContent = 'Tweet';
        tweetBtn.disabled = false;
    }
}

function addTweetToPage(tweetData) {
    // Determine the correct container based on current page/tab
    let tweetsContainer;
    
    // Check if we're on profile page
    if (window.location.pathname.includes('/profile')) {
        tweetsContainer = document.getElementById('my-tweets-content');
    } else {
        tweetsContainer = document.getElementById('tweets-container');
    }
    
    if (!tweetsContainer) {
        console.warn('Tweets container not found');
        return;
    }

    const emptyState = tweetsContainer.querySelector('.empty-state, .empty-state-tweets');

    // Remove empty state if it exists
    if (emptyState) {
        emptyState.remove();
    }

    // Create new tweet element
    const tweetDiv = document.createElement('div');
    tweetDiv.className = 'tweet-item';
    tweetDiv.style.animation = 'fadeInUp 0.3s ease-out';

    const currentUser = getCurrentUser(); // This would need to be available globally

    tweetDiv.innerHTML = `
        <div class="tweet-header">
            <div class="tweet-avatar">${currentUser?.initials || 'U'}</div>
            <div class="tweet-info">
                <span class="tweet-author">${currentUser?.name || 'User'}</span>
                <span class="tweet-username">@${currentUser?.username || 'user'}</span>
                <span class="tweet-time">just now</span>
            </div>
        </div>
        <div class="tweet-content">
            ${escapeHtml(tweetData.content).replace(/\n/g, '<br>')}
        </div>
        <div class="tweet-actions">
            <span class="tweet-likes">❤️ 0</span>
            <span class="tweet-timestamp">just now</span>
        </div>
    `;

    // Add to beginning of tweets list
    tweetsContainer.insertBefore(tweetDiv, tweetsContainer.firstChild);
}

function startChat(username) {
    if (!username) {
        showNotification('Invalid username', 'error');
        return;
    }

    // Show loading state
    const buttons = document.querySelectorAll(`[onclick*="${username}"]`);
    buttons.forEach(btn => {
        btn.textContent = 'Starting...';
        btn.disabled = true;
    });

    fetch('/api/create-chat/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({
            username: username
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            showNotification(data.exists ? 'Opening existing chat...' : 'Starting new chat...', 'success');
            setTimeout(() => {
                window.location.href = `/chat/${data.chat_id}/`;
            }, 500);
        } else {
            showNotification('Failed to start chat: ' + (data.error || 'Unknown error'), 'error');
        }
    })
    .catch(error => {
        console.error('Error starting chat:', error);
        showNotification('Network error. Please check your connection and try again.', 'error');
    })
    .finally(() => {
        // Reset buttons
        buttons.forEach(btn => {
            btn.textContent = 'Chat';
            btn.disabled = false;
        });
    });
}

// Enhanced notification system
function showNotification(message, type = 'info', duration = 4000) {
    // Remove existing notifications
    const existingNotifications = document.querySelectorAll('.notification');
    existingNotifications.forEach(notif => notif.remove());

    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification--${type}`;
    notification.textContent = message;

    // Enhanced styling
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        border-radius: 0.75rem;
        color: white;
        font-weight: 600;
        z-index: 10000;
        transform: translateX(100%);
        transition: all 0.3s cubic-bezier(0.68, -0.55, 0.265, 1.55);
        max-width: 350px;
        word-wrap: break-word;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        cursor: pointer;
    `;

    // Set background color and icon based on type
    const styles = {
        success: { bg: '#28a745', icon: '✅' },
        error: { bg: '#dc3545', icon: '❌' },
        warning: { bg: '#ffc107', icon: '⚠️' },
        info: { bg: '#17a2b8', icon: 'ℹ️' }
    };

    const style = styles[type] || styles.info;
    notification.style.backgroundColor = style.bg;
    notification.innerHTML = `${style.icon} ${message}`;

    document.body.appendChild(notification);

    // Animate in
    setTimeout(() => {
        notification.style.transform = 'translateX(0)';
    }, 100);

    // Click to dismiss
    notification.addEventListener('click', () => {
        dismissNotification(notification);
    });

    // Auto dismiss
    setTimeout(() => {
        dismissNotification(notification);
    }, duration);
}

function dismissNotification(notification) {
    notification.style.transform = 'translateX(100%)';
    notification.style.opacity = '0';
    setTimeout(() => {
        if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
        }
    }, 300);
}

// Utility Functions
function getCSRFToken() {
    console.log('getCSRFToken called');
    
    // Check cookies first
    const cookies = document.cookie.split(';');
    console.log('Cookies:', cookies);
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        console.log('Cookie:', name, '=', value);
        if (name === 'csrftoken') {
            console.log('Found CSRF token in cookies:', value);
            return value;
        }
    }

    // Fallback: try to get from hidden input or meta tag
    const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
    console.log('CSRF input element:', csrfInput);
    if (csrfInput) {
        console.log('CSRF token from input:', csrfInput.value);
        return csrfInput.value;
    }

    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    console.log('CSRF meta element:', csrfMeta);
    if (csrfMeta) {
        console.log('CSRF token from meta:', csrfMeta.getAttribute('content'));
        return csrfMeta.getAttribute('content');
    }
    
    console.log('No CSRF token found');
    return '';
}

function escapeHtml(text) {
    if (!text) return '';

    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };

    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

function getCurrentUser() {
    // This would ideally be populated by Django template or a separate API call
    // For now, we'll try to extract from the page
    const userInfo = document.querySelector('.user-info');
    if (userInfo) {
        const nameEl = userInfo.querySelector('.user-name');
        const statusEl = userInfo.querySelector('.user-status');
        const avatarEl = userInfo.querySelector('.user-avatar');

        return {
            name: nameEl?.textContent || 'User',
            username: statusEl?.textContent?.replace('@', '') || 'user',
            initials: avatarEl?.textContent || 'U'
        };
    }
    return null;
}

// Global functions (for onclick handlers in templates)
window.startChat = startChat;
window.showNotification = showNotification;

// Modal management functions
window.openModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'block';
        document.body.style.overflow = 'hidden'; // Prevent background scrolling
        // Refresh Lucide icons in the modal
        setTimeout(() => {
            if (window.refreshLucideIcons) {
                window.refreshLucideIcons();
            }
        }, 10);
    }
};

window.closeModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto'; // Restore background scrolling
    }
};

// Mobile modal functions
window.openMobileModal = function(modalType) {
    // First check if this page uses the new modal structure (chatsModal, searchModal, etc.)
    const newStyleModal = document.getElementById(modalType + 'Modal');
    if (newStyleModal) {
        // Use the new-style modals (dashboard.html, profile.html)
        newStyleModal.classList.add('active');
        document.body.style.overflow = 'hidden';
        
        // Focus search input if applicable
        setTimeout(() => {
            if (modalType === 'chats') {
                const searchInput = document.getElementById('userSearchInput');
                if (searchInput) searchInput.focus();
            } else if (modalType === 'search') {
                const searchInput = document.getElementById('userSearchInputAlt');
                if (searchInput) searchInput.focus();
            }
            // Refresh Lucide icons
            if (window.refreshLucideIcons) {
                window.refreshLucideIcons();
            }
        }, 100);
        return;
    }
    
    // Fallback to old-style mobileModal with sections
    const modal = document.getElementById('mobileModal');
    if (!modal) {
        console.warn('No mobile modal found for type:', modalType);
        return;
    }
    
    const modalContent = modal.querySelector('.modal-content');
    if (!modalContent) {
        console.warn('No modal content found');
        return;
    }
    
    // Hide all modal sections
    const sections = modalContent.querySelectorAll('.modal-section');
    sections.forEach(section => section.style.display = 'none');
    
    // Show the requested section
    const targetSection = modalContent.querySelector(`[data-section="${modalType}"]`);
    if (targetSection) {
        targetSection.style.display = 'block';
        modal.style.display = 'block';
        document.body.style.overflow = 'hidden';
        
        // Refresh Lucide icons
        setTimeout(() => {
            if (window.refreshLucideIcons) {
                window.refreshLucideIcons();
            }
        }, 10);
    }
};

window.closeMobileModal = function() {
    // Close new-style modals
    const activeModals = document.querySelectorAll('.mobile-modal.active');
    activeModals.forEach(modal => {
        modal.classList.remove('active');
    });
    
    // Close old-style modal
    const modal = document.getElementById('mobileModal');
    if (modal) {
        modal.style.display = 'none';
    }
    
    document.body.style.overflow = 'auto';
};

// Close modal when clicking outside
window.addEventListener('click', function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
});

// Close modal on Escape key
window.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        const modals = document.querySelectorAll('.modal[style*="display: block"]');
        modals.forEach(modal => {
            modal.style.display = 'none';
            document.body.style.overflow = 'auto';
        });
    }
});

// Enhanced error handling for the entire app
// Disabled - was causing false positive error toasts
// Errors are still logged to console for debugging
window.addEventListener('error', function(e) {
    console.error('JavaScript error:', e.error);
    // Don't show notification - too many false positives
});

window.addEventListener('unhandledrejection', function(e) {
    console.error('Unhandled promise rejection:', e.reason);
    // Don't show notification - too many false positives
});

// Initialize Lucide icons when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Lucide icons
    if (window.lucide && window.lucide.createIcons) {
        window.lucide.createIcons();
        console.log('✅ Lucide icons initialized');
    } else {
        console.warn('⚠️ Lucide library not loaded, icons may not display');
    }
});

// ===== GLOBAL NAVBAR FUNCTIONS =====
// Moved from navbar.html to ensure availability on all pages

// Search functions
window.handleGlobalSearch = function(event) {
    if (event.key === 'Enter') {
        const query = event.target.value.trim();
        if (query) {
            // Assuming search page exists or using discover page
            window.location.href = '/chat/discover-groups/?q=' + encodeURIComponent(query);
        }
    }
};

window.handleMobileSearch = function(event) {
    const query = event.target.value.trim();
    if (query.length < 2) {
        const results = document.getElementById('searchResults');
        if (results) results.innerHTML = '<p class="ig-search-placeholder">Search for users...</p>';
        return;
    }
    
    fetch('/api/search-users/?q=' + encodeURIComponent(query))
        .then(r => r.json())
        .then(data => {
            const container = document.getElementById('searchResults');
            if (!container) return;
            
            if (data.users && data.users.length > 0) {
                container.innerHTML = data.users.map(u => `
                    <a href="/chat/profile/${u.username}/" class="ig-search-result">
                        <img src="${u.profile_picture_url || ''}" alt="" class="ig-search-avatar" onerror="this.style.display='none'">
                        <div class="ig-search-info">
                            <span class="ig-search-username">${u.username}</span>
                            <span class="ig-search-name">${u.full_name || ''}</span>
                        </div>
                    </a>
                `).join('');
            } else {
                container.innerHTML = '<p class="ig-search-placeholder">No users found</p>';
            }
            if (typeof lucide !== 'undefined') lucide.createIcons();
        })
        .catch(err => console.error('Search error:', err));
};

// Modal functions
window.openSearchModal = function() {
    const modal = document.getElementById('searchModal');
    if (modal) {
        modal.style.display = 'flex';
        const input = document.getElementById('mobileSearchInput');
        if (input) input.focus();
    }
};

window.closeSearchModal = function(event) {
    if (!event || event.target === event.currentTarget) {
        const modal = document.getElementById('searchModal');
        if (modal) modal.style.display = 'none';
    }
};

window.openChatsPanel = function() {
    const panel = document.getElementById('chatsPanel');
    if (panel) {
        panel.style.display = 'flex';
        loadChatsPanel();
    }
};

window.closeChatsPanel = function(event) {
    if (!event || event.target === event.currentTarget) {
        const panel = document.getElementById('chatsPanel');
        if (panel) panel.style.display = 'none';
    }
};

window.openActivityPanel = function() {
    const panel = document.getElementById('activityPanel');
    if (panel) {
        panel.style.display = 'flex';
        loadActivityPanel();
    }
};

window.closeActivityPanel = function(event) {
    if (!event || event.target === event.currentTarget) {
        const panel = document.getElementById('activityPanel');
        if (panel) panel.style.display = 'none';
    }
};

// Load chats into panel
window.loadChatsPanel = function() {
    fetch('/api/chats/')
        .then(r => r.json())
        .then(data => {
            const container = document.getElementById('chatsList');
            if (!container) return;
            
            if (data.chats && data.chats.length > 0) {
                container.innerHTML = data.chats.map(chat => `
                    <a href="/chat/chat/${chat.id}/" class="ig-chat-item">
                        <div class="ig-chat-avatar-container">
                            ${chat.is_group 
                                ? '<div class="ig-chat-avatar-group"><i data-lucide="users"></i></div>'
                                : `<img src="${chat.avatar || ''}" alt="" class="ig-chat-avatar" onerror="this.outerHTML='<div class=\\'ig-chat-avatar-placeholder\\'>${chat.initials || 'U'}</div>'">`
                            }
                        </div>
                        <div class="ig-chat-info">
                            <span class="ig-chat-name">${chat.name || 'Chat'}</span>
                            <span class="ig-chat-preview">${chat.last_message || 'No messages yet'}</span>
                        </div>
                        ${chat.unread_count > 0 ? `<span class="ig-chat-badge">${chat.unread_count}</span>` : ''}
                    </a>
                `).join('');
            } else {
                container.innerHTML = `
                    <div class="ig-empty-state">
                        <i data-lucide="message-circle"></i>
                        <h3>No Messages Yet</h3>
                        <p>Start a conversation with someone!</p>
                    </div>
                `;
            }
            if (typeof lucide !== 'undefined') lucide.createIcons();
        })
        .catch(err => {
            console.error('Failed to load chats:', err);
            const container = document.getElementById('chatsList');
            if (container) container.innerHTML = '<p class="ig-error-text">Failed to load messages</p>';
        });
};

// Load activity into panel
window.loadActivityPanel = function() {
    // FIXED: Correct URL for story inbox
    fetch('/api/story-inbox/')
        .then(r => r.json())
        .then(data => {
            const container = document.getElementById('activityContent');
            if (!container) return;
            
            if (data.replies && data.replies.length > 0) {
                container.innerHTML = data.replies.map(r => `
                    <div class="ig-activity-item">
                        <img src="${r.replier?.profile_picture_url || ''}" alt="" class="ig-activity-avatar" onerror="this.style.background='var(--brand-gradient)'">
                        <div class="ig-activity-info">
                            <span class="ig-activity-username">${r.replier?.username || 'Someone'}</span>
                            <span class="ig-activity-text">${r.content || 'replied to your story'}</span>
                            <span class="ig-activity-time">${r.time_ago || ''}</span>
                        </div>
                    </div>
                `).join('');
            } else {
                container.innerHTML = `
                    <div class="ig-empty-state">
                        <i data-lucide="heart"></i>
                        <h3>No Activity Yet</h3>
                        <p>When someone interacts with you, you'll see it here.</p>
                    </div>
                `;
            }
            if (typeof lucide !== 'undefined') lucide.createIcons();
        })
        .catch(err => {
            console.error('Failed to load activity:', err);
            const container = document.getElementById('activityContent');
            if (container) container.innerHTML = '<p class="ig-error-text">Failed to load activity</p>';
        });
};

// Create post modal (stub - will be overridden by page-specific implementation)
window.openCreatePostModal = function() {
    // Check if page has its own implementation
    if (typeof window.pageOpenCreatePostModal === 'function') {
        window.pageOpenCreatePostModal();
    } else {
        // Use dashboard with create param
        window.location.href = '/chat/dashboard/?action=create';
    }
};

window.openCreateChatModal = function() {
    // Redirect to find users to chat with
    window.location.href = '/chat/discover-groups/';
};

console.log('✅ Enhanced Odnix JavaScript initialized successfully');
