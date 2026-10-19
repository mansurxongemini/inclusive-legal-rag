/**
 * Tahririyat — Savol-javoblar sahifasi.
 * Huquqshunos savolga javobni qo'lda kiritadi va Lex.uz moddalariga bog'laydi.
 * Foydalanuvchi matni faqat textContent / xavfsiz markdown orqali chiqariladi.
 */
import { h, clear } from '../dom.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import { Button } from '../../components/Button.js';
import { Badge } from '../../components/Badge.js';
import { EmptyState } from '../../components/EmptyState.js';
import { SkeletonCard } from '../../components/Skeleton.js';
import { createSlideOver } from '../../components/SlideOver.js';
import { createModal } from '../../components/Modal.js';
import { showToast } from '../../components/Toast.js';
import { parseMarkdown } from '../markdown.js';

const STATUS_LABELS = {
  draft: 'Qoralama',
  published: 'Nashrda',
  needs_review: 'Tekshiruv kerak',
  archived: 'Arxivda',
};

function statusVariant(s) {
  if (s === 'published') return 'success';
  if (s === 'needs_review') return 'warning';
  if (s === 'archived') return 'neutral';
  return 'info';
}

export function renderQAPage() {
  const container = h('div', { className: 'space-y-4' });
  let statusFilter = 'all';
  let searchQuery = '';
  let debounce = null;
  let editor = null;
  let deleteModal = null;
  let lawsCache = null;

  const badgeTotal = h('span', { className: 'badge badge-neutral tabular-nums font-semibold' }, '0 ta javob');

  const header = h('div', { className: 'card-surface p-5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4' },
    h('div', {},
      h('div', { className: 'flex items-center gap-2-5 flex-wrap' },
        h('h2', { className: 'text-sm font-bold text-main' }, 'Savol-javoblar'),
        badgeTotal
      ),
      h('p', { className: 'text-xs text-muted mt-1' },
        'Huquqshunos javoblari: har bir javob kamida bitta Lex.uz moddasiga bog‘lanadi.'
      )
    ),
    Button({ text: 'Yangi javob', icon: icons.plus('icon-sm'), variant: 'primary', onClick: () => openEditor(null) })
  );

  const statusPills = h('div', { className: 'flex items-center gap-1-5 flex-wrap' });
  function renderPills(activeCounts) {
    clear(statusPills);
    ['all', 'draft', 'published', 'needs_review', 'archived'].forEach((s) => {
      const label = s === 'all' ? 'Barchasi' : STATUS_LABELS[s];
      statusPills.appendChild(h('button', {
        type: 'button',
        className: `btn btn-sm ${statusFilter === s ? 'btn-primary' : 'btn-secondary'} tabular-nums`,
        'aria-pressed': statusFilter === s ? 'true' : 'false',
        onclick: () => { statusFilter = s; renderPills(); loadList(); },
      }, label));
    });
    void activeCounts;
  }

  const searchInput = h('input', {
    type: 'text',
    className: 'input-text pl-9',
    placeholder: 'Savol yoki javob matni bo‘yicha qidirish...',
    'aria-label': 'Savol-javob qidirish',
    oninput: (e) => {
      clearTimeout(debounce);
      searchQuery = e.target.value.trim();
      debounce = setTimeout(loadList, 300);
    },
  });

  const filterCard = h('div', { className: 'card-surface p-4 space-y-3' },
    h('div', { className: 'relative w-full' },
      h('span', { className: 'absolute left-3 top-2-5 text-muted pointer-events-none' }, icons.search('icon-sm')),
      searchInput
    ),
    statusPills
  );

  const listEl = h('div', { className: 'space-y-2-5', role: 'list', 'aria-label': 'Tahririy javoblar ro‘yxati' });

  container.appendChild(header);
  container.appendChild(filterCard);
  container.appendChild(listEl);

  renderPills();
  loadList();

  // Bildirishnomadan "Tahrirlash" bilan kelingan bo'lsa, tahrirlovchini ochamiz.
  try {
    const pending = sessionStorage.getItem('editorial_edit_answer');
    if (pending) {
      sessionStorage.removeItem('editorial_edit_answer');
      const parsed = JSON.parse(pending);
      openEditor(Number(parsed.answerId), parsed.notifId ? Number(parsed.notifId) : null);
    }
  } catch { /* e'tibor bermaymiz */ }

  async function loadList() {
    clear(listEl);
    for (let i = 0; i < 3; i++) listEl.appendChild(SkeletonCard({ rows: 2 }));
    try {
      const data = await api.editorialAnswers({ status: statusFilter, q: searchQuery, limit: 50, offset: 0 });
      const items = data.items || [];
      badgeTotal.textContent = `${data.total || 0} ta javob`;
      clear(listEl);
      if (!items.length) {
        listEl.appendChild(EmptyState({
          icon: icons.search('icon-lg'),
          title: 'Javob topilmadi',
          description: 'Yangi javob yarating yoki filtrlarni tozalang.',
        }));
        return;
      }
      items.forEach((a) => {
        const card = h('div', {
          className: 'card-surface p-4 hover:border-accent cursor-pointer transition',
          role: 'listitem', tabIndex: 0,
          onclick: () => openEditor(a.id),
          onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') openEditor(a.id); },
        },
          h('div', { className: 'flex items-center gap-2 flex-wrap mb-1-5' },
            Badge({ text: STATUS_LABELS[a.status] || a.status, variant: statusVariant(a.status) }),
            Badge({ text: `${a.links_count || 0} ta huquqiy asos`, variant: (a.links_count || 0) > 0 ? 'info' : 'warning' }),
            h('span', { className: 'text-2xs text-subtle font-mono' }, `#${a.id} • ${a.category || ''}`)
          ),
          h('h3', { className: 'text-xs font-bold text-main leading-relaxed' }, a.question),
          h('p', { className: 'text-xs text-muted line-clamp-1 mt-1' }, (a.answer_md || '').slice(0, 160))
        );
        // h() matnni textContent sifatida qo'yadi — innerHTML ishlatilmaydi.
        listEl.appendChild(card);
      });
    } catch (err) {
      clear(listEl);
      listEl.appendChild(EmptyState({
        icon: icons.close('icon-lg text-danger'),
        title: 'Yuklashda xatolik',
        description: err.message,
      }));
    }
  }

  async function ensureLaws() {
    if (lawsCache) return lawsCache;
    try {
      const data = await api.editorialLaws();
      lawsCache = data.items || [];
    } catch {
      lawsCache = [];
    }
    return lawsCache;
  }

  function openEditor(answerId, resolveNotifId = null) {
    if (!editor) {
      editor = createSlideOver({ title: 'Javob tahrirlovchi', maxWidth: '720px' });
      document.body.appendChild(editor.element);
    }
    editor.setTitle(answerId ? `Javob #${answerId}` : 'Yangi javob', null);
    editor.setContent([h('p', { className: 'text-xs text-muted' }, 'Yuklanmoqda...')]);
    editor.setFooter([]);
    editor.open();
    buildEditorBody(answerId, resolveNotifId);
  }

  async function buildEditorBody(answerId, resolveNotifId) {
    let answer = null;
    let links = [];
    let history = [];
    if (answerId) {
      try {
        const data = await api.editorialAnswerGet(answerId);
        answer = data;
        links = data.links || [];
        history = data.history || [];
      } catch (err) {
        editor.setContent([h('p', { className: 'text-danger text-xs' }, `Yuklab bo‘lmadi: ${err.message}`)]);
        return;
      }
    }

    const qInput = h('textarea', { rows: 2, className: 'textarea-field', maxlength: 2000 }, answer ? answer.question : '');
    const altInput = h('textarea', { rows: 2, className: 'textarea-field', placeholder: 'Har qatorda bitta muqobil savol' },
      answer ? (answer.alt_questions || []).join('\n') : '');
    const mdInput = h('textarea', { rows: 8, className: 'textarea-field font-mono', maxlength: 20000 },
      answer ? answer.answer_md : '');
    const previewBox = h('div', { className: 'p-3 bg-surface-2 rounded-md border border-border' });
    const showdown = { on: false };
    const previewBtn = h('button', {
      type: 'button', className: 'btn btn-secondary btn-sm', 'aria-pressed': 'false',
      onclick: () => {
        showdown.on = !showdown.on;
        previewBtn.setAttribute('aria-pressed', showdown.on ? 'true' : 'false');
        previewBtn.textContent = showdown.on ? 'Tahrirlashga qaytish' : 'Oldindan ko‘rish';
        clear(previewBox);
        if (showdown.on) previewBox.appendChild(parseMarkdown(mdInput.value, {}));
        mdInput.classList.toggle('hidden', showdown.on);
        previewBox.classList.toggle('hidden', !showdown.on);
      },
    }, 'Oldindan ko‘rish');
    previewBox.classList.add('hidden');

    // Huquqiy asos tanlagich
    const lawSelect = h('select', { className: 'select-dropdown', 'aria-label': 'Hujjat filtri' },
      h('option', { value: '' }, 'Barcha hujjatlar'));
    const normSearch = h('input', {
      type: 'text', className: 'input-text', placeholder: 'Modda qidirish (masalan: nafaqa 15-modda)...',
      'aria-label': 'Modda qidirish',
    });
    const normResults = h('div', { className: 'space-y-2 max-h-56 overflow-y-auto' });
    const linkedBox = h('div', { className: 'space-y-2' });

    const laws = await ensureLaws();
    laws.slice(0, 200).forEach((l) => {
      lawSelect.appendChild(h('option', { value: l.law_id }, `${l.law_number} — ${(l.law_title || '').slice(0, 60)}`));
    });

    let searchTimer = null;
    async function runNormSearch() {
      clear(normResults);
      const q = normSearch.value.trim();
      if (!q && !lawSelect.value) {
        normResults.appendChild(h('p', { className: 'text-2xs text-muted' }, 'Qidiruv so‘zi yoki hujjat tanlang.'));
        return;
      }
      normResults.appendChild(h('p', { className: 'text-2xs text-muted' }, 'Qidirilmoqda...'));
      try {
        const data = await api.editorialNormsSearch({ q, law_id: lawSelect.value || undefined, limit: 10 });
        clear(normResults);
        const items = data.items || [];
        if (!items.length) {
          normResults.appendChild(h('p', { className: 'text-2xs text-muted' }, 'Modda topilmadi.'));
          return;
        }
        items.forEach((n) => {
          const row = h('div', { className: 'p-2-5 border border-border rounded-md bg-surface flex flex-col gap-1' },
            h('div', { className: 'flex items-center gap-2 flex-wrap' },
              h('span', { className: 'text-2xs font-mono font-bold' }, `${n.law_number} ${n.article_number}`),
              n.status !== 'active' ? Badge({ text: 'faol emas', variant: 'warning' }) : null
            ),
            h('p', { className: 'text-2xs text-muted line-clamp-2' }, n.preview || ''),
            h('div', { className: 'flex items-center gap-2' },
              n.source_url ? h('a', {
                href: n.source_url, target: '_blank', rel: 'noopener noreferrer',
                className: 'text-2xs text-accent hover:underline',
              }, 'Lex.uz') : null,
              Button({
                text: 'Qo‘shish', variant: 'secondary', size: 'sm',
                onClick: async () => {
                  if (!answerId) { showToast('Avval javobni saqlang', 'warning'); return; }
                  try {
                    await api.editorialAddLink(answerId, { canonical_id: n.canonical_id });
                    showToast('Huquqiy asos qo‘shildi', 'success');
                    buildEditorBody(answerId, resolveNotifId);
                  } catch (e) { showToast(e.message, 'danger'); }
                },
              })
            )
          );
          normResults.appendChild(row);
        });
      } catch (e) {
        clear(normResults);
        normResults.appendChild(h('p', { className: 'text-2xs text-danger' }, e.message));
      }
    }
    normSearch.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(runNormSearch, 350); });
    lawSelect.addEventListener('change', runNormSearch);

    function renderLinks() {
      clear(linkedBox);
      if (!links.length) {
        linkedBox.appendChild(h('p', { className: 'text-2xs text-warning' },
          'Huquqiy asos yo‘q — nashr qilish uchun kamida 1 ta Lex.uz moddasi majburiy.'));
        return;
      }
      links.forEach((l) => {
        linkedBox.appendChild(h('div', { className: 'p-2-5 border border-border rounded-md bg-surface-2 flex items-start justify-between gap-2' },
          h('div', { className: 'min-w-0' },
            h('p', { className: 'text-2xs font-bold font-mono' }, l.article_label || l.canonical_id),
            h('p', { className: 'text-2xs text-muted line-clamp-2' }, (l.snapshot_text || '').slice(0, 200))
          ),
          h('button', {
            type: 'button', className: 'btn btn-ghost btn-sm text-danger shrink-0',
            'aria-label': `Bog‘lanishni olib tashlash: ${l.canonical_id}`,
            onclick: async () => {
              try {
                await api.editorialRemoveLink(answerId, l.canonical_id);
                showToast('Bog‘lanish olib tashlandi', 'success');
                buildEditorBody(answerId, resolveNotifId);
              } catch (e) { showToast(e.message, 'danger'); }
            },
          }, 'Olib tashlash')
        ));
      });
    }
    renderLinks();

    const historyBox = h('details', { className: 'text-xs' },
      h('summary', { className: 'cursor-pointer text-muted font-medium hover:text-main select-none py-1' },
        `Versiya tarixi (${history.length})`),
      h('div', { className: 'space-y-1 mt-1' },
        ...history.map((hh) => h('p', { className: 'text-2xs text-muted font-mono' },
          `v${hh.version} • ${hh.action} • ${hh.editor || '—'} • ${hh.at || ''}`))
      )
    );

    editor.setTitle(answerId ? `Javob #${answerId}${resolveNotifId ? ' — bildirishnoma bo‘yicha tahrir' : ''}` : 'Yangi javob', null);
    editor.setContent([
      h('div', { className: 'space-y-1-5' },
        h('label', { className: 'block text-xs font-semibold text-main' }, 'Savol'),
        qInput),
      h('div', { className: 'space-y-1-5' },
        h('label', { className: 'block text-xs font-semibold text-main' }, 'Muqobil savollar'),
        altInput),
      h('div', { className: 'space-y-1-5' },
        h('div', { className: 'flex items-center justify-between' },
          h('label', { className: 'block text-xs font-semibold text-main' }, 'Javob (markdown)'),
          previewBtn),
        mdInput, previewBox),
      h('div', { className: 'space-y-2 pt-2 border-t border-border' },
        h('h4', { className: 'text-xs font-bold text-main' }, 'Huquqiy asos (Lex.uz moddalari)'),
        linkedBox,
        h('div', { className: 'flex flex-col sm:flex-row gap-2' }, lawSelect, normSearch),
        normResults),
      historyBox,
    ]);

    async function collectPayload() {
      return {
        question: qInput.value.trim(),
        alt_questions: altInput.value.split('\n').map((s) => s.trim()).filter(Boolean).slice(0, 20),
        answer_md: mdInput.value.trim(),
      };
    }

    const footerBtns = [
      Button({
        text: 'Saqlash', variant: 'secondary',
        onClick: async () => {
          const payload = await collectPayload();
          try {
            let saved;
            if (!answerId) {
              saved = await api.editorialAnswerCreate({ ...payload, language: 'uz', category: 'general' });
              showToast('Javob saqlandi', 'success');
              editor.close();
              loadList();
              openEditor(saved.id, resolveNotifId);
            } else {
              saved = await api.editorialAnswerUpdate(answerId, payload);
              showToast('Saqlangan tahrir', 'success');
              if (resolveNotifId) {
                await api.editorialResolve(resolveNotifId, { action: 'edited', note: 'Tahrirlovchidan saqlandi' });
                showToast('Bildirishnoma hal qilindi (edited)', 'success');
              }
              editor.close();
              loadList();
            }
          } catch (e) { showToast(e.message, 'danger'); }
        },
      }),
      Button({
        text: 'Nashr qilish', variant: 'primary',
        onClick: async () => {
          try {
            if (!answerId) {
              showToast('Avval javobni qoralama sifatida saqlang', 'warning');
              return;
            }
            if (!links || links.length === 0) {
              showToast('Nashr qilish uchun kamida 1 ta Lex.uz moddasi bog‘langan bo‘lishi shart', 'warning');
              return;
            }
            const payload = await collectPayload();
            await api.editorialAnswerUpdate(answerId, payload);
            await api.editorialPublish(answerId);
            if (resolveNotifId) {
              await api.editorialResolve(resolveNotifId, { action: 'edited', note: 'Tahrir + nashr' });
            }
            showToast('Javob muvaffaqiyatli nashr qilindi', 'success');
            editor.close();
            loadList();
          } catch (e) { showToast(`Nashr qilishda xatolik: ${e.message}`, 'danger'); }
        },
      }),
    ];
    if (answerId) {
      if (answer && answer.status === 'published') {
        footerBtns.push(Button({
          text: 'Nashrdan olish', variant: 'secondary',
          onClick: async () => {
            try {
              await api.editorialUnpublish(answerId);
              showToast('Javob nashrdan olindi (qoralama holatiga o‘tdi)', 'success');
              editor.close();
              loadList();
            } catch (e) { showToast(`Xatolik: ${e.message}`, 'danger'); }
          },
        }));
      }
      footerBtns.push(Button({
        text: answer && answer.status === 'archived' ? 'Arxivdan chiqarish' : 'Arxivlash',
        variant: 'secondary',
        onClick: async () => {
          try {
            const nextStatus = answer && answer.status === 'archived' ? 'draft' : 'archived';
            await api.editorialAnswerUpdate(answerId, { status: nextStatus });
            showToast(nextStatus === 'archived' ? 'Javob arxivlandi' : 'Javob arxivdan chiqarildi', 'success');
            editor.close();
            loadList();
          } catch (e) { showToast(`Xatolik: ${e.message}`, 'danger'); }
        },
      }));
      footerBtns.push(Button({
        text: 'O‘chirish', variant: 'danger',
        onClick: () => confirmDelete(answerId),
      }));
    }
    editor.setFooter(footerBtns);
  }

  function confirmDelete(answerId) {
    if (!deleteModal) {
      deleteModal = createModal({ id: 'modal-qa-delete', title: 'Javobni o‘chirish', maxWidth: '440px' });
      document.body.appendChild(deleteModal.element);
    }
    deleteModal.setContent([
      h('p', { className: 'text-xs text-main' },
        'Javob, uning huquqiy bog‘lanishlari va store proyeksiyasi o‘chadi. Davom etasizmi?'),
    ]);
    deleteModal.setFooter([
      Button({ text: 'Bekor qilish', variant: 'secondary', onClick: () => deleteModal.close() }),
      Button({
        text: 'Ha, o‘chirish', variant: 'danger',
        onClick: async () => {
          try {
            await api.editorialAnswerDelete(answerId);
            showToast('Javob o‘chirildi', 'success');
            deleteModal.close();
            editor.close();
            loadList();
          } catch (e) { showToast(e.message, 'danger'); }
        },
      }),
    ]);
    deleteModal.open();
  }

  return container;
}
