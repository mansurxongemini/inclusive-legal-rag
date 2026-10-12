/**
 * Hand-written Inline SVG Icons Set (~15 icons)
 * Clean, lightweight, zero-dependency, WCAG-compliant with aria-hidden="true".
 */

export function createSvg(pathContent, sizeClass = 'icon', extraProps = {}) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', sizeClass);

  for (const [k, v] of Object.entries(extraProps)) {
    svg.setAttribute(k, v);
  }

  svg.innerHTML = pathContent;
  return svg;
}

export const icons = {
  // Navigation 5 sections
  chat: (cls) => createSvg('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>', cls),
  book: (cls) => createSvg('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>', cls),
  cpu: (cls) => createSvg('<rect x="4" y="4" width="16" height="16" rx="2"></rect><rect x="9" y="9" width="6" height="6"></rect><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"></path>', cls),
  key: (cls) => createSvg('<path d="M21 2l-2 2m-1.5 1.5L16 7l-1.5-1.5L13 7l1.5 1.5L13 10l-1.5-1.5L10 10l1.5 1.5L8 15a5.5 5.5 0 1 1-6-6l7-7h12v10z"></path>', cls),
  chart: (cls) => createSvg('<line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line>', cls),

  // UI Utilities
  search: (cls) => createSvg('<circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>', cls),
  filter: (cls) => createSvg('<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>', cls),
  chevronDown: (cls) => createSvg('<polyline points="6 9 12 15 18 9"></polyline>', cls),
  chevronRight: (cls) => createSvg('<polyline points="9 18 15 12 9 6"></polyline>', cls),
  chevronLeft: (cls) => createSvg('<polyline points="15 18 9 12 15 6"></polyline>', cls),
  chevronUp: (cls) => createSvg('<polyline points="18 15 12 9 6 15"></polyline>', cls),
  close: (cls) => createSvg('<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>', cls),
  copy: (cls) => createSvg('<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>', cls),
  check: (cls) => createSvg('<polyline points="20 6 9 17 4 12"></polyline>', cls),
  trash: (cls) => createSvg('<polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>', cls),
  externalLink: (cls) => createSvg('<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line>', cls),
  moreDots: (cls) => createSvg('<circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle>', cls),
  menu: (cls) => createSvg('<line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line>', cls),
  plus: (cls) => createSvg('<line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line>', cls),
  refresh: (cls) => createSvg('<polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>', cls),
  edit: (cls) => createSvg('<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>', cls),
  sun: (cls) => createSvg('<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>', cls),
  moon: (cls) => createSvg('<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>', cls),
  scales: (cls) => createSvg('<path d="M16 16l3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1zM2 16l3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1zM7 21h10M12 3v18M3 7h18"></path>', cls),
  send: (cls) => createSvg('<line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>', cls)
};
