/**
 * Accessible Slide-Over (Right Drawer) Component Factory
 * Features: smooth slide-in, backdrop blur, Esc closing, keyboard trapping.
 */
import { h } from '../js/dom.js';
import { icons } from '../js/icons.js';

export function createSlideOver({
  title = '',
  badge = null,
  content = null,
  footer = null,
  onClose = null,
  maxWidth = '600px'
}) {
  let lastActiveElement = null;

  const titleEl = h('h3', { className: 'text-sm font-bold text-main line-clamp-1' }, title);
  const badgeContainer = h('div', { className: 'flex items-center gap-2' }, badge);

  const closeBtn = h('button', {
    type: 'button',
    className: 'btn-ghost btn-icon p-1.5 rounded-sm text-muted',
    'aria-label': 'Yopish',
    onclick: () => drawer.close()
  }, icons.close('icon-sm'));

  const header = h('div', { className: 'px-6 py-4 border-b border-border bg-surface-2 flex items-center justify-between' },
    h('div', { className: 'flex items-center gap-2.5 min-w-0 flex-1 mr-3' },
      badgeContainer,
      titleEl
    ),
    closeBtn
  );

  const body = h('div', { className: 'px-6 py-5 overflow-y-auto flex-1 space-y-4' }, content);

  const footerEl = h('div', { className: 'px-6 py-3.5 border-t border-border bg-surface-2 flex items-center justify-between gap-3' }, footer);

  const panel = h('aside', {
    className: 'slide-over-panel hidden-drawer',
    style: `max-width: ${maxWidth};`,
    role: 'dialog',
    'aria-modal': 'true',
    'aria-label': title || 'Maʼlumot oynasi',
    onclick: (e) => e.stopPropagation()
  },
    header,
    body,
    footerEl
  );

  const backdrop = h('div', {
    className: 'slide-over-backdrop hidden opacity-0',
    onclick: () => drawer.close()
  }, panel);

  function trapFocus(e) {
    if (e.key !== 'Tab') return;
    const focusable = panel.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
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
      drawer.close();
    } else if (e.key === 'Tab') {
      trapFocus(e);
    }
  }

  const drawer = {
    element: backdrop,
    open: () => {
      lastActiveElement = document.activeElement;
      backdrop.classList.remove('hidden');
      setTimeout(() => {
        backdrop.style.opacity = '1';
        panel.classList.remove('hidden-drawer');
      }, 10);
      document.addEventListener('keydown', handleKeyDown);
      closeBtn.focus();
    },
    close: () => {
      panel.classList.add('hidden-drawer');
      backdrop.style.opacity = '0';
      setTimeout(() => {
        backdrop.classList.add('hidden');
      }, 180);
      document.removeEventListener('keydown', handleKeyDown);
      if (lastActiveElement && lastActiveElement.focus) {
        lastActiveElement.focus();
      }
      if (typeof onClose === 'function') onClose();
    },
    setTitle: (newTitle, newBadge = null) => {
      titleEl.textContent = newTitle;
      badgeContainer.innerHTML = '';
      if (newBadge) badgeContainer.appendChild(newBadge);
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
      footerEl.innerHTML = '';
      if (newFooter) {
        if (Array.isArray(newFooter)) {
          newFooter.forEach(f => footerEl.appendChild(f));
        } else {
          footerEl.appendChild(newFooter);
        }
      }
    }
  };

  return drawer;
}
