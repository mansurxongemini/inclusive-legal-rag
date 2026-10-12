/**
 * Button Component Factory
 */
import { h } from '../js/dom.js';

export function Button({
  text,
  icon = null,
  variant = 'secondary',
  size = 'md',
  disabled = false,
  onClick = null,
  className = '',
  type = 'button',
  ...props
}) {
  const variantClass = `btn-${variant}`;
  const sizeClass = size === 'sm' ? 'btn-sm' : '';
  const finalClass = `btn ${variantClass} ${sizeClass} ${className}`.trim();

  const children = [];
  if (icon) children.push(icon);
  if (text) children.push(h('span', {}, text));

  return h('button', {
    type,
    className: finalClass,
    disabled: Boolean(disabled),
    onclick: onClick,
    ...props
  }, ...children);
}
