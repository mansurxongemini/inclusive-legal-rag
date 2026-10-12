/**
 * Semantic Accessible Table Component Factory
 */
import { h } from '../js/dom.js';

export function createTable({
  columns = [],
  data = [],
  emptyMessage = 'Maʼlumotlar mavjud emas',
  onRowClick = null,
  className = ''
}) {
  const thead = h('thead', {},
    h('tr', {},
      ...columns.map(col => h('th', {
        className: `${col.align === 'right' ? 'text-right' : (col.align === 'center' ? 'text-center' : 'text-left')} ${col.sticky ? 'sticky-col' : ''}`.trim(),
        style: col.width ? `width: ${col.width};` : ''
      }, col.label))
    )
  );

  const tbody = h('tbody', {});

  function renderRows(rows) {
    tbody.innerHTML = '';
    if (!rows || rows.length === 0) {
      tbody.appendChild(
        h('tr', {},
          h('td', {
            colSpan: columns.length,
            className: 'text-center p-8 text-muted'
          }, emptyMessage)
        )
      );
      return;
    }

    rows.forEach(item => {
      const tr = h('tr', {
        className: onRowClick ? 'cursor-pointer hover:bg-surface-2 transition' : '',
        tabIndex: onRowClick ? 0 : undefined,
        onclick: onRowClick ? () => onRowClick(item) : undefined,
        onkeydown: onRowClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') onRowClick(item); } : undefined
      },
        ...columns.map(col => {
          const val = typeof col.render === 'function' ? col.render(item[col.key], item) : (item[col.key] ?? '-');
          return h('td', {
            className: `${col.align === 'right' ? 'text-right' : (col.align === 'center' ? 'text-center' : 'text-left')} ${col.sticky ? 'sticky-col' : ''}`.trim()
          }, val);
        })
      );
      tbody.appendChild(tr);
    });
  }

  renderRows(data);

  const table = h('div', { className: `table-wrapper ${className}`.trim() },
    h('table', { className: 'data-table' }, thead, tbody)
  );

  return {
    element: table,
    update: (newData) => renderRows(newData)
  };
}
