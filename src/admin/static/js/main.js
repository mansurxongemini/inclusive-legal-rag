/**
 * Main Application Orchestrator & Shell Router
 * Modular, zero-build native ES modules architecture.
 * Permanent Light Theme. Sticky Sidebar at all breakpoints.
 */
import { h, mount, clear } from './dom.js';
import { icons } from './icons.js';
import { store } from './state.js';
import { api } from './api.js';
import { Badge } from '../components/Badge.js';
import { renderDocumentsPage } from './pages/documents.js';
import { renderStatsPage } from './pages/stats.js';
import { renderApiKeysPage } from './pages/apikeys.js';
import { renderPlaygroundPage } from './pages/playground.js';
import { renderVectorizerPage } from './pages/vectorizer.js';

// Section definition
const NAV_ITEMS = [
  { id: 'documents', label: 'Hujjatlar', title: "Qonunlar va me'yoriy hujjatlar", icon: icons.book, render: renderDocumentsPage },
  { id: 'stats', label: 'Statistika', title: "Tizim tahlili va ko'rsatkichlari", icon: icons.chart, render: renderStatsPage },
  { id: 'apikeys', label: 'API Kalitlar', title: 'API kalitlarini boshqarish', icon: icons.key, render: renderApiKeysPage },
  { id: 'playground', label: 'Sinov zali', title: 'Semantik qidiruv va sinov zali', icon: icons.chat, render: renderPlaygroundPage },
  { id: 'vectorizer', label: 'Vektorlash', title: 'Matnlarni vektorlash va embedding', icon: icons.cpu, render: renderVectorizerPage }
];

function renderPlaceholder(id, name) {
  return () => {
    return h('div', { className: 'card p-12 text-center max-w-md mx-auto mt-12' },
      h('div', { className: 'w-12 h-12 rounded-full bg-surface-2 text-accent flex items-center justify-center mx-auto mb-4' },
        icons.refresh('icon-md')
      ),
      h('h3', { className: 'text-md font-semibold text-main mb-1' }, `${name} bo'limi`),
      h('p', { className: 'text-xs text-muted mb-4' }, "Ushbu bo'lim yangi modulli arxitekturaga bosqichma-bosqich ko'chirilmoqda."),
      Badge({ label: 'Rejalashtirilgan', variant: 'neutral' })
    );
  };
}

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
  }

  getInitialTab() {
    const hash = window.location.hash.replace(/^#\/?/, '').trim();
    const found = NAV_ITEMS.find(item => item.id === hash);
    return found ? found.id : 'documents';
  }

  init() {
    this.renderShell();
    this.setupRouting();
    this.navigate(this.currentTab, false);
    this.pollHealth();
    setInterval(() => this.pollHealth(), 30000);
  }

  setupRouting() {
    window.addEventListener('hashchange', () => {
      const hash = window.location.hash.replace(/^#\/?/, '').trim();
      if (hash && hash !== this.currentTab && NAV_ITEMS.some(item => item.id === hash)) {
        this.navigate(hash, false);
      }
    });
  }

  navigate(tabId, updateHash = true) {
    const item = NAV_ITEMS.find(n => n.id === tabId);
    if (!item) return;

    this.currentTab = tabId;
    if (updateHash) {
      window.location.hash = tabId;
    }

    // Update desktop nav links
    this.navLinks.forEach((linkEl, id) => {
      if (id === tabId) {
        linkEl.classList.add('active');
        linkEl.setAttribute('aria-current', 'page');
      } else {
        linkEl.classList.remove('active');
        linkEl.removeAttribute('aria-current');
      }
    });

    // Update mobile nav links
    this.mobileNavLinks.forEach((linkEl, id) => {
      if (id === tabId) {
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
        const pageNode = item.render();
        mount(this.pageContentEl, pageNode);
      } catch (err) {
        console.error(`Page render error (${tabId}):`, err);
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
      // Top section: Brand & Navigation
      h('div', { className: 'space-y-6' },
        // Brand header
        h('div', { className: 'flex items-center justify-between pb-3 border-b border-border' },
          h('div', { className: 'space-y-0-5' },
            h('div', { className: 'flex items-center gap-2' },
              h('div', { className: 'w-7 h-7 rounded-md bg-accent text-accent-text flex items-center justify-center font-bold text-xs' }, 'IL'),
              h('h1', { className: 'text-sm font-bold text-main tracking-tight' }, 'Legal RAG')
            ),
            h('p', { className: 'text-2xs text-muted font-medium' }, 'Uzbekistan Legal RAG')
          ),
          Badge({ label: 'v1.2', variant: 'neutral' })
        ),

        // Navigation Menu
        h('nav', { className: 'space-y-1', 'aria-label': 'Asosiy menyu' },
          ...NAV_ITEMS.map(item => {
            const link = h('button', {
              type: 'button',
              className: 'nav-link w-full text-left',
              onclick: () => this.navigate(item.id)
            },
              h('span', { className: 'flex items-center gap-2-5' },
                item.icon('icon-sm text-muted'),
                h('span', {}, item.label)
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
          h('span', {}, 'Lex.uz qonunchilik portali'),
          icons.externalLink('icon-xs')
        )
      )
    );

    // ==========================================
    // 2. MOBILE STICKY TOP NAVIGATION (< 768px)
    // Always visible and sticky at top!
    // ==========================================
    const mobileHeader = h('div', { className: 'mobile-top-bar' },
      // Top row: Brand + Status + v1 link
      h('div', { className: 'flex items-center justify-between px-4 py-2.5 border-b border-border-subtle' },
        h('div', { className: 'flex items-center gap-2' },
          h('div', { className: 'w-6 h-6 rounded bg-accent text-accent-text flex items-center justify-center font-bold text-2xs' }, 'IL'),
          h('span', { className: 'text-xs font-bold text-main' }, 'Legal RAG'),
          Badge({ label: 'v1.2', variant: 'neutral' }),
          this.mobileStatusEl = h('span', { className: 'w-2 h-2 rounded-full bg-success ml-1' })
        ),
        h('a', {
          href: '/admin',
          className: 'btn btn-secondary btn-sm text-2xs px-2 py-1',
          title: "Eski panelga o'tish"
        },
          icons.refresh('icon-xs text-muted'),
          h('span', {}, "v1 panel")
        )
      ),
      // Bottom row: Horizontal scrollable tabs
      h('nav', { className: 'flex items-center gap-1 px-2 py-1.5 overflow-x-auto no-scrollbar', 'aria-label': 'Mobil menyu' },
        ...NAV_ITEMS.map(item => {
          const mLink = h('button', {
            type: 'button',
            className: 'nav-link flex-shrink-0 text-xs px-2.5 py-1 gap-1.5',
            onclick: () => this.navigate(item.id)
          },
            item.icon('icon-xs text-muted'),
            h('span', {}, item.label)
          );
          this.mobileNavLinks.set(item.id, mLink);
          return mLink;
        })
      )
    );

    // ==========================================
    // 3. MAIN CONTENT AREA
    // ==========================================
    this.pageTitleEl = h('h2', { className: 'text-base font-bold text-main tracking-tight' }, "Qonunlar va me'yoriy hujjatlar");

    const desktopTopBar = h('header', { className: 'hidden md:flex bg-surface border-b border-border px-6 py-4 items-center justify-between sticky top-0 z-30' },
      h('div', { className: 'flex items-center gap-3' },
        this.pageTitleEl
      ),
      h('div', { className: 'flex items-center gap-2' },
        h('a', {
          href: '/admin',
          className: 'btn btn-secondary btn-sm',
          title: "Eski admin panelga o'tish"
        },
          icons.refresh('icon-sm text-muted'),
          h('span', {}, "Eski panel (v1)")
        )
      )
    );

    this.pageContentEl = h('main', { className: 'p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full flex-1' });

    const contentWrapper = h('div', { className: 'main-content-wrapper' },
      desktopTopBar,
      this.pageContentEl
    );

    // Mount all shell components together (mount clears target before appending)
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
