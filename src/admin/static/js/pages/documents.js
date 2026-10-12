/**
 * Documents (Qonunlar) Page Module — Master-Detail with Slide-over & Pagination
 */
import { h, clear, mount } from '../dom.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import { store } from '../state.js';
import { Button } from '../../components/Button.js';
import { Badge } from '../../components/Badge.js';
import { EmptyState } from '../../components/EmptyState.js';
import { SkeletonCard } from '../../components/Skeleton.js';
import { createSlideOver } from '../../components/SlideOver.js';
import { createModal } from '../../components/Modal.js';
import { showToast } from '../../components/Toast.js';

// Domain labels dictionary
const DOMAIN_LABELS = {
  'all': "Barcha sohalar",
  'pensions_and_benefits': "Nafaqalar va pensiyalar",
  'labor_rights': "Mehnat huquqlari",
  'labor_code': "Mehnat kodeksi",
  'disability_rights': "Nogironlik huquqlari",
  'medical_social_expertise': "Tibbiy-ijtimoiy ekspertiza (TMEK)",
  'tax_benefits': "Soliq imtiyozlari",
  'rehabilitation_prosthetics': "Protez-ortopediya va reabilitatsiya",
  'sanatorium_health': "Sanatoriy-kurortda davolanish",
  'inclusive_education': "Inklyuziv ta'lim",
  'education': "Ta'lim kafolatlari",
  'accessibility_infrastructure': "To'siqsiz shaharsozlik",
  'social_protection': "Ijtimoiy himoya",
  'social_protection_governance': "Ijtimoiy himoya boshqaruvi",
  'international_treaty': "BMT Konvensiyasi"
};

function getDomainLabel(key) {
  if (!key) return "Umumiy qoida";
  return DOMAIN_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

const DISABILITY_LABELS = {
  'group_1': "I guruh",
  'group_2': "II guruh",
  'group_3': "III guruh",
  'childhood_disability': "Bolalar",
  'physical': "Tayanch-harakat",
  'visual': "Ko'rish",
  'hearing': "Eshitish"
};

function getAuthorityBadgeVariant() {
  return 'neutral';
}

export function renderDocumentsPage() {
  const container = h('div', { className: 'space-y-4' });

  // Page local state
  let currentDocType = 'all';
  let searchQuery = '';
  let authorityFilter = 'all';
  let searchDebounceTimer = null;

  let currentSelectedLawNumber = null;
  let allDetailNorms = [];
  let visibleNormsCount = 25; // Client-side pagination/virtualization chunk

  // Global Slide-over & Edit Modal instances
  let slideOver = null;
  let editModal = null;
  let uploadModal = null;
  let urlImportModal = null;

  // Header Bar
  const badgeTotalDocs = h('span', { className: 'badge badge-neutral tabular-nums font-semibold' }, '0 ta hujjat');
  const badgeTotalNorms = h('span', { className: 'badge badge-neutral tabular-nums font-semibold' }, '0 ta norma');

  // Secondary "⋯" menu
  let isMenuOpen = false;
  const menuDropdown = h('div', {
    className: 'hidden absolute right-0 top-full mt-1 w-48 bg-surface border border-border rounded-md shadow-overlay py-1 z-30'
  });

  const moreBtn = h('button', {
    type: 'button',
    className: 'btn btn-secondary btn-icon',
    'aria-label': 'Boshqa amallar',
    onclick: (e) => {
      e.stopPropagation();
      isMenuOpen = !isMenuOpen;
      menuDropdown.classList.toggle('hidden', !isMenuOpen);
    }
  }, icons.moreDots('icon-sm'));

  menuDropdown.appendChild(
    h('button', {
      type: 'button',
      className: 'w-full text-left px-3 py-2 text-xs text-main hover:bg-surface-2 flex items-center gap-2',
      onclick: () => {
        isMenuOpen = false;
        menuDropdown.classList.add('hidden');
        triggerFolderImport();
      }
    }, icons.refresh('icon-sm text-muted'), h('span', {}, 'Yangilash (Papkadan)'))
  );

  menuDropdown.appendChild(
    h('button', {
      type: 'button',
      className: 'w-full text-left px-3 py-2 text-xs text-main hover:bg-surface-2 flex items-center gap-2',
      onclick: () => {
        isMenuOpen = false;
        menuDropdown.classList.add('hidden');
        openUrlImport();
      }
    }, icons.externalLink('icon-sm text-accent'), h('span', {}, 'Lex.uz'))
  );

  document.addEventListener('click', () => {
    if (isMenuOpen) {
      isMenuOpen = false;
      menuDropdown.classList.add('hidden');
    }
  });

  const header = h('div', { className: 'card-surface p-5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4' },
    h('div', {},
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Qonunchilik bazasi'),
        badgeTotalDocs,
        badgeTotalNorms
      ),
      h('p', { className: 'text-xs text-muted mt-1' },
        'O‘zbekiston Respublikasining inklyuziv huquqiy hujjatlari, farmon va qarorlari.'
      )
    ),
    h('div', { className: 'flex items-center gap-2 relative' },
      Button({
        text: 'Qo‘shish',
        icon: icons.plus('icon-sm'),
        variant: 'primary',
        onClick: () => openManualUpload()
      }),
      moreBtn,
      menuDropdown
    )
  );

  // Search & Filters Row
  const searchInput = h('input', {
    type: 'text',
    className: 'input-text pl-9',
    placeholder: 'Hujjat nomi yoki raqami (masalan: 440, O‘RQ-641)...',
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
    typePillsContainer.innerHTML = '';
    typePillsContainer.appendChild(h('span', { className: 'text-2xs text-muted font-medium mr-1' }, 'Turi:'));

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

  // Master Grid Container
  const documentsGrid = h('div', { className: 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4' });

  // Detail View Container
  const detailContainer = h('div', { className: 'hidden space-y-4' });

  // Master View Wrapper
  const masterView = h('div', { className: 'space-y-4' },
    header,
    filterCard,
    documentsGrid
  );

  container.appendChild(masterView);
  container.appendChild(detailContainer);

  // --- API Actions ---

  async function loadDocuments() {
    documentsGrid.innerHTML = '';
    for (let i = 0; i < 6; i++) {
      documentsGrid.appendChild(SkeletonCard({ rows: 2 }));
    }

    try {
      const data = await api.fetchDocuments({
        doc_type: currentDocType,
        authority: authorityFilter,
        q: searchQuery
      });

      const docs = data.documents || [];
      const counts = data.type_counts || {};

      Object.assign(typeCountsMap, counts);
      renderTypePills();

      badgeTotalDocs.textContent = `${counts.all || docs.length} ta hujjat`;
      let sumNorms = 0;
      docs.forEach(d => { sumNorms += (d.norm_count || 0); });
      badgeTotalNorms.textContent = `${sumNorms} ta norma`;

      documentsGrid.innerHTML = '';

      if (docs.length === 0) {
        documentsGrid.appendChild(
          h('div', { className: 'col-span-full' },
            EmptyState({
              icon: icons.search('icon-lg'),
              title: 'Mos hujjatlar topilmadi',
              description: 'Qidiruv so‘zini o‘zgartiring yoki filtrlarni tozalang.'
            })
          )
        );
        return;
      }

      docs.forEach(d => {
        const card = h('div', {
          className: 'card-surface p-5 flex flex-col justify-between hover:shadow-md transition'
        },
          h('div', { className: 'space-y-3' },
            h('div', { className: 'flex items-center justify-between gap-2 flex-wrap' },
              Badge({ text: d.authority || 'Davlat organi', variant: 'neutral' }),
              h('div', { className: 'flex items-center gap-1-5' },
                Badge({ text: d.doc_type, variant: 'neutral' }),
                Badge({ text: `${d.norm_count} ta norma`, variant: 'neutral', className: 'tabular-nums' })
              )
            ),
            h('div', {},
              h('h3', { className: 'text-sm font-bold text-main font-mono tracking-tight' }, d.law_number),
              h('p', {
                className: 'text-xs text-muted mt-1 line-clamp-2 leading-relaxed',
                title: d.law_title || d.law_number
              }, d.law_title || d.law_number)
            )
          ),
          h('div', { className: 'pt-3 mt-4 border-t border-border flex items-center justify-between gap-2' },
            h('a', {
              href: d.source_url,
              target: '_blank',
              rel: 'noopener noreferrer',
              className: 'text-muted hover:text-accent text-2xs font-medium inline-flex items-center gap-1 transition'
            }, h('span', {}, 'Lex.uz'), icons.externalLink('icon-sm')),
            Button({
              text: 'Normalarni ko‘rish',
              icon: icons.chevronRight('icon-sm'),
              variant: 'secondary',
              size: 'sm',
              onClick: () => openDetailView(d.law_number)
            })
          )
        );
        documentsGrid.appendChild(card);
      });

    } catch (err) {
      documentsGrid.innerHTML = '';
      documentsGrid.appendChild(
        h('div', { className: 'col-span-full' },
          EmptyState({
            icon: icons.close('icon-lg text-danger'),
            title: 'Xatolik yuz berdi',
            description: err.message
          })
        )
      );
    }
  }

  async function openDetailView(lawNumber) {
    currentSelectedLawNumber = lawNumber;
    masterView.classList.add('hidden');
    detailContainer.classList.remove('hidden');

    detailContainer.innerHTML = '';
    detailContainer.appendChild(SkeletonCard({ rows: 4 }));

    try {
      const data = await api.fetchDocumentNorms(lawNumber);
      allDetailNorms = data.norms || [];
      visibleNormsCount = 25; // Reset virtualization slice

      renderDetailView(data);
    } catch (err) {
      detailContainer.innerHTML = '';
      detailContainer.appendChild(
        EmptyState({
          icon: icons.close('icon-lg text-danger'),
          title: 'Normalarni yuklashda xatolik',
          description: err.message,
          action: Button({
            text: 'Ortga qaytish',
            icon: icons.chevronLeft('icon-sm'),
            onClick: () => closeDetailView()
          })
        })
      );
    }
  }

  function closeDetailView() {
    detailContainer.classList.add('hidden');
    masterView.classList.remove('hidden');
    currentSelectedLawNumber = null;
    loadDocuments();
  }

  function renderDetailView(docData) {
    detailContainer.innerHTML = '';

    // Header Card
    const backBtn = Button({
      text: 'Hujjatlar ro‘yxatiga qaytish',
      icon: icons.chevronLeft('icon-sm'),
      variant: 'secondary',
      size: 'sm',
      onClick: () => closeDetailView()
    });

    const lexLink = docData.source_url ? h('a', {
      href: docData.source_url,
      target: '_blank',
      rel: 'noopener noreferrer',
      className: 'btn btn-secondary btn-sm inline-flex items-center gap-1 text-accent'
    }, h('span', {}, 'Rasmiy Lex.uz manbasi'), icons.externalLink('icon-sm')) : null;

    const detailHeader = h('div', { className: 'card-surface p-5 space-y-3' },
      h('div', { className: 'flex items-center justify-between flex-wrap gap-3' },
        backBtn,
        lexLink
      ),
      h('div', { className: 'border-t border-border pt-3 space-y-1' },
        h('div', { className: 'flex items-center gap-2 flex-wrap mb-1' },
          Badge({ text: docData.authority, variant: 'neutral' }),
          Badge({ text: docData.doc_type, variant: 'neutral' }),
          Badge({ text: `${docData.total_norms} ta norma`, variant: 'neutral', className: 'tabular-nums' })
        ),
        h('h2', { className: 'text-base font-bold text-main font-mono' }, docData.law_number),
        h('p', { className: 'text-xs text-muted leading-relaxed' }, docData.law_title || docData.law_number)
      )
    );

    // Search bar inside document
    const normsSearchInput = h('input', {
      type: 'text',
      className: 'input-text pl-9 text-xs',
      placeholder: 'Modda raqami yoki so‘z bo‘yicha qidirish...',
      oninput: (e) => {
        filterNorms(e.target.value.trim());
      }
    });

    const filteredCountBadge = h('span', { className: 'text-xs font-mono text-muted tabular-nums whitespace-nowrap' }, `${allDetailNorms.length} ta norma`);

    const filterToolbar = h('div', { className: 'card-surface p-3-5 flex flex-col md:flex-row items-center justify-between gap-3' },
      h('div', { className: 'relative flex-1 w-full' },
        h('span', { className: 'absolute left-3 top-2-5 text-muted pointer-events-none' }, icons.search('icon-sm')),
        normsSearchInput
      ),
      filteredCountBadge
    );

    // Norms List Container
    const normsListContainer = h('div', { className: 'space-y-2-5' });

    // Load More Button Container (Client-side virtualization)
    const loadMoreContainer = h('div', { className: 'pt-2 flex justify-center' });

    detailContainer.appendChild(detailHeader);
    detailContainer.appendChild(filterToolbar);
    detailContainer.appendChild(normsListContainer);
    detailContainer.appendChild(loadMoreContainer);

    let activeFilterQuery = '';

    function filterNorms(q) {
      activeFilterQuery = (q || '').toLowerCase();
      visibleNormsCount = 25; // Reset virtualization slice
      renderNormsList();
    }

    function renderNormsList() {
      normsListContainer.innerHTML = '';
      loadMoreContainer.innerHTML = '';

      let filtered = allDetailNorms;
      if (activeFilterQuery) {
        filtered = allDetailNorms.filter(n => {
          const uz = (n.text_uz || '').toLowerCase();
          const ru = (n.text_ru || '').toLowerCase();
          const num = (n.article_number || '').toLowerCase();
          const title = (n.title || '').toLowerCase();
          return uz.includes(activeFilterQuery) || ru.includes(activeFilterQuery) || num.includes(activeFilterQuery) || title.includes(activeFilterQuery);
        });
      }

      filteredCountBadge.textContent = `${filtered.length} ta norma`;

      if (filtered.length === 0) {
        normsListContainer.appendChild(
          EmptyState({
            icon: icons.search('icon-lg'),
            title: 'Norma topilmadi',
            description: 'Qidiruv parametrlarini o‘zgartiring.'
          })
        );
        return;
      }

      // Slice for client-side virtualization
      const sliced = filtered.slice(0, visibleNormsCount);

      sliced.forEach(n => {
        const domain = getDomainLabel(n.category);
        const preview = (n.text_uz || '').slice(0, 150).trim();

        const card = h('div', {
          className: 'card-surface p-4 hover:border-accent cursor-pointer transition flex flex-col md:flex-row md:items-center justify-between gap-3 group',
          tabIndex: 0,
          onclick: () => openNormDetailSlideOver(n),
          onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') openNormDetailSlideOver(n); }
        },
          h('div', { className: 'space-y-1-5 flex-1 min-w-0' },
            h('div', { className: 'flex items-center gap-2 flex-wrap' },
              h('span', { className: 'px-2 py-0-5 rounded-sm text-xs font-mono font-bold bg-text text-white' }, n.article_number),
              (n.title && n.title.trim() && n.title.trim().toLowerCase() !== (n.article_number || '').trim().toLowerCase()) ?
                h('h4', { className: 'text-xs font-bold text-main truncate max-w-sm group-hover:text-accent transition', title: n.title }, n.title) : null,
              Badge({ text: domain, variant: 'info' }),
              ...(n.disability_types || []).slice(0, 2).map(dt => Badge({ text: DISABILITY_LABELS[dt] || dt, variant: 'neutral' }))
            ),
            h('p', { className: 'text-xs text-muted line-clamp-1 leading-relaxed' }, `${preview}${preview.length >= 150 ? '...' : ''}`)
          ),
          h('div', { className: 'flex items-center gap-2 shrink-0 pt-2 md:pt-0 border-t md:border-t-0 border-border' },
            Button({
              icon: icons.edit('icon-sm'),
              variant: 'ghost',
              size: 'sm',
              onClick: (e) => {
                e.stopPropagation();
                openEditModal(n);
              }
            }),
            icons.chevronRight('icon-sm text-muted group-hover:text-accent transition')
          )
        );

        normsListContainer.appendChild(card);
      });

      // Show "Load More" button if there are more items
      if (filtered.length > visibleNormsCount) {
        const remaining = filtered.length - visibleNormsCount;
        const loadMoreBtn = Button({
          text: `Ko‘proq ko‘rsatish (+${Math.min(remaining, 25)} ta norma)`,
          icon: icons.chevronDown('icon-sm'),
          variant: 'secondary',
          onClick: () => {
            visibleNormsCount += 25;
            renderNormsList();
          }
        });
        loadMoreContainer.appendChild(loadMoreBtn);
      }
    }

    renderNormsList();
  }

  // --- Slide-over Panel Setup ---
  function openNormDetailSlideOver(norm) {
    if (!slideOver) {
      slideOver = createSlideOver({
        title: '',
        maxWidth: '620px'
      });
      document.body.appendChild(slideOver.element);
    }

    const badge = h('span', { className: 'px-2 py-0-5 rounded-sm text-xs font-mono font-bold bg-text text-white' }, norm.article_number);
    slideOver.setTitle(`${norm.law_number} • ${norm.title || norm.article_number}`, badge);

    const uzBody = h('div', { className: 'p-4 bg-surface-2 rounded-md border border-border text-xs text-main leading-relaxed whitespace-pre-wrap select-text' }, norm.text_uz || '');
    
    let ruSection = null;
    if (norm.text_ru && norm.text_ru.trim()) {
      ruSection = h('details', { className: 'text-xs mt-3' },
        h('summary', { className: 'cursor-pointer text-muted font-medium hover:text-main select-none py-1' }, 'Ruscha rasmiy matn'),
        h('div', { className: 'p-4 mt-2 bg-surface-2 rounded-md border border-border text-xs text-muted leading-relaxed whitespace-pre-wrap select-text' }, norm.text_ru)
      );
    }

    const tags = h('div', { className: 'flex items-center gap-1-5 flex-wrap mb-3' },
      Badge({ text: getDomainLabel(norm.category), variant: 'info' }),
      ...(norm.disability_types || []).map(dt => Badge({ text: DISABILITY_LABELS[dt] || dt, variant: 'neutral' }))
    );

    const meta = h('div', { className: 'pt-3 border-t border-border flex items-center justify-between text-2xs text-subtle font-mono' },
      h('span', {}, `ID: ${norm.canonical_id}`),
      h('span', {}, `Oxirgi tekshiruv: ${norm.last_verified_date || '2026-09-01'}`)
    );

    slideOver.setContent([tags, uzBody, ruSection, meta]);

    slideOver.setFooter([
      Button({
        text: 'Nusxalash',
        icon: icons.copy('icon-sm'),
        variant: 'secondary',
        onClick: () => {
          navigator.clipboard.writeText(`${norm.law_number} ${norm.article_number}\n${norm.title || ''}\n\n${norm.text_uz || ''}`);
          showToast('Norma matni nusxalandi', 'success');
        }
      }),
      Button({
        text: 'Tahrirlash',
        icon: icons.edit('icon-sm'),
        variant: 'primary',
        onClick: () => {
          slideOver.close();
          openEditModal(norm);
        }
      })
    ]);

    slideOver.open();
  }

  // --- Modal: Edit & Re-vectorize ---
  function openEditModal(norm) {
    if (!editModal) {
      editModal = createModal({
        id: 'modal-edit-norm',
        title: 'Normani tahrirlash va qayta vektorlash',
        maxWidth: '600px'
      });
      document.body.appendChild(editModal.element);
    }

    const titleInput = h('input', { type: 'text', className: 'input-text', value: norm.title || '' });
    const categorySelect = h('select', { className: 'select-dropdown' });
    Object.keys(DOMAIN_LABELS).forEach(k => {
      if (k === 'all') return;
      const opt = h('option', { value: k }, DOMAIN_LABELS[k]);
      if (k === norm.category) opt.selected = true;
      categorySelect.appendChild(opt);
    });

    const textUzArea = h('textarea', { rows: 6, className: 'textarea-field' }, norm.text_uz || '');
    const textRuArea = h('textarea', { rows: 3, className: 'textarea-field', placeholder: 'Ruscha rasmiy matn...' }, norm.text_ru || '');

    const content = h('div', { className: 'space-y-3 text-xs' },
      h('div', { className: 'grid grid-cols-2 gap-3' },
        h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Hujjat raqami'), h('input', { type: 'text', className: 'input-text opacity-70', value: norm.law_number, readonly: true })),
        h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Modda raqami'), h('input', { type: 'text', className: 'input-text opacity-70', value: norm.article_number, readonly: true }))
      ),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Modda sarlavhasi'), titleInput),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Huquqiy soha'), categorySelect),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Norma matni (O‘zbek tilida)'), textUzArea),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Norma matni (Rus tilida)'), textRuArea)
    );

    editModal.setContent(content);

    const saveBtn = Button({
      text: 'Saqlash va qayta vektorlash',
      icon: icons.refresh('icon-sm'),
      variant: 'primary',
      onClick: async () => {
        const uz = textUzArea.value.trim();
        if (!uz) {
          alert('Normaning o‘zbekcha matni bo‘sh bo‘lishi mumkin emas.');
          return;
        }
        saveBtn.disabled = true;
        saveBtn.innerText = 'Vektorlanmoqda...';

        try {
          await api.updateNorm(norm.canonical_id, {
            title: titleInput.value.trim(),
            text_uz: uz,
            text_ru: textRuArea.value.trim() || null,
            category: categorySelect.value
          });

          // Update local memory
          norm.title = titleInput.value.trim() || norm.article_number;
          norm.category = categorySelect.value;
          norm.text_uz = uz;
          norm.text_ru = textRuArea.value.trim();

          showToast('Norma saqlandi va BGE-M3 orqali qayta vektorlandi', 'success');
          editModal.close();
          if (currentSelectedLawNumber) {
            openDetailView(currentSelectedLawNumber);
          }
        } catch (err) {
          alert(`Xatolik: ${err.message}`);
        } finally {
          saveBtn.disabled = false;
        }
      }
    });

    const footer = [
      Button({ text: 'Bekor qilish', variant: 'ghost', onClick: () => editModal.close() }),
      saveBtn
    ];

    editModal.setFooter(footer);
    editModal.open();
  }

  // --- Modal: Manual Upload ---
  function openManualUpload() {
    if (!uploadModal) {
      uploadModal = createModal({
        id: 'modal-upload-article',
        title: 'Yangi huquqiy norma qo‘shish',
        maxWidth: '520px'
      });
      document.body.appendChild(uploadModal.element);
    }

    const artNumInput = h('input', { type: 'text', className: 'input-text', placeholder: 'Masalan: 18-modda' });
    const lawNumInput = h('input', { type: 'text', className: 'input-text', placeholder: 'O‘RQ-641' });
    const lawTitleInput = h('input', { type: 'text', className: 'input-text', placeholder: 'Qonun to‘liq nomi...' });
    const artTitleInput = h('input', { type: 'text', className: 'input-text', placeholder: 'Modda sarlavhasi...' });
    const catSelect = h('select', { className: 'select-dropdown' });
    Object.keys(DOMAIN_LABELS).forEach(k => {
      if (k === 'all') return;
      catSelect.appendChild(h('option', { value: k }, DOMAIN_LABELS[k]));
    });
    const textArea = h('textarea', { rows: 4, className: 'textarea-field', placeholder: 'Moddaning to‘liq matnini kiriting...' });

    const form = h('div', { className: 'space-y-3 text-xs' },
      h('div', { className: 'grid grid-cols-2 gap-3' },
        h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Modda / band'), artNumInput),
        h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Qonun raqami'), lawNumInput)
      ),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Qonun nomi'), lawTitleInput),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Modda sarlavhasi'), artTitleInput),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Huquqiy soha'), catSelect),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Norma matni'), textArea)
    );

    uploadModal.setContent(form);

    const submitBtn = Button({
      text: 'Saqlash va indekslash',
      variant: 'primary',
      onClick: async () => {
        const artNum = artNumInput.value.trim();
        const lawNum = lawNumInput.value.trim();
        const text = textArea.value.trim();

        if (!artNum || !lawNum || !text) {
          alert('Modda raqami, qonun raqami va matnini kiritish majburiy.');
          return;
        }

        submitBtn.disabled = true;
        try {
          const res = await api.uploadArticle({
            article_number: artNum,
            law_number: lawNum,
            law_title: lawTitleInput.value.trim() || lawNum,
            title: artTitleInput.value.trim() || artNum,
            category: catSelect.value,
            text: text
          });
          showToast(res.message || 'Norma muvaffaqiyatli saqlandi', 'success');
          uploadModal.close();
          loadDocuments();
        } catch (err) {
          alert(`Xatolik: ${err.message}`);
        } finally {
          submitBtn.disabled = false;
        }
      }
    });

    uploadModal.setFooter([
      Button({ text: 'Bekor qilish', variant: 'ghost', onClick: () => uploadModal.close() }),
      submitBtn
    ]);
    uploadModal.open();
  }

  // --- Modal: Lex.uz URL Import ---
  function openUrlImport() {
    if (!urlImportModal) {
      urlImportModal = createModal({
        id: 'modal-url-import',
        title: 'Lex.uz havolasi orqali yuklash',
        maxWidth: '500px'
      });
      document.body.appendChild(urlImportModal.element);
    }

    const urlInput = h('textarea', { rows: 3, className: 'textarea-field font-mono', placeholder: 'https://lex.uz/uz/docs/-5049511' });
    const catSelect = h('select', { className: 'select-dropdown' },
      h('option', { value: '' }, 'Avtomatik aniqlash'),
      ...Object.keys(DOMAIN_LABELS).filter(k => k !== 'all').map(k => h('option', { value: k }, DOMAIN_LABELS[k]))
    );

    const form = h('div', { className: 'space-y-3 text-xs' },
      h('p', { className: 'text-muted' }, 'Lex.uz rasmiy havolasini kiriting. Tizim uni avtomatik yuklab, vektorlaydi.'),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Lex.uz havolasi'), urlInput),
      h('div', {}, h('label', { className: 'block font-semibold mb-1' }, 'Huquqiy soha'), catSelect)
    );

    urlImportModal.setContent(form);

    const submitBtn = Button({
      text: 'Yuklash va indekslash',
      variant: 'primary',
      onClick: async () => {
        const url = urlInput.value.trim();
        if (!url) {
          alert('Iltimos, Lex.uz havolasini kiriting.');
          return;
        }

        submitBtn.disabled = true;
        try {
          const res = await api.importUrl({ url: url, category: catSelect.value || null });
          showToast(`Hujjat qabul qilindi: ${res.law_number || ''}`, 'success');
          urlImportModal.close();
          loadDocuments();
        } catch (err) {
          alert(`Xatolik: ${err.message}`);
        } finally {
          submitBtn.disabled = false;
        }
      }
    });

    urlImportModal.setFooter([
      Button({ text: 'Bekor qilish', variant: 'ghost', onClick: () => urlImportModal.close() }),
      submitBtn
    ]);
    urlImportModal.open();
  }

  async function triggerFolderImport() {
    if (!confirm('data/qonunlar papkasidagi hujjatlarni indekslashni boshlaysizmi?')) return;
    try {
      showToast('Papkadagi hujjatlar skanerlanmoqda...', 'neutral', 5000);
      const res = await api.importFolder();
      showToast(res.message || 'Papkadagi hujjatlar qayta ishlandi', 'success');
      loadDocuments();
    } catch (err) {
      alert(`Xatolik: ${err.message}`);
    }
  }

  // Initial load
  loadDocuments();

  return container;
}
