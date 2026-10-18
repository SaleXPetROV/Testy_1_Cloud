/**
 * Build step: Content-Security-Policy for the SPA, WITHOUT 'unsafe-inline' for scripts.
 * Every inline <script> of build/index.html is allowed by its exact SHA-256 hash, so an injected
 * script can't run. Writes build/csp.conf (an nginx `add_header`), included by nginx.conf.
 *   node scripts/csp.js            (run after `craco build`; the Dockerfile does it)
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const html = fs.readFileSync(path.join(__dirname, '..', 'build', 'index.html'), 'utf8');
const hashes = [];
for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)) {
  if (!m[1].trim()) continue;
  hashes.push(`'sha256-${crypto.createHash('sha256').update(m[1], 'utf8').digest('base64')}'`);
}
// Monetag rewarded ads (admin → «Данные» → «Monetag»): the SDK lives on libtl.com; extra script hosts for
// another ad SDK can be listed in CSP_EXTRA_SCRIPT_SRC (frontend/.env or the build environment), space-separated.
let extra = process.env.CSP_EXTRA_SCRIPT_SRC || '';
try {
  const env = fs.readFileSync(path.join(__dirname, '..', '.env'), 'utf8');
  const m = env.match(/^CSP_EXTRA_SCRIPT_SRC=(.*)$/m);
  if (!extra && m) extra = m[1].trim();
} catch (_) { /* no .env */ }
extra = extra.split(/\s+/).filter((h) => /^https:\/\/[A-Za-z0-9.*-]+$/.test(h)).join(' ');
const ADS = `https://libtl.com https://*.libtl.com${extra ? ` ${extra}` : ''}`;
const policy = [
  "default-src 'self'",
  `script-src 'self' ${hashes.join(' ')} https://telegram.org https://accounts.google.com https://challenges.cloudflare.com ${ADS} blob:`,
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com",
  "font-src 'self' data: https://fonts.gstatic.com",
  "img-src 'self' data: blob: https:",
  "connect-src 'self' https: wss:",
  "media-src 'self' data: blob: https:",
  "worker-src 'self' blob:",
  // ad creatives open in frames from the ad network's hosts
  "frame-src https://telegram.org https://*.telegram.org https://accounts.google.com https://challenges.cloudflare.com https:",
  "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ');
fs.writeFileSync(path.join(__dirname, '..', 'build', 'csp.conf'), `add_header Content-Security-Policy "${policy}" always;\n`);
console.log(`CSP: ${hashes.length} inline script hash(es), no 'unsafe-inline' for scripts`);
