/**
 * Umumiy Holat (Stats) Sahifasi — Tizim ko'rsatkichlari va umumiy holat
 * Zero-build native ES modul, WCAG 2.2 AA talablariga mos, doimiy ochiq rang mavzusi.
 */
import { h, clear } from '../dom.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import { Button } from '../../components/Button.js';
import { Badge } from '../../components/Badge.js';
import { EmptyState } from '../../components/EmptyState.js';
import { SkeletonCard } from '../../components/Skeleton.js';
import { categoryLabel as getDomainLabel } from '../labels.js';


export function renderStatsPage() {
  const container = h('div', { className: 'space-y-6' });

  let showAllCategories = false;
  let cachedData = null;

  const lastUpdatedEl = h('span', { className: 'text-2xs text-muted font-mono tabular-nums' }, '');
  const refreshBtn = Button({
    text: 'Yangilash',
    icon: icons.refresh('icon-sm text-muted'),
    variant: 'secondary',
    size: 'sm',
    onClick: () => loadData()
  });

  const header = h('div', { className: 'card-surface p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4' },
    h('div', { className: 'space-y-1' },
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Tizimning umumiy holati'),
        Badge({ label: 'Jonli monitoring', variant: 'neutral' })
      ),
      h('p', { className: 'text-xs text-muted' },
        'Lex.uz qonunlari, Huquq+ maqolalari, tahririyat savol-javoblari va API integratsiyalari holati.'
      )
    ),
    h('div', { className: 'flex items-center gap-3' },
      lastUpdatedEl,
      refreshBtn
    )
  );

  const metricsGrid = h('div', { className: 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4' });
  const categoryCard = h('div', { className: 'card-surface p-5 space-y-4' });
  const statusCard = h('div', { className: 'card-surface p-5 space-y-4' });

  const twoColLayout = h('div', { className: 'grid grid-cols-1 lg:grid-cols-3 gap-6' },
    h('div', { className: 'lg:col-span-2' }, categoryCard),
    h('div', {}, statusCard)
  );

  container.appendChild(header);
  container.appendChild(metricsGrid);
  container.appendChild(twoColLayout);

  async function loadData() {
    clear(metricsGrid);
    clear(categoryCard);
    clear(statusCard);

    for (let i = 0; i < 8; i++) {
      metricsGrid.appendChild(SkeletonCard({ rows: 1 }));
    }
    categoryCard.appendChild(SkeletonCard({ rows: 5 }));
    statusCard.appendChild(SkeletonCard({ rows: 3 }));

    try {
      const stats = await api.getAdminStats();
      cachedData = stats;

      renderMetrics(stats);
      renderCategories(stats);
      renderStatuses(stats);

      const now = new Date();
      const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
      lastUpdatedEl.textContent = `Yangilandi: ${timeStr}`;

    } catch (err) {
      clear(metricsGrid);
      clear(categoryCard);
      clear(statusCard);

      metricsGrid.appendChild(
        h('div', { className: 'col-span-full' },
          EmptyState({
            icon: icons.close('icon-lg text-danger'),
            title: 'Statistikani yuklashda xatolik',
            description: err.message,
            action: Button({
              text: 'Qayta urinish',
              icon: icons.refresh('icon-sm'),
              onClick: () => loadData()
            })
          })
        )
      );
    }
  }

  function renderMetrics(data) {
    clear(metricsGrid);

    const items = [
      {
        title: 'Lex.uz rasmiy aktlari',
        value: Number(data.lex_documents_count || data.total_documents || 0).toLocaleString('uz-UZ'),
        subtitle: 'Bazada mavjud qonun va me‘yoriy hujjatlar',
        icon: icons.book,
        hash: 'documents'
      },
      {
        title: 'Lex.uz qonun bandlari',
        value: Number(data.lex_articles_count || data.total_articles || 0).toLocaleString('uz-UZ'),
        subtitle: 'Indekslangan va vektorlangan moddalar/bandlar',
        icon: icons.book,
        hash: 'documents'
      },
      {
        title: 'Faol Huquq+ maqolalari',
        value: Number(data.huquqplus_active_posts || 0).toLocaleString('uz-UZ'),
        subtitle: `${data.huquqplus_uz_count || 0} o‘zbekcha / ${data.huquqplus_ru_count || 0} ruscha`,
        icon: icons.book,
        hash: 'huquqplus'
      },
      {
        title: 'Nashrdagi savol-javoblar',
        value: Number(data.published_qa_count || 0).toLocaleString('uz-UZ'),
        subtitle: 'Qonun moddalariga bog‘langan tahririyat javoblari',
        icon: icons.edit,
        hash: 'qa'
      },
      {
        title: 'Ochiq bildirishnomalar',
        value: Number(data.open_notifications_count || 0).toLocaleString('uz-UZ'),
        subtitle: 'Ko‘rib chiqilishi kerak bo‘lgan qonun o‘zgarishlari',
        icon: icons.bell || icons.refresh,
        hash: 'notifications',
        alert: (data.open_notifications_count || 0) > 0
      },
      {
        title: 'Faol API mijozlari',
        value: Number(data.active_api_clients || 0).toLocaleString('uz-UZ'),
        subtitle: 'Yordamchi botlar va tashqi portallar',
        icon: icons.key,
        hash: 'integrations'
      },
      {
        title: 'Xizmat ko‘rsatilgan so‘rovlar',
        value: Number(data.total_requests_served || 0).toLocaleString('uz-UZ'),
        subtitle: 'API orqali berilgan savol-javoblar',
        icon: icons.chart,
        hash: 'integrations'
      },
      {
        title: 'Tizim xotirasi (RAM)',
        value: data.rss_memory_mb ? `${Math.round(data.rss_memory_mb)} MB` : 'Faol',
        subtitle: 'Tezkor xotira va vektor do‘koni holati',
        icon: icons.cpu,
        hash: null
      }
    ];

    items.forEach(item => {
      const card = h('div', {
        className: `card-surface p-4 flex flex-col justify-between space-y-2 transition-all ${item.hash ? 'cursor-pointer hover:border-accent hover:shadow-xs' : ''} ${item.alert ? 'border-warning bg-warning-subtle' : ''}`,
        onclick: () => {
          if (item.hash) {
            window.location.hash = item.hash;
          }
        }
      },
        h('div', { className: 'flex items-center justify-between' },
          h('span', { className: 'text-2xs font-medium text-muted uppercase tracking-wider' }, item.title),
          h('span', { className: item.alert ? 'text-warning' : 'text-muted' }, item.icon('icon-sm'))
        ),
        h('div', { className: 'space-y-0-5' },
          h('div', { className: 'text-xl font-bold text-main font-mono tabular-nums tracking-tight' }, item.value),
          h('p', { className: 'text-2xs text-muted' }, item.subtitle)
        )
      );
      metricsGrid.appendChild(card);
    });
  }

  function renderCategories(data) {
    clear(categoryCard);

    const catList = Object.entries(data.categories || {})
      .map(([key, count]) => ({ key, label: getDomainLabel(key), count }))
      .sort((a, b) => b.count - a.count);

    const total = data.total_articles || 1;
    const maxCount = catList.length > 0 ? catList[0].count : 1;
    const visibleItems = showAllCategories ? catList : catList.slice(0, 8);

    const cardHeader = h('div', { className: 'flex items-center justify-between pb-3 border-b border-border' },
      h('div', {},
        h('h3', { className: 'text-sm font-bold text-main' }, 'Huquqiy sohalar bo‘yicha taqsimot'),
        h('p', { className: 'text-2xs text-muted mt-0-5' }, 'Lex.uz qonun bandlarining sohalar bo‘yicha ulushi')
      ),
      Badge({ label: `${catList.length} ta soha`, variant: 'neutral' })
    );

    const barsList = h('div', { className: 'space-y-3 pt-1' });

    visibleItems.forEach((item, idx) => {
      const percentage = ((item.count / total) * 100).toFixed(1);
      const barWidth = Math.max(4, Math.round((item.count / maxCount) * 100));

      const row = h('div', { className: 'space-y-1.5' },
        h('div', { className: 'flex items-center justify-between text-xs' },
          h('span', { className: 'text-main font-medium truncate pr-2' }, item.label),
          h('div', { className: 'flex items-center gap-2 font-mono text-2xs tabular-nums text-muted flex-shrink-0' },
            h('span', { className: 'font-semibold text-main' }, `${item.count} ta`),
            h('span', { className: 'text-subtle' }, `(${percentage}%)`)
          )
        ),
        h('div', { className: 'w-full bg-surface-2 h-2 rounded-full overflow-hidden' },
          h('div', {
            className: 'bg-accent h-full rounded-full transition-all',
            style: `width: ${barWidth}%; opacity: ${idx === 0 ? '1' : '0.70'};`
          })
        )
      );

      barsList.appendChild(row);
    });

    categoryCard.appendChild(cardHeader);
    categoryCard.appendChild(barsList);

    if (catList.length > 8) {
      const toggleBtn = h('div', { className: 'pt-2 border-t border-border flex justify-center' },
        Button({
          text: showAllCategories ? 'Kamroq ko‘rsatish' : `Barchasini ko‘rsatish (+${catList.length - 8})`,
          icon: showAllCategories ? icons.chevronUp('icon-xs') : icons.chevronDown('icon-xs'),
          variant: 'secondary',
          size: 'sm',
          onClick: () => {
            showAllCategories = !showAllCategories;
            renderCategories(cachedData);
          }
        })
      );
      categoryCard.appendChild(toggleBtn);
    }
  }

  function renderStatuses(data) {
    clear(statusCard);

    const activeCount = data.statuses?.active ?? data.total_articles;
    const repealedCount = data.statuses?.repealed ?? 0;
    const total = activeCount + repealedCount || 1;

    const activePct = ((activeCount / total) * 100).toFixed(1);
    const repealedPct = ((repealedCount / total) * 100).toFixed(1);

    const cardHeader = h('div', { className: 'pb-3 border-b border-border' },
      h('h3', { className: 'text-sm font-bold text-main' }, 'Qonuniy maqomi'),
      h('p', { className: 'text-2xs text-muted mt-0-5' }, 'Normalarning amaldagi va bekor qilinganlik holati')
    );

    const ratioBar = h('div', { className: 'space-y-2' },
      h('div', { className: 'w-full bg-surface-2 h-2.5 rounded-full overflow-hidden flex' },
        h('div', { className: 'bg-accent h-full', style: `width: ${activePct}%;`, title: `Amalda: ${activePct}%` }),
        h('div', { className: 'bg-border h-full', style: `width: ${repealedPct}%;`, title: `Bekor qilingan: ${repealedPct}%` })
      ),
      h('div', { className: 'flex justify-between text-2xs text-subtle font-mono tabular-nums' },
        h('span', {}, `Amalda: ${activePct}%`),
        h('span', {}, `Bekor qilingan: ${repealedPct}%`)
      )
    );

    const list = h('div', { className: 'space-y-3 pt-2' },
      h('div', { className: 'flex items-center justify-between p-3 rounded-md bg-surface-2' },
        h('div', { className: 'flex items-center gap-2' },
          h('span', { className: 'w-2.5 h-2.5 rounded-full bg-accent' }),
          h('span', { className: 'text-xs font-medium text-main' }, 'Amaldagi normalar')
        ),
        h('span', { className: 'text-xs font-mono font-bold text-main tabular-nums' }, activeCount.toLocaleString('uz-UZ'))
      ),
      h('div', { className: 'flex items-center justify-between p-3 rounded-md bg-surface-2' },
        h('div', { className: 'flex items-center gap-2' },
          h('span', { className: 'w-2.5 h-2.5 rounded-full bg-border' }),
          h('span', { className: 'text-xs font-medium text-main' }, 'Bekor qilingan normalar')
        ),
        h('span', { className: 'text-xs font-mono font-bold text-main tabular-nums' }, repealedCount.toLocaleString('uz-UZ'))
      )
    );

    statusCard.appendChild(cardHeader);
    statusCard.appendChild(ratioBar);
    statusCard.appendChild(list);
  }

  loadData();
  return container;
}
