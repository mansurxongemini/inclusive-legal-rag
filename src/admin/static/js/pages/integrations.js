/**
 * Integrations Management Page — Assistant API clients, keys, and 30-day usage.
 * Strictly avoids innerHTML with data: uses h() helper and textContent.
 */
import { h, clear } from '../dom.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import { Button } from '../../components/Button.js';
import { Badge } from '../../components/Badge.js';
import { EmptyState } from '../../components/EmptyState.js';
import { SkeletonCard } from '../../components/Skeleton.js';
import { createModal } from '../../components/Modal.js';
import { showToast } from '../../components/Toast.js';

export function renderIntegrationsPage() {
  const container = h('div', { className: 'space-y-6' });

  let clientsList = [];
  let selectedClientId = null;
  let clientDetailData = null;

  // 1. Header Card
  const header = h('div', { className: 'card-surface p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4' },
    h('div', { className: 'space-y-1' },
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'API va integratsiyalar'),
        Badge({ label: 'Ulangan mijozlar', variant: 'neutral' })
      ),
      h('p', { className: 'text-xs text-muted' },
        'AI yordamchi bilan ishlaydigan tashqi mijozlar (Telegram bot, veb-ilovalar), ularning API kalitlari va limitlari.'
      )
    ),
    Button({
      text: 'Yangi mijoz',
      icon: icons.plus('icon-sm'),
      variant: 'primary',
      onClick: () => openCreateClientModal()
    })
  );

  // 2. Clients list container
  const clientsContainer = h('div', { className: 'space-y-3' });

  // 3. Detail section container (keys + 30-day usage)
  const detailContainer = h('div', { className: 'space-y-4 hidden' });

  container.appendChild(header);
  container.appendChild(clientsContainer);
  container.appendChild(detailContainer);

  // Initial load
  loadClients();

  async function loadClients() {
    clear(clientsContainer);
    for (let i = 0; i < 3; i++) {
      clientsContainer.appendChild(SkeletonCard({ rows: 3 }));
    }

    try {
      const data = await api.fetchIntegrationClients();
      clientsList = data.clients || [];
      renderClientsList();
      if (selectedClientId) {
        loadClientDetail(selectedClientId);
      }
    } catch (err) {
      clear(clientsContainer);
      clientsContainer.appendChild(EmptyState({
        icon: icons.close('icon-lg text-danger'),
        title: 'Mijozlarni yuklashda xatolik',
        description: err.message
      }));
    }
  }

  function renderClientsList() {
    clear(clientsContainer);

    if (clientsList.length === 0) {
      clientsContainer.appendChild(EmptyState({
        icon: icons.key('icon-lg text-muted'),
        title: 'Hali mijozlar mavjud emas',
        description: 'Telegram bot yoki veb-sayt uchun yangi integratsiya mijozini yarating.'
      }));
      return;
    }

    clientsList.forEach(c => {
      clientsContainer.appendChild(renderClientCard(c));
    });
  }

  function renderClientCard(client) {
    const isSelected = selectedClientId === client.client_id;
    const isBrowser = client.kind === 'browser';

    const card = h('div', {
      className: `card-surface p-4 transition-all duration-150 ${isSelected ? 'ring-2 ring-accent' : ''}`
    });

    // Top row: Name, kind badge, active toggle
    const topRow = h('div', { className: 'flex flex-col sm:flex-row sm:items-center justify-between gap-2' },
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h3', { className: 'text-sm font-semibold text-main' }, client.name),
        Badge({
          label: client.kind === 'server' ? 'Server (maxfiy)' : 'Brauzer (ochiq)',
          variant: client.kind === 'server' ? 'neutral' : 'primary'
        }),
        Badge({
          label: client.is_active ? 'Faol' : 'Nofaol',
          variant: client.is_active ? 'success' : 'danger'
        })
      ),
      h('div', { className: 'flex items-center gap-2' },
        Button({
          text: client.is_active ? 'To‘xtatish' : 'Faollashtirish',
          size: 'sm',
          variant: client.is_active ? 'secondary' : 'primary',
          onClick: async () => {
            try {
              await api.updateIntegrationClient(client.client_id, { is_active: !client.is_active });
              showToast(`Mijoz holati ${!client.is_active ? 'faollashtirildi' : 'to‘xtatildi'}.`, 'success');
              loadClients();
            } catch (e) {
              showToast(e.message, 'danger');
            }
          }
        }),
        Button({
          text: isSelected ? 'Yopish' : 'Tafsilotlar',
          size: 'sm',
          variant: isSelected ? 'primary' : 'secondary',
          icon: isSelected ? icons.close('icon-xs') : icons.chart('icon-xs'),
          onClick: () => {
            if (selectedClientId === client.client_id) {
              selectedClientId = null;
              detailContainer.classList.add('hidden');
              clear(detailContainer);
              renderClientsList();
            } else {
              selectedClientId = client.client_id;
              renderClientsList();
              loadClientDetail(client.client_id);
            }
          }
        })
      )
    );

    // Meta details row: scopes, limits, usage
    const metaRow = h('div', { className: 'grid grid-cols-2 sm:grid-cols-4 gap-2 text-2xs text-muted mt-3 pt-3 border-t border-border' },
      h('div', {},
        h('span', { className: 'font-semibold text-main' }, 'Ruxsatlar: '),
        h('span', {}, (client.scopes || []).join(', '))
      ),
      h('div', {},
        h('span', { className: 'font-semibold text-main' }, 'Limitlar: '),
        h('span', {}, `${client.rate_per_min}/daq (har user: ${client.user_rate_per_min}/daq)`)
      ),
      h('div', {},
        h('span', { className: 'font-semibold text-main' }, 'Kunlik kvota: '),
        h('span', {}, client.daily_quota ? `${client.daily_quota} ta` : 'Cheksiz')
      ),
      h('div', {},
        h('span', { className: 'font-semibold text-main' }, 'Bugungi so‘rovlar: '),
        h('span', { className: 'font-mono text-main font-bold' }, String(client.requests_today || 0))
      )
    );

    // If browser client, show allowed origins
    if (isBrowser && client.allowed_origins && client.allowed_origins.length > 0) {
      const originsRow = h('div', { className: 'text-2xs text-muted mt-2' },
        h('span', { className: 'font-semibold text-main' }, 'Ruxsat etilgan domenlar: '),
        h('span', { className: 'font-mono' }, client.allowed_origins.join(', '))
      );
      card.appendChild(topRow);
      card.appendChild(metaRow);
      card.appendChild(originsRow);
    } else {
      card.appendChild(topRow);
      card.appendChild(metaRow);
    }

    return card;
  }

  async function loadClientDetail(clientId) {
    detailContainer.classList.remove('hidden');
    clear(detailContainer);
    detailContainer.appendChild(SkeletonCard({ rows: 4 }));

    try {
      const data = await api.getIntegrationClient(clientId, 30);
      clientDetailData = data;
      renderClientDetailView(data);
    } catch (e) {
      clear(detailContainer);
      detailContainer.appendChild(EmptyState({
        icon: icons.close('icon-lg text-danger'),
        title: 'Tafsilotlarni yuklashda xatolik',
        description: e.message
      }));
    }
  }

  function renderClientDetailView(data) {
    clear(detailContainer);
    const client = data.client;
    const keys = data.keys || [];
    const usage = data.usage || [];

    // Header of detail card
    const detailHeader = h('div', { className: 'card-surface p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3' },
      h('div', {},
        h('h3', { className: 'text-sm font-bold text-main' }, `${client.name} — Kalitlar va 30 kunlik statistika`),
        h('p', { className: 'text-2xs text-muted mt-0.5' }, `Mijoz ID: ${client.client_id}`)
      ),
      Button({
        text: 'Yangi kalit yaratish (Rotatsiya)',
        size: 'sm',
        variant: 'primary',
        icon: icons.plus('icon-xs'),
        onClick: () => handleIssueNewKey(client.client_id)
      })
    );

    // Keys List Card
    const keysCard = h('div', { className: 'card-surface p-4 space-y-3' },
      h('h4', { className: 'text-xs font-bold text-main' }, 'Faol va bekor qilingan kalitlar'),
      renderKeysTable(keys)
    );

    // 30-Day Usage Table Card
    const usageCard = h('div', { className: 'card-surface p-4 space-y-3' },
      h('h4', { className: 'text-xs font-bold text-main' }, 'Oxirgi 30 kunlik faollik'),
      renderUsageTable(usage)
    );

    detailContainer.appendChild(detailHeader);
    detailContainer.appendChild(keysCard);
    detailContainer.appendChild(usageCard);
  }

  function renderKeysTable(keys) {
    if (!keys || keys.length === 0) {
      return h('p', { className: 'text-2xs text-muted' }, 'Ushbu mijoz uchun hali kalitlar mavjud emas.');
    }

    const table = h('table', { className: 'w-full text-left text-2xs border-collapse' });
    const thead = h('thead', { className: 'border-b border-border text-muted font-semibold' },
      h('tr', {},
        h('th', { className: 'py-2 px-2' }, 'Prefiks'),
        h('th', { className: 'py-2 px-2' }, 'Yaratilgan'),
        h('th', { className: 'py-2 px-2' }, 'Oxirgi foydalanish'),
        h('th', { className: 'py-2 px-2' }, 'Holat'),
        h('th', { className: 'py-2 px-2 text-right' }, 'Amal')
      )
    );

    const tbody = h('tbody', { className: 'divide-y divide-border' });
    keys.forEach(k => {
      const createdStr = new Date(k.created_at * 1000).toLocaleString('uz-UZ', { dateStyle: 'short', timeStyle: 'short' });
      const lastUsedStr = k.last_used_at
        ? new Date(k.last_used_at * 1000).toLocaleString('uz-UZ', { dateStyle: 'short', timeStyle: 'short' })
        : 'Ishlatilmagan';

      const statusBadge = k.is_usable
        ? Badge({ label: 'Faol', variant: 'success' })
        : (k.revoked_at ? Badge({ label: 'Bekor qilingan', variant: 'danger' }) : Badge({ label: 'Muddati tugagan', variant: 'neutral' }));

      const actionBtn = k.is_usable
        ? Button({
            text: 'Bekor qilish',
            size: 'sm',
            variant: 'danger',
            onClick: () => confirmRevokeKey(k)
          })
        : h('span', { className: 'text-muted text-3xs' }, 'Faol emas');

      const tr = h('tr', {},
        h('td', { className: 'py-2 px-2 font-mono text-main font-semibold select-all' }, k.prefix),
        h('td', { className: 'py-2 px-2 text-muted' }, createdStr),
        h('td', { className: 'py-2 px-2 text-muted' }, lastUsedStr),
        h('td', { className: 'py-2 px-2' }, statusBadge),
        h('td', { className: 'py-2 px-2 text-right' }, actionBtn)
      );
      tbody.appendChild(tr);
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    return h('div', { className: 'overflow-x-auto' }, table);
  }

  function renderUsageTable(usage) {
    if (!usage || usage.length === 0) {
      return h('p', { className: 'text-2xs text-muted' }, 'Oxirgi 30 kunda so‘rovlar qayd etilmagan.');
    }

    const table = h('table', { className: 'w-full text-left text-2xs border-collapse' });
    const thead = h('thead', { className: 'border-b border-border text-muted font-semibold' },
      h('tr', {},
        h('th', { className: 'py-2 px-2' }, 'Sana'),
        h('th', { className: 'py-2 px-2' }, 'Jami so‘rovlar'),
        h('th', { className: 'py-2 px-2' }, 'Rad etilgan (Refusals)'),
        h('th', { className: 'py-2 px-2' }, 'Xatolar'),
        h('th', { className: 'py-2 px-2' }, 'Bloklangan (Rejected)')
      )
    );

    const tbody = h('tbody', { className: 'divide-y divide-border' });
    usage.forEach(u => {
      const tr = h('tr', {},
        h('td', { className: 'py-2 px-2 font-mono text-main' }, u.day),
        h('td', { className: 'py-2 px-2 font-semibold text-main' }, String(u.requests)),
        h('td', { className: 'py-2 px-2 text-muted' }, String(u.refusals)),
        h('td', { className: 'py-2 px-2 text-danger font-semibold' }, String(u.errors)),
        h('td', { className: 'py-2 px-2 text-warning' }, String(u.rejected))
      );
      tbody.appendChild(tr);
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    return h('div', { className: 'overflow-x-auto max-h-64' }, table);
  }

  // Issue new key
  async function handleIssueNewKey(clientId) {
    try {
      const res = await api.issueIntegrationKey(clientId, {});
      showOneTimeKeyModal(res.api_key, res.warning);
      loadClientDetail(clientId);
      loadClients();
    } catch (e) {
      showToast(e.message, 'danger');
    }
  }

  // Revoke Key Confirmation Modal
  function confirmRevokeKey(keyInfo) {
    let modalInstance = null;

    const content = h('div', { className: 'space-y-3' },
      h('p', { className: 'text-xs text-main' },
        `Haqiqatan ham quyidagi kalitni bekor qilmoqchimisiz?`
      ),
      h('p', { className: 'font-mono text-xs text-danger bg-surface-2 p-2 rounded border border-border select-all' },
        keyInfo.prefix
      ),
      h('p', { className: 'text-2xs text-muted' },
        'Ushbu kalitdan foydalanayotgan barcha bot yoki tizimlar darhol 401 xatosi oladi.'
      )
    );

    const footer = h('div', { className: 'flex justify-end gap-2' },
      Button({
        text: 'Bekor qilish',
        variant: 'secondary',
        size: 'sm',
        onClick: () => modalInstance.close()
      }),
      Button({
        text: 'Ha, kalitni bekor qilish',
        variant: 'danger',
        size: 'sm',
        onClick: async () => {
          modalInstance.close();
          try {
            await api.revokeIntegrationKey(keyInfo.key_id);
            showToast('Kalit muvaffaqiyatli bekor qilindi.', 'success');
            if (selectedClientId) {
              loadClientDetail(selectedClientId);
            }
            loadClients();
          } catch (e) {
            showToast(e.message, 'danger');
          }
        }
      })
    );

    modalInstance = createModal({
      id: 'revoke-key-modal',
      title: 'Kalitni bekor qilishni tasdiqlash',
      content,
      footer
    });
    document.body.appendChild(modalInstance.element);
    modalInstance.open();
  }

  // Show One-Time Key Reveal Modal
  function showOneTimeKeyModal(rawKey, warningText) {
    let modalInstance = null;

    const copyBtn = Button({
      text: 'Nusxa olish',
      icon: icons.copy('icon-xs'),
      variant: 'primary',
      size: 'sm',
      onClick: async () => {
        try {
          await navigator.clipboard.writeText(rawKey);
          showToast('API kalit xotiraga nusxalandi!', 'success');
        } catch {
          showToast('Nusxalashda xatolik yuz berdi. Iltimos qo‘lda nusxalang.', 'warning');
        }
      }
    });

    const keyBox = h('div', { className: 'relative' },
      h('input', {
        type: 'text',
        readOnly: true,
        value: rawKey,
        className: 'input font-mono text-xs w-full pr-24 select-all bg-surface-2'
      }),
      h('div', { className: 'absolute right-1 top-1' }, copyBtn)
    );

    const content = h('div', { className: 'space-y-4' },
      h('div', { className: 'p-3 rounded-md bg-warning-bg border border-warning-border text-xs text-warning-text' },
        h('p', { className: 'font-semibold' }, 'DIQQAT:'),
        h('p', { className: 'mt-0.5' }, warningText || 'Ushbu kalit faqat bir marta ko‘rsatiladi. Uni hoziroq xavfsiz joyga saqlang.')
      ),
      keyBox,
      h('p', { className: 'text-2xs text-muted' },
        'Ushbu kalitni xabar almashish guruhlariga yoki ochiq repozitoriylarga joylashtirmang.'
      )
    );

    const footer = h('div', { className: 'flex justify-end' },
      Button({
        text: 'Tushundim, saqlab oldim',
        variant: 'secondary',
        size: 'sm',
        onClick: () => modalInstance.close()
      })
    );

    modalInstance = createModal({
      id: 'one-time-key-modal',
      title: 'Yangi API Kalit',
      content,
      footer
    });
    document.body.appendChild(modalInstance.element);
    modalInstance.open();
  }

  // Create Client Modal
  function openCreateClientModal() {
    let modalInstance = null;

    const nameInput = h('input', {
      type: 'text',
      className: 'input input-sm w-full',
      placeholder: 'Masalan: Telegram Bot yoki Portal Veb-sayti'
    });

    const kindSelect = h('select', { className: 'input input-sm w-full' },
      h('option', { value: 'server' }, 'Server (maxfiy kalit — Telegram bot, sayt backend)'),
      h('option', { value: 'browser' }, 'Brauzer (ochiq kalit — faqat belgilangan saytdan)')
    );

    const originsGroup = h('div', { className: 'space-y-1 hidden' },
      h('label', { className: 'text-2xs font-semibold text-main' }, 'Ruxsat etilgan domenlar (har qatorda bittadan)'),
      h('textarea', {
        className: 'input input-sm w-full font-mono text-2xs h-20',
        placeholder: 'https://huquqplus.uz\nhttp://localhost:5173'
      }),
      h('p', { className: 'text-3xs text-muted' }, 'Brauzer kalitlari faqat shu manzillardan yuborilgan so‘rovlarda ishlaydi.')
    );

    kindSelect.addEventListener('change', (e) => {
      if (e.target.value === 'browser') {
        originsGroup.classList.remove('hidden');
      } else {
        originsGroup.classList.add('hidden');
      }
    });

    const rateInput = h('input', {
      type: 'number',
      className: 'input input-sm w-full',
      value: '120',
      min: '1',
      max: '10000'
    });

    const userRateInput = h('input', {
      type: 'number',
      className: 'input input-sm w-full',
      value: '10',
      min: '1',
      max: '1000'
    });

    const quotaInput = h('input', {
      type: 'number',
      className: 'input input-sm w-full',
      value: '0',
      min: '0'
    });

    const noteInput = h('input', {
      type: 'text',
      className: 'input input-sm w-full',
      placeholder: 'Qo‘shimcha izoh (ixtiyoriy)'
    });

    const formContent = h('div', { className: 'space-y-3' },
      h('div', { className: 'space-y-1' },
        h('label', { className: 'text-2xs font-semibold text-main' }, 'Mijoz nomi *'),
        nameInput
      ),
      h('div', { className: 'space-y-1' },
        h('label', { className: 'text-2xs font-semibold text-main' }, 'Integratsiya turi *'),
        kindSelect
      ),
      originsGroup,
      h('div', { className: 'grid grid-cols-2 gap-2' },
        h('div', { className: 'space-y-1' },
          h('label', { className: 'text-2xs font-semibold text-main' }, 'Daqiqalik umumiy limit'),
          rateInput
        ),
        h('div', { className: 'space-y-1' },
          h('label', { className: 'text-2xs font-semibold text-main' }, 'Foydalanuvchi limiti (daq)'),
          userRateInput
        )
      ),
      h('div', { className: 'space-y-1' },
        h('label', { className: 'text-2xs font-semibold text-main' }, 'Kunlik kvota (0 = cheksiz)'),
        quotaInput
      ),
      h('div', { className: 'space-y-1' },
        h('label', { className: 'text-2xs font-semibold text-main' }, 'Izoh'),
        noteInput
      )
    );

    const footer = h('div', { className: 'flex justify-end gap-2' },
      Button({
        text: 'Bekor qilish',
        variant: 'secondary',
        size: 'sm',
        onClick: () => modalInstance.close()
      }),
      Button({
        text: 'Mijozni yaratish',
        variant: 'primary',
        size: 'sm',
        onClick: async () => {
          const name = nameInput.value.trim();
          if (!name) {
            showToast('Mijoz nomini kiriting.', 'warning');
            return;
          }
          const kind = kindSelect.value;
          let allowedOrigins = [];
          if (kind === 'browser') {
            const textarea = originsGroup.querySelector('textarea');
            allowedOrigins = (textarea.value || '')
              .split('\n')
              .map(o => o.trim())
              .filter(Boolean);
            if (allowedOrigins.length === 0) {
              showToast('Brauzer mijoziga kamida bitta ruxsat etilgan domen kerak.', 'warning');
              return;
            }
          }

          const payload = {
            name,
            kind,
            scopes: ['ask', 'feedback'],
            allowed_origins: allowedOrigins,
            rate_per_min: parseInt(rateInput.value, 10) || 120,
            user_rate_per_min: parseInt(userRateInput.value, 10) || 10,
            daily_quota: parseInt(quotaInput.value, 10) || 0,
            note: noteInput.value.trim()
          };

          try {
            const res = await api.createIntegrationClient(payload);
            modalInstance.close();
            showToast('Yangi mijoz muvaffaqiyatli yaratildi!', 'success');
            showOneTimeKeyModal(res.api_key, res.warning);
            loadClients();
          } catch (e) {
            showToast(e.message, 'danger');
          }
        }
      })
    );

    modalInstance = createModal({
      id: 'create-client-modal',
      title: 'Yangi integratsiya mijozi qo‘shish',
      content: formContent,
      footer
    });
    document.body.appendChild(modalInstance.element);
    modalInstance.open();
  }

  return container;
}
