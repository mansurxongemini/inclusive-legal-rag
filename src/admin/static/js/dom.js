/**
 * Safe DOM Creation Helper — Zero-Dependency VDOM-like builder
 * Prevents XSS and quote-escaping bugs by working with direct DOM nodes.
 */

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);

  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) {
        continue;
      }

      if (key === 'className' || key === 'class') {
        if (Array.isArray(value)) {
          el.className = value.filter(Boolean).join(' ');
        } else if (typeof value === 'object') {
          el.className = Object.entries(value)
            .filter(([_, cond]) => Boolean(cond))
            .map(([cls]) => cls)
            .join(' ');
        } else {
          el.className = String(value);
        }
      } else if (key === 'style') {
        if (typeof value === 'object') {
          Object.assign(el.style, value);
        } else {
          el.style.cssText = String(value);
        }
      } else if (key.startsWith('on') && typeof value === 'function') {
        const eventName = key.slice(2).toLowerCase();
        el.addEventListener(eventName, value);
      } else if (key === 'dataset' && typeof value === 'object') {
        Object.assign(el.dataset, value);
      } else if (key === 'html') {
        // Explicit sanitized HTML insertion (use sparingly)
        el.innerHTML = value;
      } else {
        if (typeof value === 'boolean') {
          if (value) el.setAttribute(key, '');
        } else {
          el.setAttribute(key, String(value));
        }
      }
    }
  }

  appendChildren(el, children);
  return el;
}

function appendChildren(parent, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) {
      continue;
    }
    if (Array.isArray(child)) {
      appendChildren(parent, child);
    } else if (child instanceof Node) {
      parent.appendChild(child);
    } else {
      parent.appendChild(document.createTextNode(String(child)));
    }
  }
}

export function text(content) {
  return document.createTextNode(String(content ?? ''));
}

export function clear(el) {
  if (el) {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }
}

export function mount(target, ...children) {
  const container = typeof target === 'string' ? document.querySelector(target) : target;
  if (!container) return null;
  clear(container);
  appendChildren(container, children);
  return container;
}
