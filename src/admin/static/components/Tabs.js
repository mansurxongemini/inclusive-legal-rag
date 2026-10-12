/**
 * Tabs and Segmented Control Component Factory
 */
import { h } from '../js/dom.js';

export function SegmentedControl({
  items = [],
  activeId = '',
  onChange = null,
  className = ''
}) {
  let currentActive = activeId || (items[0] && items[0].id);

  const buttons = items.map(item => {
    const isActive = item.id === currentActive;
    const btn = h('button', {
      type: 'button',
      className: `segmented-item ${isActive ? 'active' : ''}`,
      role: 'tab',
      'aria-selected': isActive ? 'true' : 'false',
      'data-tab-id': item.id,
      onclick: () => {
        if (currentActive === item.id) return;
        currentActive = item.id;
        updateActiveStates();
        if (typeof onChange === 'function') onChange(item.id);
      }
    },
      h('span', {}, item.label),
      item.count !== undefined && item.count !== null ? h('span', { className: 'ml-1 font-mono text-2xs tabular-nums opacity-80' }, `(${item.count})`) : null
    );
    btn.dataset.tabId = item.id;
    return btn;
  });

  const container = h('div', {
    className: `segmented-control ${className}`.trim(),
    role: 'tablist'
  }, ...buttons);

  function updateActiveStates() {
    container.querySelectorAll('.segmented-item').forEach(b => {
      const isAct = b.dataset.tabId === currentActive;
      if (isAct) {
        b.classList.add('active');
        b.setAttribute('aria-selected', 'true');
      } else {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
      }
    });
  }

  return {
    element: container,
    setActive: (id) => {
      currentActive = id;
      updateActiveStates();
    },
    updateCounts: (countsMap) => {
      container.querySelectorAll('.segmented-item').forEach(b => {
        const id = b.dataset.tabId;
        const item = items.find(it => it.id === id);
        if (item && countsMap[id] !== undefined) {
          b.innerHTML = '';
          b.appendChild(h('span', {}, item.label));
          b.appendChild(h('span', { className: 'ml-1 font-mono text-2xs tabular-nums opacity-80' }, `(${countsMap[id]})`));
        }
      });
    }
  };
}
