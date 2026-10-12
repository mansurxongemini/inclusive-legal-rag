/**
 * Tahririyat — Bildirishnomalar sahifasi.
 * Lex.uz moddasi o'zgarganda/kuchini yo'qotganda tushadigan bildirishnomalar:
 * eski va yangi matn yonma-yon, so'z darajasida diff bilan.
 * Barcha matn textContent orqali chiqariladi (XSS siz).
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

const KIND_LABELS = {
  norm_amended: 'O‘zgartirish kiritildi',
  norm_repealed: 'Kuchini yo‘qotgan',
  norm_removed: 'Topilmadi (o‘chirilgan)',
  document_amended: 'Hujjatga o‘zgartirish kiritildi',
};

function kindVariant(k) {
  if (k === 'norm_repealed' || k === 'norm_removed') return 'danger';
  return 'warning';
}

/** So'z darajasida diff (LCS): [{t:'same'|'del'|'ins', w}]. Katta matnlar 2000 belgigacha kesiladi. */
export function wordDiff(oldText, newText) {
  const a = (oldText || '').slice(0, 2000).split(/(\s+)/);
  const b = (newText || '').slice(0, 2000).split(/(\s+)/);
  const n = a.length, m = b.length;
  // Xotira chegarasi: juda uzun matnlar uchun sodda rejim
  if (n * m > 400000) {
    return { left: [{ t: 'same', w: (oldText || '').slice(0, 2000) }], right: [{ t: 'same', w: (newText || '').slice(0, 2000) }] };
  }
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const left = [], right = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { left.push({ t: 'same', w: a[i] }); right.push({ t: 'same', w: b[j] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { left.push({ t: 'del', w: a[i] }); i++; }
    else { right.push({ t: 'ins', w: b[j] }); j++; }
  }
  while (i < n) left.push({ t: 'del', w: a[i++] });
  while (j < m) right.push({ t: 'ins', w: b[j++] });
  return { left, right };
}

function renderTokens(box, tokens) {
  clear(box);
  tokens.forEach((tok) => {
    if (tok.t === 'same') {
      box.appendChild(document.createTextNode(tok.w));
    } else {
      box.appendChild(h('span', {
        className: tok.t === 'del' ? 'diff-del' : 'diff-ins',
      }, tok.w));
    }
  });
}

export function renderNotificationsPage() {
  const container = h('div', { className: 'space-y-4' });
  let statusFilter = 'open';
  let deleteModal = null;

  const badgeOpen = h('span', { className: 'badge badge-warning tabular-nums font-semibold' }, '0 ta ochiq');

  const header = h('div', { className: 'card-surface p-5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4' },
    h('div', {},
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Bildirishnomalar'),
        badgeOpen
      ),
      h('p', { className: 'text-xs text-muted mt-1' },
        'Bog‘langan Lex.uz moddasi o‘zgarsa, kuchini yo‘qotsa yoki topilmasa — shu yerga bildirishnoma tushadi.'
      )
    ),
    Button({
      text: 'Hozir tekshirish', icon: icons.refresh('icon-sm'), variant: 'secondary',
      onClick: async () => {
        try {
          const res = await api.editorialCheckLinks();
          showToast(`Tekshirildi: ${res.checked_links} ta bog‘lanish, ${res.new_notifications} ta yangi`, 'success');
          loadList();
        } catch (e) { showToast(e.message, 'danger'); }
      },
    })
  );

  const filterRow = h('div', { className: 'flex items-center gap-1-5 flex-wrap' },
    ...['open', 'resolved', 'all'].map((s) => h('button', {
      type: 'button',
      className: `btn btn-sm ${statusFilter === s ? 'btn-primary' : 'btn-secondary'}`,
      'aria-pressed': statusFilter === s ? 'true' : 'false',
      onclick: () => {
        statusFilter = s;
        [...filterRow.children].forEach((btn) => {
          const on = btn.textContent === ({ open: 'Ochiq', resolved: 'Hal qilingan', all: 'Barchasi' })[statusFilter];
          btn.classList.toggle('btn-primary', on);
          btn.classList.toggle('btn-secondary', !on);
          btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        loadList();
      },
    }, s === 'open' ? 'Ochiq' : s === 'resolved' ? 'Hal qilingan' : 'Barchasi'))
  );

  const listEl = h('div', { className: 'space-y-3', role: 'list', 'aria-label': 'Bildirishnomalar ro‘yxati' });

  const styleEl = h('style', {},
    '.diff-del{background:#fee2e2;color:#991b1b;text-decoration:line-through;border-radius:3px;padding:0 2px;}'
    + '.diff-ins{background:#dcfce7;color:#166534;border-radius:3px;padding:0 2px;}');
  container.appendChild(styleEl);
  container.appendChild(header);
  container.appendChild(filterRow);
  container.appendChild(listEl);

  loadList();

  async function loadList() {
    clear(listEl);
    for (let i = 0; i < 3; i++) listEl.appendChild(SkeletonCard({ rows: 3 }));
    try {
      const data = await api.editorialNotifications({ status: statusFilter, limit: 50, offset: 0 });
      badgeOpen.textContent = `${data.open_count || 0} ta ochiq`;
      const items = data.items || [];
      clear(listEl);
      if (!items.length) {
        listEl.appendChild(EmptyState({
          icon: icons.check ? icons.check('icon-lg') : icons.search('icon-lg'),
          title: statusFilter === 'open' ? 'Ochiq bildirishnoma yo‘q' : 'Bildirishnoma topilmadi',
          description: 'Bog‘langan moddalar o‘zgarmagan. Hammasi joyida.',
        }));
        return;
      }
      items.forEach((n) => listEl.appendChild(renderCard(n)));
    } catch (err) {
      clear(listEl);
      listEl.appendChild(EmptyState({
        icon: icons.close('icon-lg text-danger'),
        title: 'Yuklashda xatolik',
        description: err.message,
      }));
    }
  }

  function renderCard(n) {
    const diff = wordDiff(n.old_text || '', n.new_text || '');
    const leftBox = h('div', { className: 'p-3 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text' });
    const rightBox = h('div', { className: 'p-3 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text' });
    renderTokens(leftBox, diff.left);
    renderTokens(rightBox, diff.right);

    // whole-act links (law:<id>) carry a list of changed units instead of one norm's old/new wording
    const isDocLink = (n.canonical_id || '').startsWith('law:');
    const summaryBox = h('div', { className: 'p-3 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text' },
      n.new_text || '');
    const diffGrid = isDocLink
      ? h('div', { className: 'grid grid-cols-1 gap-2' },
        h('div', {}, h('p', { className: 'text-2xs font-bold text-main mb-1' }, 'Maqola tayangan hujjatdagi o‘zgarishlar'), summaryBox))
      : (n.kind === 'norm_removed')
      ? h('div', { className: 'grid grid-cols-1 gap-2' },
        h('div', {}, h('p', { className: 'text-2xs font-bold text-main mb-1' }, 'Eski matn (modda store‘da topilmadi)'), leftBox))
      : h('div', { className: 'grid grid-cols-1 md:grid-cols-2 gap-2' },
        h('div', {}, h('p', { className: 'text-2xs font-bold text-main mb-1' }, 'Eski matn'), leftBox),
        h('div', {}, h('p', { className: 'text-2xs font-bold text-main mb-1' }, 'Yangi matn'), rightBox));

    const card = h('div', { className: 'card-surface p-4 space-y-3', role: 'listitem' },
      h('div', { className: 'flex items-center gap-2 flex-wrap' },
        Badge({ text: KIND_LABELS[n.kind] || n.kind, variant: kindVariant(n.kind) }),
        Badge({ text: n.owner_type === 'huquqplus' ? 'Huquq+' : 'Curated QA', variant: n.owner_type === 'huquqplus' ? 'primary' : 'neutral' }),
        n.status !== 'open' ? Badge({ text: n.status === 'resolved' ? 'Hal qilingan' : 'Yopilgan', variant: 'neutral' }) : null,
        h('span', { className: 'text-2xs text-subtle font-mono' }, n.canonical_id || '')
      ),
      n.owner_type === 'huquqplus'
        ? h('div', { className: 'space-y-1' },
            n.url
              ? h('a', {
                  href: n.url,
                  target: '_blank',
                  rel: 'noopener noreferrer',
                  className: 'text-xs font-bold text-main hover:text-accent leading-relaxed inline-block break-words'
                }, n.title || n.question || 'Huquq+ maqolasi')
              : h('h3', { className: 'text-xs font-bold text-main leading-relaxed' }, n.title || n.question || 'Huquq+ maqolasi'),
            n.wp_admin_url
              ? h('div', { className: 'pt-0.5' },
                  h('a', {
                    href: n.wp_admin_url,
                    target: '_blank',
                    rel: 'noopener noreferrer',
                    className: 'text-2xs text-accent underline inline-flex items-center gap-1'
                  }, 'WordPress‘da tahrirlash ↗')
                )
              : null
          )
        : (n.question ? h('h3', { className: 'text-xs font-bold text-main leading-relaxed' }, n.question) : null),
      n.resolution ? h('p', { className: 'text-2xs text-muted' }, `Hal etish: ${n.resolution}`) : null,
      diffGrid
    );

    if (n.status === 'open') {
      let btnRow;
      if (n.owner_type === 'huquqplus') {
        btnRow = h('div', { className: 'flex items-center gap-2 flex-wrap pt-1 border-t border-border' },
          Button({
            text: 'Maqola hali to‘g‘ri', variant: 'primary', size: 'sm',
            onClick: () => resolveNotif(n.id, 'keep', 'Maqola hali to‘g‘ri deb tasdiqlandi'),
          }),
          Button({
            text: 'Saytda yangiladim', variant: 'secondary', size: 'sm',
            onClick: () => resolveNotif(n.id, 'edited', 'Saytda yangilandi, qayta sinxronlandi'),
          }),
          Button({
            text: 'RAG‘dan vaqtincha olish', variant: 'secondary', size: 'sm',
            onClick: () => resolveNotif(n.id, 'unpublish', 'RAG dan vaqtincha olindi'),
          })
        );
      } else {
        btnRow = h('div', { className: 'flex items-center gap-2 flex-wrap pt-1 border-t border-border' },
          Button({
            text: 'Javob hali to‘g‘ri', variant: 'primary', size: 'sm',
            onClick: () => resolveNotif(n.id, 'keep', 'Javob hali to‘g‘ri deb tasdiqlandi'),
          }),
          Button({
            text: 'Tahrirlash', variant: 'secondary', size: 'sm',
            onClick: () => {
              try {
                sessionStorage.setItem('editorial_edit_answer',
                  JSON.stringify({ answerId: n.owner_id, notifId: n.id }));
              } catch { /* saqlanmasa ham navigatsiya ishlaydi */ }
              window.location.hash = 'qa';
            },
          }),
          Button({
            text: 'Nashrdan olish', variant: 'secondary', size: 'sm',
            onClick: () => resolveNotif(n.id, 'unpublish', ''),
          }),
          h('button', {
            type: 'button', className: 'btn btn-danger btn-sm',
            'aria-label': 'Javobni o‘chirish',
            onclick: () => confirmDeleteNotif(n),
          }, 'O‘chirish')
        );
      }
      card.appendChild(btnRow);
    }
    return card;
  }

  async function resolveNotif(id, action, note) {
    try {
      await api.editorialResolve(id, { action, note });
      showToast('Bildirishnoma hal qilindi', 'success');
      loadList();
    } catch (e) { showToast(e.message, 'danger'); }
  }

  function confirmDeleteNotif(n) {
    if (!deleteModal) {
      deleteModal = createModal({ id: 'modal-notif-delete', title: 'Javobni o‘chirish', maxWidth: '440px' });
      document.body.appendChild(deleteModal.element);
    }
    deleteModal.setContent([
      h('p', { className: 'text-xs text-main' },
        'Bog‘langan javob butunlay o‘chadi. Bu amalni ortga qaytarib bo‘lmaydi. Davom etasizmi?'),
    ]);
    deleteModal.setFooter([
      Button({ text: 'Bekor qilish', variant: 'secondary', onClick: () => deleteModal.close() }),
      Button({
        text: 'Ha, o‘chirish', variant: 'danger',
        onClick: async () => {
          try {
            await api.editorialResolve(n.id, { action: 'delete', note: 'Bildirishnomadan o‘chirildi' });
            showToast('Javob o‘chirildi', 'success');
            deleteModal.close();
            loadList();
          } catch (e) { showToast(e.message, 'danger'); }
        },
      }),
    ]);
    deleteModal.open();
  }

  return container;
}
