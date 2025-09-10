const messages = window.messagesData;
let isScrollingProgrammatically = false;

function showMessage(sanitizedId, element) {
  // Remove previous selection
  document.querySelectorAll('.message-item.selected').forEach(el => {
    el.classList.remove('selected');
  });

  // Mark current as selected
  element.classList.add('selected');

  // Update URL hash with the sanitized ID
  window.location.hash = sanitizedId;

  // Scroll to the corresponding email in the main content
  const emailElement = document.getElementById('msg-' + sanitizedId);
  if (emailElement) {
    emailElement.scrollIntoView({ behavior: 'auto', block: 'start' });
  }
}

// Set up intersection observer to track visible messages
function setupMessageObserver() {
  const observer = new IntersectionObserver((entries) => {
    // Find the topmost visible message
    let topMostEntry = null;
    let topMostY = Infinity;
    
    for (const entry of entries) {
      if (entry.isIntersecting) {
        const rect = entry.boundingClientRect;
        if (rect.top < topMostY) {
          topMostY = rect.top;
          topMostEntry = entry;
        }
      }
    }
    
    if (topMostEntry) {
      const currentSanitizedId = topMostEntry.target.id.replace('msg-', '');
      
      // Update URL hash
      window.location.hash = currentSanitizedId;
      
      // Update sidebar selection
      document.querySelectorAll('.message-item.selected').forEach(el => {
        el.classList.remove('selected');
      });
      
      const currentItem = document.getElementById('sidebar-' + currentSanitizedId);
      if (currentItem) {
        currentItem.classList.add('selected');
        // Scroll the sidebar item into view
        currentItem.scrollIntoView({ behavior: 'auto', block: 'nearest' });
      }
    }
  }, {
    root: document.getElementById('main-content'),
    rootMargin: '-20% 0px -80% 0px', // Top 20% of the viewport
    threshold: 0
  });

  // Observe all email messages
  document.querySelectorAll('.email-message').forEach(el => {
    observer.observe(el);
  });
}

// Handle URL hash on page load
function handleInitialHash() {
  const hash = window.location.hash;
  if (hash) {
    const sanitizedId = hash.substring(1);
    const sidebarItem = document.getElementById('sidebar-' + sanitizedId);
    if (sidebarItem) {
      sidebarItem.click();
      return;
    }
  }
  // Default to first message if no valid hash
  updateCurrentMessage();
}

// Keyboard navigation
function handleKeyboardNavigation(event) {
  if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
    return; // Don't intercept when user is typing
  }

  const currentSelected = document.querySelector('.message-item.selected');
  if (!currentSelected) return;

  let targetElement = null;

  switch (event.key) {
    case 'j':
    case 'J':
      event.preventDefault();
      targetElement = currentSelected.nextElementSibling;
      break;
    case 'k':
    case 'K':
      event.preventDefault();
      targetElement = currentSelected.previousElementSibling;
      break;
  }

  if (targetElement && targetElement.classList.contains('message-item')) {
    targetElement.click();
  }
}

document.addEventListener('keydown', handleKeyboardNavigation);

// Initialize with hash or first message selected
document.addEventListener('DOMContentLoaded', function() {
  setupMessageObserver();
  handleInitialHash();
});
