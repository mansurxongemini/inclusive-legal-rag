/**
 * Huquq+ maqolalari va sinxronlash sahifasi.
 * huquqplus.uz maqolalari ro'yxati, holat ko'rsatkichlari, sinxronlash va qayta sinxronlash.
 * XSS-himoyalangan: barcha matnlar textContent orqali chiqariladi (innerHTML taqiqlangan).
 */
import { h, clear } from '../dom.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import { Button } from '../../components/Button.js';
import { Badge } from '../../components/Badge.js';
import { EmptyState } from '../../components/EmptyState.js';
import { SkeletonCard } from '../../components/Skeleton.js';
import { showToast } from '../../components/Toast.js';

export function renderHuquqPlusPage() {
  const container = h('div', { className: 'space-y-4' });

  let langFilter = 'all';
  let statusFilter = 'all';
  let searchQuery = '';
  let searchTimeout = null;

  // 1. Header & Sync action
  const headerCard = h('div', { className: 'card-surface p-5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4' },
    h('div', {},
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Huquq+ maqolalari va sinxronlash'),
        Badge({ text: 'huquqplus.uz', variant: 'primary' })
      ),
      h('p', { className: 'text-xs text-muted mt-1' },
        'Portal maqolalari RAG bazasiga sinxronlashadi va savollarga amaliy tushuntirish berishda ishlatiladi.'
      )
    ),
    Button({
      text: 'Hozir sinxronlash',
      icon: icons.refresh('icon-sm'),
      variant: 'primary',
      onClick: async () => {
        try {
          await api.huquqplusSync();
          showToast("To'liq sinxronlash fonda boshlandi. Jarayon biroz vaqt olishi mumkin.", 'success');
          loadStatus();
          loadPosts();
        } catch (e) {
          showToast(e.message, 'danger');
        }
      }
    })
  );

  // 2. Stats cards row
  const statsContainer = h('div', { className: 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3' });

  // 3. Filters row
  const searchInput = h('input', {
    type: 'text',
    className: 'input input-sm flex-1 min-w-[200px]',
    placeholder: 'Sarlavha yoki havola bo‘yicha qidirish...',
    oninput: (e) => {
      searchQuery = e.target.value.trim();
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => loadPosts(), 350);
    }
  });

  const langSelect = h('select', {
    className: 'input input-sm w-auto',
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
    className: 'input input-sm w-auto',
    onchange: (e) => {
      statusFilter = e.target.value;
      loadPosts();
    }
  },
    h('option', { value: 'all' }, 'Barcha holatlar'),
    h('option', { value: 'active' }, 'Faol (active)'),
    h('option', { value: 'suspended' }, 'To‘xtatilgan (suspended)'),
    h('option', { value: 'deleted' }, 'O‘chirilgan (deleted)')
  );

  const filterRow = h('div', { className: 'card-surface p-3 flex flex-wrap items-center gap-2' },
    searchInput,
    langSelect,
    statusSelect
  );

  // 4. Posts list container
  const postsListEl = h('div', { className: 'space-y-3', role: 'list', 'aria-label': 'Maqolalar ro‘yxati' });

  container.appendChild(headerCard);
  container.appendChild(statsContainer);
  container.appendChild(filterRow);
  container.appendChild(postsListEl);

  // Initial load
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

      const queuePending = (data.queue_stats || {}).pending || 0;
      const lastRun = (data.last_runs || [])[0] || null;
      const lastRunMsg = lastRun
        ? `${lastRun.finished_at ? lastRun.finished_at.slice(0, 16).replace('T', ' ') : 'Jarayonda'}`
        : 'Mavjud emas';

      // Card 1: Active posts
      statsContainer.appendChild(createStatCard(
        'Faol maqolalar',
        `${data.total_active_posts || 0} ta`,
        `O‘zbekcha: ${uzCount} | Ruscha: ${ruCount}`,
        icons.book('icon-md text-primary')
      ));

      // Card 2: Last sync
      statsContainer.appendChild(createStatCard(
        'Oxirgi sinxronlash',
        lastRunMsg,
        lastRun ? `+${lastRun.added || 0} yangi, ~${lastRun.updated || 0} yangilandi` : 'Hali bajarilmagan',
        icons.refresh('icon-md text-success')
      ));

      // Card 3: Queue status
      statsContainer.appendChild(createStatCard(
        'Webhook navbati',
        `${queuePending} kutilmoqda`,
        `Bajarilgan: ${(data.queue_stats || {}).done || 0} ta`,
        icons.cpu('icon-md text-warning')
      ));

      // Card 4: Unresolved links
      statsContainer.appendChild(createStatCard(
        'Korpusda yo‘q hujjatlarga havolalar',
        `${data.missing_doc_refs_count || 0} ta`,
        `${data.doc_level_refs_count || 0} ta havola hujjat darajasida kuzatiladi`,
        icons.info ? icons.info('icon-md text-danger') : icons.chart('icon-md text-danger')
      ));
    } catch (e) {
      clear(statsContainer);
      statsContainer.appendChild(h('div', { className: 'col-span-full p-3 bg-surface-2 text-danger text-xs rounded-md' },
        `Statistika yuklashda xatolik: ${e.message}`
      ));
    }
  }

  function createStatCard(title, value, subtext, icon) {
    return h('div', { className: 'card-surface p-4 flex items-center justify-between gap-3' },
      h('div', {},
        h('p', { className: 'text-2xs font-semibold text-muted' }, title),
        h('p', { className: 'text-lg font-bold text-main mt-0.5' }, value),
        h('p', { className: 'text-2xs text-subtle mt-0.5' }, subtext)
      ),
      h('div', { className: 'w-10 h-10 rounded-lg bg-surface-2 flex items-center justify-center shrink-0' }, icon)
    );
  }

  async function loadPosts() {
    clear(postsListEl);
    for (let i = 0; i < 3; i++) {
      postsListEl.appendChild(SkeletonCard({ rows: 3 }));
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
          icon: icons.search('icon-lg'),
          title: 'Maqolalar topilmadi',
          description: 'Berilgan qidiruv yoki filtr shartlariga mos maqola mavjud emas.'
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

    // references to acts that are in the corpus are watched as a whole act; only the rest are real gaps
    const allUnresolved = post.unresolved_links || [];
    const unresolvedLinks = allUnresolved.filter(ref => !ref.law_id);
    const docLevelCount = allUnresolved.length - unresolvedLinks.length;

    const titleLink = h('a', {
      href: post.url,
      target: '_blank',
      rel: 'noopener noreferrer',
      className: 'text-xs font-bold text-main hover:text-accent leading-relaxed inline-block break-words'
    }, post.title || 'Sarlavhasiz maqola');

    const resyncBtn = Button({
      text: 'Qayta sinxronlash',
      variant: 'secondary',
      size: 'sm',
      onClick: async () => {
        try {
          await api.huquqplusResyncPost(post.lang, post.wp_id);
          showToast(`Maqola (${post.wp_id}) qayta sinxronlandi`, 'success');
          loadPosts();
          loadStatus();
        } catch (e) {
          showToast(`Xatolik: ${e.message}`, 'danger');
        }
      }
    });

    const wpEditLink = h('a', {
      href: `https://huquqplus.uz/wp-admin/post.php?post=${post.wp_id}&action=edit`,
      target: '_blank',
      rel: 'noopener noreferrer',
      className: 'btn btn-secondary btn-sm inline-flex items-center gap-1'
    }, 'WordPress tahrirlash');

    // Unresolved refs container
    let unresolvedBox = null;
    if (unresolvedLinks.length > 0) {
      const refItems = unresolvedLinks.map(ref => {
        return h('li', { className: 'text-2xs text-muted flex items-center gap-1.5' },
          h('span', { className: 'font-mono text-warning font-semibold' }, `doc_id: ${ref.doc_id}`),
          h('a', {
            href: ref.url,
            target: '_blank',
            rel: 'noopener noreferrer',
            className: 'text-accent underline truncate max-w-xs'
          }, ref.url)
        );
      });

      unresolvedBox = h('div', { className: 'p-2.5 bg-surface-2 rounded border border-border mt-2' },
        h('p', { className: 'text-2xs font-bold text-warning mb-1' },
          `Korpusda yo‘q hujjatlarga havolalar (${unresolvedLinks.length} ta):`
        ),
        h('ul', { className: 'space-y-1 list-disc list-inside' }, ...refItems)
      );
    }

    const card = h('div', { className: 'card-surface p-4 space-y-2.5', role: 'listitem' },
      h('div', { className: 'flex items-start justify-between gap-3 flex-wrap' },
        h('div', { className: 'flex-1 min-w-[240px]' },
          h('div', { className: 'flex items-center gap-2 flex-wrap mb-1' },
            Badge({ text: (post.lang || 'uz').toUpperCase(), variant: 'neutral' }),
            Badge({ text: statusLabel, variant: statusVariant }),
            h('span', { className: 'text-2xs text-subtle font-mono' }, `ID: ${post.wp_id}`),
            h('span', { className: 'text-2xs text-muted' }, `Bo‘laklar: ${post.units_count || 0} ta`),
            h('span', { className: 'text-2xs text-muted' }, `Kuzatiladi: ${post.resolved_links_count || 0} modda, ${docLevelCount} hujjat`)
          ),
          titleLink
        ),
        h('div', { className: 'flex items-center gap-2 shrink-0' },
          wpEditLink,
          resyncBtn
        )
      ),
      h('div', { className: 'flex items-center justify-between text-2xs text-subtle pt-1 border-t border-border flex-wrap gap-2' },
        h('span', {}, `O‘zgartirilgan: ${post.modified ? post.modified.replace('T', ' ') : 'Noma‘lum'}`),
        h('span', {}, `Sinxronlangan: ${post.synced_at ? post.synced_at.slice(0, 19).replace('T', ' ') : 'Noma‘lum'}`)
      ),
      unresolvedBox
    );

    return card;
  }

  return container;
}
