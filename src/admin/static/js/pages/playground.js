/**
 * Sinov (playground.js) — Bot javobini to'g'ridan-to'g'ri sinash
 * POST /api/v1/query (stream=false) orqali bot oladigan real javobni tekshiradi.
 * WCAG 2.2 AA talablariga mos, innerHTML ishlatilmagan (faqat h() va parseMarkdown).
 */
import { h, clear } from '../dom.js';
import { icons } from '../icons.js';
import { api } from '../api.js';
import { Badge } from '../../components/Badge.js';
import { Button } from '../../components/Button.js';
import { EmptyState } from '../../components/EmptyState.js';
import { showToast } from '../../components/Toast.js';
import { parseMarkdown } from '../markdown.js';

const SAMPLE_QUESTIONS = [
  "I va II guruh nogironligi bo‘lgan shaxslar uchun haftalik ish vaqti necha soat qilib belgilanadi?",
  "Nogironlar aravachasi va protez-ortopediya buyumlari qancha muddatda davlat tomonidan bepul almashtiriladi?",
  "Nogironligi bo‘lgan abituriyentlar uchun OTMlarga kirishda qanday imtiyozli kvotalar mavjud?",
  "Muddatsiz nogironlik qaysi holatlarda belgilanadi va TMEK xulosasidan qanday shikoyat qilinadi?",
  "I va II guruh nogironligi bo‘lgan shaxslar qaysi soliqlardan ozod qilingan?"
];

export function renderPlaygroundPage() {
  const container = h('div', { className: 'space-y-6' });

  let isQuerying = false;
  let startTime = null;

  // 1. Header Card
  const header = h('div', { className: 'card-surface p-5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4' },
    h('div', { className: 'space-y-1' },
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Qidiruv va javob berishni sinash'),
        Badge({ label: 'Botdagi kabi', variant: 'neutral' })
      ),
      h('p', { className: 'text-xs text-muted' },
        'Bot foydalanuvchilarga beradigan yakuniy javob, iqtiboslar va aniqlangan qonuniy asoslarni sinab ko‘ring.'
      )
    )
  );

  // 2. Main Grid Layout
  const grid = h('div', { className: 'grid grid-cols-1 lg:grid-cols-12 gap-6' });

  // --- Left Column: Controls (5 cols) ---
  const leftCol = h('div', { className: 'lg:col-span-5 space-y-4' });
  const formCard = h('div', { className: 'card-surface p-5 space-y-4' });

  // Language & Mode Selectors
  const langSelect = h('select', { className: 'select-dropdown' },
    h('option', { value: 'auto' }, 'Avtomatik aniqlash'),
    h('option', { value: 'uz' }, 'O‘zbekcha'),
    h('option', { value: 'ru' }, 'Русский'),
    h('option', { value: 'en' }, 'English')
  );

  const modeSelect = h('select', { className: 'select-dropdown' },
    h('option', { value: 'plain' }, 'Oddiy tilda (xulosa)'),
    h('option', { value: 'legal_text' }, 'Rasmiy qonun tili')
  );

  const langModeGrid = h('div', { className: 'grid grid-cols-2 gap-3' },
    h('div', { className: 'space-y-1-5' },
      h('label', { className: 'block text-xs font-semibold text-main' }, 'Javob tili'),
      langSelect
    ),
    h('div', { className: 'space-y-1-5' },
      h('label', { className: 'block text-xs font-semibold text-main' }, 'Javob uslubi'),
      modeSelect
    )
  );

  // Question Textarea
  const questionInput = h('textarea', {
    rows: 4,
    className: 'textarea-field',
    placeholder: 'Savolni kiriting... (masalan: 1-guruh nogironlariga qanday pensiya va ish imtiyozlari bor?)'
  });

  const questionField = h('div', { className: 'space-y-1-5' },
    h('label', { className: 'block text-xs font-semibold text-main' }, 'Savol matni'),
    questionInput
  );

  // Sample prompt pills
  const samplesContainer = h('div', { className: 'space-y-2' },
    h('span', { className: 'text-2xs font-semibold text-muted uppercase tracking-wider' }, 'Namuna savollar:'),
    h('div', { className: 'flex flex-wrap gap-1.5' },
      ...SAMPLE_QUESTIONS.map(q => {
        return h('button', {
          type: 'button',
          className: 'btn btn-secondary btn-sm btn-wrap text-2xs max-w-full',
          onclick: () => {
            questionInput.value = q;
            questionInput.focus();
          }
        }, q);
      })
    )
  );

  // Submit Button
  let executeBtn = null;
  executeBtn = Button({
    text: 'Savolni sinash',
    icon: icons.chat('icon-sm'),
    variant: 'primary',
    onClick: handleExecuteQuery
  });

  formCard.appendChild(questionField);
  formCard.appendChild(langModeGrid);
  formCard.appendChild(executeBtn);
  leftCol.appendChild(formCard);
  leftCol.appendChild(samplesContainer);

  // --- Right Column: Results (7 cols) ---
  const rightCol = h('div', { className: 'lg:col-span-7 space-y-4' });
  const resultContainer = h('div', { className: 'min-h-[360px]' });

  // Initial Empty State
  resultContainer.appendChild(
    EmptyState({
      icon: icons.chat('icon-lg text-muted'),
      title: 'Sinov natijasi bu yerda ko‘rinadi',
      description: 'Chap paneldan savol kiritib, "Savolni sinash" tugmasini bosing.'
    })
  );

  rightCol.appendChild(resultContainer);
  grid.appendChild(leftCol);
  grid.appendChild(rightCol);

  container.appendChild(header);
  container.appendChild(grid);

  async function handleExecuteQuery() {
    const questionText = questionInput.value.trim();
    if (!questionText) {
      showToast('Iltimos, avval savol matnini kiriting.', 'warning');
      questionInput.focus();
      return;
    }

    if (isQuerying) return;
    isQuerying = true;
    executeBtn.disabled = true;
    startTime = performance.now();

    renderLoadingState();

    try {
      const payload = {
        question: questionText,
        language: langSelect.value,
        mode: modeSelect.value,
        stream: false
      };

      const result = await api.queryBot(payload);
      const elapsedMs = Math.round(performance.now() - startTime);

      renderResult(result, elapsedMs);

    } catch (err) {
      renderErrorState(err.message);
      showToast(`Xatolik: ${err.message}`, 'error');
    } finally {
      isQuerying = false;
      executeBtn.disabled = false;
    }
  }

  function renderLoadingState() {
    clear(resultContainer);
    const skeleton = h('div', { className: 'card-surface p-6 space-y-4 animate-pulse' },
      h('div', { className: 'h-4 bg-surface-2 rounded w-1/3' }),
      h('div', { className: 'space-y-2 pt-2' },
        h('div', { className: 'h-3 bg-surface-2 rounded w-full' }),
        h('div', { className: 'h-3 bg-surface-2 rounded w-5/6' }),
        h('div', { className: 'h-3 bg-surface-2 rounded w-4/6' })
      ),
      h('div', { className: 'h-16 bg-surface-2 rounded mt-4' })
    );
    resultContainer.appendChild(skeleton);
  }

  function renderErrorState(errorMsg) {
    clear(resultContainer);
    resultContainer.appendChild(
      h('div', { className: 'card-surface p-5 border-danger space-y-3' },
        h('div', { className: 'flex items-center gap-2 text-danger font-semibold text-xs' },
          icons.close('icon-sm text-danger'),
          h('span', {}, 'So‘rov bajarilmadi')
        ),
        h('p', { className: 'text-xs text-muted leading-relaxed' }, errorMsg),
        Button({
          text: 'Qayta urinish',
          icon: icons.refresh('icon-sm'),
          variant: 'secondary',
          size: 'sm',
          onClick: handleExecuteQuery
        })
      )
    );
  }

  function renderResult(data, elapsedMs) {
    clear(resultContainer);

    const citations = data.citations || [];
    const citationMap = {};
    citations.forEach((c, idx) => {
      const num = c.index || (idx + 1);
      if (c.canonical_id) citationMap[c.canonical_id] = c;
      citationMap[String(num)] = c;
    });

    const card = h('div', { className: 'card-surface p-5 space-y-4' });

    // 1. Result Header
    const timeText = elapsedMs >= 1000 ? `${(elapsedMs / 1000).toFixed(2)} soniya` : `${elapsedMs} ms`;
    const timeBadge = h('span', { className: 'text-2xs font-mono text-muted bg-surface-2 px-2 py-0.5 rounded border border-border tabular-nums' }, timeText);

    const isRefusal = data.is_refusal === true;
    const refusalBadge = isRefusal ? Badge({ label: 'Rad etildi', variant: 'warning' }) : Badge({ label: 'Javob berildi', variant: 'success' });

    const copyBtn = Button({
      text: 'Nusxalash',
      icon: icons.copy('icon-sm'),
      variant: 'secondary',
      size: 'sm',
      onClick: () => {
        const textToCopy = data.telegram_formatted || data.clean_answer || data.answer || '';
        if (!textToCopy) return;
        navigator.clipboard.writeText(textToCopy).then(() => {
          showToast('Javob matni nusxalandi.', 'success');
        }).catch(() => {
          showToast('Nusxalash imkoni bo‘lmadi.', 'error');
        });
      }
    });

    const resultHeader = h('div', { className: 'flex items-center justify-between pb-3 border-b border-border flex-wrap gap-2' },
      h('div', { className: 'flex items-center gap-2' },
        refusalBadge,
        h('h3', { className: 'text-xs font-bold text-main' }, isRefusal ? 'Savol rad etildi' : 'AI Yordamchi javobi')
      ),
      h('div', { className: 'flex items-center gap-2' },
        timeBadge,
        copyBtn
      )
    );

    // 2. Answer Body
    const rawAnswer = data.clean_answer || data.answer || '';
    const answerFragment = parseMarkdown(rawAnswer, citationMap);
    const answerContainer = h('div', { className: 'py-1 text-xs leading-relaxed text-main select-text' }, answerFragment);

    // 3. Status ogohlantirishlari (agar bo'lsa)
    let warningsBox = null;
    if (data.status_warnings && data.status_warnings.length > 0) {
      warningsBox = h('div', { className: 'p-3 rounded bg-warning-subtle border border-warning text-xs space-y-1' },
        h('p', { className: 'font-bold text-warning' }, 'Diqqat: ayrim moddalar bo‘yicha ogohlantirishlar mavjud:'),
        ...data.status_warnings.map(w => h('p', { className: 'text-2xs text-muted' }, `${w.law_number || ''}: ${w.warning || w.message || ''}`))
      );
    }

    // 4. "Qidiruvda topilgan normalar" yig'iladigan blok (citations)
    const citationsSection = h('details', { className: 'pt-3 border-t border-border group', open: citations.length > 0 },
      h('summary', { className: 'cursor-pointer text-xs font-bold text-main flex items-center justify-between py-1 select-none' },
        h('span', { className: 'flex items-center gap-2' },
          h('span', {}, 'Qidiruvda topilgan qonuniy asoslar:'),
          Badge({ label: `${citations.length} ta norma`, variant: citations.length > 0 ? 'neutral' : 'neutral' })
        ),
        icons.chevronDown('icon-xs text-muted transition-transform group-open:rotate-180')
      )
    );

    if (citations.length === 0) {
      citationsSection.appendChild(
        h('p', { className: 'text-2xs text-muted italic mt-2' }, 'Ushbu javob uchun alohida norma havolalari topilmadi.')
      );
    } else {
      const citationsList = h('div', { className: 'space-y-2 mt-3' });
      citations.forEach((c, idx) => {
        const sourceUrl = c.source_url && c.source_url.startsWith('https://') ? c.source_url : 'https://lex.uz/';
        const normNum = c.article_number || `Norma #${idx + 1}`;
        const lawTitle = c.law_title || c.law_number || '';

        const itemCard = h('div', { className: 'p-3 rounded-md bg-surface-2 border border-border space-y-1.5 text-2xs' },
          h('div', { className: 'flex items-start justify-between gap-2' },
            h('div', { className: 'flex items-center gap-2' },
              h('span', { className: 'font-mono font-bold text-accent' }, normNum),
              lawTitle ? h('span', { className: 'font-semibold text-main truncate max-w-xs' }, lawTitle) : null
            ),
            h('a', {
              href: sourceUrl,
              target: '_blank',
              rel: 'noopener noreferrer',
              className: 'text-accent hover:underline flex items-center gap-1 shrink-0'
            }, h('span', {}, 'Lex.uz'), icons.externalLink('icon-xs'))
          ),
          c.quote_snippet ? h('blockquote', { className: 'italic text-muted border-l-2 border-accent pl-2' }, `«${c.quote_snippet}»`) : null
        );
        citationsList.appendChild(itemCard);
      });
      citationsSection.appendChild(citationsList);
    }

    card.appendChild(resultHeader);
    if (warningsBox) card.appendChild(warningsBox);
    card.appendChild(answerContainer);
    card.appendChild(citationsSection);

    resultContainer.appendChild(card);
  }

  return container;
}
