/**
 * Skeleton Loader Component Factory
 */
import { h } from '../js/dom.js';

export function SkeletonBox({ width = '100%', height = '16px', className = '' }) {
  return h('div', {
    className: `skeleton-box ${className}`.trim(),
    style: `width: ${width}; height: ${height};`
  });
}

export function SkeletonCard({ rows = 3, className = '' }) {
  const children = [
    h('div', { className: 'flex items-center justify-between pb-2 border-b border-border' },
      SkeletonBox({ width: '40%', height: '18px' }),
      SkeletonBox({ width: '20%', height: '14px' })
    )
  ];

  for (let i = 0; i < rows; i++) {
    const w = i === rows - 1 ? '60%' : '100%';
    children.push(SkeletonBox({ width: w, height: '14px' }));
  }

  return h('div', {
    className: `card-surface p-5 space-y-3 ${className}`.trim()
  }, ...children);
}
