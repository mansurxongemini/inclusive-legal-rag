/**
 * EmptyState Component Factory
 */
import { h } from '../js/dom.js';

export function EmptyState({
  icon = null,
  title = 'Maʼlumot topilmadi',
  description = '',
  action = null,
  className = ''
}) {
  const children = [];

  if (icon) {
    children.push(h('div', {
      className: 'w-10 h-10 rounded-full bg-surface-2 flex items-center justify-center text-muted mb-2'
    }, icon));
  }

  children.push(h('h4', { className: 'text-xs font-bold text-main' }, title));

  if (description) {
    children.push(h('p', { className: 'text-xs text-muted max-w-sm mx-auto mt-1' }, description));
  }

  if (action) {
    children.push(h('div', { className: 'mt-3' }, action));
  }

  return h('div', {
    className: `card-surface p-12 text-center flex flex-col items-center justify-center ${className}`.trim()
  }, ...children);
}
