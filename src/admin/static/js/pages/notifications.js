/**
 * Tahririyat — Bildirishnomalar sahifasi.
 * Lex.uz moddasi o'zgarganda/kuchini yo'qotganda tushadigan bildirishnomalar.
 * Barcha matn textContent va h() orqali chiqariladi (innerHTML taqiqlangan).
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

function formatResolution(res) {
  if (!res) return '';
  const r = String(res);
  const prefix = r.split(':')[0];
  if (prefix === 'keep') return 'Hali to‘g‘ri deb tasdiqlandi';
  if (prefix === 'edited') return 'Saytda/javobda yangilandi';
  if (prefix === 'unpublish') return 'AI‘dan olib turilgan';
  if (prefix === 'delete') return 'O‘chirilgan';
  if (r === 'corpus_widened' || r === 'auto:no_real_change' || prefix === 'auto') {
    return 'Avtomatik yopildi: Lex.uz‘da matn o‘zgarmagan';
  }
  if (prefix === 'article_updated') return 'Maqola yangilangani uchun yopildi';
  return r;
}

/** So'z darajasida diff (LCS): [{t:'same'|'del'|'ins', w}]. Katta matnlar 2000 belgigacha kesiladi. */
export function wordDiff(oldText, newText) {
  const a = (oldText || '').slice(0, 2000).split(/(\s+)/);
  const b = (newText || '').slice(0, 2000).split(/(\s+)/);
  const n = a.length, m = b.length;
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
      text: 'Hozir tekshirish', icon: icons.refresh ? icons.refresh('icon-sm') : null, variant: 'secondary',
      onClick: async () => {
        try {
          const res = await api.editorialCheckLinks();
          showToast(`Tekshirildi: ${res.checked_links} ta bog‘lanish, ${res.new_notifications} ta yangi`, 'success');
          loadList();
        } catch (e) { showToast(e.message, 'danger'); }
      },
    })
  );

  // Tepada yig'iladigan izoh
  const helpDetails = h('details', {
    className: 'card-surface p-4 text-xs',
    open: true,
  },
    h('summary', { className: 'cursor-pointer font-bold text-main select-none flex items-center justify-between' },
      h('span', { className: 'inline-flex items-center gap-1.5' },
        'Bu nima va nima qilish kerak?'
      )
    ),
    h('div', { className: 'mt-2.5 text-xs text-muted leading-relaxed space-y-1.5 pt-2 border-t border-border' },
      h('p', {}, 'Huquq+ maqolasi yoki tayyor javob tayangan qonun bandi Lex.uz‘da o‘zgarsa, shu yerga xabar keladi.'),
      h('p', {}, '1) Quyida bandning avvalgi va yangi matnini solishtiring.'),
      h('p', {}, '2) Maqoladagi maʼlumot hali to‘g‘rimi — tekshiring.'),
      h('p', {}, '3) Tugmalardan birini tanlang. Siz qaror qilguningizcha AI bu maqoladan foydalanmaydi.')
    )
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
  container.appendChild(helpDetails);
  container.appendChild(filterRow);
  container.appendChild(listEl);

  loadList();

  async function loadList() {
    clear(listEl);
    for (let i = 0; i < 3; i++) listEl.appendChild(SkeletonCard({ rows: 3 }));
    try {
      const data = await api.editorialNotifications({ status: statusFilter, limit: 50, offset: 0 });
      const openCount = data.open_count || 0;
      badgeOpen.textContent = `${openCount} ta ochiq`;
      helpDetails.open = openCount > 0;

      const items = data.items || [];
      clear(listEl);
      if (!items.length) {
        listEl.appendChild(EmptyState({
          icon: icons.check ? icons.check('icon-lg') : null,
          title: statusFilter === 'open' ? 'Ochiq bildirishnoma yo‘q' : 'Bildirishnoma topilmadi',
          description: 'Bog‘langan moddalar o‘zgarmagan. Hammasi joyida.',
        }));
        return;
      }
      items.forEach((n) => listEl.appendChild(renderCard(n)));
    } catch (err) {
      clear(listEl);
      listEl.appendChild(EmptyState({
        icon: icons.close ? icons.close('icon-lg text-danger') : null,
        title: 'Yuklashda xatolik',
        description: err.message,
      }));
    }
  }

  function renderCard(n) {
    const isHp = n.owner_kind === 'huquqplus' || n.owner_type === 'huquqplus';
    const ownerBadgeText = isHp ? 'Huquq+ maqolasi' : 'Tayyor javob';
    const ownerBadgeVariant = isHp ? 'primary' : 'neutral';

    // Holat jumlasi
    const lawRef = n.law_label || 'hujjat';
    const ownerNoun = isHp ? 'maqola' : 'javob';
    let statusSentenceText = `Bu ${ownerNoun} tayangan ${lawRef} Lex.uz‘da o‘zgardi.`;
    if (n.kind === 'norm_repealed') {
      statusSentenceText = `Bu ${ownerNoun} tayangan ${lawRef} Lex.uz‘da kuchini yo‘qotdi.`;
    } else if (n.kind === 'norm_removed') {
      statusSentenceText = `Bu ${ownerNoun} tayangan ${lawRef} Lex.uz‘da olib tashlandi.`;
    }
    const statusSentence = h('p', { className: 'text-2xs text-main font-medium' }, statusSentenceText);

    // AI paused bildirishnomasi
    const aiPausedNotice = n.ai_paused
      ? h('div', { className: 'p-2.5 bg-amber-500/10 text-amber-700 dark:text-amber-400 rounded-md text-2xs font-medium flex items-center gap-1.5 border border-amber-500/20' },
          `⏸ AI hozir bu ${isHp ? 'maqoladan' : 'javobdan'} foydalanmayapti — siz qaror qilguningizcha.`
        )
      : null;

    // Changes bloklari
    let changesBlock;
    if (n.changes && n.changes.length > 0) {
      const changeItems = n.changes.map((ch) => {
        let chBadgeText = 'O‘zgartirildi';
        let chBadgeVar = 'warning';
        if (ch.kind === 'repealed') {
          chBadgeText = 'Kuchini yo‘qotdi';
          chBadgeVar = 'danger';
        } else if (ch.kind === 'removed') {
          chBadgeText = 'Olib tashlandi';
          chBadgeVar = 'danger';
        }

        const head = h('div', { className: 'flex items-center gap-2 flex-wrap mb-1.5' },
          h('span', { className: 'text-2xs font-bold text-main' }, ch.label || 'Band'),
          Badge({ text: chBadgeText, variant: chBadgeVar }),
          (ch.url && /^https:\/\/lex\.uz\//.test(ch.url))
            ? h('a', {
                href: ch.url,
                target: '_blank',
                rel: 'noopener noreferrer',
                className: 'text-2xs text-accent underline inline-flex items-center gap-0.5 ml-auto'
              }, 'Lex.uz‘da ochish ↗')
            : null
        );

        let body;
        if (ch.old_text && ch.new_text) {
          const diff = wordDiff(ch.old_text, ch.new_text);
          const leftBox = h('div', { className: 'p-2.5 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text max-h-72 overflow-y-auto' });
          const rightBox = h('div', { className: 'p-2.5 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text max-h-72 overflow-y-auto' });
          renderTokens(leftBox, diff.left);
          renderTokens(rightBox, diff.right);
          body = h('div', { className: 'grid grid-cols-1 md:grid-cols-2 gap-2 mt-1' },
            h('div', {}, h('p', { className: 'text-2xs font-bold text-muted mb-1' }, 'Avval'), leftBox),
            h('div', {}, h('p', { className: 'text-2xs font-bold text-muted mb-1' }, 'Hozir'), rightBox)
          );
        } else {
          const txt = ch.new_text || ch.old_text || '';
          const isLong = txt.length > 400;
          let expanded = false;
          const textContainer = h('div', { className: 'p-2.5 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text' },
            isLong ? txt.slice(0, 400) + '...' : txt
          );
          const toggleBtn = isLong
            ? h('button', {
                type: 'button',
                className: 'text-2xs text-accent hover:underline mt-1 inline-block',
                onclick: () => {
                  expanded = !expanded;
                  textContainer.textContent = expanded ? txt : (txt.slice(0, 400) + '...');
                  toggleBtn.textContent = expanded ? 'Qisqartirish' : 'To‘liq ko‘rsatish';
                }
              }, 'To‘liq ko‘rsatish')
            : null;
          body = h('div', { className: 'mt-1' },
            h('p', { className: 'text-2xs font-bold text-muted mb-1' }, ch.new_text ? 'Matn' : 'Eski matn'),
            textContainer,
            toggleBtn
          );
        }

        return h('div', { className: 'p-3 bg-surface-1 rounded-lg border border-border space-y-1' }, head, body);
      });

      const addedNotice = (n.added_count && n.added_count > 0)
        ? h('p', { className: 'text-2xs text-muted italic pt-1' }, `Hujjatga yana ${n.added_count} ta yangi band qo‘shilgan.`)
        : null;

      changesBlock = h('div', { className: 'space-y-2' }, ...changeItems, addedNotice);
    } else {
      // Fallback
      const isDocLink = (n.canonical_id || '').startsWith('law:');
      if (isDocLink) {
        changesBlock = h('div', { className: 'p-3 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text' }, n.new_text || '');
      } else if (n.old_text && n.new_text) {
        const diff = wordDiff(n.old_text, n.new_text);
        const leftBox = h('div', { className: 'p-2.5 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text' });
        const rightBox = h('div', { className: 'p-2.5 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text' });
        renderTokens(leftBox, diff.left);
        renderTokens(rightBox, diff.right);
        changesBlock = h('div', { className: 'grid grid-cols-1 md:grid-cols-2 gap-2' },
          h('div', {}, h('p', { className: 'text-2xs font-bold text-muted mb-1' }, 'Avval'), leftBox),
          h('div', {}, h('p', { className: 'text-2xs font-bold text-muted mb-1' }, 'Hozir'), rightBox)
        );
      } else {
        changesBlock = h('div', { className: 'p-2.5 bg-surface-2 rounded-md border border-border text-2xs leading-relaxed whitespace-pre-wrap select-text' }, n.new_text || n.old_text || '');
      }
    }

    const card = h('div', { className: 'card-surface p-4 space-y-3', role: 'listitem' },
      h('div', { className: 'flex items-center gap-2 flex-wrap' },
        Badge({ text: KIND_LABELS[n.kind] || n.kind, variant: kindVariant(n.kind) }),
        Badge({ text: ownerBadgeText, variant: ownerBadgeVariant }),
        n.status !== 'open' ? Badge({ text: n.status === 'resolved' ? 'Hal qilingan' : 'Yopilgan', variant: 'neutral' }) : null,
        h('span', { className: 'text-2xs text-subtle font-mono' }, n.canonical_id || '')
      ),
      isHp
        ? h('div', { className: 'space-y-1' },
            (n.url && /^https:\/\//.test(n.url))
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
      statusSentence,
      aiPausedNotice,
      n.resolution ? h('p', { className: 'text-2xs text-muted font-medium' }, `Hal etish: ${formatResolution(n.resolution)}`) : null,
      changesBlock
    );

    if (n.status === 'open') {
      let actionSection;
      if (isHp) {
        actionSection = h('div', { className: 'pt-3 border-t border-border space-y-2' },
          h('div', { className: 'flex items-center gap-2 flex-wrap' },
            Button({
              text: 'Maqola hali to‘g‘ri', variant: 'primary', size: 'sm',
              onClick: () => resolveNotif(n.id, 'keep', 'Maqola hali to‘g‘ri deb tasdiqlandi'),
            }),
            Button({
              text: 'Saytda yangiladim', variant: 'secondary', size: 'sm',
              onClick: () => resolveNotif(n.id, 'edited', 'Saytda yangilandi, qayta sinxronlandi'),
            }),
            Button({
              text: 'AI‘dan vaqtincha olish', variant: 'secondary', size: 'sm',
              onClick: () => resolveNotif(n.id, 'unpublish', 'AI dan vaqtincha olindi'),
            })
          ),
          h('div', { className: 'space-y-1 text-2xs text-muted pt-1 border-t border-border/50' },
            h('p', {}, '• ', h('span', { className: 'font-semibold text-main' }, 'Maqola hali to‘g‘ri:'), ' O‘zgarish maqoladagi maʼlumotga taʼsir qilmaydi. Xabar yopiladi, AI maqoladan yana foydalanadi.'),
            h('p', {}, '• ', h('span', { className: 'font-semibold text-main' }, 'Saytda yangiladim:'), ' Maqolani WordPress‘da tuzatib bo‘ldingiz. Tizim yangi matnni saytdan oladi.'),
            h('p', {}, '• ', h('span', { className: 'font-semibold text-main' }, 'AI‘dan vaqtincha olish:'), ' Maqolani tuzatguningizcha AI undan foydalanmaydi. Saytda yangilaganingizdan keyin avtomatik qaytadi.')
          )
        );
      } else {
        actionSection = h('div', { className: 'pt-3 border-t border-border space-y-2' },
          h('div', { className: 'flex items-center gap-2 flex-wrap' },
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
          ),
          h('div', { className: 'space-y-1 text-2xs text-muted pt-1 border-t border-border/50' },
            h('p', {}, '• ', h('span', { className: 'font-semibold text-main' }, 'Javob hali to‘g‘ri:'), ' O‘zgarish javob mazmuniga taʼsir qilmaydi. Havola yangilanadi, javob qayta eʼlon qilinadi.'),
            h('p', {}, '• ', h('span', { className: 'font-semibold text-main' }, 'Tahrirlash:'), ' Javob matnini yoki huquqiy asosini tahrirlash sahifasida yangilash.'),
            h('p', {}, '• ', h('span', { className: 'font-semibold text-main' }, 'Nashrdan olish:'), ' Javob arxivlanadi va AI qidiruvidan butunlay olinadi.'),
            h('p', {}, '• ', h('span', { className: 'font-semibold text-main' }, 'O‘chirish:'), ' Javob va uning barcha havolalari butunlay o‘chiriladi.')
          )
        );
      }
      card.appendChild(actionSection);
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
