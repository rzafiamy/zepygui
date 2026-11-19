# TODO: security roadmap

Follow-up to the hardening in the `[Unreleased]` section of the [changelog](CHANGELOG.md)
(one-time launch token, launch file, `Host`/`Origin` checks, CSP, hardening headers).
Ordered by priority. See [SECURITY.md](SECURITY.md) for the current security model.

## 1. Close the remaining gaps (no API change)

- [ ] **Signed file URLs.** `/_pg/file?p=...` serves any file of the disk to the authenticated
      window (`zepygui/fs.py` `file_url`, `zepygui/server.py` `_local_file`). Script running in the
      window despite the CSP could `fetch` `~/.ssh/id_rsa`. Make `file_url()` add an HMAC of the path
      (keyed by a per-run secret, with an expiry) and refuse any path Python did not hand out.
      Optionally restrict to allowed root folders.
- [ ] **CSP in the native macOS window.** The page is a local file, so the CSP header does not apply:
      add the policy as `<meta http-equiv="Content-Security-Policy">` in `_index_html(inline=True)`,
      with a nonce on the inlined `client.js`.
- [ ] **Stricter Chromium flags** (`zepygui/window.py`): add `--disable-extensions` and
      `--disable-component-extensions-with-background-pages`; make sure `--no-sandbox` and
      `--remote-debugging-port` are never passed.
- [ ] **Test the launch file outside Linux**: Edge on Windows, Chrome on macOS (`mode="window"`),
      and Chromium installed as a snap (the profile folder must stay readable by the browser).

## 2. Harden the public API (minor release, 0.4.0)

- [ ] **Sanitize `ui.html()` by default** with an allowlist of tags and attributes; keep raw
      insertion behind `ui.html(markup, trusted=True)`. The CSP blocks scripts, not fake forms,
      misleading links or CSS-based leaks.
- [ ] **Validate `app.expose` calls** (`zepygui/app.py`, `call` messages): check arguments against
      the function's type annotations, reject unexpected types, rate-limit calls per session.
      (Events are already limited to the handlers of the rendered tree.)
- [ ] **Strict WebSocket message schema**: known `type`s only, typed fields, per-type size limits,
      a rate limit per session so a page cannot flood the session queue.

## 3. Permissions, like Tauri

- [ ] **Declared capabilities**: e.g. `App(capabilities={"fs": ["~/Documents"], "shell": False,
      "open_url": ["https://*.example.com"]})`; refuse anything not declared (file URLs,
      `open_url`, commands run through `ui.task`).
- [ ] **No local port**: embed the system webview in-process, as on macOS: WebView2 on Windows
      (`ctypes` + COM), WebKitGTK on Linux, or Chromium's `--remote-debugging-pipe` as a portless
      fallback. Keep the WebSocket transport for `browser` and `server` modes.

## 4. Continuous security testing

- [ ] **Fuzz** the WebSocket frame parser and the HTTP handler (malformed frames, huge lengths,
      invalid UTF-8), e.g. with `atheris` or randomised tests in CI.
- [ ] **Static analysis** in CI (CodeQL or Bandit), with rules against `eval`, `shell=True` and
      `pickle` on data coming from the UI.
- [ ] **End-to-end security tests in Chromium** in CI: XSS payloads through `ui.html`, hostile
      `Origin`, reused launch URL, launch through the `file://` launch file.
- [ ] **Written threat model** in `SECURITY.md`: attackers (web page, other local user, crafted
      file, network in `server` mode), what is protected and what is not.

## 5. Distribution

- [ ] **PyPI Trusted Publishing** with Sigstore attestations.
- [ ] **Reproducible builds** and an SBOM.
- [ ] **Guide for shipped apps**: code signing on Windows and macOS, notarization on macOS
      (PyInstaller / Briefcase).

## 6. `server` mode and development

- [ ] **Built-in TLS** with the stdlib `ssl` module: `app.run(mode="server", certfile=..., keyfile=...)`.
- [ ] **Refuse to bind a non-loopback address without TLS** unless asked explicitly (`insecure=True`).
- [ ] **Warn** when `debug=True` or `reload=True` runs outside development.
