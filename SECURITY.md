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
  on a random port. Every request needs a per-run secret token (set as an `HttpOnly`,
  `SameSite=Strict` cookie), so other local users' browsers and web pages cannot reach the app.
- `fs.file_url` serves the user's files only to that authenticated window, and with a
  `Content-Security-Policy: sandbox` header, so an HTML file on disk never runs as the app.
- `ui.html` and `ui.run_js` insert content as-is: never pass them text that came from outside your app.
