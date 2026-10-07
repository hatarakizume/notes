'use strict';

const API = '/api';
const body = document.body;
const URLS = {
    home: body.dataset.urlHome,
    login: body.dataset.urlLogin,
    workspace: body.dataset.urlWorkspace,
};
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value);
    }
    children.flat().forEach((child) => child && node.append(child));
    return node;
}

function icon(name, color) {
    const span = el('span', { class: 'material-symbols-outlined', text: name });
    if (color) span.style.color = color;
    return span;
}

function fmtDate(iso) {
    return new Date(iso).toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
}

function storage(action, key, value) {
    try {
        if (action === 'get') return localStorage.getItem(key);
        if (action === 'set') localStorage.setItem(key, value);
        if (action === 'del') localStorage.removeItem(key);
    } catch { }
    return null;
}

const tokens = {
    get access() { return storage('get', 'access'); },
    get refresh() { return storage('get', 'refresh'); },
    save(data) {
        if (data && data.access) storage('set', 'access', data.access);
        if (data && data.refresh) storage('set', 'refresh', data.refresh);
    },
    clear() { storage('del', 'access'); storage('del', 'refresh'); },
    get present() { return Boolean(this.access || this.refresh); },
};

function errorText(data, status) {
    if (status === 429) return 'Слишком много попыток. Подождите немного и попробуйте снова.';
    if (!data) return status ? `Ошибка сервера (${status})` : 'Нет связи с сервером';
    if (typeof data === 'string') return data;
    if (data.detail) return String(data.detail);
    return Object.values(data).flat().map(String).join(' ');
}

async function send(path, { method = 'GET', data, auth = true } = {}) {
    const isForm = data instanceof FormData;
    const headers = {};
    if (data !== undefined && !isForm) headers['Content-Type'] = 'application/json';
    if (auth && tokens.access) headers.Authorization = 'Bearer ' + tokens.access;
    const res = await fetch(API + path, {
        method,
        headers,
        body: data === undefined ? undefined : (isForm ? data : JSON.stringify(data)),
        credentials: 'same-origin',
    });
    const json = res.status === 204 ? null : await res.json().catch(() => null);
    return { res, json };
}

async function refreshTokens() {
    if (!tokens.refresh) return false;
    const { res, json } = await send('/auth/refresh/', {
        method: 'POST', data: { refresh: tokens.refresh }, auth: false,
    });
    if (!res.ok) return false;
    tokens.save(json);
    return true;
}

async function api(path, options = {}) {
    let { res, json } = await send(path, options);
    if (res.status === 401 && (await refreshTokens())) {
        ({ res, json } = await send(path, options));
    }
    if (res.status === 401) {
        tokens.clear();
        window.location.replace(URLS.login);
        throw new Error('Сессия истекла, войдите снова');
    }
    if (!res.ok) throw new Error(errorText(json, res.status));
    return json;
}

async function logout() {
    if (tokens.refresh) {
        try {
            await send('/auth/logout/', { method: 'POST', data: { refresh: tokens.refresh }, auth: false });
        } catch { }
    }
    tokens.clear();
    window.location.replace(URLS.home);
}

function paintAvatar(node, user) {
    if (user.avatar) {
        node.textContent = '';
        node.style.backgroundImage = `url(${JSON.stringify(user.avatar)})`;
    } else {
        node.style.backgroundImage = '';
        node.textContent = (user.username || '?').charAt(0).toUpperCase();
    }
}

function setBusy(form, busy) {
    $$('button', form).forEach((b) => { b.disabled = busy; });
}

function initIndex() {
    const loggedIn = tokens.present;
    $$('[data-guest-only]').forEach((n) => { n.hidden = loggedIn; });
    $$('[data-user-only]').forEach((n) => { n.hidden = !loggedIn; });
}

function initLogin() {
    if (tokens.present) { window.location.replace(URLS.workspace); return; }
    const form = $('#loginForm');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const login = $('#login').value.trim();
        const password = $('#password').value;
        const error = $('#formError');
        if (!login || !password) { error.textContent = 'Введите email (или имя пользователя) и пароль.'; return; }
        error.textContent = '';
        setBusy(form, true);
        try {
            const { res, json } = await send('/auth/login/', {
                method: 'POST', data: { username: login, password }, auth: false,
            });
            if (!res.ok) throw new Error(errorText(json, res.status));
            tokens.save(json);
            window.location.replace(URLS.workspace);
        } catch (err) {
            error.textContent = err.message;
            setBusy(form, false);
        }
    });
}

function initRegister() {
    if (tokens.present) { window.location.replace(URLS.workspace); return; }
    const form = $('#registerForm');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const error = $('#formError');
        const data = {
            username: $('#name').value.trim(),
            email: $('#email').value.trim(),
            password: $('#password').value,
            password_confirm: $('#password2').value,
        };
        if (!data.username || !data.email || !data.password) {
            error.textContent = 'Заполните все поля.'; return;
        }
        if (data.password !== data.password_confirm) {
            error.textContent = 'Пароли не совпадают.'; return;
        }
        error.textContent = '';
        setBusy(form, true);
        try {
            const { res, json } = await send('/auth/register/', { method: 'POST', data, auth: false });
            if (!res.ok) throw new Error(errorText(json, res.status));
            tokens.save(json);
            window.location.replace(URLS.workspace);
        } catch (err) {
            error.textContent = err.message;
            setBusy(form, false);
        }
    });
}

async function initAccount() {
    if (!tokens.present) { window.location.replace(URLS.login); return; }

    const fill = (user) => {
        $('#accName').value = user.username;
        $('#accEmail').value = user.email;
        $('#accPhone').value = user.phone || '';
        paintAvatar($('#avatarLarge'), user);
    };
    try {
        fill(await api('/auth/me/'));
    } catch (err) {
        $('#profileError').textContent = err.message;
    }

    const profileForm = $('#profileForm');
    profileForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        $('#profileError').textContent = '';
        $('#profileOk').textContent = '';
        const data = new FormData();
        data.append('phone', $('#accPhone').value.trim());
        const file = $('#accAvatar').files[0];
        if (file) data.append('avatar', file);
        setBusy(profileForm, true);
        try {
            fill(await api('/auth/me/', { method: 'PATCH', data }));
            $('#accAvatar').value = '';
            $('#profileOk').textContent = 'Изменения сохранены';
        } catch (err) {
            $('#profileError').textContent = err.message;
        } finally {
            setBusy(profileForm, false);
        }
    });

    const pwdForm = $('#passwordForm');
    pwdForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        $('#passwordError').textContent = '';
        $('#passwordOk').textContent = '';
        setBusy(pwdForm, true);
        try {
            const json = await api('/auth/change-password/', {
                method: 'POST',
                data: { old_password: $('#oldPassword').value, new_password: $('#newPassword').value },
            });
            tokens.save(json);
            pwdForm.reset();
            $('#passwordOk').textContent = 'Пароль изменён';
        } catch (err) {
            $('#passwordError').textContent = err.message;
        } finally {
            setBusy(pwdForm, false);
        }
    });

    $('#logoutBtn').addEventListener('click', logout);
}

const DRAW_PAPER = '#FFFFFF';
const DRAW_COLORS = ['#2D2D2D', '#D26343', '#3B82F6', '#2E9E5B'];

function createDrawingPad(canvas) {
    const ctx = canvas.getContext('2d');
    const pen = { color: DRAW_COLORS[0], eraser: false };
    let drawn = false;
    let stroking = false;
    let last = null;
    let history = [];
    let original = '';
    let loaded = true;

    function clear() {
        ctx.fillStyle = DRAW_PAPER;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    function snapshot() {
        history.push({ img: ctx.getImageData(0, 0, canvas.width, canvas.height), drawn });
        if (history.length > 30) history.shift();
    }

    function setTool(eraser) {
        pen.eraser = eraser;
        $('#toolPen').setAttribute('aria-pressed', String(!eraser));
        $('#toolEraser').setAttribute('aria-pressed', String(eraser));
        $$('.draw-swatch').forEach((s) =>
            s.setAttribute('aria-pressed', String(!eraser && s.dataset.color === pen.color)));
    }

    DRAW_COLORS.forEach((color, i) => {
        const swatch = el('button', {
            type: 'button', class: 'draw-swatch', 'data-color': color,
            title: 'Цвет ' + (i + 1), 'aria-label': 'Цвет ' + (i + 1),
            'aria-pressed': String(i === 0),
            onclick: () => { pen.color = color; setTool(false); },
        });
        swatch.style.background = color;
        $('#drawSwatches').append(swatch);
    });

    $('#toolPen').addEventListener('click', () => setTool(false));
    $('#toolEraser').addEventListener('click', () => setTool(true));
    $('#toolUndo').addEventListener('click', () => {
        const step = history.pop();
        if (!step) return;
        ctx.putImageData(step.img, 0, 0);
        drawn = step.drawn;
    });
    $('#toolClear').addEventListener('click', () => { snapshot(); clear(); drawn = false; });

    function point(e) {
        const r = canvas.getBoundingClientRect();
        return {
            x: (e.clientX - r.left) * canvas.width / r.width,
            y: (e.clientY - r.top) * canvas.height / r.height,
        };
    }

    function applyStyle() {
        const width = Number($('#toolSize').value) || 4;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.strokeStyle = ctx.fillStyle = pen.eraser ? DRAW_PAPER : pen.color;
        ctx.lineWidth = pen.eraser ? width * 3 : width;
    }

    canvas.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        canvas.setPointerCapture(e.pointerId);
        snapshot();
        stroking = true;
        last = point(e);
        applyStyle();
        ctx.beginPath();
        ctx.arc(last.x, last.y, ctx.lineWidth / 2, 0, Math.PI * 2);
        ctx.fill();
        if (!pen.eraser) drawn = true;
    });
    canvas.addEventListener('pointermove', (e) => {
        if (!stroking) return;
        const p = point(e);
        applyStyle();
        ctx.beginPath();
        ctx.moveTo(last.x, last.y);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        last = p;
    });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((type) =>
        canvas.addEventListener(type, () => { stroking = false; }));

    return {
        reset(dataUrl) {
            history = [];
            drawn = false;
            clear();
            setTool(false);
            original = '';
            loaded = true;
            if (dataUrl && dataUrl.startsWith('data:image/png;base64,')) {
                original = dataUrl;
                loaded = false;
                const img = new Image();
                img.onload = () => {
                    if (history.length === 0) clear();
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    drawn = true;
                    loaded = true;
                };
                img.src = dataUrl;
            }
        },
        value() {
            if (!loaded && history.length === 0) return original;
            return drawn ? canvas.toDataURL('image/png') : '';
        },
    };
}

const COLORS = ['#FEFAF4', '#FFF9C4', '#E3F2FD', '#FCE4EC'];
const STAR_COLOR = '#D26343';
const TAB_TITLES = { main: 'Главная', important: 'Важное', trash: 'Корзина' };

function initWorkspace() {
    if (!tokens.present) { window.location.replace(URLS.login); return; }

    const state = { notes: [], trash: [], tab: 'main', query: '', editing: null };
    const grid = $('#grid');
    const addCard = $('#addCard');
    const modal = $('#noteModal');
    const form = $('#noteForm');
    let dragged = null;
    const pad = createDrawingPad($('#drawCanvas'));

    function showError(message) {
        const box = $('#boardError');
        box.textContent = message;
        box.hidden = !message;
    }

    async function load() {
        try {
            const [notes, trash] = await Promise.all([api('/notes/'), api('/notes/?trash=1')]);
            state.notes = notes;
            state.trash = trash;
            showError('');
            render();
        } catch (err) {
            showError(err.message);
        }
    }

    function visibleNotes() {
        let list;
        if (state.tab === 'trash') list = state.trash;
        else if (state.tab === 'important') list = state.notes.filter((n) => n.is_important);
        else list = state.notes;
        const q = state.query;
        if (!q) return list;
        return list.filter((n) => [n.title, n.description, n.category]
            .some((v) => (v || '').toLowerCase().includes(q)));
    }

    function actionButton(name, label, onClick, color) {
        return el('button', {
            type: 'button', class: 'action-btn', title: label, 'aria-label': label,
            onclick: (e) => { e.stopPropagation(); onClick(); },
        }, icon(name, color));
    }

    function noteContent(note) {
        const content = el('div', { class: 'note-content' });
        const lines = (note.description || '').split('\n').map((s) => s.trim()).filter(Boolean);
        if (lines.length) {
            content.append(el('ul', {}, lines.map((line) =>
                el('li', {}, el('span', { class: 'checkbox-mock' }), el('span', { text: line })))));
        }
        if (note.drawing && note.drawing.startsWith('data:image/png;base64,')) {
            content.append(el('img', { class: 'note-image', src: note.drawing, alt: 'Рисунок к заметке' }));
        }
        return content;
    }

    function noteCard(note) {
        const inTrash = state.tab === 'trash';
        const actions = inTrash
            ? [
                actionButton('restore_from_trash', 'Восстановить', () => restore(note)),
                actionButton('delete_forever', 'Удалить навсегда', () => purge(note)),
            ]
            : [
                actionButton('palette', 'Сменить цвет', () => cycleColor(note)),
                actionButton(note.is_important ? 'star' : 'star_border',
                    note.is_important ? 'Убрать из важного' : 'Отметить как важное',
                    () => toggleImportant(note), note.is_important ? STAR_COLOR : null),
                actionButton('delete', 'В корзину', () => moveToTrash(note)),
            ];

        const footer = el('div', { class: 'note-footer' },
            note.category ? el('span', { class: 'badge', text: note.category }) : el('span'),
            el('span', { text: fmtDate(inTrash && note.deleted_at ? note.deleted_at : note.updated_at) }));

        const card = el('article', {
            class: 'note-card' + (inTrash ? ' is-trash' : ' is-editable'),
            draggable: inTrash ? null : 'true',
            'data-id': String(note.id),
        },
            el('div', { class: 'note-tape' }),
            el('div', { class: 'note-actions' }, actions),
            el('h3', { class: 'note-title', text: note.title }),
            noteContent(note),
            footer);

        if (COLORS.includes(note.color)) card.style.backgroundColor = note.color;
        if (!inTrash) {
            card.addEventListener('click', () => openModal(note));
            addDragHandlers(card);
        }
        return card;
    }

    function render() {
        $$('.sidebar-menu a').forEach((a) => a.classList.toggle('active', a.dataset.tab === state.tab));
        $('#boardTitle').textContent = TAB_TITLES[state.tab];
        const all = state.notes.concat(state.trash);
        const latest = all.reduce((max, n) => (n.updated_at > max ? n.updated_at : max), '');
        $('#lastChange').textContent = latest
            ? 'Последнее изменение: ' + fmtDate(latest)
            : 'Заметок пока нет';

        const list = visibleNotes();
        const cards = list.map(noteCard);
        const nodes = [...cards];
        if (state.tab !== 'trash') nodes.push(addCard);
        if (!list.length) {
            const hint = state.query ? 'Ничего не нашлось'
                : state.tab === 'trash' ? 'Корзина пуста'
                    : state.tab === 'important' ? 'Отметьте заметку звёздочкой, и она появится здесь' : '';
            if (hint) nodes.unshift(el('p', { class: 'empty-hint', text: hint }));
        }
        grid.replaceChildren(...nodes);
    }

        async function update(note, data) {
        Object.assign(note, data);
        render();
        try {
            await api(`/notes/${note.id}/`, { method: 'PATCH', data });
        } catch (err) {
            showError(err.message);
            await load();
        }
    }

    function cycleColor(note) {
        const next = COLORS[(COLORS.indexOf(note.color) + 1) % COLORS.length];
        update(note, { color: next });
    }

    function toggleImportant(note) {
        update(note, { is_important: !note.is_important });
    }

    async function moveToTrash(note) {
        try {
            await api(`/notes/${note.id}/`, { method: 'DELETE' });
            await load();
        } catch (err) { showError(err.message); }
    }

    async function restore(note) {
        try {
            await api(`/notes/${note.id}/restore/`, { method: 'POST' });
            await load();
        } catch (err) { showError(err.message); }
    }

    async function purge(note) {
        if (!window.confirm(`Удалить «${note.title}» навсегда? Это действие нельзя отменить.`)) return;
        try {
            await api(`/notes/${note.id}/purge/`, { method: 'DELETE' });
            await load();
        } catch (err) { showError(err.message); }
    }

    function addDragHandlers(card) {
        card.addEventListener('dragstart', (e) => {
            dragged = card;
            if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = 'move';
            }
            setTimeout(() => card.classList.add('dragging'), 0);
        });

        card.addEventListener('dragend', () => {
            card.classList.remove('dragging');
            dragged = null;
        });

        card.addEventListener('dragover', (e) => {
            e.preventDefault();
            if (!dragged || dragged === card) return;

            const rect = card.getBoundingClientRect();
            const relX = e.clientX - rect.left;
            const relY = e.clientY - rect.top;

            const insertAfter = relY > rect.height / 2 || (relY > 0 && relX > rect.width / 2);
            const nextSibling = insertAfter ? card.nextElementSibling : card;

            if (dragged.nextElementSibling === nextSibling) return;

            const children = Array.from(grid.children);
            const rects = new Map();
            children.forEach((c) => rects.set(c, c.getBoundingClientRect()));

            if (insertAfter) {
                card.after(dragged);
            } else {
                card.before(dragged);
            }

            children.forEach((c) => {
                const first = rects.get(c);
                if (!first) return;
                const last = c.getBoundingClientRect();
                const dx = first.left - last.left;
                const dy = first.top - last.top;
                if (dx !== 0 || dy !== 0) {
                    c.animate(
                        [
                            { transform: `translate(${dx}px, ${dy}px)` },
                            { transform: 'translate(0, 0)' }
                        ],
                        { duration: 250, easing: 'ease-out' }
                    );
                }
            });
        });
    }

    function openModal(note = null) {
        state.editing = note;
        $('#modalTitle').textContent = note ? 'Редактирование' : 'Новая заметка';
        $('#noteTitle').value = note ? note.title : '';
        $('#noteText').value = note ? note.description : '';
        $('#noteCategory').value = note ? note.category : '';
        $('#noteError').textContent = '';
        pad.reset(note ? note.drawing : '');
        modal.style.display = 'flex';
        $('#noteTitle').focus();
    }

    function closeModal() {
        modal.style.display = 'none';
        state.editing = null;
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = {
            title: $('#noteTitle').value.trim(),
            description: $('#noteText').value,
            category: $('#noteCategory').value.trim(),
            drawing: pad.value(),
        };
        if (!data.title) { $('#noteError').textContent = 'Введите заголовок'; return; }
        setBusy(form, true);
        try {
            if (state.editing) await api(`/notes/${state.editing.id}/`, { method: 'PATCH', data });
            else await api('/notes/', { method: 'POST', data });
            closeModal();
            await load();
        } catch (err) {
            $('#noteError').textContent = err.message;
        } finally {
            setBusy(form, false);
        }
    });

    $('#modalClose').addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.style.display === 'flex') closeModal();
    });
    $('#createBtn').addEventListener('click', () => openModal());
    addCard.addEventListener('click', () => openModal());

    $$('.sidebar-menu a').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        state.tab = a.dataset.tab;
        render();
    }));
    $('#search').addEventListener('input', (e) => {
        state.query = e.target.value.trim().toLowerCase();
        render();
    });

    api('/auth/me/').then((user) => {
        $('#userEmail').textContent = user.email;
        paintAvatar($('#userAvatar'), user);
    }).catch((err) => showError(err.message));
    load();
}

const PAGES = {
    index: initIndex,
    login: initLogin,
    register: initRegister,
    account: initAccount,
    workspace: initWorkspace,
};
(PAGES[body.dataset.page] || (() => { }))();