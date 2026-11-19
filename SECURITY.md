# Security policy

## Supported versions

Security fixes are made on the latest release.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's
[private vulnerability reporting](https://github.com/rzafiamy/zepygui/security/advisories/new)
with a description, the affected version and steps to reproduce. You will get an answer within a
week.

## Security model

- On macOS the UI talks to Python through a WebKit message bridge: no network port is opened.
- On Windows and Linux (and in `browser`/`server` mode) the app serves its UI on `127.0.0.1` only,
  on a random port. Every request needs a per-run session secret, held in an `HttpOnly`,
  `SameSite=Strict` cookie, so other local users' browsers and web pages cannot reach the app.
- The window gets that cookie with a separate **launch token** that works once (reusable only in
  `server` mode, where several browsers may open the printed URL). The app window is started on a
  launch file in its private profile folder, so the token is never on the browser's command line,
  which other local users can read.
- A server bound to loopback answers only to its own `Host` (against DNS rebinding) plus
  `App(allowed_hosts=...)`, and refuses WebSockets and POSTs whose `Origin` is another site.
- ZePyGUI's page has a Content-Security-Policy: scripts run only from the app or with the page's
  per-response nonce (no inline handlers, no `javascript:` URLs, no `eval`), objects are off and
  other sites cannot frame it. Responses also send `nosniff`, `no-referrer`, same-origin opener and
  resource policies and a Permissions-Policy that turns camera, microphone, location... off.
- `fs.file_url` serves the user's files only to that authenticated window, and with a
  `Content-Security-Policy: sandbox` header, so an HTML file on disk never runs as the app.
- `ui.html` and `ui.run_js` insert content as-is: never pass them text that came from outside your app.
  The CSP stops injected markup from running scripts, but it can still change what the page shows.
- On macOS the page is a local file in the native window; the CSP header does not apply there.
- `server` mode has no TLS: put it behind a reverse proxy or an SSH tunnel to reach it remotely.
