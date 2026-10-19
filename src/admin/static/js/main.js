/**
 * Main Application Orchestrator & Shell Router
 * Modular, zero-build native ES modules architecture.
 * Permanent Light Theme. Sticky Sidebar at all breakpoints.
 */
import { h, mount, clear } from './dom.js';
import { icons, createSvg } from './icons.js';

const bellIcon = (cls) => createSvg(
  '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path>',
  cls
);

import { api } from './api.js';
import { Badge } from '../components/Badge.js';
import { renderStatsPage } from './pages/stats.js';
import { renderDocumentsPage } from './pages/documents.js';
import { renderHuquqPlusPage } from './pages/huquqplus.js';
import { renderQAPage } from './pages/qa.js';
import { renderNotificationsPage } from './pages/notifications.js';
import { renderPlaygroundPage } from './pages/playground.js';
import { renderIntegrationsPage } from './pages/integrations.js';

// 7 ta asosiy bo'lim
const NAV_ITEMS = [
  { id: 'stats', label: 'Umumiy holat', title: 'Tizimning umumiy holati va ko‘rsatkichlari', icon: icons.chart, render: renderStatsPage },
  { id: 'documents', label: 'Qonunlar bazasi', title: 'Qonunlar va me‘yoriy hujjatlar bazasi', icon: icons.book, render: renderDocumentsPage },
  { id: 'huquqplus', label: 'Huquq+ maqolalari', title: 'huquqplus.uz maqolalari va tahlillari', icon: icons.book, render: renderHuquqPlusPage },
  { id: 'qa', label: 'Savol-javoblar', title: 'Tahririyat savol-javoblari', icon: icons.edit, render: renderQAPage },
  { id: 'notifications', label: 'Bildirishnomalar', title: 'Huquqiy o‘zgarishlar bildirishnomalari', icon: bellIcon, render: renderNotificationsPage, badge: true },
  { id: 'playground', label: 'Sinov', title: 'Savol-javob va qidiruv sinovi', icon: icons.chat, render: renderPlaygroundPage },
  { id: 'integrations', label: 'API va integratsiyalar', title: 'API mijozlari va integratsiyalar', icon: icons.key, render: renderIntegrationsPage },
];

const HASH_MAP = {
  'apikeys': 'integrations',
  'vectorizer': 'documents',
  'stats': 'stats',
  'documents': 'documents',
  'huquqplus': 'huquqplus',
  'qa': 'qa',
  'notifications': 'notifications',
  'playground': 'playground',
  'integrations': 'integrations',
};

class AdminApp {
  constructor() {
    this.appEl = document.getElementById('app');
    this.currentTab = this.getInitialTab();
    this.pageContentEl = null;
    this.navLinks = new Map();
    this.mobileNavLinks = new Map();
    this.pageTitleEl = null;
    this.systemStatusEl = null;
    this.mobileStatusEl = null;
    this.memoryBadgeEl = null;
    this.notifBadgeEl = null;
    this.notifBadgeMobileEl = null;
  }

  parseHash() {
    const raw = window.location.hash.replace(/^#\/?/, '').trim();
    if (!raw) {
      return { tabId: 'stats', params: new URLSearchParams(), rawPath: '', queryPart: '' };
    }
    const qIndex = raw.indexOf('?');
    const pathPart = qIndex >= 0 ? raw.slice(0, qIndex) : raw;
    const queryPart = qIndex >= 0 ? raw.slice(qIndex + 1) : '';
    const mapped = HASH_MAP[pathPart] || pathPart;
    const found = NAV_ITEMS.find(item => item.id === mapped);
    const tabId = found ? found.id : 'stats';
    const params = new URLSearchParams(queryPart);
    return { tabId, params, rawPath: pathPart, queryPart };
  }

  getInitialTab() {
    return this.parseHash().tabId;
  }

  init() {
    this.renderShell();
    this.setupRouting();
    const { tabId, params } = this.parseHash();
    this.navigate(tabId, false, params);
    this.pollHealth();
    this.pollNotifications();
    setInterval(() => this.pollHealth(), 30000);
    setInterval(() => this.pollNotifications(), 60000);
  }

  async pollNotifications() {
    try {
      const data = await api.editorialNotificationsCount();
      const open = Number(data.open || 0);
      [this.notifBadgeEl, this.notifBadgeMobileEl].forEach((el) => {
        if (!el) return;
        el.textContent = String(open);
        el.classList.toggle('hidden', open <= 0);
      });
    } catch {
      // Bildirishnoma xizmati ishlamasa, badge yashirin qoladi.
    }
  }

  setupRouting() {
    window.addEventListener('hashchange', () => {
      const { tabId, params, rawPath, queryPart } = this.parseHash();
      if (rawPath && HASH_MAP[rawPath] && HASH_MAP[rawPath] !== rawPath) {
        const query = queryPart ? `?${queryPart}` : '';
        window.location.hash = HASH_MAP[rawPath] + query;
        return;
      }
      this.navigate(tabId, false, params);
    });
  }

  navigate(tabId, updateHash = true, params = null) {
    const resolvedId = HASH_MAP[tabId] || tabId;
    const item = NAV_ITEMS.find(n => n.id === resolvedId);
    if (!item) return;

    this.currentTab = resolvedId;
    if (updateHash) {
      window.location.hash = resolvedId;
    }

    if (!params) {
      const parsed = this.parseHash();
      params = parsed.tabId === resolvedId ? parsed.params : new URLSearchParams();
    }

    // overlays belong to the page that opened them: drop them so they do not stay on top of the next page
    document.querySelectorAll('.modal-backdrop, .slide-over-backdrop').forEach((el) => el.remove());

    // Update desktop nav links
    this.navLinks.forEach((linkEl, id) => {
      if (id === resolvedId) {
        linkEl.classList.add('active');
        linkEl.setAttribute('aria-current', 'page');
      } else {
        linkEl.classList.remove('active');
        linkEl.removeAttribute('aria-current');
      }
    });

    // Update mobile nav links
    this.mobileNavLinks.forEach((linkEl, id) => {
      if (id === resolvedId) {
        linkEl.classList.add('active');
        linkEl.setAttribute('aria-current', 'page');
      } else {
        linkEl.classList.remove('active');
        linkEl.removeAttribute('aria-current');
      }
    });

    // Update Header
    if (this.pageTitleEl) {
      this.pageTitleEl.textContent = item.title;
    }

    // Mount page
    if (this.pageContentEl) {
      clear(this.pageContentEl);
      try {
        const pageNode = item.render(params);
        mount(this.pageContentEl, pageNode);
      } catch (err) {
        console.error(`Page render error (${resolvedId}):`, err);
        mount(this.pageContentEl, h('div', { className: 'card p-8 border-danger text-center' },
          h('p', { className: 'text-danger font-medium' }, `Sahifani yuklashda xatolik yuz berdi: ${err.message}`)
        ));
      }
    }
  }

  async pollHealth() {
    try {
      const stats = await api.getStats();
      if (this.systemStatusEl) {
        this.systemStatusEl.className = 'w-2 h-2 rounded-full bg-success';
      }
      if (this.mobileStatusEl) {
        this.mobileStatusEl.className = 'w-2 h-2 rounded-full bg-success';
      }
      if (this.memoryBadgeEl && stats.memory_mb) {
        this.memoryBadgeEl.textContent = `RAM: ${Math.round(stats.memory_mb)} MB`;
        this.memoryBadgeEl.classList.remove('hidden');
      }
    } catch {
      if (this.systemStatusEl) {
        this.systemStatusEl.className = 'w-2 h-2 rounded-full bg-danger';
      }
      if (this.mobileStatusEl) {
        this.mobileStatusEl.className = 'w-2 h-2 rounded-full bg-danger';
      }
    }
  }

  renderShell() {
    clear(this.appEl);

    // ==========================================
    // 1. DESKTOP / TABLET SIDEBAR (>= 768px)
    // ==========================================
    const desktopSidebar = h('aside', { className: 'app-sidebar' },
      h('div', { className: 'space-y-6' },
        // Brand header
        h('div', { className: 'flex items-center justify-between pb-3 border-b border-border' },
          h('div', { className: 'space-y-0-5' },
            h('div', { className: 'flex items-center gap-2' },
              h('div', { className: 'w-7 h-7 rounded-md bg-accent text-accent-text flex items-center justify-center font-bold text-xs' }, 'NH'),
              h('h1', { className: 'text-sm font-bold text-main tracking-tight' }, 'Boshqaruv Paneli')
            ),
            h('p', { className: 'text-2xs text-muted font-medium' }, 'Nogironlik huquqlari AI yordamchisi')
          )
        ),

        // Navigation Menu (7 bo'lim)
        h('nav', { className: 'space-y-1', 'aria-label': 'Asosiy menyu' },
          ...NAV_ITEMS.map(item => {
            const badgeEl = item.badge
              ? h('span', { className: 'badge badge-warning tabular-nums hidden', 'aria-label': 'Ochiq bildirishnomalar soni' }, '0')
              : null;
            if (item.badge) this.notifBadgeEl = badgeEl;
            const link = h('button', {
              type: 'button',
              className: 'nav-link w-full text-left',
              onclick: () => this.navigate(item.id)
            },
              h('span', { className: 'flex items-center gap-2-5' },
                item.icon('icon-sm text-muted'),
                h('span', {}, item.label),
                badgeEl
              )
            );
            this.navLinks.set(item.id, link);
            return link;
          })
        )
      ),

      // Bottom section: System Health & Lex.uz link
      h('div', { className: 'pt-4 border-t border-border space-y-3' },
        h('div', { className: 'flex items-center justify-between text-2xs px-1' },
          h('div', { className: 'flex items-center gap-2' },
            this.systemStatusEl = h('span', { className: 'w-2 h-2 rounded-full bg-success' }),
            h('span', { className: 'text-muted font-medium' }, 'Tizim: Faol')
          ),
          this.memoryBadgeEl = h('span', { className: 'text-subtle font-mono tabular-nums text-2xs hidden' }, '')
        ),
        h('a', {
          href: 'https://lex.uz',
          target: '_blank',
          rel: 'noopener noreferrer',
          className: 'flex items-center justify-between px-3 py-1-5 rounded-md text-2xs text-muted hover:text-main hover:bg-surface-2 transition-colors'
        },
          h('span', {}, 'Lex.uz rasmiy portali'),
          icons.externalLink('icon-xs')
        )
      )
    );

    // ==========================================
    // 2. MOBILE STICKY TOP NAVIGATION (< 768px)
    // ==========================================
    const mobileHeader = h('div', { className: 'mobile-top-bar' },
      h('div', { className: 'flex items-center justify-between px-4 py-2.5 border-b border-border-subtle' },
        h('div', { className: 'flex items-center gap-2' },
          h('div', { className: 'w-6 h-6 rounded bg-accent text-accent-text flex items-center justify-center font-bold text-2xs' }, 'NH'),
          h('span', { className: 'text-xs font-bold text-main' }, 'Boshqaruv Paneli'),
          this.mobileStatusEl = h('span', { className: 'w-2 h-2 rounded-full bg-success ml-1' })
        )
      ),
      h('nav', { className: 'flex items-center gap-1 px-2 py-1.5 overflow-x-auto no-scrollbar', 'aria-label': 'Mobil menyu' },
        ...NAV_ITEMS.map(item => {
          const mBadge = item.badge
            ? h('span', { className: 'badge badge-warning tabular-nums hidden' }, '0')
            : null;
          if (item.badge) this.notifBadgeMobileEl = mBadge;
          const mLink = h('button', {
            type: 'button',
            className: 'nav-link flex-shrink-0 text-xs px-2.5 py-1 gap-1.5',
            onclick: () => this.navigate(item.id)
          },
            item.icon('icon-xs text-muted'),
            h('span', {}, item.label),
            mBadge
          );
          this.mobileNavLinks.set(item.id, mLink);
          return mLink;
        })
      )
    );

    // ==========================================
    // 3. MAIN CONTENT AREA
    // ==========================================
    const initialItem = NAV_ITEMS.find(n => n.id === this.currentTab) || NAV_ITEMS[0];
    this.pageTitleEl = h('h2', { className: 'text-base font-bold text-main tracking-tight' }, initialItem.title);

    const desktopTopBar = h('header', { className: 'hidden md:flex bg-surface border-b border-border px-6 py-4 items-center justify-between sticky top-0 z-30' },
      h('div', { className: 'flex items-center gap-3' },
        this.pageTitleEl
      ),
      h('div', { className: 'flex items-center gap-2' },
        h('a', {
          href: 'https://lex.uz',
          target: '_blank',
          rel: 'noopener noreferrer',
          className: 'btn btn-secondary btn-sm',
          title: 'Lex.uz qonunchilik portaliga o‘tish'
        },
          icons.externalLink('icon-sm text-muted'),
          h('span', {}, 'Lex.uz')
        )
      )
    );

    this.pageContentEl = h('main', { className: 'p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full flex-1' });

    const contentWrapper = h('div', { className: 'main-content-wrapper' },
      desktopTopBar,
      this.pageContentEl
    );

    mount(this.appEl, desktopSidebar, mobileHeader, contentWrapper);
  }
}

// Instantiate and boot
const app = new AdminApp();
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => app.init());
} else {
  app.init();
}
