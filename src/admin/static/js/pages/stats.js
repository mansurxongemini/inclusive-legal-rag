/**
 * Statistics (Statistika) Page Module — System Metrics & Domain Distribution
 * Zero-build native ES module, WCAG 2.2 AA compliant, permanent light theme.
 */
import { h, clear } from '../dom.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import { Button } from '../../components/Button.js';
import { Badge } from '../../components/Badge.js';
import { EmptyState } from '../../components/EmptyState.js';
import { SkeletonCard } from '../../components/Skeleton.js';

// Domain labels dictionary in clear Uzbek
const DOMAIN_LABELS = {
  'pensions_and_benefits': "Nafaqalar va pensiyalar",
  'international_treaty': "BMT Konvensiyasi va xalqaro shartnomalar",
  'labor_rights': "Mehnat huquqlari",
  'disability_rights': "Nogironlik huquqlari",
  'tax_benefits': "Soliq imtiyozlari",
  'accessibility_infrastructure': "To‘siqsiz shaharsozlik",
  'medical_social_expertise': "Tibbiy-ijtimoiy ekspertiza (TMEK)",
  'sanatorium_health': "Sanatoriy-kurortda davolanish",
  'inclusive_education': "Inklyuziv ta‘lim",
  'social_protection': "Ijtimoiy himoya kafolatlari",
  'rehabilitation_prosthetics': "Protez-ortopediya va reabilitatsiya",
  'social_protection_governance': "Ijtimoiy himoya boshqaruvi",
  'education': "Ta‘lim kafolatlari",
  'labor_code': "Mehnat kodeksi"
};

function getDomainLabel(key) {
  if (!key) return "Umumiy qoida";
  return DOMAIN_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

export function renderStatsPage() {
  const container = h('div', { className: 'space-y-6' });

  // State
  let showAllCategories = false;
  let cachedData = null;

  // Header Banner
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
        h('h2', { className: 'text-sm font-bold text-main' }, 'Tizim tahlili va ko‘rsatkichlari'),
        Badge({ label: 'Jonli hisobot', variant: 'neutral' })
      ),
      h('p', { className: 'text-xs text-muted' },
        'Huquqiy normalar bazasi, API so‘rovlari va resurslar holati bo‘yicha to‘liq statistik ma‘lumotlar.'
      )
    ),
    h('div', { className: 'flex items-center gap-3' },
      lastUpdatedEl,
      refreshBtn
    )
  );

  // Content Containers
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

    // Skeletons
    for (let i = 0; i < 4; i++) {
      metricsGrid.appendChild(SkeletonCard({ rows: 1 }));
    }
    categoryCard.appendChild(SkeletonCard({ rows: 5 }));
    statusCard.appendChild(SkeletonCard({ rows: 3 }));

    try {
      // Fetch both inclusive stats and admin stats in parallel
      const [inclusiveStats, adminStats] = await Promise.all([
        api.fetchStats().catch(() => null),
        api.getAdminStats().catch(() => null)
      ]);

      const totalNorms = inclusiveStats?.total_statutory_norms ?? adminStats?.total_articles ?? 0;
      const totalDocs = adminStats?.total_documents ?? 0;
      const activeKeys = inclusiveStats?.active_api_keys ?? 0;
      const totalRequests = inclusiveStats?.total_api_requests_served ?? 0;
      const memoryMb = adminStats?.rss_memory_mb ?? 0;

      const categories = inclusiveStats?.category_distribution || adminStats?.categories || {};
      const statuses = adminStats?.statuses || { active: totalNorms, repealed: 0 };

      cachedData = { totalNorms, totalDocs, activeKeys, totalRequests, memoryMb, categories, statuses };

      renderMetrics(cachedData);
      renderCategories(cachedData);
      renderStatuses(cachedData);

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
        title: 'Jami huquqiy normalar',
        value: data.totalNorms.toLocaleString('uz-UZ'),
        subtitle: `${data.totalDocs} ta rasmiy me‘yoriy hujjatda`,
        icon: icons.book
      },
      {
        title: 'Faol API kalitlar',
        value: data.activeKeys.toLocaleString('uz-UZ'),
        subtitle: 'Tashqi integratsiyalar uchun',
        icon: icons.key
      },
      {
        title: 'Ko‘rsatilgan so‘rovlar',
        value: data.totalRequests.toLocaleString('uz-UZ'),
        subtitle: 'Muvaffaqiyatli RAG javoblari',
        icon: icons.chart
      },
      {
        title: 'Xotira sarfi (RAM)',
        value: data.memoryMb ? `${Math.round(data.memoryMb)} MB` : 'Barqaror',
        subtitle: 'SQLite + LanceDB vektori',
        icon: icons.cpu
      }
    ];

    items.forEach(item => {
      const card = h('div', { className: 'card-surface p-4 flex flex-col justify-between space-y-2' },
        h('div', { className: 'flex items-center justify-between' },
          h('span', { className: 'text-2xs font-medium text-muted uppercase tracking-wider' }, item.title),
          h('span', { className: 'text-muted' }, item.icon('icon-sm'))
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

    // Sort categories descending
    const catList = Object.entries(data.categories || {})
      .map(([key, count]) => ({ key, label: getDomainLabel(key), count }))
      .sort((a, b) => b.count - a.count);

    const total = data.totalNorms || 1;
    const maxCount = catList.length > 0 ? catList[0].count : 1;

    const visibleItems = showAllCategories ? catList : catList.slice(0, 8);

    const cardHeader = h('div', { className: 'flex items-center justify-between pb-3 border-b border-border' },
      h('div', {},
        h('h3', { className: 'text-sm font-bold text-main' }, 'Huquqiy sohalar bo‘yicha taqsimot'),
        h('p', { className: 'text-2xs text-muted mt-0-5' }, 'Normalar soni va umumiy bazadagi ulushi')
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

    const activeCount = data.statuses?.active ?? data.totalNorms;
    const repealedCount = data.statuses?.repealed ?? 0;
    const total = activeCount + repealedCount || 1;

    const activePct = ((activeCount / total) * 100).toFixed(1);
    const repealedPct = ((repealedCount / total) * 100).toFixed(1);

    const cardHeader = h('div', { className: 'pb-3 border-b border-border' },
      h('h3', { className: 'text-sm font-bold text-main' }, 'Huquqiy maqom holati'),
      h('p', { className: 'text-2xs text-muted mt-0-5' }, 'Normalarning amalda qo‘llanilish holati')
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

  // Initial load
  loadData();

  return container;
}
