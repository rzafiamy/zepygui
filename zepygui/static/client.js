/* ZePyGUI client runtime: receives UI trees from Python, patches the DOM, sends events back. */
(() => {
  "use strict";
  const CFG = window.__PG__ || {};
  const SVG = "http://www.w3.org/2000/svg";
  const root = document.getElementById("pg-root");
  const toastBox = document.getElementById("pg-toasts");
  const statusEl = document.getElementById("pg-status");
  const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.zepygui;
  const NATIVE = !!bridge;
  const PROPS = { value: 1, checked: 1 };
  const calls = new Map();
  const debounced = new Map();
  const throttled = new Map();
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
      if (m.diff && !rendered) { send({ type: "resync" }); return; }
      if (!rendered) { root.innerHTML = ""; rendered = true; }
      try {
        if (m.diff) applyPatch(root, [m.tree], false);
        else patchChildren(root, [m.tree], false);
      } catch (err) {
        console.error(err);
        send({ type: "resync" });  // the DOM drifted from what Python expects: ask for a full tree
      }
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
    log(m) {
      const b = logBuf(m.id);
      if (m.reset || m.gen !== b.gen) { b.gen = m.gen; b.start = m.start; b.lines = m.lines; b.version++; }
      else { const L = b.lines, add = m.lines; for (let i = 0; i < add.length; i++) L.push(add[i]); }
      b.max = m.max || b.max;
      // trim in batches (10% slack) so a full console doesn't shift its array on every message
      if (b.lines.length > b.max * 1.1) { const cut = b.lines.length - b.max; b.lines.splice(0, cut); b.start += cut; b.version++; }
      for (const el of b.views) scheduleLog(el);
    },
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
    if (el._ed) d.value = el._ed.ta.value;  // a code editor: its text, whatever the event
    else if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
      d.value = el.value;
      if (el.type === "checkbox" || el.type === "radio") d.checked = el.checked;
    }
    if ("key" in e) d.key = e.key;
    if ("ctrlKey" in e) { d.ctrl = e.ctrlKey; d.shift = e.shiftKey; d.alt = e.altKey; d.meta = e.metaKey; }
    if (e.type === "scroll") {
      d.scrollTop = Math.round(el.scrollTop); d.scrollLeft = Math.round(el.scrollLeft);
      d.width = el.clientWidth; d.height = el.clientHeight;
    }
    // Event delegation: one handler on a list receives the data-pg-item of the row under the
    // pointer, so a list of 10,000 rows needs one handler instead of 10,000.
    const item = e.target && e.target.closest ? e.target.closest("[data-pg-item]") : null;
    if (item && el.contains(item)) d.item = item.getAttribute("data-pg-item");
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
      if (spec.throttle) {
        // first event goes out at once; later ones at most every `throttle` ms, last one always
        const t = throttled.get(spec.h) || { last: 0, timer: null, data: null };
        throttled.set(spec.h, t);
        t.data = data;
        const wait = t.last + spec.throttle - performance.now();
        if (wait <= 0 && !t.timer) { t.last = performance.now(); emit(spec, data, el, false); }
        else if (!t.timer) t.timer = setTimeout(() => { t.timer = null; t.last = performance.now(); emit(spec, t.data, el, false); }, Math.max(wait, 0));
        continue;
      }
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
    if (k === "data-pg-reveal" && v != null && v !== false) {
      // keep the element (e.g. the row picked with the keyboard) in view
      requestAnimationFrame(() => el.isConnected && el.scrollIntoView({ block: "nearest", inline: "nearest" }));
    } else if (k === "data-pg-popover" && v != null && v !== false) {
      // a dropdown menu: fixed position under its trigger, so no scrolling parent clips it
      requestAnimationFrame(() => placePopover(el, String(v)));
    } else if (k === "data-pg-scroll" && v != null) {
      const top = parseFloat(String(v));  // "offset:nonce": the nonce lets the same offset be sent again
      requestAnimationFrame(() => { if (Math.abs(el.scrollTop - top) > 1) el.scrollTop = top; });
    }
  }

  function placePopover(el, align) {
    if (!el.isConnected) return;
    const trigger = el.parentElement && el.parentElement.querySelector("[data-pg-trigger]");
    if (!trigger) return;
    const r = trigger.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
    let left = align === "start" ? r.left : r.right - w;
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
    let top = r.bottom + 6;
    if (top + h > window.innerHeight - 8 && r.top - h - 6 > 8) top = r.top - h - 6;  // open upwards near the bottom
    el.style.left = left + "px";
    el.style.top = top + "px";
    // a transformed ancestor (a card lifted on hover) moves "fixed" boxes: correct by what we measure
    const b = el.getBoundingClientRect();
    if (Math.abs(b.left - left) > 0.5) el.style.left = (2 * left - b.left) + "px";
    if (Math.abs(b.top - top) > 0.5) el.style.top = (2 * top - b.top) + "px";
    el.classList.add("pg-menu-placed");
    const first = el.querySelector(".pg-menu-item:not([disabled])");
    if (first) first.focus({ preventScroll: true });
  }

  document.addEventListener("keydown", (e) => {
    // arrow keys move between the items of an open menu
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const menu = e.target.closest && e.target.closest(".pg-menu");
    if (!menu) return;
    e.preventDefault();
    const items = Array.from(menu.querySelectorAll(".pg-menu-item:not([disabled])"));
    const i = items.indexOf(document.activeElement);
    const next = items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length];
    if (next) next.focus();
  });

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
    if (a["data-pg-log"] != null) {
      mountLog(el, a);  // the console draws its own children from its line buffer
      return;
    }
    if (el._log) unmountLog(el);  // this node was a console and is now reused for something else
    if (a["data-pg-editor"] != null) { mountEditor(el, a); return; }  // the editor draws its own children
    if (el._ed) unmountEditor(el);
    if (v.h != null) {
      if (el._pgH !== v.h) { el.innerHTML = v.h; el._pgH = v.h; }
    } else {
      if (el._pgH != null) { el.innerHTML = ""; el._pgH = null; }
      const childSvg = svg && v.t !== "foreignObject";
      if (v.d) applyPatch(el, v.c || [], childSvg);
      else patchChildren(el, v.c || [], childSvg);
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

  // A patch (see zepygui/diff.py) names the old children it keeps by index: a number keeps
  // that node untouched, an object with "o" updates that node, anything else is created.
  function applyPatch(parent, ps, svg) {
    const olds = Array.from(parent.childNodes);
    const used = new Set();
    const next = ps.map((p) => {
      if (typeof p === "number" || (p && typeof p === "object" && p.o != null)) {
        const node = olds[typeof p === "number" ? p : p.o];
        if (!node || used.has(node)) throw new Error("zepygui: patch does not match the DOM");
        used.add(node);
        if (typeof p !== "number") update(node, p, svg || p.t === "svg");
        return node;
      }
      return create(p, svg);
    });
    for (const n of olds) if (!used.has(n)) n.remove();
    for (let i = 0; i < next.length; i++) {
      const cur = parent.childNodes[i];
      if (cur !== next[i]) parent.insertBefore(next[i], cur || null);
    }
  }

  // ------------------------------------------------------------------ log console
  // Lines live in a buffer per Log id (outside the DOM, so a view can be re-created without a
  // resend). A view only creates elements for the lines in its viewport.
  const logs = new Map();
  const LOG_OVERSCAN = 20;
  const LEVEL = [[/\b(ERROR|FATAL|CRITICAL)\b|Traceback|Exception\b/, "pg-log-err"], [/\bWARN(ING)?\b/, "pg-log-warn"], [/\bDEBUG\b/, "pg-log-dim"], [/\b(SUCCESS|PASSED)\b|✔/, "pg-log-ok"], [/(^|\s)(▶|━━|==>)\s/, "pg-log-head"]];

  function logBuf(id) {
    let b = logs.get(id);
    if (!b) { b = { gen: -1, start: 0, lines: [], max: 100000, version: 0, views: new Set() }; logs.set(id, b); }
    return b;
  }

  function mountLog(el, a) {
    if (!el._log) {
      const L = el._log = { id: null, follow: true, lh: 0, raf: 0 };
      el.innerHTML = '<div class="pg-log-spacer"></div><div class="pg-log-rows"></div>';
      L.onScroll = () => {
        if (!L.programmatic) L.follow = el.scrollTop + el.clientHeight >= el.scrollHeight - (L.lh || 18) * 1.5;
        L.programmatic = false;
        scheduleLog(el);
      };
      el.addEventListener("scroll", L.onScroll, { passive: true });
    }
    const L = el._log;
    if (L.id !== a["data-pg-log"]) {
      if (L.id) logBuf(L.id).views.delete(el);
      L.id = a["data-pg-log"];
      logBuf(L.id).views.add(el);
      L.idx = null;
    }
    L.filter = String(a["data-filter"] || "").toLowerCase();
    L.followOn = a["data-follow"] !== "false";
    scheduleLog(el);
  }

  function unmountLog(el) {
    const L = el._log;
    if (L.raf) cancelAnimationFrame(L.raf);
    if (L.id) logBuf(L.id).views.delete(el);
    el.removeEventListener("scroll", L.onScroll);
    el._log = null;
    el.innerHTML = "";
  }

  function scheduleLog(el) {
    const L = el._log;
    if (L && !L.raf) L.raf = requestAnimationFrame(() => { L.raf = 0; drawLog(el); });
  }

  function drawLog(el) {
    const L = el._log, b = logBuf(L.id);
    if (!el.isConnected) { b.views.delete(el); return; }
    const spacer = el.firstChild, rows = el.lastChild;
    if (!L.lh) {
      const probe = document.createElement("div");
      probe.textContent = "M";
      rows.appendChild(probe);
      L.lh = probe.getBoundingClientRect().height || 18;
      probe.remove();
    }
    let n = b.lines.length, pick = null;
    if (L.filter) {
      // the matching-line index grows incrementally; rebuilt only when the filter or buffer resets
      if (!L.idx || L.idxFilter !== L.filter || L.idxVersion !== b.version) {
        L.idx = []; L.scanned = 0; L.idxFilter = L.filter; L.idxVersion = b.version;
      }
      for (let i = L.scanned; i < b.lines.length; i++) if (b.lines[i].toLowerCase().includes(L.filter)) L.idx.push(i);
      L.scanned = b.lines.length;
      n = L.idx.length; pick = L.idx;
    }
    spacer.style.height = n * L.lh + "px";
    if (L.followOn && L.follow) {
      const bottom = Math.max(0, n * L.lh - el.clientHeight);
      if (Math.abs(el.scrollTop - bottom) > 1) { L.programmatic = true; el.scrollTop = bottom; }
    }
    const first = Math.max(0, Math.floor(el.scrollTop / L.lh) - LOG_OVERSCAN);
    const last = Math.min(n, Math.ceil((el.scrollTop + el.clientHeight) / L.lh) + LOG_OVERSCAN);
    rows.style.transform = `translateY(${first * L.lh}px)`;
    const need = Math.max(0, last - first);
    while (rows.childElementCount < need) rows.appendChild(document.createElement("div"));
    while (rows.childElementCount > need) rows.lastChild.remove();
    for (let i = 0; i < need; i++) {
      const at = pick ? pick[first + i] : first + i;
      const text = b.lines[at], row = rows.children[i];
      if (row.textContent !== text) {
        row.textContent = text;
        let cls = "";
        for (const [re, c] of LEVEL) if (re.test(text)) { cls = c; break; }
        row.className = cls;
      }
      const num = String(b.start + at + 1);
      if (row.dataset.n !== num) row.dataset.n = num;
    }
  }


  // ------------------------------------------------------------------ code editor
  // A transparent textarea over a highlighted <pre>: the textarea keeps native editing,
  // selection, IME and undo; the <pre> under it only paints colours.
  const ED_LH = 20;
  const escH = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const tok = (cls, s) => s ? `<span class="tk-${cls}">${escH(s)}</span>` : "";

  // Inline tokens shared by every language: interpolations ${...}, strings, numbers, keywords.
  function hlValue(s, lang) {
    let out = "", i = 0;
    const kw = lang === "python" ? /^(def|class|return|if|elif|else|for|while|import|from|as|with|try|except|finally|raise|in|not|and|or|is|lambda|yield|pass|break|continue|None|True|False)\b/
      : lang === "shell" ? /^(if|then|else|elif|fi|for|do|done|while|case|esac|function|export|local|return|in|echo|cd|exit)\b/
      : /^(true|false|yes|no|on|off|null|True|False|None|~)(?=\s*(?:$|[,\]}#;]))/;
    while (i < s.length) {
      const r = s.slice(i);
      let m;
      if ((m = /^\$\{[^}\n]*\}?|^\$[A-Za-z_][A-Za-z0-9_]*/.exec(r))) { out += tok("var", m[0]); i += m[0].length; continue; }
      if ((lang === "yaml" || lang === "python" || lang === "shell" || lang === "toml") && (m = /^#.*/.exec(r)) && (i === 0 || /\s/.test(s[i - 1]))) { out += tok("com", m[0]); break; }
      if (lang === "ini" && (m = /^\s[;#].*/.exec(r))) { out += tok("com", m[0]); break; }
      if ((m = /^"(?:[^"\\]|\\.)*"?|^'(?:[^'\\]|\\.)*'?/.exec(r))) { out += hlString(m[0]); i += m[0].length; continue; }
      if ((m = /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])/.exec(r)) && (i === 0 || /[\s:=,\[{(]/.test(s[i - 1]))) { out += tok("num", m[0]); i += m[0].length; continue; }
      if ((m = kw.exec(r)) && (i === 0 || /[\s:=,\[{(]/.test(s[i - 1]))) { out += tok("kw", m[0]); i += m[0].length; continue; }
      if (lang === "yaml" && (m = /^[&*][\w-]+|^![\w!-]+/.exec(r)) && (i === 0 || /\s/.test(s[i - 1]))) { out += tok("tag", m[0]); i += m[0].length; continue; }
      if ((m = /^[\[\]{},|&;<>()]+/.exec(r))) { out += tok("pun", m[0]); i += m[0].length; continue; }
      if ((m = /^[^\s$"'#;\[\]{},|&<>()]+|^\s+/.exec(r))) { out += escH(m[0]); i += m[0].length; continue; }
      out += escH(s[i]); i++;
    }
    return out;
  }

  function hlString(s) {
    // keep ${...} visible inside strings
    return s.split(/(\$\{[^}]*\}?)/).map((p, k) => k % 2 ? tok("var", p) : tok("str", p)).join("");
  }

  function hlYamlLine(line, st) {
    if (st.block != null) {
      const ind = line.match(/^\s*/)[0].length;
      if (!line.trim() || ind > st.block) return hlString(line);
      st.block = null;
    }
    if (/^\s*#/.test(line)) return tok("com", line);
    if (/^(---|\.\.\.)\s*$/.test(line)) return tok("pun", line);
    const m = /^(\s*)((?:-\s+)*)((?:"[^"]*"|'[^']*'|[^\s#'"\-:][^#:]*?|-[^\s][^#:]*?))(\s*:)(?=\s|$)(.*)$/.exec(line);
    let head = "", rest = line, ind = 0;
    if (m) {
      ind = m[1].length + m[2].length;
      head = escH(m[1]) + tok("pun", m[2]) + tok("key", m[3]) + tok("pun", m[4]);
      rest = m[5];
    } else {
      const d = /^(\s*)((?:-\s+|-$)+)(.*)$/.exec(line);
      if (d) { head = escH(d[1]) + tok("pun", d[2]); rest = d[3]; ind = d[1].length; }
    }
    if (/^\s*[|>][-+0-9]*\s*(#.*)?$/.test(rest)) st.block = ind;
    return head + hlValue(rest, "yaml");
  }

  function hlIniLine(line, st) {
    let m;
    if (st.cont && /^\s+\S/.test(line) && !/^\s*[;#]/.test(line)) return hlValue(line, "ini");
    st.cont = false;
    if ((m = /^(\s*)([;#].*)$/.exec(line))) return escH(m[1]) + tok("com", m[2]);
    if ((m = /^(\s*)(\[)([^\]]*)(\])(.*)$/.exec(line))) {
      const name = m[3].split(":");
      const inner = name.length > 1 ? tok("kw", name[0]) + tok("pun", ":") + tok("sec", name.slice(1).join(":")) : tok("sec", m[3]);
      return escH(m[1]) + tok("pun", m[2]) + inner + tok("pun", m[4]) + hlValue(m[5], "ini");
    }
    if ((m = /^(\s*)([^=:\s][^=:]*?)(\s*[=:])(.*)$/.exec(line))) { st.cont = true; return escH(m[1]) + tok("key", m[2]) + tok("pun", m[3]) + hlValue(m[4], "ini"); }
    return hlValue(line, "ini");
  }

  function hlTomlLine(line, st) {
    let m;
    if ((m = /^(\s*)(\[\[?)([^\]]*)(\]\]?)(.*)$/.exec(line))) return escH(m[1]) + tok("pun", m[2]) + tok("sec", m[3]) + tok("pun", m[4]) + hlValue(m[5], "toml");
    if ((m = /^(\s*)([\w.\-"']+)(\s*=)(.*)$/.exec(line))) return escH(m[1]) + tok("key", m[2]) + tok("pun", m[3]) + hlValue(m[4], "toml");
    return hlValue(line, "toml");
  }

  function hlJsonLine(line) {
    return line.replace(/("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b|([{}\[\],])|([^"\d{}\[\],tfn-]+|.)/g,
      (all, str, colon, num, kw, pun, other) => str ? (colon ? tok("key", str) + tok("pun", colon) : tok("str", str))
        : num ? tok("num", num) : kw ? tok("kw", kw) : pun ? tok("pun", pun) : escH(all));
  }

  function highlight(text, lang) {
    const lines = text.split("\n"), st = {}, out = new Array(lines.length);
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      out[i] = lang === "yaml" ? hlYamlLine(l, st) : lang === "ini" ? hlIniLine(l, st) : lang === "toml" ? hlTomlLine(l, st)
        : lang === "json" ? hlJsonLine(l) : lang === "text" ? escH(l) : hlValue(l, lang);
    }
    return out;
  }

  function mountEditor(el, a) {
    let E = el._ed;
    if (!E) {
      el.innerHTML = '<div class="pg-ed-gutter"><div class="pg-ed-gin"></div></div>' +
        '<div class="pg-ed-main"><pre class="pg-ed-hl" aria-hidden="true"><code></code></pre>' +
        '<textarea class="pg-ed-ta" spellcheck="false" autocapitalize="off" autocomplete="off" wrap="off"></textarea></div>' +
        '<div class="pg-ed-status"><span class="pg-ed-pos"></span><span class="pg-ed-sum"></span><span class="pg-ed-lang"></span></div>';
      E = el._ed = {
        gutter: el.querySelector(".pg-ed-gin"), hl: el.querySelector(".pg-ed-hl"), code: el.querySelector("code"),
        ta: el.querySelector("textarea"), pos: el.querySelector(".pg-ed-pos"), sum: el.querySelector(".pg-ed-sum"),
        langEl: el.querySelector(".pg-ed-lang"), raf: 0, markers: [], lang: "text", goto: null, lines: -1, cur: 0,
      };
      const ta = E.ta;
      const sync = () => {
        E.hl.scrollTop = ta.scrollTop; E.hl.scrollLeft = ta.scrollLeft;
        E.gutter.style.transform = `translateY(${-ta.scrollTop}px)`;
      };
      ta.addEventListener("scroll", sync, { passive: true });
      ta.addEventListener("input", () => scheduleEditor(el));
      const caret = () => { editorCaret(el); };
      ta.addEventListener("keyup", caret); ta.addEventListener("click", caret); ta.addEventListener("select", caret);
      ta.addEventListener("keydown", (e) => editorKey(el, e));
      E.sync = sync;
    }
    E.lang = a["data-pg-editor"] || "text";
    E.tab = +(a["data-tab"] || 2);
    E.langEl.textContent = E.lang.toUpperCase();
    E.ta.readOnly = a["data-readonly"] === "true";
    E.ta.placeholder = a["data-placeholder"] || "";
    try { E.markers = a["data-markers"] ? JSON.parse(a["data-markers"]) : []; } catch (_) { E.markers = []; }
    const v = a["data-value"] == null ? "" : String(a["data-value"]);
    // Don't overwrite what the user is typing until Python has seen it.
    if (!(el._pgPending || (el._pgSeq || 0) > ack) && E.ta.value !== v) {
      const s0 = E.ta.selectionStart, s1 = E.ta.selectionEnd;
      E.ta.value = v;
      if (document.activeElement === E.ta) { E.ta.selectionStart = Math.min(s0, v.length); E.ta.selectionEnd = Math.min(s1, v.length); }
    }
    if (a["data-goto"] && a["data-goto"] !== E.goto) {
      E.goto = a["data-goto"];
      const line = parseInt(E.goto, 10);
      requestAnimationFrame(() => editorGoto(el, line));
    }
    E.lines = -1;  // force a full redraw (markers or language may have changed)
    scheduleEditor(el);
  }

  function unmountEditor(el) {
    if (el._ed.raf) cancelAnimationFrame(el._ed.raf);
    el._ed = null;
    el.innerHTML = "";
  }

  function scheduleEditor(el) {
    const E = el._ed;
    if (E && !E.raf) E.raf = requestAnimationFrame(() => { E.raf = 0; drawEditor(el); });
  }

  function drawEditor(el) {
    const E = el._ed;
    if (!E || !el.isConnected) return;
    const text = E.ta.value;
    const html = highlight(text, E.lang);
    const byLine = new Map();
    const rank = { error: 3, warning: 2, info: 1 };
    for (const m of E.markers) {
      const cur = byLine.get(m.line);
      if (!cur) byLine.set(m.line, { sev: m.severity, msgs: [m.message] });
      else { cur.msgs.push(m.message); if (rank[m.severity] > rank[cur.sev]) cur.sev = m.severity; }
    }
    const caretLine = E.cur;
    let code = "", gut = "";
    for (let i = 0; i < html.length; i++) {
      const mk = byLine.get(i + 1);
      const cls = (mk ? " pg-ed-" + mk.sev : "") + (i === caretLine ? " pg-ed-cur" : "");
      code += `<span class="pg-ed-line${cls}">${html[i] || " "}</span>`;
      gut += `<div class="pg-ed-n${cls}"${mk ? ` title="${esc(mk.msgs.join("\n"))}"` : ""}>${i + 1}</div>`;
    }
    E.code.innerHTML = code;
    E.gutter.innerHTML = gut;
    E.lines = html.length;
    const errs = E.markers.filter((m) => m.severity === "error").length, warns = E.markers.filter((m) => m.severity === "warning").length;
    E.sum.innerHTML = (errs ? `<b class="e">● ${errs} error${errs > 1 ? "s" : ""}</b>` : "") + (warns ? `<b class="w">▲ ${warns} warning${warns > 1 ? "s" : ""}</b>` : "") + (!errs && !warns ? `<b class="ok">✓ no problems</b>` : "");
    editorCaret(el, true);
    E.sync();
  }

  function editorCaret(el, quiet) {
    const E = el._ed;
    if (!E) return;
    const ta = E.ta, before = ta.value.slice(0, ta.selectionStart);
    const line = before.split("\n").length - 1, col = ta.selectionStart - before.lastIndexOf("\n");
    E.pos.textContent = `Ln ${line + 1}, Col ${col}` + (ta.selectionEnd > ta.selectionStart ? ` (${ta.selectionEnd - ta.selectionStart} selected)` : "");
    if (line !== E.cur) {
      const prev = E.cur;
      E.cur = line;
      if (!quiet) {
        for (const box of [E.code, E.gutter]) {
          const p = box.children[prev], n = box.children[line];
          if (p) p.classList.remove("pg-ed-cur");
          if (n) n.classList.add("pg-ed-cur");
        }
      }
    }
  }

  function editorGoto(el, line) {
    const E = el._ed;
    if (!E || !line) return;
    const lines = E.ta.value.split("\n");
    let pos = 0;
    for (let i = 0; i < Math.min(line - 1, lines.length - 1); i++) pos += lines[i].length + 1;
    E.ta.focus();
    E.ta.setSelectionRange(pos, pos + (lines[line - 1] || "").length);
    E.ta.scrollTop = Math.max(0, (line - 1) * ED_LH - E.ta.clientHeight / 2);
    editorCaret(el);
  }

  function insertText(ta, text) {
    // execCommand keeps the native undo stack; fall back to setRangeText where it is missing
    if (!document.execCommand || !document.execCommand("insertText", false, text)) {
      ta.setRangeText(text, ta.selectionStart, ta.selectionEnd, "end");
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  function editorKey(el, e) {
    const E = el._ed, ta = E.ta, v = ta.value;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && (e.key === "s" || e.key === "S")) {
      e.preventDefault();
      el.dispatchEvent(new CustomEvent("pgsave", { bubbles: false }));
      return;
    }
    if (ta.readOnly) return;
    const pad = " ".repeat(E.tab);
    const s = ta.selectionStart, end = ta.selectionEnd;
    const ls = v.lastIndexOf("\n", s - 1) + 1;
    if (e.key === "Tab" && !mod && !e.altKey) {
      e.preventDefault();
      if (s === end && !e.shiftKey) { insertText(ta, pad); return; }
      // indent / dedent every selected line
      const le = v.indexOf("\n", end - (end > s && v[end - 1] === "\n" ? 1 : 0));
      const stop = le < 0 ? v.length : le;
      const block = v.slice(ls, stop).split("\n");
      const changed = block.map((l) => e.shiftKey ? l.replace(new RegExp("^ {1," + E.tab + "}"), "") : pad + l).join("\n");
      ta.setSelectionRange(ls, stop);
      insertText(ta, changed);
      ta.setSelectionRange(ls, ls + changed.length);
      return;
    }
    if (e.key === "Enter" && !mod && !e.shiftKey && !e.altKey) {
      const line = v.slice(ls, s);
      let ind = line.match(/^\s*/)[0];
      if (E.lang === "yaml" && /^\s*-\s+\S/.test(line)) ind += "  ";  // continue inside the list item
      if ((E.lang === "yaml" || E.lang === "python") && /:\s*(#.*)?$/.test(line)) ind += pad;
      e.preventDefault();
      insertText(ta, "\n" + ind);
      return;
    }
    if (mod && e.key === "/") {
      e.preventDefault();
      const mark = E.lang === "ini" ? ";" : E.lang === "json" ? null : "#";
      if (!mark) return;
      const le = v.indexOf("\n", end);
      const stop = le < 0 ? v.length : le;
      const block = v.slice(ls, stop).split("\n");
      const all = block.every((l) => !l.trim() || l.trim().startsWith(mark));
      const changed = block.map((l) => !l.trim() ? l : all ? l.replace(new RegExp("^(\\s*)" + (mark === "#" ? "#" : ";") + " ?"), "$1") : l.replace(/^(\s*)/, "$1" + mark + " ")).join("\n");
      ta.setSelectionRange(ls, stop);
      insertText(ta, changed);
      ta.setSelectionRange(ls, ls + changed.length);
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
  window.zepygui = {
    /** Call a Python function registered with @app.expose: `await zepygui.call("name", arg1, arg2)` */
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
