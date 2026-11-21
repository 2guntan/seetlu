// AC-F7-3: the JavaScript needed for the first screen must stay ≤ 300 KB gzipped.
// Counts the entry chunk plus everything index.html preloads; lazy routes are excluded.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const BUDGET = 300 * 1024;
const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const html = readFileSync(join(dist, "index.html"), "utf8");
const files = [...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.js)"/g)].map((m) => m[1]);
let total = 0;
for (const f of new Set(files)) {
  const size = gzipSync(readFileSync(join(dist, f))).length;
  total += size;
  console.log(`${f}\t${(size / 1024).toFixed(1)} KB gz`);
}
console.log(`initial JS: ${(total / 1024).toFixed(1)} KB gz (budget ${BUDGET / 1024} KB)`);
if (files.length === 0 || total > BUDGET) {
  console.error(files.length === 0 ? "no JS found in index.html" : "over budget");
  process.exit(1);
}
