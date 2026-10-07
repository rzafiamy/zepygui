/* PyGUI client runtime: receives UI trees from Python, patches the DOM, sends events back. */
(() => {
  "use strict";
  const CFG = window.__PG__ || {};
  const SVG = "http://www.w3.org/2000/svg";
  const root = document.getElementById("pg-root");
  const toastBox = document.getElementById("pg-toasts");
  const statusEl = document.getElementById("pg-status");
  const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pygui;
  const NATIVE = !!bridge;
  const PROPS = { value: 1, checked: 1 };
  const calls = new Map();
  const debounced = new Map();
  let ws = null, seq = 0, ack = 0, retries = 0, boot = null, statusTimer = null, callId = 0, rendered = false;

  // ------------------------------------------------------------------ transport
  function send(msg) {
    if (NATIVE) { bridge.postMessage(JSON.stringify(msg)); return true; }
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify(msg)); return true; }
    return false;
  }

  function currentPath() {
    return NATIVE ? (location.hash.slice(1) || "/") : location.pathname + location.search;
  }

  function setPath(path) {
    if (currentPath() === path) return;
    if (NATIVE) history.pushState(null, "", location.href.split("#")[0] + "#" + path);
    else history.pushState(null, "", path);
  }

  function connect() {
    const q = new URLSearchParams({ sid: sessionId(), path: currentPath(), theme: document.documentElement.dataset.theme });
    ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/_pg/ws?${q}`);
    ws.onopen = () => { retries = 0; showStatus(false); };
    ws.onmessage = (e) => { try { handle(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    ws.onclose = () => { ws = null; showStatus(true); setTimeout(connect, Math.min(200 * 2 ** retries++, 2000)); };
  }

  function sessionId() {
    let sid = null;
    try { sid = sessionStorage.getItem("pg_sid"); } catch (_) { }
    if (!sid) {
      sid = Math.random().toString(36).slice(2) + Date.now().toString(36);
      try { sessionStorage.setItem("pg_sid", sid); } catch (_) { }
    }
    return sid;
  }

  function showStatus(on) {
    clearTimeout(statusTimer);
    if (on) statusTimer = setTimeout(() => statusEl.classList.add("show"), 500);
    else statusEl.classList.remove("show");
  }

  // ------------------------------------------------------------------ messages
  const handlers = {
    hello(m) { if (boot && boot !== m.boot) { location.reload(); return; } boot = m.boot; },
    render(m) {
      ack = m.ack || 0;
      if (!rendered) { root.innerHTML = ""; rendered = true; }
      patchChildren(root, [m.tree], false);
    },
    ack(m) { ack = Math.max(ack, m.ack || 0); },
    toast(m) { toast(m); },
    nav(m) { setPath(m.path); window.scrollTo(0, 0); },
    title(m) { document.title = m.title; },
    theme(m) { applyTheme(m.theme, true); },
    js(m) { try { (new Function(m.code))(); } catch (err) { console.error(err); } },
    result(m) {
      const p = calls.get(m.id);
      if (!p) return;
      calls.delete(m.id);
      m.ok ? p.resolve(m.value) : p.reject(new Error(m.error));
    },
    close() { window.close(); },
  };
  function handle(m) { const f = handlers[m.type]; if (f) f(m); }
  window.__pg_recv = handle;

  // ------------------------------------------------------------------ theme
  function applyTheme(theme, report) {
    try { localStorage.setItem("pg_theme:" + CFG.title, theme); } catch (_) { }
    const resolved = theme === "auto" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : theme;
    document.documentElement.classList.add("pg-theme-switch");
    document.documentElement.dataset.theme = resolved;
    setTimeout(() => document.documentElement.classList.remove("pg-theme-switch"), 300);
    if (report) send({ type: "theme", theme: resolved });
  }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    let pref = CFG.theme;
    try { pref = localStorage.getItem("pg_theme:" + CFG.title) || pref; } catch (_) { }
    if (pref === "auto") applyTheme("auto", true);
  });

  // ------------------------------------------------------------------ events
  function extract(e, el) {
    const d = {};
    if (e.type === "submit") {
      const form = {};
      new FormData(el).forEach((v, k) => { form[k] = k in form ? [].concat(form[k], v) : v; });
      el.querySelectorAll("input[type=checkbox][name]").forEach((c) => { form[c.name] = c.checked; });
      d.form = form;
      return d;
    }
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
      d.value = el.value;
      if (el.type === "checkbox" || el.type === "radio") d.checked = el.checked;
    }
    if ("key" in e) { d.key = e.key; d.ctrl = e.ctrlKey; d.shift = e.shiftKey; d.alt = e.altKey; d.meta = e.metaKey; }
    return d;
  }

  function emit(spec, data, el, isInput) {
    const s = ++seq;
    if (isInput && el) el._pgSeq = s;
    send({ type: "event", h: spec.h, d: data, s });
  }

  function flushDebounced() {
    for (const [h, p] of debounced) { clearTimeout(p.timer); debounced.delete(h); p.fire(); }
  }

  function listener(e) {
    const el = e.currentTarget;
    const specs = el._pgE && el._pgE[e.type];
    if (!specs) return;
    if (el.type === "range") el.style.setProperty("--pct", rangePct(el));
    const isInput = e.type === "input" || e.type === "change";
    for (const spec of specs) {
      if (spec.keys && !spec.keys.includes(e.key)) continue;
      if (spec.self && e.target !== el) continue;
      if (spec.prevent) e.preventDefault();
      if (spec.stop) e.stopPropagation();
      const data = extract(e, el);
      if (spec.debounce) {
        const prev = debounced.get(spec.h);
        if (prev) clearTimeout(prev.timer);
        el._pgPending = true;
        const fire = () => { el._pgPending = false; emit(spec, data, el, isInput); };
        debounced.set(spec.h, { fire, timer: setTimeout(() => { debounced.delete(spec.h); fire(); }, spec.debounce) });
      } else {
        flushDebounced();
        emit(spec, data, el, isInput);
      }
    }
  }

  function navigate(path) {
    setPath(path);
    send({ type: "nav", path });
    window.scrollTo(0, 0);
  }

  document.addEventListener("click", (e) => {
    const copyBtn = e.target.closest("[data-pg-copy]");
    if (copyBtn) {
      copyText(copyBtn.getAttribute("data-pg-copy"));
      return;
    }
    const a = e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0) return;
    const href = a.getAttribute("href");
    if (a.hasAttribute("data-pg-link")) {
      if (e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      navigate(href);
    } else if (NATIVE && /^(https?|mailto):/i.test(href)) {
      e.preventDefault();  // external links open in the user's browser, never inside the app
      send({ type: "open_url", url: a.href });
    }
  });
  window.addEventListener(NATIVE ? "hashchange" : "popstate", () => send({ type: "nav", path: currentPath() }));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const layers = document.querySelectorAll("[data-pg-esc]");
    const top = layers[layers.length - 1];
    if (top && top._pgE && top._pgE.click) emit(top._pgE.click[0], {}, null, false);
  });

  function copyText(value) {
    const done = () => toast({ message: "Copied to clipboard", kind: "success", duration: 1.5 });
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(value).then(done, () => fallbackCopy(value, done));
    } else fallbackCopy(value, done);
  }

  function fallbackCopy(value, done) {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); done(); } catch (_) { }
    ta.remove();
  }

  // ------------------------------------------------------------------ DOM patching
  function rangePct(el) {
    const min = +el.min || 0, max = +el.max || 100;
    return max === min ? "0%" : ((el.value - min) / (max - min)) * 100 + "%";
  }

  function setAttr(el, k, v) {
    if (k in PROPS) {
      // Don't overwrite what the user is typing until Python has seen it.
      if (el._pgPending || (el._pgSeq || 0) > ack) return;
      if (k === "value") {
        const s = v == null ? "" : String(v);
        if (el.value !== s) el.value = s;
      } else el.checked = !!v;
      return;
    }
    if (v === true) el.setAttribute(k, "");
    else if (v === false || v == null) el.removeAttribute(k);
    else el.setAttribute(k, String(v));
  }

  function update(el, v, svg) {
    const a = v.a || {}, old = el._pgA || {};
    for (const k in old) if (!(k in a) && !(k in PROPS)) el.removeAttribute(k);
    let deferredValue;
    for (const k in a) {
      if (k in PROPS) {
        if (el.tagName === "SELECT") deferredValue = a[k];
        else setAttr(el, k, a[k]);
      } else if (!(k in old) || old[k] !== a[k]) setAttr(el, k, a[k]);
    }
    el._pgA = a;
    el._pgE = v.e || null;
    if (v.e) {
      if (!el._pgL) el._pgL = new Set();
      for (const type in v.e) if (!el._pgL.has(type)) { el._pgL.add(type); el.addEventListener(type, listener); }
    }
    if (v.h != null) {
      if (el._pgH !== v.h) { el.innerHTML = v.h; el._pgH = v.h; }
    } else {
      if (el._pgH != null) { el.innerHTML = ""; el._pgH = null; }
      patchChildren(el, v.c || [], svg && v.t !== "foreignObject");
    }
    if (deferredValue !== undefined) setAttr(el, "value", deferredValue);
    if (el.type === "range") el.style.setProperty("--pct", rangePct(el));
  }

  function create(v, svg) {
    if (typeof v === "string") return document.createTextNode(v);
    const isSvg = svg || v.t === "svg";
    const el = isSvg ? document.createElementNS(SVG, v.t) : document.createElement(v.t);
    if (v.k != null) el._pgK = v.k;
    update(el, v, isSvg);
    if (v.a && v.a.autofocus) requestAnimationFrame(() => el.focus());
    return el;
  }

  function same(node, v) {
    if (typeof v === "string") return node.nodeType === 3;
    return node.nodeType === 1 && node.localName === v.t && (node._pgK ?? null) === (v.k ?? null);
  }

  function patchChildren(parent, vs, svg) {
    const olds = Array.from(parent.childNodes);
    const keyed = new Map();
    const unkeyed = [];
    for (const n of olds) (n._pgK != null ? keyed.set(n._pgK, n) : unkeyed.push(n));
    let u = 0;
    const used = new Set();
    const next = vs.map((v) => {
      const key = typeof v === "object" ? v.k : null;
      let node = null;
      if (key != null) node = keyed.get(key) || null;
      else if (u < unkeyed.length) node = unkeyed[u++];
      if (node && !used.has(node) && same(node, v)) {
        used.add(node);
        if (typeof v === "string") { if (node.nodeValue !== v) node.nodeValue = v; }
        else update(node, v, svg || v.t === "svg");
        return node;
      }
      return create(v, svg);
    });
    for (const n of olds) if (!used.has(n)) n.remove();
    for (let i = 0; i < next.length; i++) {
      const cur = parent.childNodes[i];
      if (cur !== next[i]) parent.insertBefore(next[i], cur || null);
    }
  }

  // ------------------------------------------------------------------ toasts
  const TOAST_ICONS = {
    success: '<path d="M20 6 9 17l-5-5"/>',
    error: '<path d="M18 6 6 18M6 6l12 12"/>',
    warning: '<path d="M12 9v4M12 17h.01"/><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>',
    info: '<path d="M12 16v-4M12 8h.01"/><circle cx="12" cy="12" r="10"/>',
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function toast({ message, title, kind = "info", duration = 3 }) {
    const t = document.createElement("div");
    t.className = `pg-toast pg-toast-${kind}`;
    t.innerHTML = `<span class="pg-toast-icon"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${TOAST_ICONS[kind] || TOAST_ICONS.info}</svg></span><div class="pg-toast-body">${title ? `<div class="pg-toast-title">${esc(title)}</div>` : ""}<div class="pg-toast-msg">${esc(message)}</div></div>`;
    t.addEventListener("click", () => dismiss(t));
    toastBox.appendChild(t);
    requestAnimationFrame(() => requestAnimationFrame(() => t.classList.add("show")));
    if (duration > 0) setTimeout(() => dismiss(t), duration * 1000);
  }

  function dismiss(t) {
    t.classList.remove("show");
    t.classList.add("hide");
    setTimeout(() => t.remove(), 260);
  }

  // ------------------------------------------------------------------ public API
  window.pygui = {
    /** Call a Python function registered with @app.expose: `await pygui.call("name", arg1, arg2)` */
    call(name, ...args) {
      return new Promise((resolve, reject) => {
        const id = ++callId;
        calls.set(id, { resolve, reject });
        if (!send({ type: "call", id, name, args })) { calls.delete(id); reject(new Error("not connected")); }
      });
    },
    navigate,
    toast,
    setTheme: (t) => applyTheme(t, true),
  };

  if (NATIVE) send({ type: "connect", path: currentPath(), theme: document.documentElement.dataset.theme });
  else connect();
})();
