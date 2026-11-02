// Regenerate the screenshots in docs/screenshots/ from the real examples.
//
//     node tools/screenshots.mjs            # all shots
//     node tools/screenshots.mjs explorer   # only shots whose name contains "explorer"
//
// Each example runs headless (ZEPYGUI_MODE=server) with HOME pointing at a demo folder made by
// tools/demo_home.py, and is driven with Playwright's Chromium. Needs Node and `playwright`.
import { spawn, execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "docs", "screenshots");
const PY = process.env.PYTHON || "python3";
const filter = process.argv[2] || "";

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const rowNamed = (name) => `.pg-fb-item:has(.pg-truncate:text-is("${name}")), .pg-fb-tile:has(.pg-fb-tile-name:text-is("${name}"))`;

const SHOTS = [
  { name: "explorer-dark", example: "explorer.py", scheme: "dark", steps: async (p) => {
      await p.dblclick(rowNamed("Documents")); await wait(400);
      await p.click(rowNamed("Quarterly report.pdf")); await wait(300);
    } },
  { name: "explorer-light", example: "explorer.py", scheme: "light", steps: async (p) => {
      await p.click('.pg-fb-place:has-text("Pictures")'); await wait(300);
      await p.click('.pg-fb-views .pg-seg-item[title="Large icons"]'); await wait(500);
      await p.click(rowNamed("Mountains.png")); await wait(500);
    } },
  { name: "explorer-this-pc", example: "explorer.py", scheme: "light", steps: async (p) => {
      await p.click(".pg-fb-addr-icon"); await wait(500);
    } },
  { name: "file-dialog", example: "explorer.py", scheme: "dark", steps: async (p) => {
      await p.click('button:has-text("Save as")'); await wait(400);
      await p.click('.pg-fd .pg-fb-place:has-text("Documents")'); await wait(400);
    } },
  { name: "dashboard", example: "dashboard.py", scheme: "dark", size: [1280, 820] },
  { name: "dashboard-light", example: "dashboard.py", scheme: "light", size: [1280, 820] },
  { name: "console", example: "console.py", scheme: "dark", size: [1200, 760], steps: async (p) => {
      await p.click('button:has-text("Write 70,000 lines")'); await wait(2500);
      await p.click('button:has-text("Run")'); await wait(1500);
    } },
  { name: "signup", example: "signup.py", scheme: "light", size: [1100, 760], steps: async (p) => {
      await p.click('button:has-text("Create account")'); await wait(400);
    } },
];

function start(example, home, port) {
  return new Promise((resolve, reject) => {
    const proc = spawn(PY, [join(ROOT, "examples", example)], {
      cwd: home, env: { ...process.env, HOME: home, USERPROFILE: home, ZEPYGUI_MODE: "server", ZEPYGUI_PORT: String(port) },
    });
    let out = "";
    const timer = setTimeout(() => reject(new Error(`${example} did not start:\n${out}`)), 15000);
    const onData = (d) => {
      out += d;
      const m = out.match(/serving on (http:\/\/\S+)/);
      if (m) { clearTimeout(timer); resolve({ proc, url: m[1] }); }
    };
    proc.stdout.on("data", onData);
    proc.stderr.on("data", onData);
  });
}

// DEMO_HOME=/home/alex gives tidy paths in the pictures (that folder is left in place);
// by default a temporary folder is used and removed afterwards
const home = process.env.DEMO_HOME || join(mkdtempSync(join(tmpdir(), "zepygui-shots-")), "me");
execFileSync(PY, [join(ROOT, "tools", "demo_home.py"), home]);
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
let port = 8790;
try {
  for (const shot of SHOTS.filter((s) => s.name.includes(filter))) {
    const { proc, url } = await start(shot.example, home, port++);
    try {
      const [w, h] = shot.size || [1320, 820];
      const page = await browser.newPage({ viewport: { width: w, height: h }, colorScheme: shot.scheme, deviceScaleFactor: 2 });
      page.on("pageerror", (e) => console.error(`  ${shot.name}: page error: ${e.message}`));
      page.on("console", (m) => m.type() === "error" && console.error(`  ${shot.name}: console: ${m.text()}`));
      await page.goto(url);
      await page.waitForSelector(".pg-page");
      await wait(shot.settle || 700);
      if (shot.steps) await shot.steps(page);
      await page.mouse.move(0, h - 1);  // no hover highlight in the picture
      await wait(250);
      await page.screenshot({ path: join(OUT, `${shot.name}.png`) });
      await page.close();
      console.log(`docs/screenshots/${shot.name}.png`);
    } finally {
      proc.kill();
    }
  }
} finally {
  await browser.close();
  if (!process.env.DEMO_HOME) rmSync(dirname(home), { recursive: true, force: true });
}
