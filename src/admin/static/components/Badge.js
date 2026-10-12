/**
 * Badge Component Factory
 */
import { h } from '../js/dom.js';

export function Badge({
  text,
  label,
  variant = 'neutral',
  icon = null,
  dot = false,
  className = '',
  ...props
}) {
  const badgeText = text !== undefined ? text : label;
  const children = [];

  if (dot) {
    children.push(h('span', {
      className: 'pulse-dot',
      style: variant === 'danger' ? 'background-color: var(--danger-text);' : ''
    }));
  }

  if (icon) {
    children.push(icon);
  }

  if (badgeText !== undefined && badgeText !== null) {
    children.push(h('span', {}, String(badgeText)));
  }

  return h('span', {
    className: `badge badge-${variant} ${className}`.trim(),
    ...props
  }, ...children);
}
