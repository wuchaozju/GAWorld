import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("renders the bilingual GAWorld landing page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();

  assert.match(html, /<title>GAWorld — Generative Urban Social Simulation<\/title>/i);
  assert.match(html, /让一座城市成为可重放、可干预、可比较的社会实验/);
  assert.match(html, /在 GitHub 查看/);
  assert.match(html, /一分钟启动你的第一座城市/);
  assert.match(html, /感知/);
  assert.match(html, /记忆更新/);
  assert.match(html, /href="https:\/\/github\.com\/wuchaozju\/GAWorld"/);
  assert.match(html, /id="capabilities"/);
  assert.match(html, /id="architecture"/);
  assert.match(html, /id="quick-start"/);
});

test("ships complete matching Chinese and English content", async () => {
  const source = await readFile(new URL("../app/content.ts", import.meta.url), "utf8");
  assert.match(source, /zh:\s*\{/);
  assert.match(source, /en:\s*\{/);
  assert.match(source, /Turn a city into a replayable, intervenable, comparable social experiment/);
  assert.match(source, /python generative_city_sim\.py run/);
  assert.match(source, /https:\/\/github\.com\/wuchaozju\/GAWorld/);
});

test("removes all disposable starter surfaces", async () => {
  const [page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(page, /codex-preview|SkeletonPreview/);
  assert.doesNotMatch(layout, /Starter Project|codex-preview/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await assert.rejects(access(new URL("../app/_sites-preview", root)));
});

test("includes resilient locale, clipboard, and reduced-motion behavior", async () => {
  const [page, css] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(page, /gaworld-locale/);
  assert.match(page, /navigator\.clipboard\.writeText/);
  assert.match(page, /catch/);
  assert.match(page, /aria-live="polite"/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /@media\s*\(max-width:\s*720px\)/);
});
