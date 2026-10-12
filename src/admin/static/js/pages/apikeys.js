/**
 * API Keys Management Page — Inclusive Legal RAG
 * Features:
 * - Segmented filter (Faol / Bekor qilingan / Hammasi), defaulting to Faol
 * - Clean semantic table with rates, requests, prefix, and statuses
 * - Revocation confirmation via shared Modal (no browser confirm())
 * - One-time reveal modal for newly generated keys with instant copy & security warning
 * - Integration snippets (cURL, Python) with one-click copy
 */
import { h, clear, mount } from '../dom.js';
import { icons } from '../icons.js';
import { api } from '../api.js';
import { Badge } from '../../components/Badge.js';
import { Button } from '../../components/Button.js';
import { createModal } from '../../components/Modal.js';
import { createTable } from '../../components/Table.js';
import { SegmentedControl } from '../../components/Tabs.js';
import { showToast } from '../../components/Toast.js';
import { EmptyState } from '../../components/EmptyState.js';
import { SkeletonTable } from '../../components/Skeleton.js';

export function renderApiKeysPage() {
  const container = h('div', { className: 'space-y-6' });

  // State
  let rawKeysList = [];
  let currentFilter = 'active'; // Default to 'active' as requested!
  let isLoading = false;

  // Modals
  let createModalInstance = null;
  let revokeModalInstance = null;

  // 1. Header Card
  const header = h('div', { className: 'card-surface p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4' },
    h('div', { className: 'space-y-1' },
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'API kalitlar va integratsiya'),
        Badge({ label: 'Xavfsiz ulanish', variant: 'neutral' })
      ),
      h('p', { className: 'text-xs text-muted' },
        'Tashqi ilovalar, nodavlat tashkilotlar va Telegram botlar uchun ruxsatnomalar.'
      )
    ),
    Button({
      text: 'Yangi API kalit',
      icon: icons.plus('icon-sm'),
      variant: 'primary',
      onClick: () => openCreateModal()
    })
  );

  // 2. Table Section Container
  const tableCard = h('div', { className: 'card-surface space-y-4 p-5' });

  // Segmented Control Filter
  const segmented = SegmentedControl({
    items: [
      { id: 'active', label: 'Faol', count: 0 },
      { id: 'revoked', label: 'Bekor qilingan', count: 0 },
      { id: 'all', label: 'Hammasi', count: 0 }
    ],
    activeId: 'active',
    onChange: (newFilter) => {
      currentFilter = newFilter;
      renderTableContent();
    }
  });

  const countBadge = h('span', { className: 'text-2xs text-muted font-mono tabular-nums' }, '0 ta kalit');

  const filterRow = h('div', { className: 'flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border' },
    segmented.element,
    countBadge
  );

  const tableContainer = h('div', {});

  // Table Component Setup
  const columns = [
    {
      key: 'name',
      label: 'Xizmat nomi',
      sticky: true,
      render: (val) => h('div', { className: 'font-medium text-main text-xs' }, val || 'Nomsiz mijoz')
    },
    {
      key: 'key_prefix',
      label: 'Kalit prefiksi',
      render: (val) => h('span', { className: 'font-mono text-2xs text-muted select-all bg-surface-2 px-1.5 py-0.5 rounded border border-border' }, val || '-')
    },
    {
      key: 'rate_limit_per_min',
      label: 'Cheklov / daq',
      align: 'center',
      render: (val) => h('span', { className: 'tabular-nums text-2xs text-muted' }, `${val || 60} / daq`)
    },
    {
      key: 'total_requests',
      label: 'So‘rovlar soni',
      align: 'center',
      render: (val) => h('span', { className: 'font-mono font-semibold tabular-nums text-xs text-main' }, String(val || 0))
    },
    {
      key: 'created_at',
      label: 'Yaratilgan sana',
      render: (val) => {
        if (!val) return h('span', { className: 'text-subtle text-2xs' }, '-');
        const d = new Date(val * 1000);
        const pad = (n) => String(n).padStart(2, '0');
        const formatted = `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
        return h('span', { className: 'text-muted text-2xs tabular-nums' }, formatted);
      }
    },
    {
      key: 'is_active',
      label: 'Holati',
      render: (val) => val
        ? Badge({ text: 'Faol', variant: 'success', dot: true })
        : Badge({ text: 'Bekor qilingan', variant: 'neutral' })
    },
    {
      key: 'key_id',
      label: 'Amal',
      align: 'right',
      render: (_, item) => {
        if (!item.is_active) {
          return h('span', { className: 'text-subtle text-2xs' }, '-');
        }
        return Button({
          text: 'Bekor qilish',
          variant: 'danger',
          size: 'sm',
          onClick: (e) => {
            e.stopPropagation();
            openRevokeConfirmModal(item);
          }
        });
      }
    }
  ];

  const tableInstance = createTable({
    columns,
    data: [],
    emptyMessage: 'Kalitlar mavjud emas'
  });

  tableCard.appendChild(filterRow);
  tableCard.appendChild(tableContainer);

  // 3. Integration Snippets Section
  const integrationCard = renderIntegrationSnippets();

  container.appendChild(header);
  container.appendChild(tableCard);
  container.appendChild(integrationCard);

  // ==========================================
  // DATA LOADING & RENDERING
  // ==========================================

  async function loadApiKeys() {
    isLoading = true;
    clear(tableContainer);
    tableContainer.appendChild(SkeletonTable({ cols: 7, rows: 3 }));

    try {
      const res = await api.fetchApiKeys();
      rawKeysList = res.api_keys || [];
      updateFilterCounts();
      renderTableContent();
    } catch (err) {
      clear(tableContainer);
      tableContainer.appendChild(
        EmptyState({
          icon: icons.close('icon-lg text-danger'),
          title: 'Kalitlarni yuklashda xatolik',
          description: err.message,
          action: Button({
            text: 'Qayta urinish',
            icon: icons.refresh('icon-sm'),
            onClick: () => loadApiKeys()
          })
        })
      );
    } finally {
      isLoading = false;
    }
  }

  function updateFilterCounts() {
    const activeCount = rawKeysList.filter(k => k.is_active).length;
    const revokedCount = rawKeysList.filter(k => !k.is_active).length;
    const totalCount = rawKeysList.length;

    segmented.updateCounts({
      active: activeCount,
      revoked: revokedCount,
      all: totalCount
    });
  }

  function renderTableContent() {
    clear(tableContainer);

    let filtered = rawKeysList;
    if (currentFilter === 'active') {
      filtered = rawKeysList.filter(k => k.is_active);
    } else if (currentFilter === 'revoked') {
      filtered = rawKeysList.filter(k => !k.is_active);
    }

    const label = currentFilter === 'active'
      ? `${filtered.length} ta faol kalit`
      : (currentFilter === 'revoked' ? `${filtered.length} ta bekor qilingan kalit` : `${filtered.length} ta jami kalit`);
    countBadge.textContent = label;

    if (filtered.length === 0) {
      const emptyDesc = currentFilter === 'active'
        ? 'Ayni paytda faol API kalitlar mavjud emas. Yangi kalit yaratish uchun yuqoridagi tugmani bosing.'
        : (currentFilter === 'revoked' ? 'Bekor qilingan kalitlar mavjud emas.' : 'Kalitlar ro‘yxati bo‘sh.');

      tableContainer.appendChild(
        EmptyState({
          icon: icons.key('icon-lg text-muted'),
          title: 'Hech qanday kalit topilmadi',
          description: emptyDesc
        })
      );
      return;
    }

    tableInstance.update(filtered);

    // Desktop & Tablet View: Table with sticky first column
    const desktopView = h('div', { className: 'hidden md:block' }, tableInstance.element);

    // Mobile View (< 768px): Card-based layout with direct "Bekor qilish" action
    const mobileView = h('div', { className: 'block md:hidden space-y-3' },
      ...filtered.map(renderMobileCard)
    );

    tableContainer.appendChild(desktopView);
    tableContainer.appendChild(mobileView);
  }

  function renderMobileCard(item) {
    const d = item.created_at ? new Date(item.created_at * 1000) : null;
    const pad = (n) => String(n).padStart(2, '0');
    const dateStr = d ? `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}` : '-';

    return h('div', { className: 'card-surface p-4 space-y-3 border border-border' },
      h('div', { className: 'flex items-start justify-between gap-2' },
        h('div', { className: 'space-y-1 min-w-0' },
          h('h4', { className: 'font-semibold text-xs text-main truncate' }, item.name || 'Nomsiz mijoz'),
          h('span', { className: 'font-mono text-2xs text-muted select-all bg-surface-2 px-1.5 py-0.5 rounded border border-border inline-block' }, item.key_prefix || '-')
        ),
        item.is_active
          ? Badge({ text: 'Faol', variant: 'success', dot: true })
          : Badge({ text: 'Bekor qilingan', variant: 'neutral' })
      ),
      h('div', { className: 'grid grid-cols-3 gap-2 pt-2 border-t border-border text-2xs' },
        h('div', {},
          h('span', { className: 'text-muted block' }, 'Cheklov:'),
          h('span', { className: 'font-medium text-main' }, `${item.rate_limit_per_min || 60}/daq`)
        ),
        h('div', {},
          h('span', { className: 'text-muted block' }, 'So‘rovlar:'),
          h('span', { className: 'font-mono font-semibold text-main' }, String(item.total_requests || 0))
        ),
        h('div', {},
          h('span', { className: 'text-muted block' }, 'Sana:'),
          h('span', { className: 'text-muted' }, dateStr)
        )
      ),
      item.is_active ? h('div', { className: 'pt-2 border-t border-border flex justify-end' },
        Button({
          text: 'Bekor qilish',
          icon: icons.trash('icon-xs'),
          variant: 'danger',
          size: 'sm',
          onClick: () => openRevokeConfirmModal(item)
        })
      ) : null
    );
  }

  // ==========================================
  // MODAL 1: REVOKE CONFIRMATION (NO BROWSER CONFIRM)
  // ==========================================

  function openRevokeConfirmModal(keyItem) {
    if (!revokeModalInstance) {
      revokeModalInstance = createModal({
        id: 'revoke-key-modal',
        title: 'API kalitni bekor qilish',
        maxWidth: '480px'
      });
      document.body.appendChild(revokeModalInstance.element);
    }

    const content = h('div', { className: 'space-y-4 text-xs' },
      h('div', { className: 'p-3 bg-danger-bg border border-danger-border rounded-md text-danger flex items-start gap-2.5' },
        h('span', { className: 'flex-shrink-0 mt-0.5' }, icons.trash('icon-sm text-danger')),
        h('div', { className: 'space-y-1' },
          h('p', { className: 'font-semibold' }, 'Ushbu amalni ortga qaytarib bo‘lmaydi!'),
          h('p', { className: 'text-2xs opacity-90' },
            'Kalit bekor qilingach, ushbu kalit orqali ishlayotgan barcha tashqi tizimlar, botlar va ilovalar darhol tizimdan uziladi.'
          )
        )
      ),

      h('div', { className: 'bg-surface-2 p-3.5 rounded-md border border-border space-y-2' },
        h('div', { className: 'flex justify-between' },
          h('span', { className: 'text-muted' }, 'Xizmat nomi:'),
          h('span', { className: 'font-semibold text-main' }, keyItem.name)
        ),
        h('div', { className: 'flex justify-between' },
          h('span', { className: 'text-muted' }, 'Kalit prefiksi:'),
          h('span', { className: 'font-mono text-2xs text-main' }, keyItem.key_prefix)
        ),
        h('div', { className: 'flex justify-between' },
          h('span', { className: 'text-muted' }, 'Bajarilgan so‘rovlar:'),
          h('span', { className: 'font-mono font-semibold text-main' }, `${keyItem.total_requests || 0} ta`)
        )
      )
    );

    const submitBtn = Button({
      text: 'Ha, kalitni bekor qilish',
      variant: 'danger',
      icon: icons.trash('icon-sm'),
      onClick: async () => {
        submitBtn.disabled = true;
        submitBtn.innerHTML = 'Bekor qilinmoqda...';

        try {
          await api.revokeApiKey(keyItem.key_id);
          showToast(`"${keyItem.name}" kaliti bekor qilindi`, 'success');
          revokeModalInstance.close();
          loadApiKeys();
        } catch (err) {
          showToast(`Xatolik: ${err.message}`, 'danger');
          submitBtn.disabled = false;
          submitBtn.innerHTML = 'Ha, kalitni bekor qilish';
        }
      }
    });

    const footer = [
      Button({
        text: 'Ortga qaytish',
        variant: 'secondary',
        onClick: () => revokeModalInstance.close()
      }),
      submitBtn
    ];

    revokeModalInstance.setContent(content);
    revokeModalInstance.setFooter(footer);
    revokeModalInstance.open();
  }

  // ==========================================
  // MODAL 2: ONE-TIME REVEAL KEY GENERATION
  // ==========================================

  function openCreateModal() {
    if (!createModalInstance) {
      createModalInstance = createModal({
        id: 'create-key-modal',
        title: 'Yangi API kalit yaratish',
        maxWidth: '520px'
      });
      document.body.appendChild(createModalInstance.element);
    }

    // Reset to creation form
    const nameInput = h('input', {
      type: 'text',
      className: 'input-text',
      placeholder: 'Masalan: Nogironlar huquqlari boti yoki Mobil ilova',
      autofocus: true
    });

    const limitSelect = h('select', { className: 'select-dropdown' },
      h('option', { value: '30' }, '30 ta so‘rov / daqiqa'),
      h('option', { value: '60', selected: true }, '60 ta so‘rov / daqiqa (Standart)'),
      h('option', { value: '120' }, '120 ta so‘rov / daqiqa (Yuqori yuklama)'),
      h('option', { value: '300' }, '300 ta so‘rov / daqiqa (Cheksiz hamkorlik)')
    );

    const form = h('div', { className: 'space-y-4 text-xs' },
      h('div', { className: 'space-y-1.5' },
        h('label', { className: 'font-medium text-main' }, 'Xizmat yoki foydalanuvchi nomi *'),
        nameInput,
        h('p', { className: 'text-2xs text-muted' }, 'Ushbu kalit qaysi dastur yoki tashkilot tomonidan ishlatilishini yozing.')
      ),
      h('div', { className: 'space-y-1.5' },
        h('label', { className: 'font-medium text-main' }, 'Daqiqalik so‘rov cheklovi (Rate limit)'),
        limitSelect,
        h('p', { className: 'text-2xs text-muted' }, 'Tizim barqarorligini ta‘minlash uchun ruxsat etilgan maksimal chastota.')
      )
    );

    const submitBtn = Button({
      text: 'Kalitni yaratish',
      variant: 'primary',
      icon: icons.key('icon-sm'),
      onClick: async () => {
        const nameVal = nameInput.value.trim();
        const limitVal = parseInt(limitSelect.value, 10) || 60;

        if (!nameVal) {
          nameInput.focus();
          showToast('Iltimos, xizmat nomini kiriting', 'danger');
          return;
        }

        submitBtn.disabled = true;
        submitBtn.innerHTML = 'Yaratilmoqda...';

        try {
          const res = await api.createApiKey({ name: nameVal, rate_limit_per_min: limitVal });
          const rawKey = res.key?.api_key;

          if (!rawKey) {
            throw new Error('Server kalit qaytarmadi');
          }

          renderOneTimeRevealState(nameVal, rawKey);
          loadApiKeys();
        } catch (err) {
          showToast(`Xatolik: ${err.message}`, 'danger');
          submitBtn.disabled = false;
          submitBtn.innerHTML = 'Kalitni yaratish';
        }
      }
    });

    const footer = [
      Button({
        text: 'Bekor qilish',
        variant: 'ghost',
        onClick: () => createModalInstance.close()
      }),
      submitBtn
    ];

    createModalInstance.setContent(form);
    createModalInstance.setFooter(footer);
    createModalInstance.open();
  }

  function renderOneTimeRevealState(clientName, secretKey) {
    // 1. One-time reveal security banner
    const warningBanner = h('div', { className: 'p-3.5 bg-warning-bg border border-warning-border rounded-md text-warning space-y-1' },
      h('div', { className: 'flex items-center gap-2 font-semibold' },
        icons.scales('icon-sm text-warning'),
        h('span', {}, 'DIQQAT: Ushbu kalit faqat bir marta to‘liq ko‘rsatiladi!')
      ),
      h('p', { className: 'text-2xs opacity-90 leading-relaxed' },
        'Xavfsizlik nuqtai nazaridan, ushbu kalit bazada xeshlab saqlanadi. Uni hoziroq nusxalab, xavfsiz joyda saqlang. Ushbu oynani yopganingizdan so‘ng kalitni qayta to‘liq ko‘rib bo‘lmaydi.'
      )
    );

    // 2. Token Display Box with Copy Action
    const keyBox = h('div', { className: 'space-y-2' },
      h('label', { className: 'text-2xs font-semibold text-muted uppercase tracking-wider' }, `Yangi yaratilgan kalit (${clientName})`),
      h('div', { className: 'flex items-stretch gap-2' },
        h('input', {
          type: 'text',
          readOnly: true,
          value: secretKey,
          className: 'input-text font-mono text-xs select-all bg-surface-2 border-accent',
          onclick: (e) => e.target.select()
        }),
        Button({
          text: 'Nusxalash',
          icon: icons.copy('icon-sm'),
          variant: 'primary',
          onClick: (e) => {
            navigator.clipboard.writeText(secretKey).then(() => {
              showToast('API kalit xotiraga nusxalandi!', 'success');
              const btn = e.currentTarget;
              btn.innerHTML = '';
              btn.appendChild(icons.check('icon-sm'));
              btn.appendChild(h('span', {}, 'Nusxalandi!'));
              setTimeout(() => {
                btn.innerHTML = '';
                btn.appendChild(icons.copy('icon-sm'));
                btn.appendChild(h('span', {}, 'Nusxalash'));
              }, 2500);
            }).catch(() => {
              showToast('Nusxalashda xatolik, qo‘lda nusxalang', 'danger');
            });
          }
        })
      )
    );

    const revealContent = h('div', { className: 'space-y-4 py-1' },
      warningBanner,
      keyBox
    );

    createModalInstance.setContent(revealContent);
    createModalInstance.setFooter([
      Button({
        text: 'Tushundim, yopish',
        variant: 'primary',
        onClick: () => createModalInstance.close()
      })
    ]);
  }

  // ==========================================
  // 4. INTEGRATION SNIPPETS HELPER
  // ==========================================

  function renderIntegrationSnippets() {
    const card = h('div', { className: 'card-surface p-5 space-y-4' });

    const headerRow = h('div', { className: 'space-y-0.5' },
      h('h3', { className: 'text-sm font-bold text-main' }, 'Integratsiya namunalari'),
      h('p', { className: 'text-2xs text-muted' },
        'Inclusive Legal RAG qidiruv va huquqiy tahlil API siga tashqi tizimlardan ulanish namunalari.'
      )
    );

    const curlCode = `curl -X POST "http://localhost:8000/api/v1/inclusive/query" \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: <SIZNING_API_KALITINGIZ>" \\
  -d '{
    "query": "1-guruh nogironligi bo'lgan shaxslarga beriladigan imtiyozlar"
  }'`;

    const pythonCode = `import requests

url = "http://localhost:8000/api/v1/inclusive/query"
headers = {
    "Content-Type": "application/json",
    "X-API-Key": "<SIZNING_API_KALITINGIZ>"
}
payload = {
    "query": "1-guruh nogironligi bo'lgan shaxslarga beriladigan imtiyozlar"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())`;

    function createSnippetBlock(title, language, code) {
      return h('div', { className: 'space-y-2' },
        h('div', { className: 'flex items-center justify-between' },
          h('span', { className: 'text-2xs font-semibold text-muted uppercase tracking-wider font-mono' }, `${title} (${language})`),
          Button({
            text: 'Kodni nusxalash',
            icon: icons.copy('icon-xs'),
            variant: 'ghost',
            size: 'sm',
            onClick: (e) => {
              navigator.clipboard.writeText(code).then(() => {
                showToast(`${title} kodi nusxalandi!`, 'success');
              });
            }
          })
        ),
        h('pre', { className: 'code-block' }, code)
      );
    }

    const grid = h('div', { className: 'grid grid-cols-1 lg:grid-cols-2 gap-4 pt-1' },
      createSnippetBlock('cURL So‘rovi', 'Bash', curlCode),
      createSnippetBlock('Python So‘rovi', 'Python', pythonCode)
    );

    card.appendChild(headerRow);
    card.appendChild(grid);
    return card;
  }

  // Initial load
  loadApiKeys();

  return container;
}
