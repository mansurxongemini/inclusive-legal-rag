/**
 * Qonunlar Bazasi (documents.js) — Lex.uz qonunchilik aktlari va normalari
 * Faqat Lex.uz aktlari, tabiiy bandlar tartibi, o'qish uchun rejim, 3 qadamli yangi modal.
 * WCAG 2.2 AA talablariga mos, innerHTML ishlatilmagan (faqat h() va textContent).
 */
import { h, clear, mount } from '../dom.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import { Button } from '../../components/Button.js';
import { Badge } from '../../components/Badge.js';
import { EmptyState } from '../../components/EmptyState.js';
import { SkeletonCard } from '../../components/Skeleton.js';
import { createSlideOver } from '../../components/SlideOver.js';
import { createModal } from '../../components/Modal.js';
import { showToast } from '../../components/Toast.js';
import { categoryLabel as formatCategory } from '../labels.js';


// Tabiiy tartiblash funksiyasi:
// 1. Preambula
// 2. Asosiy matn (1, 2, ..., 5-1, 6, ...)
// 3. Ilovalar (1-ilova bandlari, 2-ilova bandlari...)
function naturalSortNorms(norms) {
  return [...norms].sort((a, b) => {
    const isPreambleA = a.kind === 'preamble' || (a.article_number || '').toLowerCase().includes('preambula');
    const isPreambleB = b.kind === 'preamble' || (b.article_number || '').toLowerCase().includes('preambula');
    if (isPreambleA && !isPreambleB) return -1;
    if (!isPreambleA && isPreambleB) return 1;
    if (isPreambleA && isPreambleB) return 0;

    const annexA = a.annex_number || null;
    const annexB = b.annex_number || null;
    if (!annexA && annexB) return -1;
    if (annexA && !annexB) return 1;

    if (annexA && annexB) {
      const numA = parseInt(annexA, 10) || 0;
      const numB = parseInt(annexB, 10) || 0;
      if (numA !== numB) return numA - numB;
    }

    function parseNum(str) {
      const clean = (str || '').replace(/[^\d\^-]/g, '');
      const match = clean.match(/^(\d+)(?:[\^-](\d+))?/);
      if (!match) return [999999, 0];
      return [parseInt(match[1], 10), match[2] ? parseInt(match[2], 10) : 0];
    }

    const [mainA, subA] = parseNum(a.article_number || a.canonical_id);
    const [mainB, subB] = parseNum(b.article_number || b.canonical_id);

    if (mainA !== mainB) return mainA - mainB;
    return subA - subB;
  });
}

export function renderDocumentsPage(params) {
  const container = h('div', { className: 'space-y-4' });

  const initialAddId = params ? (typeof params.get === 'function' ? params.get('add') : params.add) : null;

  let currentDocType = 'all';
  let searchQuery = '';
  let authorityFilter = 'all';
  let searchDebounceTimer = null;

  let slideOver = null;
  let addModal = null;

  // Sarlavhadagi hisoblagichlar ("Umumiy holat" bilan bir xil)
  const badgeTotalDocs = h('span', { className: 'badge badge-neutral tabular-nums font-semibold' }, '0 ta hujjat');
  const badgeTotalNorms = h('span', { className: 'badge badge-neutral tabular-nums font-semibold' }, '0 ta band');

  const header = h('div', { className: 'card-surface p-5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4' },
    h('div', {},
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Qonunlar bazasi'),
        badgeTotalDocs,
        badgeTotalNorms
      ),
      h('p', { className: 'text-xs text-muted mt-1' },
        'Lex.uz rasmiy portali orqali shakllantirilgan nogironlik qonunchiligi reestri va moddalari.'
      )
    ),
    h('div', { className: 'flex items-center gap-2' },
      Button({
        text: 'Lex.uz‘dan hujjat qo‘shish',
        icon: icons.plus('icon-sm'),
        variant: 'primary',
        onClick: () => openAddDocumentModal()
      })
    )
  );

  // Qidiruv va filtrlar
  const searchInput = h('input', {
    type: 'text',
    className: 'input-text pl-9',
    placeholder: 'Hujjat nomi yoki raqami (masalan: 641, O‘RQ-641)...',
    oninput: (e) => {
      clearTimeout(searchDebounceTimer);
      searchQuery = e.target.value.trim();
      searchDebounceTimer = setTimeout(loadDocuments, 300);
    }
  });

  const authoritySelect = h('select', {
    className: 'select-dropdown',
    onchange: (e) => {
      authorityFilter = e.target.value;
      loadDocuments();
    }
  },
    h('option', { value: 'all' }, 'Barcha davlat organlari'),
    h('option', { value: 'Oliy Majlis' }, 'Oliy Majlis'),
    h('option', { value: 'Prezident' }, 'O‘zbekiston Respublikasi Prezidenti'),
    h('option', { value: 'Vazirlar Mahkamasi' }, 'Vazirlar Mahkamasi'),
    h('option', { value: 'Ijtimoiy himoya' }, 'Ijtimoiy himoya milliy agentligi'),
    h('option', { value: 'Sog‘liqni saqlash' }, 'Sog‘liqni saqlash vazirligi'),
    h('option', { value: 'BMT' }, 'BMT (Xalqaro shartnoma)'),
    h('option', { value: 'Boshqa' }, 'Boshqa davlat organi')
  );

  const typeCountsMap = { all: 0, Qonun: 0, Farmon: 0, Qaror: 0, Buyruq: 0, Boshqa: 0 };
  const typePillsContainer = h('div', { className: 'flex items-center gap-1-5 flex-wrap pt-2 border-t border-border' });

  function renderTypePills() {
    clear(typePillsContainer);
    typePillsContainer.appendChild(h('span', { className: 'text-2xs text-muted font-medium mr-1' }, 'Hujjat turi:'));

    ['all', 'Qonun', 'Farmon', 'Qaror', 'Buyruq', 'Boshqa'].forEach(t => {
      const label = t === 'all' ? 'Barchasi' : `${t}lar`;
      const count = typeCountsMap[t] || 0;
      const isAct = currentDocType === t;
      const pill = h('button', {
        type: 'button',
        className: `btn btn-sm ${isAct ? 'btn-primary' : 'btn-secondary'} tabular-nums`,
        onclick: () => {
          currentDocType = t;
          renderTypePills();
          loadDocuments();
        }
      }, `${label} (${count})`);
      typePillsContainer.appendChild(pill);
    });
  }

  const filterCard = h('div', { className: 'card-surface p-4 space-y-3' },
    h('div', { className: 'flex flex-col lg:flex-row items-center gap-3' },
      h('div', { className: 'relative flex-1 min-w-0 w-full' },
        h('span', { className: 'absolute left-3 top-2-5 text-muted pointer-events-none' }, icons.search('icon-sm')),
        searchInput
      ),
      h('div', { className: 'w-full lg:w-64 flex-shrink-0' }, authoritySelect)
    ),
    typePillsContainer
  );

  const documentsGrid = h('div', { className: 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4' });

  container.appendChild(header);
  container.appendChild(filterCard);
  container.appendChild(documentsGrid);

  // Hujjatlarni yuklash
  async function loadDocuments() {
    clear(documentsGrid);
    for (let i = 0; i < 6; i++) {
      documentsGrid.appendChild(SkeletonCard({ rows: 2 }));
    }

    try {
      // Statistika bilan birga olamiz
      const [docData, statsData] = await Promise.all([
        api.fetchDocuments({
          doc_type: currentDocType,
          authority: authorityFilter,
          q: searchQuery
        }),
        api.getAdminStats().catch(() => null)
      ]);

      const docs = docData.documents || [];
      const counts = docData.type_counts || {};

      Object.assign(typeCountsMap, counts);
      renderTypePills();

      if (statsData) {
        badgeTotalDocs.textContent = `${statsData.lex_documents_count || docs.length} ta akt`;
        badgeTotalNorms.textContent = `${Number(statsData.lex_articles_count || 0).toLocaleString('uz-UZ')} ta band`;
      } else {
        badgeTotalDocs.textContent = `${docs.length} ta akt`;
      }

      clear(documentsGrid);

      if (docs.length === 0) {
        documentsGrid.appendChild(
          h('div', { className: 'col-span-full' },
            EmptyState({
              icon: icons.book('icon-lg text-muted'),
              title: 'Hujjatlar topilmadi',
              description: searchQuery
                ? 'Qidiruv bo‘yicha hech qanday Lex.uz hujjati topilmadi.'
                : 'Ushbu toifada hozircha hujjatlar mavjud emas.'
            })
          )
        );
        return;
      }

      docs.forEach(doc => {
        const docNumber = doc.law_number || doc.law_id || 'Nomaʼlum';
        const docTitle = doc.law_title || docNumber;
        const normCount = doc.norm_count || 0;
        const authority = doc.authority || 'Davlat organi';
        const docType = doc.doc_type || 'Qonun';
        const lexUrl = doc.source_url && doc.source_url.startsWith('https://') ? doc.source_url : 'https://lex.uz/';

        const card = h('div', {
          className: 'card-surface p-4 flex flex-col justify-between space-y-3 cursor-pointer hover:border-accent hover:shadow-xs transition-all',
          role: 'button',
          tabIndex: 0,
          'aria-label': `${docNumber} — ${docTitle}, moddalarni ochish`,
          onclick: () => openDocumentDetails(doc),
          onkeydown: (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              openDocumentDetails(doc);
            }
          }
        },
          h('div', { className: 'space-y-2' },
            h('div', { className: 'flex items-start justify-between gap-2' },
              h('span', { className: 'font-mono text-xs font-bold text-main truncate' }, docNumber),
              Badge({ label: docType, variant: 'neutral' })
            ),
            h('h3', { className: 'text-xs font-semibold text-main line-clamp-2 leading-relaxed' }, docTitle),
            h('p', { className: 'text-2xs text-muted' }, authority)
          ),
          h('div', { className: 'flex items-center justify-between pt-2 border-t border-border text-2xs' },
            h('span', { className: 'font-mono font-medium text-main tabular-nums' }, `${normCount} ta band`),
            h('a', {
              href: lexUrl,
              target: '_blank',
              rel: 'noopener noreferrer',
              className: 'text-muted hover:text-accent flex items-center gap-1',
              onclick: (e) => e.stopPropagation()
            },
              h('span', {}, 'Lex.uz'),
              icons.externalLink('icon-xs')
            )
          )
        );

        documentsGrid.appendChild(card);
      });

    } catch (err) {
      clear(documentsGrid);
      documentsGrid.appendChild(
        h('div', { className: 'col-span-full' },
          EmptyState({
            icon: icons.close('icon-lg text-danger'),
            title: 'Hujjatlarni yuklashda xatolik',
            description: err.message,
            action: Button({
              text: 'Qayta urinish',
              icon: icons.refresh('icon-sm'),
              onClick: loadDocuments
            })
          })
        )
      );
      showToast({ message: `Hujjatlarni yuklashda xatolik: ${err.message}`, type: 'error' });
    }
  }

  // Akt sahifasi (SlideOver)
  async function openDocumentDetails(doc) {
    if (slideOver) slideOver.close();

    const docNumber = doc.law_number || doc.law_id || 'Nomaʼlum';
    const docTitle = doc.law_title || docNumber;
    const lexId = doc.law_id || '';
    const lexUrl = doc.source_url && doc.source_url.startsWith('https://') ? doc.source_url : 'https://lex.uz/';

    const contentEl = h('div', { className: 'space-y-4' });
    const normsListEl = h('div', { className: 'space-y-3' });

    let isRefreshing = false;
    const refreshBtn = Button({
      text: 'Lex.uz‘dan yangilash',
      icon: icons.refresh('icon-xs'),
      variant: 'secondary',
      size: 'sm',
      onClick: async () => {
        if (isRefreshing) return;
        isRefreshing = true;
        refreshBtn.disabled = true;

        try {
          showToast({ message: 'Yangilash vazifasi boshlandi...', type: 'info' });
          const jobRes = await api.corpusRefresh({ lex_id: lexId });
          const jobId = jobRes.job_id;

          // Polling
          const pollTimer = setInterval(async () => {
            try {
              const statusData = await api.corpusJobStatus(jobId);
              if (statusData.status === 'done') {
                clearInterval(pollTimer);
                isRefreshing = false;
                refreshBtn.disabled = false;
                showToast({ message: statusData.summary || 'Hujjat yangilandi!', type: 'success' });
                await loadNorms();
                loadDocuments();
              } else if (statusData.status === 'failed') {
                clearInterval(pollTimer);
                isRefreshing = false;
                refreshBtn.disabled = false;
                showToast({ message: `Xatolik: ${statusData.error || 'Nomaʼlum xatolik'}`, type: 'error' });
              }
            } catch {
              clearInterval(pollTimer);
              isRefreshing = false;
              refreshBtn.disabled = false;
            }
          }, 1500);

        } catch (err) {
          isRefreshing = false;
          refreshBtn.disabled = false;
          showToast({ message: `Yangilash boshlanmadi: ${err.message}`, type: 'error' });
        }
      }
    });

    const infoCard = h('div', { className: 'card-surface p-4 space-y-3' },
      h('div', { className: 'flex items-center justify-between flex-wrap gap-2' },
        h('span', { className: 'font-mono text-xs font-bold text-main' }, docNumber),
        h('div', { className: 'flex items-center gap-2' },
          refreshBtn,
          h('a', {
            href: lexUrl,
            target: '_blank',
            rel: 'noopener noreferrer',
            className: 'btn btn-secondary btn-sm flex items-center gap-1 text-2xs'
          },
            h('span', {}, 'Lex.uz'),
            icons.externalLink('icon-xs')
          )
        )
      ),
      h('p', { className: 'text-xs text-main font-medium leading-relaxed' }, docTitle),
      h('div', { className: 'flex items-center gap-2 text-2xs text-muted' },
        h('span', {}, doc.authority || 'Davlat organi'),
        h('span', {}, '•'),
        Badge({ label: formatCategory(doc.category), variant: 'neutral' })
      )
    );

    // Qidiruv va hisoblagich
    let allSortedNorms = [];
    let normSearchQuery = '';
    let normSearchTimer = null;

    const normSearchCount = h('span', { className: 'text-2xs font-mono font-medium text-muted tabular-nums shrink-0' }, '');
    const normSearchInput = h('input', {
      type: 'text',
      className: 'input-text w-full pl-8 text-xs',
      placeholder: 'Modda raqami yoki matn bo‘yicha qidiruv...',
      oninput: (e) => {
        clearTimeout(normSearchTimer);
        normSearchTimer = setTimeout(() => {
          normSearchQuery = e.target.value.trim().toLowerCase();
          renderNormsList();
        }, 200);
      }
    });

    const normSearchContainer = h('div', { className: 'card-surface p-3 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2.5' },
      h('div', { className: 'relative flex-1 min-w-0' },
        h('span', { className: 'absolute left-2.5 top-2.5 text-muted pointer-events-none' }, icons.search('icon-xs')),
        normSearchInput
      ),
      normSearchCount
    );

    function renderNormsList() {
      clear(normsListEl);
      if (allSortedNorms.length === 0) {
        normSearchCount.textContent = '0 tadan 0 ta';
        normsListEl.appendChild(
          EmptyState({
            icon: icons.book('icon-md text-muted'),
            title: 'Bandlar topilmadi',
            description: 'Ushbu hujjat uchun normalar yuklanmagan.'
          })
        );
        return;
      }

      const filtered = !normSearchQuery
        ? allSortedNorms
        : allSortedNorms.filter(norm => {
            const num = (norm.article_number || norm.canonical_id || '').toLowerCase();
            const title = (norm.title || norm.title_uz || '').toLowerCase();
            const text = (norm.text_uz || norm.text || '').toLowerCase();
            return num.includes(normSearchQuery) || title.includes(normSearchQuery) || text.includes(normSearchQuery);
          });

      normSearchCount.textContent = `${allSortedNorms.length} tadan ${filtered.length} ta`;

      if (filtered.length === 0) {
        normsListEl.appendChild(
          EmptyState({
            icon: icons.search('icon-md text-muted'),
            title: 'Bandlar topilmadi',
            description: 'Qidiruv bo‘yicha hech qanday modda yoki band topilmadi.'
          })
        );
        return;
      }

      filtered.forEach(norm => {
        const normNumber = norm.article_number || norm.canonical_id || 'Band';
        const normTitle = norm.title || norm.title_uz || '';
        const normText = norm.text_uz || norm.text || '';
        const categoryName = formatCategory(norm.category);

        const normCard = h('div', { className: 'card-surface p-4 space-y-2' },
          h('div', { className: 'flex items-center justify-between gap-2' },
            h('span', { className: 'font-mono text-xs font-bold text-accent' }, normNumber),
            Badge({ label: categoryName, variant: 'neutral' })
          ),
          normTitle ? h('h4', { className: 'text-xs font-semibold text-main' }, normTitle) : null,
          // Matn faqat o'qish uchun: tahrirlash/qalam tugmasi yo'q!
          h('p', { className: 'text-xs text-muted leading-relaxed whitespace-pre-wrap select-text font-serif' }, normText)
        );

        normsListEl.appendChild(normCard);
      });
    }

    contentEl.appendChild(infoCard);
    contentEl.appendChild(normSearchContainer);
    contentEl.appendChild(normsListEl);

    slideOver = createSlideOver({
      title: `${docNumber} moddalari`,
      content: contentEl,
      size: 'lg'
    });

    slideOver.open();

    async function loadNorms() {
      clear(normsListEl);
      for (let i = 0; i < 4; i++) {
        normsListEl.appendChild(SkeletonCard({ rows: 3 }));
      }

      try {
        const res = await api.fetchDocumentNorms(docNumber);
        const rawNorms = res.norms || [];
        allSortedNorms = naturalSortNorms(rawNorms);
        renderNormsList();
      } catch (err) {
        clear(normsListEl);
        normSearchCount.textContent = '';
        normsListEl.appendChild(
          EmptyState({
            icon: icons.close('icon-md text-danger'),
            title: 'Bandlarni yuklashda xatolik',
            description: err.message
          })
        );
      }
    }

    loadNorms();
  }

  // YANGI "Lex.uz'dan hujjat qo'shish" 3 qadamli modal
  function openAddDocumentModal(initialSource = '') {
    if (addModal) addModal.close();

    let currentStep = 1;
    let previewData = null;
    let selectedInclude = 'all';

    const modalBody = h('div', { className: 'space-y-4' });

    function renderStep1() {
      clear(modalBody);

      const inputSource = h('input', {
        type: 'text',
        className: 'input-text w-full',
        placeholder: 'Masalan: https://lex.uz/docs/-683 yoki -683',
        autofocus: true,
        value: initialSource || ''
      });

      const errorAlert = h('div', { className: 'hidden card p-3 border-danger bg-danger-subtle text-danger text-xs' });

      let isChecking = false;

      async function performCheck() {
        const val = inputSource.value.trim();
        if (!val) {
          errorAlert.textContent = 'Iltimos, Lex.uz havolasi yoki ID raqamini kiriting.';
          errorAlert.classList.remove('hidden');
          return;
        }

        if (isChecking) return;
        isChecking = true;
        checkBtn.disabled = true;
        errorAlert.classList.add('hidden');

        try {
          const result = await api.corpusPreview(val);
          previewData = result;
          selectedInclude = result.include || 'all';
          currentStep = 2;
          renderStep2();
        } catch (err) {
          errorAlert.textContent = err.message || 'Hujjatni tekshirib bo‘lmadi.';
          errorAlert.classList.remove('hidden');
        } finally {
          isChecking = false;
          checkBtn.disabled = false;
        }
      }

      const checkBtn = Button({
        text: 'Tekshirish',
        variant: 'primary',
        onClick: performCheck
      });

      modalBody.appendChild(
        h('div', { className: 'space-y-3' },
          h('p', { className: 'text-xs text-muted' },
            'Qo‘shmoqchi bo‘lgan hujjatning Lex.uz dagi havolasini (https://lex.uz/docs/...) yoki ID raqamini kiriting.'
          ),
          h('div', { className: 'space-y-1' },
            h('label', { className: 'text-2xs font-semibold text-main' }, 'Lex.uz havolasi yoki ID'),
            inputSource
          ),
          errorAlert,
          h('div', { className: 'flex justify-end gap-2 pt-2' },
            Button({
              text: 'Bekor qilish',
              variant: 'secondary',
              onClick: () => addModal.close()
            }),
            checkBtn
          )
        )
      );

      if (initialSource) {
        setTimeout(performCheck, 50);
      }
    }

    function renderStep2() {
      clear(modalBody);

      const isRepealed = previewData.status === 'repealed';
      const inRegistry = Boolean(previewData.in_registry);
      const originalInclude = previewData.include || 'all';
      selectedInclude = originalInclude;

      const selectInclude = h('select', {
        className: 'select-dropdown w-full',
        onchange: (e) => {
          selectedInclude = e.target.value;
          updateSubmitBtn();
        }
      },
        h('option', { value: 'all', selected: selectedInclude === 'all' }, 'To‘liq hujjat (barcha bandlar)'),
        h('option', { value: 'disability_articles', selected: selectedInclude === 'disability_articles' }, 'Faqat nogironlikka oid bandlar')
      );

      const existingModeLabel = originalInclude === 'disability_articles' ? 'Faqat nogironlikka oid' : 'To‘liq';

      const detailsList = h('div', { className: 'card-surface p-4 space-y-2 text-xs' },
        h('div', { className: 'flex justify-between py-1 border-b border-border' },
          h('span', { className: 'text-muted' }, 'Hujjat raqami:'),
          h('span', { className: 'font-mono font-bold text-main' }, previewData.number || 'Nomaʼlum')
        ),
        h('div', { className: 'flex justify-between py-1 border-b border-border' },
          h('span', { className: 'text-muted' }, 'Turi:'),
          h('span', { className: 'font-semibold text-main' }, previewData.doc_type || 'Qonun')
        ),
        h('div', { className: 'flex justify-between py-1 border-b border-border' },
          h('span', { className: 'text-muted' }, 'Qabul sanasi:'),
          h('span', { className: 'font-mono text-main' }, previewData.adopted || '-')
        ),
        h('div', { className: 'flex justify-between py-1 border-b border-border' },
          h('span', { className: 'text-muted' }, 'Holati:'),
          isRepealed
            ? Badge({ label: 'Bekor qilingan', variant: 'danger' })
            : Badge({ label: 'Amalda', variant: 'success' })
        ),
        h('div', { className: 'flex justify-between py-1 border-b border-border' },
          h('span', { className: 'text-muted' }, 'Bandlar soni:'),
          h('span', { className: 'font-mono font-bold text-main' }, `${previewData.units} ta`)
        ),
        h('div', { className: 'flex justify-between py-1' },
          h('span', { className: 'text-muted' }, 'Bazada mavjudligi:'),
          inRegistry
            ? Badge({ label: `Bazada mavjud (rejim: ${existingModeLabel})`, variant: 'warning' })
            : Badge({ label: 'Yangi hujjat', variant: 'neutral' })
        )
      );

      function getSubmitText() {
        if (!inRegistry) return 'Qo‘shish';
        if (selectedInclude !== originalInclude) return 'Rejimni o‘zgartirib yangilash';
        return 'Lex.uz‘dan yangilash';
      }

      const submitBtn = Button({
        text: getSubmitText(),
        variant: 'primary',
        disabled: isRepealed,
        onClick: async () => {
          currentStep = 3;
          renderStep3();
        }
      });

      function updateSubmitBtn() {
        submitBtn.textContent = getSubmitText();
      }

      modalBody.appendChild(
        h('div', { className: 'space-y-3' },
          h('h4', { className: 'text-xs font-bold text-main leading-relaxed' }, previewData.title),
          detailsList,
          (previewData.is_amending && !isRepealed)
            ? h('div', { className: 'card p-3 border-warning bg-warning-subtle text-xs' },
                'Bu hujjat boshqa hujjatlarga o‘zgartirish kirituvchi hujjat. Uning mazmuni Lex.uz’da o‘zgartirilgan asosiy ' +
                'hujjatlar matniga allaqachon kiritilgan — odatda asosiy hujjatni qo‘shish (yoki yangilash) kifoya.'
              )
            : null,
          isRepealed
            ? h('div', { className: 'card p-3 border-danger bg-danger-subtle text-danger text-xs' },
                'Ushbu hujjat Lex.uz da bekor qilingan deb belgilangan. Bekor qilingan hujjatlarni yangidan qo‘shib bo‘lmaydi.'
              )
            : h('div', { className: 'space-y-1 pt-1' },
                h('label', { className: 'text-2xs font-semibold text-main' }, 'Qo‘shish tartibi'),
                selectInclude
              ),
          h('div', { className: 'flex justify-between gap-2 pt-2' },
            Button({
              text: 'Orqaga',
              variant: 'secondary',
              onClick: () => {
                currentStep = 1;
                renderStep1();
              }
            }),
            submitBtn
          )
        )
      );
    }

    async function renderStep3() {
      clear(modalBody);

      const inRegistry = Boolean(previewData.in_registry);
      const originalInclude = previewData.include || 'all';
      const isModeChange = inRegistry && selectedInclude !== originalInclude;
      const isSimpleRefresh = inRegistry && !isModeChange;

      const progressTitle = isSimpleRefresh ? 'Hujjat yangilanmoqda...' : 'Hujjat reestrga kiritilmoqda...';

      const statusBox = h('div', { className: 'card-surface p-6 text-center space-y-3' },
        h('div', { className: 'flex justify-center' },
          icons.refresh('icon-lg text-accent animate-spin')
        ),
        h('h4', { className: 'text-xs font-bold text-main' }, progressTitle),
        h('p', { className: 'text-2xs text-muted' }, 'Bu bir necha daqiqa vaqt olishi mumkin. Iltimos, kuting.')
      );

      modalBody.appendChild(statusBox);

      try {
        let jobRes;
        if (isSimpleRefresh) {
          jobRes = await api.corpusRefresh({ lex_id: previewData.lex_id });
        } else {
          jobRes = await api.corpusAdd({
            lex_id: previewData.lex_id,
            include: selectedInclude
          });
        }
        const jobId = jobRes.job_id;

        const pollTimer = setInterval(async () => {
          try {
            const jobData = await api.corpusJobStatus(jobId);
            if (jobData.status === 'done') {
              clearInterval(pollTimer);
              clear(statusBox);
              statusBox.appendChild(
                h('div', { className: 'space-y-3 text-center' },
                  h('div', { className: 'w-10 h-10 rounded-full bg-success text-accent-text flex items-center justify-center mx-auto' },
                    icons.check('icon-md')
                  ),
                  h('h4', { className: 'text-xs font-bold text-main' },
                    inRegistry ? 'Hujjat muvaffaqiyatli yangilandi!' : 'Hujjat muvaffaqiyatli qo‘shildi!'
                  ),
                  h('p', { className: 'text-2xs text-muted' }, jobData.summary || 'Hujjat bazaga kiritildi va indekslandi.'),
                  Button({
                    text: 'Yopish va yangilash',
                    variant: 'primary',
                    onClick: () => {
                      addModal.close();
                      loadDocuments();
                    }
                  })
                )
              );
            } else if (jobData.status === 'failed') {
              clearInterval(pollTimer);
              clear(statusBox);
              statusBox.appendChild(
                h('div', { className: 'space-y-3 text-center' },
                  h('div', { className: 'w-10 h-10 rounded-full bg-danger text-accent-text flex items-center justify-center mx-auto' },
                    icons.close('icon-md')
                  ),
                  h('h4', { className: 'text-xs font-bold text-danger' }, 'Vazifada xatolik yuz berdi'),
                  h('p', { className: 'text-2xs text-muted' }, jobData.error || 'Nomaʼlum xatolik yuz berdi.'),
                  Button({
                    text: 'Yopish',
                    variant: 'secondary',
                    onClick: () => addModal.close()
                  })
                )
              );
            }
          } catch (pollErr) {
            clearInterval(pollTimer);
          }
        }, 1500);

      } catch (err) {
        clear(statusBox);
        statusBox.appendChild(
          h('div', { className: 'space-y-3 text-center' },
            h('h4', { className: 'text-xs font-bold text-danger' }, 'Vazifa boshlanmadi'),
            h('p', { className: 'text-2xs text-muted' }, err.message),
            Button({
              text: 'Yopish',
              variant: 'secondary',
              onClick: () => addModal.close()
            })
          )
        );
      }
    }

    addModal = createModal({
      title: 'Lex.uz‘dan hujjat qo‘shish',
      content: modalBody,
      size: 'md'
    });

    renderStep1();
    addModal.open();
  }

  loadDocuments();
  if (initialAddId) {
    openAddDocumentModal(initialAddId);
  }
  return container;
}
