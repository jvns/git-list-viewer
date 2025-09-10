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
    for (const entry of entries) {
      if (entry.isIntersecting) {
        const sanitizedId = entry.target.id.replace('msg-', '');
        window.location.hash = sanitizedId;
        
        // Update sidebar selection
        document.querySelectorAll('.message-item.selected').forEach(el => {
          el.classList.remove('selected');
        });
        
        const sidebarItem = document.getElementById('sidebar-' + sanitizedId);
        if (sidebarItem) {
          sidebarItem.classList.add('selected');
          sidebarItem.scrollIntoView({ behavior: 'auto', block: 'nearest' });
        }
        break; // Only handle the first intersecting element
      }
    }
  }, {
    root: document.getElementById('main-content'),
    rootMargin: '-10% 0px -90% 0px',
    threshold: 0
  });

  document.querySelectorAll('.email-message').forEach(el => observer.observe(el));
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
