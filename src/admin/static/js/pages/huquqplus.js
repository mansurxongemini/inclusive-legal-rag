/**
 * Huquq+ Maqolalari (huquqplus.js) — huquqplus.uz maqolalari va tahlillari
 * SlideOver tafsilot paneli, oddiy til, markazlashgan boshqaruv.
 * WCAG 2.2 AA talablariga mos, innerHTML ishlatilmagan (faqat h() va textContent).
 */
import { h, clear } from '../dom.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import { Button } from '../../components/Button.js';
import { Badge } from '../../components/Badge.js';
import { EmptyState } from '../../components/EmptyState.js';
import { SkeletonCard } from '../../components/Skeleton.js';
import { createSlideOver } from '../../components/SlideOver.js';
import { showToast } from '../../components/Toast.js';

export function renderHuquqPlusPage() {
  const container = h('div', { className: 'space-y-4' });

  let langFilter = 'all';
  let statusFilter = 'all';
  let searchQuery = '';
  let searchTimeout = null;
  let activeSlideOver = null;

  // 1. Header & Sync action
  let isSyncing = false;
  const headerCard = h('div', { className: 'card-surface p-5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4' },
    h('div', {},
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Huquq+ maqolalari'),
        Badge({ label: 'huquqplus.uz', variant: 'neutral' })
      ),
      h('p', { className: 'text-xs text-muted mt-1' },
        'Sayt maqolalari va huquqiy tushuntirishlari RAG javoblarida amaliy tavsiyalar berish uchun ishlatiladi.'
      )
    ),
    Button({
      text: 'Hozir sinxronlash',
      icon: icons.refresh('icon-sm'),
      variant: 'primary',
      onClick: async () => {
        if (isSyncing) return;
        isSyncing = true;
        try {
          await api.huquqplusSync();
          showToast('Sinxronlash fonda boshlandi. Bu biroz vaqt olishi mumkin.', 'info');
          loadStatus();
          loadPosts();
        } catch (e) {
          showToast(`Sinxronlashda xatolik: ${e.message}`, 'error');
        } finally {
          isSyncing = false;
        }
      }
    })
  );

  // 2. Stats cards row
  const statsContainer = h('div', { className: 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3' });

  // 3. Filters row
  const searchInput = h('input', {
    type: 'text',
    className: 'input-text flex-1 min-w-[200px]',
    placeholder: 'Sarlavha yoki havola bo‘yicha qidirish...',
    oninput: (e) => {
      searchQuery = e.target.value.trim();
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(loadPosts, 300);
    }
  });

  const langSelect = h('select', {
    className: 'select-dropdown w-auto',
    onchange: (e) => {
      langFilter = e.target.value;
      loadPosts();
    }
  },
    h('option', { value: 'all' }, 'Barcha tillar'),
    h('option', { value: 'uz' }, 'O‘zbekcha (uz)'),
    h('option', { value: 'ru' }, 'Ruscha (ru)')
  );

  const statusSelect = h('select', {
    className: 'select-dropdown w-auto',
    onchange: (e) => {
      statusFilter = e.target.value;
      loadPosts();
    }
  },
    h('option', { value: 'all' }, 'Barcha holatlar'),
    h('option', { value: 'active' }, 'Faol'),
    h('option', { value: 'suspended' }, 'To‘xtatilgan'),
    h('option', { value: 'deleted' }, 'O‘chirilgan')
  );

  const filterRow = h('div', { className: 'card-surface p-3 flex flex-wrap items-center gap-2' },
    searchInput,
    langSelect,
    statusSelect
  );

  // 4. Posts list container
  const postsListEl = h('div', { className: 'space-y-2', role: 'list', 'aria-label': 'Maqolalar ro‘yxati' });

  container.appendChild(headerCard);
  container.appendChild(statsContainer);
  container.appendChild(filterRow);
  container.appendChild(postsListEl);

  loadStatus();
  loadPosts();

  async function loadStatus() {
    clear(statsContainer);
    for (let i = 0; i < 4; i++) {
      statsContainer.appendChild(SkeletonCard({ rows: 2 }));
    }

    try {
      const data = await api.huquqplusStatus();
      clear(statsContainer);

      let uzCount = 0;
      let ruCount = 0;
      (data.posts_summary || []).forEach(row => {
        if (row.status === 'active') {
          if (row.lang === 'uz') uzCount += Number(row.cnt || 0);
          if (row.lang === 'ru') ruCount += Number(row.cnt || 0);
        }
      });

      const lastRun = (data.last_runs || [])[0] || null;
      const lastRunMsg = lastRun
        ? (lastRun.finished_at ? lastRun.finished_at.slice(0, 16).replace('T', ' ') : 'Jarayonda')
        : 'Mavjud emas';

      statsContainer.appendChild(createStatCard(
        'Faol maqolalar',
        `${data.total_active_posts || 0} ta`,
        `O‘zbekcha: ${uzCount} | Ruscha: ${ruCount}`,
        icons.book
      ));

      statsContainer.appendChild(createStatCard(
        'Oxirgi sinxronlash',
        lastRunMsg,
        lastRun ? `+${lastRun.added || 0} yangi, ~${lastRun.updated || 0} yangilandi` : 'Bajarilmagan',
        icons.refresh
      ));

      statsContainer.appendChild(createStatCard(
        'Kuzatilayotgan havolalar',
        `${data.doc_level_refs_count || 0} ta`,
        'Baza qonunlariga bog‘langan havolalar',
        icons.check
      ));

      statsContainer.appendChild(createStatCard(
        'Korpusda yo‘q havolalar',
        `${data.missing_doc_refs_count || 0} ta`,
        'Bazada mavjud bo‘lmagan aktlar',
        icons.info || icons.chart
      ));
    } catch (e) {
      clear(statsContainer);
      statsContainer.appendChild(h('div', { className: 'col-span-full p-3 bg-surface-2 text-danger text-xs rounded-md' },
        `Statistika yuklashda xatolik: ${e.message}`
      ));
    }
  }

  function createStatCard(title, value, subtext, iconFn) {
    return h('div', { className: 'card-surface p-4 flex items-center justify-between gap-3' },
      h('div', {},
        h('p', { className: 'text-2xs font-semibold text-muted' }, title),
        h('p', { className: 'text-lg font-bold text-main mt-0.5 font-mono tabular-nums' }, value),
        h('p', { className: 'text-2xs text-subtle mt-0.5' }, subtext)
      ),
      h('div', { className: 'w-9 h-9 rounded-md bg-surface-2 flex items-center justify-center shrink-0 text-muted' }, iconFn('icon-sm'))
    );
  }

  async function loadPosts() {
    clear(postsListEl);
    for (let i = 0; i < 4; i++) {
      postsListEl.appendChild(SkeletonCard({ rows: 2 }));
    }

    try {
      const data = await api.huquqplusPosts({
        lang: langFilter,
        status: statusFilter,
        q: searchQuery,
        limit: 50,
        offset: 0
      });

      clear(postsListEl);
      const items = data.items || [];
      if (!items.length) {
        postsListEl.appendChild(EmptyState({
          icon: icons.search('icon-lg text-muted'),
          title: 'Maqolalar topilmadi',
          description: 'Qidiruv shartlariga mos keladigan maqola topilmadi.'
        }));
        return;
      }

      items.forEach(post => {
        postsListEl.appendChild(renderPostRow(post));
      });
    } catch (err) {
      clear(postsListEl);
      postsListEl.appendChild(EmptyState({
        icon: icons.close('icon-lg text-danger'),
        title: 'Yuklashda xatolik',
        description: err.message
      }));
    }
  }

  function renderPostRow(post) {
    const isSuspended = post.status === 'suspended';
    const isDeleted = post.status === 'deleted';
    const statusVariant = isSuspended ? 'warning' : isDeleted ? 'danger' : 'success';
    const statusLabel = isSuspended ? 'To‘xtatilgan' : isDeleted ? 'O‘chirilgan' : 'Faol';

    const allUnresolved = post.unresolved_links || [];
    const missingRefsCount = allUnresolved.filter(ref => !ref.law_id).length;

    const row = h('div', {
      className: 'card-surface p-3.5 flex items-center justify-between gap-3 cursor-pointer hover:border-accent hover:shadow-xs transition-all',
      onclick: () => openPostSlideOver(post)
    },
      h('div', { className: 'flex-1 min-w-0 space-y-1' },
        h('div', { className: 'flex items-center gap-2 flex-wrap' },
          Badge({ label: (post.lang || 'uz').toUpperCase(), variant: 'neutral' }),
          Badge({ label: statusLabel, variant: statusVariant }),
          h('span', { className: 'text-2xs text-muted font-mono' }, `ID: ${post.wp_id}`),
          post.modified ? h('span', { className: 'text-2xs text-subtle' }, post.modified.slice(0, 10)) : null
        ),
        h('h4', { className: 'text-xs font-semibold text-main truncate hover:text-accent' }, post.title || 'Sarlavhasiz maqola')
      ),
      h('div', { className: 'flex items-center gap-3 shrink-0 text-2xs text-muted' },
        missingRefsCount > 0
          ? Badge({ label: `${missingRefsCount} ta hujjat korpusda yo‘q`, variant: 'warning' })
          : Badge({ label: 'Bog‘langan', variant: 'neutral' }),
        icons.chevronRight('icon-xs text-muted')
      )
    );

    return row;
  }

  function openPostSlideOver(post) {
    if (activeSlideOver) activeSlideOver.close();

    const slideContent = h('div', { className: 'space-y-5' });

    let isResyncing = false;
    const resyncBtn = Button({
      text: 'Qayta sinxronlash',
      icon: icons.refresh('icon-sm text-muted'),
      variant: 'secondary',
      size: 'sm',
      onClick: async () => {
        if (isResyncing) return;
        isResyncing = true;
        resyncBtn.disabled = true;
        try {
          await api.huquqplusResyncPost(post.lang, post.wp_id);
          showToast('Maqola qayta sinxronlandi.', 'success');
          loadPosts();
          loadStatus();
        } catch (e) {
          showToast(`Xatolik: ${e.message}`, 'error');
        } finally {
          isResyncing = false;
          resyncBtn.disabled = false;
        }
      }
    });

    const wpLink = h('a', {
      href: `https://huquqplus.uz/wp-admin/post.php?post=${post.wp_id}&action=edit`,
      target: '_blank',
      rel: 'noopener noreferrer',
      className: 'btn btn-secondary btn-sm flex items-center gap-1.5'
    },
      h('span', {}, 'WordPress‘da tahrirlash'),
      icons.externalLink('icon-xs')
    );

    const publicLink = post.url && post.url.startsWith('https://')
      ? h('a', {
          href: post.url,
          target: '_blank',
          rel: 'noopener noreferrer',
          className: 'btn btn-secondary btn-sm flex items-center gap-1.5'
        },
          h('span', {}, 'Saytda ko‘rish'),
          icons.externalLink('icon-xs')
        )
      : null;

    // Actions bar
    const actionsBar = h('div', { className: 'flex items-center gap-2 flex-wrap pt-2 border-t border-border' },
      resyncBtn,
      wpLink,
      publicLink
    );

    // Metadata card
    const metaCard = h('div', { className: 'card-surface p-4 space-y-2.5 text-xs' },
      h('h3', { className: 'text-sm font-bold text-main leading-relaxed' }, post.title),
      h('div', { className: 'grid grid-cols-2 gap-2 pt-2 border-t border-border text-2xs' },
        h('div', {},
          h('span', { className: 'text-muted block' }, 'WordPress ID:'),
          h('span', { className: 'font-mono font-bold text-main' }, String(post.wp_id))
        ),
        h('div', {},
          h('span', { className: 'text-muted block' }, 'Tili:'),
          h('span', { className: 'font-semibold text-main' }, post.lang === 'ru' ? 'Rus tili' : 'O‘zbek tili')
        ),
        h('div', {},
          h('span', { className: 'text-muted block' }, 'Indekslangan bo‘laklar:'),
          h('span', { className: 'font-mono text-main' }, `${post.units_count || 0} ta qism`)
        ),
        h('div', {},
          h('span', { className: 'text-muted block' }, 'Oxirgi o‘zgarish:'),
          h('span', { className: 'font-mono text-main' }, post.modified ? post.modified.replace('T', ' ') : '-')
        )
      )
    );

    // References section
    const allUnresolved = post.unresolved_links || [];
    const missingDocs = allUnresolved.filter(ref => !ref.law_id);
    const linkedDocs = allUnresolved.filter(ref => ref.law_id);

    const linksSection = h('div', { className: 'space-y-3' });

    // 1. Bog'langan qonunlar
    const linkedHeader = h('h4', { className: 'text-xs font-bold text-main' }, 'Bog‘langan qonunchilik hujjatlari');
    const linkedList = h('div', { className: 'space-y-1.5' });

    if (linkedDocs.length === 0 && (post.resolved_links_count || 0) === 0) {
      linkedList.appendChild(h('p', { className: 'text-2xs text-muted' }, 'Qonun moddalariga to‘g‘ridan-to‘g‘ri bog‘lanmagan.'));
    } else {
      linkedDocs.forEach(item => {
        const itemUrl = (item.source_url && item.source_url.startsWith('https://'))
          ? item.source_url
          : (item.url && item.url.startsWith('https://') ? item.url : 'https://lex.uz/');

        let labelText = item.law_label || item.law_title || '';
        if (labelText) {
          const parts = labelText.split(' ');
          if (parts.length > 1 && !labelText.includes(' — ')) {
            labelText = `${parts[0]} — ${parts.slice(1).join(' ')}`;
          }
        } else {
          labelText = item.law_id || 'Qonun hujjati';
        }

        linkedList.appendChild(
          h('div', { className: 'p-2.5 rounded bg-surface-2 flex items-center justify-between text-2xs' },
            h('div', { className: 'space-y-0.5 min-w-0 pr-2' },
              h('span', { className: 'font-bold text-main leading-relaxed block' }, labelText)
            ),
            h('a', {
              href: itemUrl,
              target: '_blank',
              rel: 'noopener noreferrer',
              className: 'text-accent hover:underline flex items-center gap-1 shrink-0 ml-2'
            }, h('span', {}, 'Lex.uz'), icons.externalLink('icon-xs'))
          )
        );
      });
    }

    // 2. Korpusda yo'q havolalar (oddiy tilda)
    const missingSection = h('div', { className: 'space-y-2' });
    if (missingDocs.length > 0) {
      const missingList = h('div', { className: 'space-y-1.5' });
      missingDocs.forEach(item => {
        const lexId = item.doc_id || item.law_id || '';
        const itemUrl = item.url && item.url.startsWith('https://') ? item.url : 'https://lex.uz/';
        const docTitle = item.title || `Lex.uz hujjati #${lexId || 'nomalum'}`;

        missingList.appendChild(
          h('div', { className: 'p-2.5 rounded bg-warning-subtle border border-warning flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-2xs' },
            h('div', { className: 'space-y-0.5 min-w-0' },
              h('span', { className: 'font-bold text-main block' }, docTitle),
              h('p', { className: 'text-muted' }, 'Ushbu hujjat hozircha nogironlik huquqiy bazasiga kiritilmagan.')
            ),
            h('div', { className: 'flex items-center gap-2 shrink-0' },
              lexId ? Button({
                text: 'Bazaga qo‘shish',
                size: 'sm',
                variant: 'primary',
                onClick: () => {
                  window.location.hash = `documents?add=${encodeURIComponent(lexId)}`;
                }
              }) : null,
              h('a', {
                href: itemUrl,
                target: '_blank',
                rel: 'noopener noreferrer',
                className: 'btn btn-secondary btn-sm flex items-center gap-1'
              }, h('span', {}, 'Lex.uz'), icons.externalLink('icon-xs'))
            )
          )
        );
      });

      missingSection.appendChild(
        h('h4', { className: 'text-xs font-bold text-warning' }, `Korpusda yo‘q havolalar (${missingDocs.length} ta)`)
      );
      missingSection.appendChild(missingList);
    }

    linksSection.appendChild(linkedHeader);
    linksSection.appendChild(linkedList);
    if (missingDocs.length > 0) {
      linksSection.appendChild(missingSection);
    }

    slideContent.appendChild(metaCard);
    slideContent.appendChild(actionsBar);
    slideContent.appendChild(linksSection);

    activeSlideOver = createSlideOver({
      title: 'Maqola tafsilotlari',
      content: slideContent,
      size: 'md'
    });

    activeSlideOver.open();
  }

  return container;
}
