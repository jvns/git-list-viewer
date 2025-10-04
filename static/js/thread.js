const messages = window.messagesData;

function selectMessage(sanitizedId) {
  history.replaceState(null, null, '#' + sanitizedId);
  document.querySelectorAll('.message-item.selected').forEach(el => {
    el.classList.remove('selected');
  });
  const sidebarItem = document.getElementById('sidebar-' + sanitizedId);
  if (sidebarItem) {
    sidebarItem.classList.add('selected');
    sidebarItem.scrollIntoView({ behavior: 'auto', block: 'nearest' });
  }
}

function showMessage(sanitizedId) {
  selectMessage(sanitizedId);
  document.getElementById('msg-' + sanitizedId)?.scrollIntoView({ behavior: 'auto', block: 'start' });
}

// Set up intersection observer to track visible messages
function setupMessageObserver() {
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        const sanitizedId = entry.target.id.replace('msg-', '');
        selectMessage(sanitizedId);
        break;
      }
    }
  }, {
    root: document.querySelector('main'),
    rootMargin: '-10% 0px -90% 0px',
    threshold: 0
  });

  document.querySelectorAll('section').forEach(el => observer.observe(el));
}

// Handle URL hash on page load
function handleInitialHash() {
  const hash = window.location.hash;
  if (hash) {
    document.getElementById('sidebar-' + hash.substring(1))?.click();
  }
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
