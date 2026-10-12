/**
 * Vektorlash va AI Tahlil Inspektori (Vectorizer / Inspector) Page — Inclusive Legal RAG
 * Features:
 * - Live Lex.uz document ingestion & inspection
 * - Raw-source vs BGE-M3 payload side-by-side comparison view
 * - Visible elapsed timer & retry affordance for slow scrapes (5-15s)
 * - Live BGE-M3 vector calculation test & TypeSafe Jev 1.13 legal classifier
 * - Segmented filtering for Tables vs Legal Clauses
 */
import { h, clear } from '../dom.js';
import { icons } from '../icons.js';
import { api } from '../api.js';
import { Badge } from '../../components/Badge.js';
import { Button } from '../../components/Button.js';
import { SegmentedControl } from '../../components/Tabs.js';
import { showToast } from '../../components/Toast.js';

export function renderVectorizerPage() {
  const container = h('div', { className: 'space-y-6' });

  // State
  let currentReport = null;
  let currentFilter = 'all';
  let isLoading = false;
  let timerInterval = null;
  let abortController = null;

  // 1. Header Banner
  const header = h('div', { className: 'card-surface p-5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4' },
    h('div', { className: 'space-y-1' },
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Vektorlash va AI tahlil inspektori'),
        Badge({ label: 'Ingestion Pipeline', variant: 'neutral' })
      ),
      h('p', { className: 'text-xs text-muted' },
        'Lex.uz hujjatlari va murakkab jadvallarining neyron modeliga tayyorlanish jarayoni.'
      )
    ),
    h('div', { className: 'flex items-center gap-2' },
      Badge({ label: 'BGE-M3 1024-dim', variant: 'neutral', className: 'font-mono' }),
      Badge({ label: 'Markdown + Semantika', variant: 'info' })
    )
  );

  // 2. URL Input & Presets Card
  const urlInput = h('input', {
    type: 'url',
    className: 'input-text font-mono text-xs flex-1',
    value: 'https://lex.uz/uz/docs/-8400823',
    placeholder: 'https://lex.uz/uz/docs/-...'
  });

  const inspectBtn = Button({
    text: 'Tahlil qilish',
    icon: icons.search('icon-sm'),
    variant: 'primary',
    className: 'shrink-0',
    onClick: () => runInspection()
  });

  const PRESETS = [
    { label: 'VMQ-440 (Transport va jadvallar)', url: 'https://lex.uz/uz/docs/-8400823' },
    { label: "O'RQ-641 (Nogironlar huquqlari)", url: 'https://lex.uz/uz/docs/-5049511' },
    { label: 'Mehnat kodeksi', url: 'https://lex.uz/docs/6257288' }
  ];

  const presetsContainer = h('div', { className: 'flex items-center gap-2 flex-wrap pt-1' },
    h('span', { className: 'text-2xs font-medium text-muted' }, 'Namunalar:')
  );

  PRESETS.forEach(p => {
    const pill = h('button', {
      type: 'button',
      className: 'prompt-pill',
      onclick: () => {
        urlInput.value = p.url;
        runInspection();
      },
      onkeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          urlInput.value = p.url;
          runInspection();
        }
      }
    }, p.label);
    presetsContainer.appendChild(pill);
  });

  const inputCard = h('div', { className: 'card-surface p-5 space-y-3' },
    h('label', { className: 'block text-xs font-semibold text-main' }, 'Lex.uz havolasi (URL)'),
    h('div', { className: 'flex items-center gap-2 flex-col sm:flex-row' },
      urlInput,
      inspectBtn
    ),
    presetsContainer
  );

  // Dynamic View Container (Pre-state, Loading, Error, or Results)
  const viewContainer = h('div', { className: 'space-y-6' });

  container.appendChild(header);
  container.appendChild(inputCard);
  container.appendChild(viewContainer);

  // Initial Pre-inspection State
  renderPreState();

  // ==========================================
  // VIEW RENDERERS
  // ==========================================

  function renderPreState() {
    clear(viewContainer);
    const preCard = h('div', { className: 'card-surface p-8 text-center space-y-3 border border-border' },
      h('div', { className: 'w-12 h-12 mx-auto rounded-full bg-surface-2 text-accent flex items-center justify-center' },
        icons.cpu('icon-md')
      ),
      h('h3', { className: 'text-xs font-bold text-main' }, 'Qayta ishlash konveyeri tayyor'),
      h('p', { className: 'text-xs text-muted max-w-md mx-auto leading-relaxed' },
        'Yuqoridagi Lex.uz havolasini kiritib «Tahlil qilish» tugmasini bosing. Dastur matn va murakkab jadvallarni ajratib, ularning AI modeliga yuborilish ko‘rinishini taqdim etadi.'
      )
    );
    viewContainer.appendChild(preCard);
  }

  function renderLoadingState() {
    clear(viewContainer);

    let seconds = 0;
    const timerLabel = h('span', { className: 'font-mono tabular-nums' }, '0s');
    const statusText = h('p', { className: 'text-xs font-medium text-main' }, 'Lex.uz sahifasi yuklanmoqda va qismlarga ajratilmoqda...');

    const cancelBtn = Button({
      text: 'Bekor qilish',
      icon: icons.close('icon-xs'),
      variant: 'secondary',
      size: 'sm',
      onClick: () => {
        if (abortController) {
          abortController.abort();
        }
        clearInterval(timerInterval);
        isLoading = false;
        inspectBtn.disabled = false;
        renderPreState();
      }
    });

    const loadingCard = h('div', { className: 'card-surface p-8 text-center space-y-3', 'aria-live': 'polite' },
      h('div', { className: 'w-8 h-8 mx-auto border-2 border-accent border-t-transparent rounded-full animate-spin' }),
      statusText,
      h('div', { className: 'flex items-center justify-center gap-2 text-2xs text-muted font-mono' },
        h('span', {}, 'O‘tgan vaqt:'),
        timerLabel,
        h('span', {}, '• BGE-M3 Ingestion Pipeline')
      ),
      h('div', { className: 'pt-2' }, cancelBtn)
    );

    viewContainer.appendChild(loadingCard);

    timerInterval = setInterval(() => {
      seconds++;
      timerLabel.textContent = `${seconds}s`;

      if (seconds >= 5 && seconds < 15) {
        statusText.textContent = 'Lex.uz portali javobi kutilmoqda (odatda 5-15 soniya davom etadi)...';
      } else if (seconds >= 15) {
        statusText.textContent = 'Hujjat hajmi katta bo‘lganligi sababli chuqur semantik tahlil davom etmoqda...';
      }
    }, 1000);
  }

  function renderErrorState(errorMessage) {
    clear(viewContainer);
    const errCard = h('div', { className: 'card-surface p-6 border-danger space-y-3' },
      h('div', { className: 'flex items-center gap-2 text-danger font-semibold text-xs' },
        icons.close('icon-sm text-danger'),
        h('span', {}, 'Hujjatni tahlil qilishda xatolik yuz berdi')
      ),
      h('p', { className: 'text-xs text-muted leading-relaxed' }, errorMessage),
      h('div', { className: 'pt-1 flex items-center gap-2' },
        Button({
          text: 'Qayta urinish',
          icon: icons.refresh('icon-sm'),
          variant: 'primary',
          size: 'sm',
          onClick: () => runInspection()
        }),
        Button({
          text: 'Bekor qilish',
          variant: 'secondary',
          size: 'sm',
          onClick: () => renderPreState()
        })
      )
    );
    viewContainer.appendChild(errCard);
  }

  function renderResults(report) {
    currentReport = report;
    clear(viewContainer);

    // 1. Summary Metrics Grid
    const metricsGrid = h('div', { className: 'grid grid-cols-2 md:grid-cols-4 gap-3' },
      h('div', { className: 'card-surface p-4 space-y-1' },
        h('span', { className: 'text-2xs font-medium text-muted block' }, 'Hujjat'),
        h('p', { className: 'text-sm font-bold text-main font-mono truncate' }, report.law_number || '-'),
        h('span', { className: 'text-2xs text-muted truncate block' }, report.law_title || '')
      ),
      h('div', { className: 'card-surface p-4 space-y-1' },
        h('span', { className: 'text-2xs font-medium text-muted block' }, 'Ajratilgan bo‘laklar'),
        h('p', { className: 'text-xl font-bold text-accent tabular-nums' }, `${report.total_units || 0} ta`),
        Badge({ label: 'AI formatga tayyor', variant: 'success' })
      ),
      h('div', { className: 'card-surface p-4 space-y-1' },
        h('span', { className: 'text-2xs font-medium text-muted block' }, 'Jadvallar'),
        h('p', { className: 'text-xl font-bold text-main tabular-nums' }, `${report.tables_count || 0} ta`),
        h('span', { className: 'text-2xs text-muted block' }, 'Markdown + Semantika')
      ),
      h('div', { className: 'card-surface p-4 space-y-1' },
        h('span', { className: 'text-2xs font-medium text-muted block' }, 'Modda va bandlar'),
        h('p', { className: 'text-xl font-bold text-main tabular-nums' }, `${report.clauses_count || 0} ta`),
        h('span', { className: 'text-2xs text-muted block' }, 'Normativ qoidalar')
      )
    );

    // 2. Filter Bar
    const segmented = SegmentedControl({
      items: [
        { id: 'all', label: 'Barchasi', count: report.total_units || 0 },
        { id: 'tables', label: 'Jadvallar', count: report.tables_count || 0 },
        { id: 'clauses', label: 'Modda va bandlar', count: report.clauses_count || 0 }
      ],
      activeId: currentFilter,
      onChange: (newFilter) => {
        currentFilter = newFilter;
        renderUnitsList();
      }
    });

    const filterRow = h('div', { className: 'flex items-center justify-between border-b border-border pb-3 flex-wrap gap-2' },
      segmented.element,
      h('span', { className: 'text-2xs text-muted font-mono' }, 'BGE-M3 Ingestion Pipeline')
    );

    // 3. Units Container
    const unitsContainer = h('div', { className: 'space-y-4' });

    viewContainer.appendChild(metricsGrid);
    viewContainer.appendChild(filterRow);
    viewContainer.appendChild(unitsContainer);

    renderUnitsList();

    function renderUnitsList() {
      clear(unitsContainer);

      let units = report.units || [];
      if (currentFilter === 'tables') {
        units = units.filter(u => u.is_table);
      } else if (currentFilter === 'clauses') {
        units = units.filter(u => !u.is_table);
      }

      if (units.length === 0) {
        unitsContainer.appendChild(
          h('div', { className: 'card-surface p-8 text-center text-muted text-xs' },
            'Ushbu filtr bo‘yicha bo‘laklar topilmadi.'
          )
        );
        return;
      }

      units.forEach(u => {
        unitsContainer.appendChild(renderUnitCard(u, report.law_number));
      });
    }
  }

  // ==========================================
  // UNIT CARD (SIDE-BY-SIDE COMPARISON VIEW)
  // ==========================================

  function renderUnitCard(unit, lawNumber) {
    const card = h('div', { className: 'card-surface overflow-hidden border border-border shadow-xs space-y-0' });

    // Output containers for inline Vector / Jev test results
    const vectorOutputContainer = h('div', { className: 'hidden mx-5 mb-4 p-3 bg-surface-2 border border-border rounded-lg text-xs space-y-1' });
    const jevOutputContainer = h('div', { className: 'hidden mx-5 mb-3 p-3 bg-surface-2 border border-border rounded-lg text-xs space-y-1-5' });

    // Top Header
    const isTbl = unit.is_table;
    const typeBadge = isTbl
      ? Badge({ text: 'Jadval', variant: 'neutral' })
      : Badge({ text: 'Huquqiy norma', variant: 'info' });

    const testVectorBtn = Button({
      text: 'Vektorini hisoblash',
      icon: icons.cpu('icon-xs'),
      variant: 'secondary',
      size: 'sm',
      onClick: async () => {
        testVectorBtn.disabled = true;
        testVectorBtn.textContent = 'Hisoblanmoqda...';
        try {
          const res = await api.testVector({ text: unit.exact_bge_prompt });
          vectorOutputContainer.classList.remove('hidden');
          clear(vectorOutputContainer);
          vectorOutputContainer.appendChild(
            h('div', { className: 'space-y-1' },
              h('div', { className: 'flex items-center justify-between text-2xs font-semibold text-main' },
                h('span', {}, `BGE-M3 Vektor natijasi (${res.dimensions}-o‘lcham, L2 norm: ${res.norm})`),
                h('span', { className: 'font-mono text-muted tabular-nums' }, `${res.duration_ms} ms`)
              ),
              h('div', { className: 'font-mono text-2xs text-muted truncate select-all bg-surface p-1.5 rounded border border-border' },
                `[${(res.sample_coordinates || []).join(', ')} ...]`
              )
            )
          );
          showToast("Vektor muvaffaqiyatli hisoblandi", 'success');
        } catch (err) {
          showToast("Vektor hisoblashda xatolik: " + err.message, 'danger');
        } finally {
          testVectorBtn.disabled = false;
          testVectorBtn.innerHTML = '';
          testVectorBtn.appendChild(icons.cpu('icon-xs mr-1'));
          testVectorBtn.appendChild(h('span', {}, 'Vektorini hisoblash'));
        }
      }
    });

    const testJevBtn = Button({
      text: 'Jev 1.13 tahlili',
      icon: icons.scales('icon-xs'),
      variant: 'secondary',
      size: 'sm',
      onClick: async () => {
        testJevBtn.disabled = true;
        testJevBtn.textContent = 'Tahlil qilinmoqda...';
        try {
          const res = await api.testJev({
            text: unit.raw_source_preview,
            law_title: lawNumber || ''
          });
          jevOutputContainer.classList.remove('hidden');
          clear(jevOutputContainer);
          jevOutputContainer.appendChild(
            h('div', { className: 'space-y-1' },
              h('div', { className: 'flex items-center justify-between text-2xs font-semibold text-main' },
                h('span', {}, 'TypeSafe Jev 1.13 Tahlili'),
                Badge({ label: res.category || 'Huquqiy norma', variant: 'neutral' })
              ),
              h('div', { className: 'text-2xs text-muted' },
                `Qaror: ${res.action || 'Qabul qilingan'} • Ishonch darajasi: ${Math.round((res.confidence || 0.85) * 100)}%`
              )
            )
          );
          showToast("Jev tahlili yakunlandi", 'success');
        } catch (err) {
          showToast("Jev tahlilida xatolik: " + err.message, 'danger');
        } finally {
          testJevBtn.disabled = false;
          testJevBtn.innerHTML = '';
          testJevBtn.appendChild(icons.scales('icon-xs mr-1'));
          testJevBtn.appendChild(h('span', {}, 'Jev 1.13 tahlili'));
        }
      }
    });

    const topHeader = h('div', { className: 'px-5 py-3 border-b border-border bg-surface-2 flex flex-wrap items-center justify-between gap-2' },
      h('div', { className: 'flex items-center gap-2 min-w-0' },
        typeBadge,
        h('span', { className: 'text-xs font-bold text-main truncate' }, `№ ${unit.order}. ${unit.title || ''}`)
      ),
      h('div', { className: 'flex items-center gap-2 flex-wrap' },
        h('span', { className: 'text-2xs text-muted font-mono tabular-nums' }, `~${unit.approx_tokens || 0} ta so‘z`),
        testJevBtn,
        testVectorBtn
      )
    );

    // 2-Column Comparison Body
    // Left: Raw Source Preview (Asl Lex.uz ko'rinishi)
    const rawPreviewBox = h('div', { className: 'source-preview' });
    if (isTbl && unit.html_table) {
      rawPreviewBox.innerHTML = unit.html_table;
    } else {
      const p = h('p', { className: 'whitespace-pre-line' }, unit.raw_source_preview || '-');
      rawPreviewBox.appendChild(p);
    }

    const leftCol = h('div', { className: 'space-y-2' },
      h('div', { className: 'flex items-center justify-between' },
        h('span', { className: 'text-2xs font-semibold text-muted uppercase tracking-wide' }, '1. Asl Lex.uz ko‘rinishi'),
        h('span', { className: 'text-2xs text-muted font-mono' }, isTbl ? 'HTML Jadval' : 'Manba matni')
      ),
      rawPreviewBox
    );

    // Right: BGE-M3 Formatted AI Text (Payload)
    const copyPayloadBtn = Button({
      text: 'Nusxa olish',
      icon: icons.copy('icon-xs'),
      variant: 'secondary',
      size: 'sm',
      onClick: () => {
        navigator.clipboard.writeText(unit.exact_bge_prompt || '').then(() => {
          showToast('BGE-M3 matni clipboardga nusxalandi', 'success');
        });
      }
    });

    const bgePre = h('div', {
      className: 'p-3-5 bg-slate-900 rounded-lg border border-slate-800 text-2xs text-emerald-400 font-mono leading-relaxed whitespace-pre-wrap max-h-80 overflow-y-auto'
    }, unit.exact_bge_prompt || '-');

    const rightCol = h('div', { className: 'space-y-2' },
      h('div', { className: 'flex items-center justify-between' },
        h('span', { className: 'text-2xs font-semibold text-accent uppercase tracking-wide' }, '2. BGE-M3 formatlangan AI matni'),
        copyPayloadBtn
      ),
      bgePre
    );

    const comparisonGrid = h('div', { className: 'p-5 grid grid-cols-1 lg:grid-cols-2 gap-4' },
      leftCol,
      rightCol
    );

    // Footer Metadata
    const footerMeta = h('div', { className: 'px-5 py-2.5 bg-surface-2 border-t border-border flex items-center justify-between text-2xs text-muted flex-wrap gap-2' },
      h('div', { className: 'flex items-center gap-3 flex-wrap' },
        unit.doc_category_name ? h('span', {}, `Kategoriya: ${unit.doc_category_name}`) : null,
        unit.clause_topic_name ? h('span', {}, `Mavzu: ${unit.clause_topic_name}`) : null
      ),
      unit.disability_types && unit.disability_types.length > 0
        ? h('span', { className: 'font-mono' }, `Toifalar: ${unit.disability_types.join(', ')}`)
        : null
    );

    card.appendChild(topHeader);
    card.appendChild(comparisonGrid);
    card.appendChild(jevOutputContainer);
    card.appendChild(vectorOutputContainer);
    card.appendChild(footerMeta);

    return card;
  }

  // ==========================================
  // ACTION HANDLERS
  // ==========================================

  async function runInspection() {
    const url = urlInput.value.trim();
    if (!url) {
      showToast('Iltimos, avval Lex.uz havolasini kiriting', 'danger');
      urlInput.focus();
      return;
    }

    if (isLoading) return;
    isLoading = true;

    inspectBtn.disabled = true;
    inspectBtn.innerHTML = '';
    inspectBtn.appendChild(icons.refresh('icon-sm animate-spin mr-1-5'));
    inspectBtn.appendChild(h('span', {}, 'Tahlil qilinmoqda...'));

    renderLoadingState();

    try {
      abortController = new AbortController();
      const report = await api.inspectDocument({ url }, 45000);
      clearInterval(timerInterval);
      renderResults(report);
      showToast(`${report.law_number || 'Hujjat'} muvaffaqiyatli tahlil qilindi`, 'success');
    } catch (err) {
      clearInterval(timerInterval);
      renderErrorState(err.message || 'Hujjatni tahlil qilib bo‘lmadi');
      showToast('Tahlilda xatolik: ' + (err.message || 'Xatolik'), 'danger');
    } finally {
      clearInterval(timerInterval);
      isLoading = false;
      inspectBtn.disabled = false;
      inspectBtn.innerHTML = '';
      inspectBtn.appendChild(icons.search('icon-sm mr-1-5'));
      inspectBtn.appendChild(h('span', {}, 'Tahlil qilish'));
    }
  }

  return container;
}
