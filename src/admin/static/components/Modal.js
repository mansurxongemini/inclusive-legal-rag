/**
 * Accessible Modal Component Factory
 * Features: focus trapping, Esc handling, backdrop click, smooth transitions.
 */
import { h } from '../js/dom.js';
import { icons } from '../js/icons.js';

export function createModal({
  id = '',
  title = '',
  content = null,
  footer = null,
  onClose = null,
  maxWidth = '520px'
}) {
  const titleId = `${id || 'modal'}-title`;

  let lastActiveElement = null;

  const closeBtn = h('button', {
    type: 'button',
    className: 'btn-ghost btn-icon p-1 rounded-sm text-muted',
    'aria-label': 'Yopish',
    onclick: () => modal.close()
  }, icons.close('icon-sm'));

  const header = h('div', { className: 'flex items-center justify-between pb-3 border-b border-border' },
    h('h3', { id: titleId, className: 'text-sm font-bold text-main' }, title),
    closeBtn
  );

  const body = h('div', { className: 'modal-body py-4 space-y-3' }, content);

  const footerContainer = h('div', {
    className: `modal-footer pt-3 border-t border-border flex items-center justify-end gap-2 ${footer ? '' : 'hidden'}`.trim()
  }, footer);

  const dialog = h('div', {
    className: 'modal-dialog',
    style: `max-width: ${maxWidth};`,
    onclick: (e) => e.stopPropagation() // Prevent backdrop click from triggering inside
  },
    header,
    body,
    footerContainer
  );

  const backdrop = h('div', {
    id: id || undefined,
    className: 'modal-backdrop hidden',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-labelledby': titleId,
    onclick: () => modal.close()
  }, dialog);

  function trapFocus(e) {
    if (e.key !== 'Tab') return;
    const focusable = dialog.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (e.shiftKey && document.activeElement === first) {
      last.focus();
      e.preventDefault();
    } else if (!e.shiftKey && document.activeElement === last) {
      first.focus();
      e.preventDefault();
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Escape') {
      modal.close();
    } else if (e.key === 'Tab') {
      trapFocus(e);
    }
  }

  const modal = {
    element: backdrop,
    open: () => {
      lastActiveElement = document.activeElement;
      backdrop.classList.remove('hidden');
      document.addEventListener('keydown', handleKeyDown);
      // Focus on first input or close button
      setTimeout(() => {
        const input = dialog.querySelector('input, textarea, select');
        if (input) input.focus();
        else closeBtn.focus();
      }, 50);
    },
    close: () => {
      backdrop.classList.add('hidden');
      document.removeEventListener('keydown', handleKeyDown);
      if (lastActiveElement && lastActiveElement.focus) {
        lastActiveElement.focus();
      }
      if (typeof onClose === 'function') onClose();
    },
    setContent: (newContent) => {
      body.innerHTML = '';
      if (newContent) {
        if (Array.isArray(newContent)) {
          newContent.forEach(c => body.appendChild(c));
        } else {
          body.appendChild(newContent);
        }
      }
    },
    setFooter: (newFooter) => {
      footerContainer.innerHTML = '';
      if (newFooter) {
        footerContainer.classList.remove('hidden');
        if (Array.isArray(newFooter)) {
          newFooter.forEach(f => footerContainer.appendChild(f));
        } else {
          footerContainer.appendChild(newFooter);
        }
      } else {
        footerContainer.classList.add('hidden');
      }
    }
  };

  return modal;
}
