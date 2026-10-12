/**
 * Toast Notification Factory
 */
import { h } from '../js/dom.js';
import { icons } from '../js/icons.js';

let toastContainer = null;

function getContainer() {
  if (!toastContainer) {
    toastContainer = h('div', { className: 'toast-container', role: 'region', 'aria-live': 'polite' });
    document.body.appendChild(toastContainer);
  }
  return toastContainer;
}

export function showToast(message, variant = 'neutral', durationMs = 3000) {
  const container = getContainer();

  let icon = null;
  if (variant === 'success') {
    icon = icons.check('icon-sm text-emerald-600');
  } else if (variant === 'danger') {
    icon = icons.close('icon-sm text-rose-600');
  }

  const toast = h('div', {
    className: 'toast',
    role: 'alert'
  },
    icon,
    h('span', {}, message)
  );

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = 'opacity 180ms ease-out, transform 180ms ease-out';
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(6px)';
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 200);
  }, durationMs);
}
