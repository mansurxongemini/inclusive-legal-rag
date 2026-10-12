/**
 * Safe, Lightweight Markdown & Citation Parser
 * Handles code blocks, nested lists, citations, quotes and backslashes safely.
 * Returns an HTMLElement document fragment.
 */

import { h } from './dom.js';

export function parseMarkdown(rawText, citationMap = {}) {
  const container = document.createElement('div');
  container.className = 'markdown-body space-y-2';

  if (!rawText) return container;

  // Strict zero-emoji policy: filter out all emojis and pictographs
  rawText = rawText.replace(/[\p{Extended_Pictographic}\uFE0F]/gu, '');
  rawText = rawText.replace(/^(#{1,6})\s+/gm, '$1 ');
  rawText = rawText.replace(/^(\s*[-*])\s+/gm, '$1 ');

  const lines = rawText.split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced Code Block (handles backticks inside the block)
    if (line.trim().startsWith('```')) {
      const lang = line.trim().slice(3).trim();
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // consume closing ```

      const pre = h('pre', {
        className: 'p-3 bg-slate-900 text-slate-100 rounded-lg text-xs font-mono overflow-x-auto leading-relaxed'
      }, h('code', { className: lang ? `language-${lang}` : '' }, codeLines.join('\n')));

      container.appendChild(pre);
      continue;
    }

    // Markdown Table (GFM)
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      const tableRows = [];
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        tableRows.push(lines[i].trim());
        i++;
      }

      if (tableRows.length >= 2) {
        const parseRow = (r) => r.slice(1, -1).split('|').map(c => c.trim());
        const headerCols = parseRow(tableRows[0]);
        const isSep = (r) => /^\|(?:\s*:?-+:?\s*\|)+$/.test(r);

        let dataStart = 1;
        if (isSep(tableRows[1])) {
          dataStart = 2;
        }

        const thead = h('thead', {},
          h('tr', {}, ...headerCols.map(col => {
            const th = h('th', {});
            appendFormattedText(th, col, citationMap);
            return th;
          }))
        );

        const tbody = h('tbody', {});
        for (let rowIdx = dataStart; rowIdx < tableRows.length; rowIdx++) {
          if (isSep(tableRows[rowIdx])) continue;
          const cols = parseRow(tableRows[rowIdx]);
          const tr = h('tr', {}, ...cols.map(c => {
            const td = h('td', {});
            appendFormattedText(td, c, citationMap);
            return td;
          }));
          tbody.appendChild(tr);
        }

        const table = h('table', { className: 'data-table' }, thead, tbody);
        const wrapper = h('div', { className: 'table-wrapper my-2' }, table);
        container.appendChild(wrapper);
        continue;
      }
    }

    // Headers
    if (line.startsWith('### ')) {
      const header = h('h5', { className: 'text-xs font-semibold text-main mt-2 mb-1' });
      appendFormattedText(header, line.slice(4), citationMap);
      container.appendChild(header);
      i++;
      continue;
    }
    if (line.startsWith('## ')) {
      const header = h('h4', { className: 'text-xs font-bold text-main mt-3 mb-1' });
      appendFormattedText(header, line.slice(3), citationMap);
      container.appendChild(header);
      i++;
      continue;
    }
    if (line.startsWith('# ')) {
      const header = h('h3', { className: 'text-sm font-bold text-main mt-3 mb-1-5' });
      appendFormattedText(header, line.slice(2), citationMap);
      container.appendChild(header);
      i++;
      continue;
    }

    // Blockquote
    if (line.startsWith('> ')) {
      const bq = h('blockquote', { className: 'p-2-5 bg-surface-2 border-l-2 border-accent text-xs italic text-muted rounded-r my-1' });
      appendFormattedText(bq, line.slice(2), citationMap);
      container.appendChild(bq);
      i++;
      continue;
    }

    // Unordered and Nested Lists
    if (/^(\s*)[-*]\s+/.test(line)) {
      const parseListLevel = (baseIndent) => {
        const ul = h('ul', { className: 'list-disc ml-4 space-y-1 my-1 text-xs' });
        let currentLi = null;

        while (i < lines.length) {
          const l = lines[i];
          const match = l.match(/^(\s*)[-*]\s+(.*)$/);
          if (!match) break;

          const indent = match[1].length;
          const text = match[2];

          if (indent === baseIndent) {
            currentLi = h('li', {});
            appendFormattedText(currentLi, text, citationMap);
            ul.appendChild(currentLi);
            i++;
          } else if (indent > baseIndent) {
            if (currentLi) {
              const subUl = parseListLevel(indent);
              currentLi.appendChild(subUl);
            } else {
              i++;
            }
          } else {
            // Less indented: return back to parent level
            break;
          }
        }
        return ul;
      };

      const match = line.match(/^(\s*)[-*]\s+/);
      const rootIndent = match ? match[1].length : 0;
      const rootUl = parseListLevel(rootIndent);
      container.appendChild(rootUl);
      continue;
    }

    // Paragraph
    const trimmed = line.trim();
    if (trimmed.length > 0) {
      const p = h('p', { className: 'text-xs leading-relaxed text-main' });
      appendFormattedText(p, trimmed, citationMap);
      container.appendChild(p);
    }
    i++;
  }

  return container;
}

function appendFormattedText(parent, text, citationMap) {
  // Regex to tokenize bold, inline code, citations
  const pattern = /(\*\*([^*]+)\*\*)|(`([^`]+)`)|(\[([a-zA-Z0-9_\-]+)(?:,\s*([^\]]+))?\])/g;

  let lastIndex = 0;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parent.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
    }

    if (match[2]) {
      // Bold
      parent.appendChild(h('strong', { className: 'font-semibold text-main' }, match[2]));
    } else if (match[4]) {
      // Code
      parent.appendChild(h('code', { className: 'px-1 py-0-5 bg-surface-2 text-accent font-mono text-2xs rounded border border-border' }, match[4]));
    } else if (match[6]) {
      // Citation
      const tag = match[6];
      let num = tag;
      const citation = citationMap[tag];
      if (citation && citation.index) {
        num = citation.index;
      }
      const chip = h('span', {
        className: 'badge badge-info font-mono tabular-nums text-2xs cursor-help select-none',
        title: citation ? `${citation.article_number} — ${citation.law_title || ''}` : `Norma: ${tag}`
      }, `[${num}]`);
      parent.appendChild(chip);
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    parent.appendChild(document.createTextNode(text.slice(lastIndex)));
  }
}
