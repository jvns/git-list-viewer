const messages = window.messagesData;
let isScrollingProgrammatically = false;

function showMessage(messageId, element) {
  // Remove previous selection
  document.querySelectorAll('.message-item.selected').forEach(el => {
    el.classList.remove('selected');
  });

  // Mark current as selected
  element.classList.add('selected');

  // Update URL hash with the actual message ID
  window.location.hash = encodeURIComponent(messageId);

  // Scroll to the corresponding email in the main content
  const sanitizedId = element.dataset.sanitizedId;
  const emailElement = document.getElementById('email-' + sanitizedId);
  if (emailElement) {
    emailElement.scrollIntoView({ behavior: 'auto', block: 'start' });
  }
}

// Track scroll position and highlight current message in sidebar
function updateCurrentMessage() {
  const mainContent = document.getElementById('main-content');
  let currentMessageId = null;
  let currentSanitizedId = null;

  // Find which email is currently most visible
  const emailElements = document.querySelectorAll('.email-message');
  for (const emailElement of emailElements) {
    const rect = emailElement.getBoundingClientRect();
    const mainContentRect = mainContent.getBoundingClientRect();

    // Check if email is in view
    if (rect.top <= mainContentRect.top + 100) {
      currentMessageId = emailElement.dataset.messageId;
      currentSanitizedId = emailElement.id.replace('email-', '');
    }
  }

  if (currentMessageId && currentSanitizedId) {
    // Update URL hash
    window.location.hash = encodeURIComponent(currentMessageId);

    // Update sidebar selection
    document.querySelectorAll('.message-item.selected').forEach(el => {
      el.classList.remove('selected');
    });

    const currentItem = document.getElementById('msg-' + currentSanitizedId);
    if (currentItem) {
      currentItem.classList.add('selected');
      // Scroll the sidebar item into view
      currentItem.scrollIntoView({ behavior: 'auto', block: 'nearest' });
    }
  }
}

// Add scroll listener to main content
document.getElementById('main-content').addEventListener('scroll', updateCurrentMessage);

// Handle URL hash on page load
function handleInitialHash() {
  const hash = window.location.hash;
  if (hash) {
    const messageId = decodeURIComponent(hash.substring(1));
    
    // Find sidebar item by looking for matching data-sanitized-id
    const sidebarItems = document.querySelectorAll('.message-item');
    for (const item of sidebarItems) {
      const itemMessageId = item.onclick.toString().match(/'([^']+)'/)?.[1];
      if (itemMessageId === messageId) {
        item.click();
        return;
      }
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
  handleInitialHash();
});
