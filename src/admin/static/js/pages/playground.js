/**
 * Sinov zali (Playground) Page — Inclusive Legal RAG
 * Real-time legal analysis query execution with safe markdown rendering,
 * grounded citation inspection, and direct Lex.uz source verification.
 */
import { h, clear } from '../dom.js';
import { icons } from '../icons.js';
import { api } from '../api.js';
import { Badge } from '../../components/Badge.js';
import { Button } from '../../components/Button.js';
import { EmptyState } from '../../components/EmptyState.js';
import { showToast } from '../../components/Toast.js';
import { parseMarkdown } from '../markdown.js';

export function renderPlaygroundPage() {
  const container = h('div', { className: 'space-y-6' });

  // State
  let isQuerying = false;
  let lastResult = null;

  // 1. Header Card
  const header = h('div', { className: 'card-surface p-5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4' },
    h('div', { className: 'space-y-1' },
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Huquqiy tahlil va sinov (Playground)'),
        Badge({ label: 'Real-vaqt tahlili', variant: 'neutral' })
      ),
      h('p', { className: 'text-xs text-muted' },
        'Qonunchilik normalari bo‘yicha sun‘iy intellekt xulosasini real vaqtda sinovdan o‘tkazing.'
      )
    ),
    h('div', { className: 'flex items-center gap-2 font-mono text-2xs text-muted' },
      h('span', { className: 'px-2 py-0.5 rounded bg-surface-2 border border-border text-main' }, 'POST /api/v1/inclusive/query'),
      Badge({ label: 'v1.0', variant: 'info' })
    )
  );

  // 2. Main Grid Layout
  const grid = h('div', { className: 'grid grid-cols-1 lg:grid-cols-12 gap-6' });

  // --- Left Column: Controls (5 cols) ---
  const leftCol = h('div', { className: 'lg:col-span-5 space-y-4' });
  const formCard = h('div', { className: 'card-surface p-5 space-y-4' });

  // Disability Group
  const groupSelect = h('select', { className: 'select-dropdown' },
    h('option', { value: 'all' }, 'Barcha toifalar (Avtomatik aniqlash)'),
    h('option', { value: 'group_1' }, 'I guruh nogironligi bo‘lgan shaxslar'),
    h('option', { value: 'group_2' }, 'II guruh nogironligi bo‘lgan shaxslar'),
    h('option', { value: 'group_3' }, 'III guruh nogironligi bo‘lgan shaxslar'),
    h('option', { value: 'childhood_disability' }, '18 yoshgacha bo‘lgan nogironligi bo‘lgan bolalar'),
    h('option', { value: 'physical' }, 'Tayanch-harakat a‘zolari shikastlangan shaxslar'),
    h('option', { value: 'visual' }, 'Ko‘rish bo‘yicha nogironligi bo‘lgan shaxslar'),
    h('option', { value: 'hearing' }, 'Eshitish bo‘yicha nogironligi bo‘lgan shaxslar')
  );

  const groupField = h('div', { className: 'space-y-1-5' },
    h('label', { className: 'block text-xs font-semibold text-main' }, 'Nogironlik toifasi'),
    groupSelect
  );

  // Domain Category
  const categorySelect = h('select', { className: 'select-dropdown' },
    h('option', { value: 'all' }, 'Barcha sohalar'),
    h('option', { value: 'disability_rights' }, 'Nogironlik huquqlari (O‘RQ-641)'),
    h('option', { value: 'pensions_and_benefits' }, 'Nafaqalar va pensiyalar'),
    h('option', { value: 'labor_rights' }, 'Mehnat huquqlari va kvotalar'),
    h('option', { value: 'medical_social_expertise' }, 'Tibbiy-ijtimoiy ekspertiza (TMEK)'),
    h('option', { value: 'tax_benefits' }, 'Soliq imtiyozlari'),
    h('option', { value: 'rehabilitation_prosthetics' }, 'Protez-ortopediya va reabilitatsiya'),
    h('option', { value: 'sanatorium_health' }, 'Sanatoriy-kurortda davolanish'),
    h('option', { value: 'inclusive_education' }, 'Inklyuziv ta‘lim va grantlar'),
    h('option', { value: 'accessibility_infrastructure' }, 'To‘siqsiz shaharsozlik')
  );

  const categoryField = h('div', { className: 'space-y-1-5' },
    h('label', { className: 'block text-xs font-semibold text-main' }, 'Huquqiy soha'),
    categorySelect
  );

  // Language & Mode Grid
  const langSelect = h('select', { className: 'select-dropdown' },
    h('option', { value: 'auto' }, 'Avtomatik'),
    h('option', { value: 'uz' }, 'O‘zbekcha'),
    h('option', { value: 'ru' }, 'Русский'),
    h('option', { value: 'en' }, 'English')
  );

  const modeSelect = h('select', { className: 'select-dropdown' },
    h('option', { value: 'plain' }, 'Tushunarli oddiy tilda'),
    h('option', { value: 'legal_text' }, 'Rasmiy huquqiy tilda')
  );

  const langModeGrid = h('div', { className: 'grid grid-cols-2 gap-3' },
    h('div', { className: 'space-y-1-5' },
      h('label', { className: 'block text-xs font-semibold text-main' }, 'Til'),
      langSelect
    ),
    h('div', { className: 'space-y-1-5' },
      h('label', { className: 'block text-xs font-semibold text-main' }, 'Uslub'),
      modeSelect
    )
  );

  // Question Textarea
  const questionInput = h('textarea', {
    rows: 4,
    className: 'textarea-field',
    placeholder: 'Masalan: I va II guruh nogironligi bo‘lgan xodimlarga haftalik ish vaqti va ta‘tillar qanday belgilanadi?'
  });

  const questionField = h('div', { className: 'space-y-1-5' },
    h('label', { className: 'block text-xs font-semibold text-main' }, 'Savol matni'),
    questionInput
  );

  // Sample Prompts
  const SAMPLE_PROMPTS = [
    {
      label: 'Mehnat va ish vaqti',
      prompt: "I va II guruh nogironlariga haftalik ish vaqti va yillik ta'til necha kun belgilanadi?",
      category: 'labor_rights',
      group: 'group_1'
    },
    {
      label: 'TMEK muddatsiz nogironlik',
      prompt: "Muddatsiz nogironlik qanday mezonlar asosida belgilanadi va TMEK xulosasidan qanday shikoyat qilinadi?",
      category: 'medical_social_expertise',
      group: 'all'
    },
    {
      label: 'Soliq imtiyozlari',
      prompt: "I va II guruh nogironlari daromad va mol-mulk solig'idan qanday tartibda ozod qilinadi?",
      category: 'tax_benefits',
      group: 'group_2'
    },
    {
      label: 'Protez va aravacha',
      prompt: "Nogironlar aravachasi va protez-ortopediya buyumlari necha yilda bir marta bepul almashtiriladi?",
      category: 'rehabilitation_prosthetics',
      group: 'physical'
    },
    {
      label: 'OTM 2% grant kvotasi',
      prompt: "Nogironligi bo'lgan abituriyentlar uchun OTMlarga qabulda qanday davlat granti kvotasi ajratilgan?",
      category: 'inclusive_education',
      group: 'childhood_disability'
    },
    {
      label: 'Sanatoriy yo‘llanmasi',
      prompt: "I guruh nogironini sanatoriyga kuzatib boruvchi shaxsga yo'llanma bepul beriladimi?",
      category: 'sanatorium_health',
      group: 'group_1'
    }
  ];

  const pillsContainer = h('div', { className: 'flex flex-wrap gap-1-5' });
  SAMPLE_PROMPTS.forEach(sample => {
    const pill = h('button', {
      type: 'button',
      className: 'prompt-pill',
      onclick: () => {
        questionInput.value = sample.prompt;
        categorySelect.value = sample.category;
        groupSelect.value = sample.group;
        questionInput.focus();
      },
      onkeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          questionInput.value = sample.prompt;
          categorySelect.value = sample.category;
          groupSelect.value = sample.group;
          questionInput.focus();
        }
      }
    }, sample.label);
    pillsContainer.appendChild(pill);
  });

  const samplesSection = h('div', { className: 'space-y-1-5' },
    h('span', { className: 'text-2xs font-medium text-muted block' }, 'Namuna savollar:'),
    pillsContainer
  );

  // Submit Button
  const submitBtn = Button({
    text: 'Huquqiy javob olish',
    icon: icons.send('icon-sm'),
    variant: 'primary',
    className: 'w-full justify-center py-2.5',
    onClick: handleExecuteQuery
  });

  formCard.appendChild(groupField);
  formCard.appendChild(categoryField);
  formCard.appendChild(langModeGrid);
  formCard.appendChild(questionField);
  formCard.appendChild(samplesSection);
  formCard.appendChild(submitBtn);

  leftCol.appendChild(formCard);

  // --- Right Column: Results (7 cols) ---
  const rightCol = h('div', { className: 'lg:col-span-7 space-y-4' });
  const resultContainer = h('div', {});

  rightCol.appendChild(resultContainer);

  grid.appendChild(leftCol);
  grid.appendChild(rightCol);

  container.appendChild(header);
  container.appendChild(grid);

  // Initial Empty State
  renderEmptyState();

  // ==========================================
  // VIEW RENDERERS
  // ==========================================

  function renderEmptyState() {
    clear(resultContainer);
    resultContainer.appendChild(
      EmptyState({
        icon: icons.chat('icon-lg text-muted'),
        title: 'Savol kiritilmadi',
        description: 'Chap tomondagi maydonga savol yozing yoki namuna savollardan birini tanlang.'
      })
    );
  }

  function renderLoadingState() {
    clear(resultContainer);
    const skeleton = h('div', { className: 'card-surface p-5 space-y-4', 'aria-live': 'polite' },
      h('div', { className: 'flex items-center justify-between pb-3 border-b border-border' },
        h('div', { className: 'h-4 w-32 skeleton rounded' }),
        h('div', { className: 'h-4 w-16 skeleton rounded' })
      ),
      h('div', { className: 'space-y-2 py-2' },
        h('div', { className: 'h-3.5 w-full skeleton rounded' }),
        h('div', { className: 'h-3.5 w-5/6 skeleton rounded' }),
        h('div', { className: 'h-3.5 w-4/6 skeleton rounded' })
      ),
      h('div', { className: 'pt-4 border-t border-border space-y-3' },
        h('div', { className: 'h-3.5 w-28 skeleton rounded' }),
        h('div', { className: 'h-16 w-full skeleton rounded-lg' }),
        h('div', { className: 'h-16 w-full skeleton rounded-lg' })
      )
    );
    resultContainer.appendChild(skeleton);
  }

  function renderErrorState(errorMessage) {
    clear(resultContainer);
    const errCard = h('div', { className: 'card-surface p-5 border-danger space-y-3' },
      h('div', { className: 'flex items-center gap-2 text-danger font-semibold text-xs' },
        icons.close('icon-sm text-danger'),
        h('span', {}, 'Xatolik yuz berdi')
      ),
      h('p', { className: 'text-xs text-muted leading-relaxed' }, errorMessage),
      Button({
        text: 'Qayta urinish',
        icon: icons.refresh('icon-sm'),
        variant: 'secondary',
        size: 'sm',
        onClick: handleExecuteQuery
      })
    );
    resultContainer.appendChild(errCard);
  }

  function renderResult(data) {
    lastResult = data;
    clear(resultContainer);

    const citations = data.citations || [];
    const citationMap = {};
    citations.forEach((c, idx) => {
      const num = c.index || (idx + 1);
      citationMap[c.canonical_id] = c;
      citationMap[String(num)] = c;
    });

    const card = h('div', { className: 'card-surface p-5 space-y-4' });

    // 1. Result Header
    const latencyVal = data.response_time_ms ? Number(data.response_time_ms) : 120;
    const latencyText = latencyVal >= 1000 ? `${(latencyVal / 1000).toFixed(1)} s` : `${Math.round(latencyVal)} ms`;
    const latencyBadge = h('span', { className: 'text-2xs font-mono text-muted bg-surface-2 px-2 py-0.5 rounded border border-border tabular-nums' }, latencyText);

    const copyBtn = Button({
      text: 'Nusxalash',
      icon: icons.copy('icon-sm'),
      variant: 'secondary',
      size: 'sm',
      onClick: () => {
        const textToCopy = data.telegram_formatted || data.clean_answer || data.answer || '';
        if (!textToCopy) return;

        navigator.clipboard.writeText(textToCopy).then(() => {
          showToast('Javob matni clipboardga nusxalandi', 'success');
        }).catch(() => {
          showToast('Nusxalashda xatolik yuz berdi', 'danger');
        });
      }
    });

    const resultHeader = h('div', { className: 'flex items-center justify-between pb-3 border-b border-border' },
      h('div', { className: 'flex items-center gap-2' },
        h('span', { className: 'w-2 h-2 rounded-full bg-accent', 'aria-hidden': 'true' }),
        h('h3', { className: 'text-xs font-bold text-main' }, 'Huquqiy xulosa va tushuntirish')
      ),
      h('div', { className: 'flex items-center gap-2' },
        latencyBadge,
        copyBtn
      )
    );

    // 2. Answer Body (Safe Markdown Parser)
    const rawAnswer = data.clean_answer || data.answer || '';
    const answerFragment = parseMarkdown(rawAnswer, citationMap);
    const answerContainer = h('div', { className: 'py-1' }, answerFragment);

    // 3. Citations Section
    const citationsSection = h('div', { className: 'pt-4 border-t border-border space-y-3' });
    const countBadge = Badge({
      text: `${citations.length} ta norma`,
      variant: citations.length > 0 ? 'info' : 'neutral'
    });

    const citationsHeader = h('div', { className: 'flex items-center justify-between' },
      h('h4', { className: 'text-xs font-bold text-main flex items-center gap-2' },
        h('span', {}, 'Asoslangan normalar:'),
        countBadge
      )
    );

    citationsSection.appendChild(citationsHeader);

    if (citations.length === 0) {
      citationsSection.appendChild(
        h('p', { className: 'text-2xs text-muted italic' }, 'Ushbu savol uchun alohida norma havolasi keltirilmadi.')
      );
    } else {
      const citationsList = h('div', { className: 'space-y-2-5' });
      citations.forEach(c => {
        citationsList.appendChild(renderCitationCard(c));
      });
      citationsSection.appendChild(citationsList);
    }

    card.appendChild(resultHeader);
    card.appendChild(answerContainer);
    card.appendChild(citationsSection);

    resultContainer.appendChild(card);
  }

  function renderCitationCard(c) {
    const card = h('div', { className: 'citation-card space-y-2' });

    // Top Row: Index Badge, Title & Lex.uz Link
    const topRow = h('div', { className: 'flex items-start justify-between gap-3' },
      h('div', { className: 'flex items-center gap-2 min-w-0' },
        h('span', { className: 'w-5 h-5 rounded-full bg-accent text-white flex items-center justify-center font-mono text-2xs font-semibold shrink-0 tabular-nums' }, String(c.index || 1)),
        h('span', { className: 'font-semibold text-main text-xs truncate' },
          `${c.article_number || 'Modda'} — ${c.law_title || c.law_number || ''}`
        )
      ),
      c.source_url ? h('a', {
        href: c.source_url,
        target: '_blank',
        rel: 'noopener noreferrer',
        className: 'inline-flex items-center gap-1 text-accent hover:underline text-2xs font-medium shrink-0'
      },
        h('span', {}, 'Lex.uz'),
        icons.externalLink('icon-xs')
      ) : null
    );

    card.appendChild(topRow);

    // Article Title if available
    if (c.article_title) {
      card.appendChild(h('div', { className: 'text-2xs font-medium text-main' }, c.article_title));
    }

    // Quote Snippet if available
    if (c.quote_snippet) {
      const quote = h('blockquote', { className: 'citation-quote' }, `«${c.quote_snippet}»`);
      card.appendChild(quote);
    }

    // Bottom Badges: Normative Tier
    if (c.normative_tier) {
      const bottomRow = h('div', { className: 'flex items-center gap-2 pt-1' },
        Badge({ text: c.normative_tier, variant: 'neutral' })
      );
      card.appendChild(bottomRow);
    }

    return card;
  }

  // ==========================================
  // ACTION HANDLERS
  // ==========================================

  async function handleExecuteQuery() {
    const question = questionInput.value.trim();
    if (!question) {
      showToast('Iltimos, avval savol matnini kiriting', 'danger');
      questionInput.focus();
      return;
    }

    if (isQuerying) return;
    isQuerying = true;

    // Update submit button state
    submitBtn.disabled = true;
    submitBtn.innerHTML = '';
    submitBtn.appendChild(icons.refresh('icon-sm animate-spin mr-1-5'));
    submitBtn.appendChild(h('span', {}, 'Tahlil qilinmoqda...'));

    renderLoadingState();

    try {
      const payload = {
        question,
        disability_group: groupSelect.value,
        category: categorySelect.value,
        language: langSelect.value,
        mode: modeSelect.value
      };

      const res = await api.sendQuery(payload);
      renderResult(res);
    } catch (err) {
      renderErrorState(err.message || 'Server bilan bog‘lanishda xatolik yuz berdi');
      showToast('So‘rov bajarilmadi: ' + (err.message || 'Xatolik'), 'danger');
    } finally {
      isQuerying = false;
      submitBtn.disabled = false;
      submitBtn.innerHTML = '';
      submitBtn.appendChild(icons.send('icon-sm mr-1-5'));
      submitBtn.appendChild(h('span', {}, 'Huquqiy javob olish'));
    }
  }

  return container;
}
