#!/usr/bin/env node
/**
 * i18n-autofill — fills every MISSING UI translation through LibreTranslate.
 *
 *   npm run i18n:check                      # only count what is missing
 *   npm run i18n:autofill                   # translate + save
 *   LIBRETRANSLATE_URL=http://127.0.0.1:5000 npm run i18n:autofill -- --langs=id,es
 *
 * Options: --dry-run  --langs=id,es  --url=http://host:5000  --force (retranslate cached)
 * Env:     LIBRETRANSLATE_URL (default http://127.0.0.1:5000), LIBRETRANSLATE_API_KEY
 *
 * What it does
 *  1. Loads the project dictionaries (see DICTS) and finds every string that
 *     exists in English (or Russian) but is missing in one of the 9 languages.
 *  2. Translates it via LibreTranslate. Placeholders ({amount}, {{x}}, %s),
 *     brand words ($CITY, TON, GRAM City) and line breaks are protected; if the
 *     engine drops any of them the string is NOT saved and goes to the report.
 *  3. Saves:
 *       i18n/auto-translations.cache.json  — every translation ever made + its
 *                                            source text (re-used, retranslated
 *                                            only when the source changes)
 *       src/lib/translationsAuto.json      — what the app loads at runtime
 *                                            (src/lib/i18nAuto.js fills the gaps)
 *       i18n/auto-translations.report.json — counts + strings that failed
 *
 * Hand-written translations always win: the runtime only fills EMPTY slots.
 */
require('sucrase/register');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'src');
const CACHE_FILE = path.join(ROOT, 'i18n', 'auto-translations.cache.json');
const REPORT_FILE = path.join(ROOT, 'i18n', 'auto-translations.report.json');
const OUT_FILE = path.join(SRC, 'lib', 'translationsAuto.json');

const LANGS = ['en', 'ru', 'es', 'zh', 'fr', 'de', 'ja', 'ko', 'id'];

// name -> [module path relative to src, export name]
const DICTS = {
  translations: ['lib/translations.js', 'translations'],
  pageTranslations: ['lib/translationsPages.js', 'pageTranslations'],
  translationsExtra: ['lib/translationsExtra.js', 'translationsExtra'],
  resourceI18n: ['lib/translationsExtra.js', 'resourceI18n'],
  businessI18n: ['lib/translationsExtra.js', 'businessI18n'],
  buffI18n: ['lib/translationsExtra.js', 'buffI18n'],
  contractI18n: ['lib/translationsExtra.js', 'contractI18n'],
  BUSINESS_NAMES: ['lib/businessNames.js', 'BUSINESS_NAMES'],
  RESOURCE_NAMES: ['lib/resourceConfig.js', 'RESOURCE_NAMES'],
  TUTORIAL_UI: ['lib/tutorialTranslations.js', 'TUTORIAL_UI'],
  TUTORIAL_STEP_TEXTS: ['lib/tutorialTranslations.js', 'TUTORIAL_STEP_TEXTS'],
};

// ───────────────────────────── args ─────────────────────────────
const args = Object.fromEntries(process.argv.slice(2).map((a) => {
  const [k, v] = a.replace(/^--/, '').split('=');
  return [k, v === undefined ? true : v];
}));
const DRY = !!args['dry-run'];
const FORCE = !!args.force;
const ONLY_LANGS = args.langs ? String(args.langs).split(',').map((s) => s.trim()).filter(Boolean) : null;
const LT_URL = String(args.url || process.env.LIBRETRANSLATE_URL || 'http://127.0.0.1:5000').replace(/\/+$/, '');
const LT_KEY = process.env.LIBRETRANSLATE_API_KEY || '';

// ───────────────────────────── scan ─────────────────────────────
const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
const nonEmpty = (v) => typeof v === 'string' && v.trim() !== '';
const langKeys = (o) => Object.keys(o).filter((k) => LANGS.includes(k));

// { en: {k: '...'}, ru: {...}, ... }
const isLangFirst = (o) => isObj(o) && isObj(o.en) && langKeys(o).length >= 2 && langKeys(o).length === Object.keys(o).length;
// { en: '...', ru: '...', ... }
const isLangMap = (o) => isObj(o) && (nonEmpty(o.en) || nonEmpty(o.ru)) && langKeys(o).length >= 1
  && Object.keys(o).every((k) => LANGS.includes(k) || typeof o[k] !== 'string');

function scan(dictName, node, p, out) {
  if (isLangFirst(node)) {
    for (const [key, enVal] of Object.entries(node.en)) {
      const ruVal = isObj(node.ru) ? node.ru[key] : undefined;
      const [src, srcLang] = nonEmpty(enVal) ? [enVal, 'en'] : nonEmpty(ruVal) ? [ruVal, 'ru'] : [null, null];
      if (!src) continue;
      for (const L of LANGS) {
        if (L === srcLang) continue;
        if (!nonEmpty(isObj(node[L]) ? node[L][key] : undefined)) out.push({ dict: dictName, path: [...p, L, key], lang: L, src, srcLang });
      }
    }
    return;
  }
  if (isLangMap(node)) {
    const [src, srcLang] = nonEmpty(node.en) ? [node.en, 'en'] : [node.ru, 'ru'];
    for (const L of LANGS) {
      if (L !== srcLang && !nonEmpty(node[L])) out.push({ dict: dictName, path: [...p, L], lang: L, src, srcLang });
    }
    for (const [k, v] of Object.entries(node)) if (!LANGS.includes(k) && typeof v === 'object') scan(dictName, v, [...p, k], out);
    return;
  }
  if (Array.isArray(node)) node.forEach((v, i) => typeof v === 'object' && scan(dictName, v, [...p, i], out));
  else if (isObj(node)) for (const [k, v] of Object.entries(node)) if (typeof v === 'object') scan(dictName, v, [...p, k], out);
}

// useTranslation() looks a key up in this order (src/lib/translations.js):
// translations[lang] -> pageTranslations[lang] -> translationsExtra[lang] -> English.
// A key present in ANY of them for that language is not missing, and filling
// it in an earlier dictionary would override a hand-written translation.
const CHAIN = ['translations', 'pageTranslations', 'translationsExtra'];

function loadMissing() {
  const missing = [];
  const loaded = {};
  for (const [name, [file, exp]] of Object.entries(DICTS)) {
    let mod;
    try { mod = require(path.join(SRC, file)); } catch (e) { console.warn(`! cannot load ${file}: ${e.message.split('\n')[0]}`); continue; }
    if (!mod[exp]) { console.warn(`! ${file} has no export "${exp}"`); continue; }
    loaded[name] = mod[exp];
    scan(name, mod[exp], [], missing);
  }
  const inChain = (lang, key) => CHAIN.some((d) => loaded[d] && isObj(loaded[d][lang]) && nonEmpty(loaded[d][lang][key]));
  const seenChainKey = new Set();
  const filtered = missing.filter((e) => {
    if (!CHAIN.includes(e.dict) || e.path.length !== 2) return true;
    const [lang, key] = e.path;
    if (inChain(lang, key)) return false;
    // the same key may be "missing" in several chain dicts: fill it once,
    // in the first dictionary of the chain that defines it in English
    const k = `${lang}|${key}`;
    if (seenChainKey.has(k)) return false;
    seenChainKey.add(k);
    return true;
  });
  return { missing: filtered, loaded };
}

// ───────────────────────────── protect / restore ─────────────────────────────
const PROTECT_RE = /\{\{[^{}]+\}\}|\{[^{}]+\}|%[sd]|\$CITY|GRAM[ -]?City|\bTON\b|https?:\/\/\S+/g;

function protect(text) {
  const tokens = [];
  let s = text.replace(PROTECT_RE, (m) => { tokens.push(m); return `<b data-p="${tokens.length - 1}"></b>`; });
  const hasNl = s.includes('\n');
  if (hasNl) s = s.replace(/\n/g, '<br data-nl="1">');
  const html = tokens.length > 0 || hasNl || /<[a-z!/]/i.test(text);
  return { s, tokens, html };
}

function restore(out, tokens) {
  let ok = true;
  const seen = new Set();
  let s = out.replace(/<b\s+data-p="(\d+)"\s*(?:\/>|>\s*<\/b>)/g, (m, i) => {
    const n = Number(i);
    if (n >= tokens.length || seen.has(n)) { ok = false; return ''; }
    seen.add(n);
    return tokens[n];
  });
  s = s.replace(/<br\s+data-nl="1"\s*\/?>/g, '\n');
  if (seen.size !== tokens.length || /data-p=|data-nl=/.test(s)) ok = false;
  return { s, ok };
}

// ───────────────────────────── LibreTranslate ─────────────────────────────
let LT_CODES = null; // project code -> server code (zh -> zh-Hans on newer servers)

async function ltLanguages() {
  const r = await fetch(`${LT_URL}/languages`);
  if (!r.ok) throw new Error(`GET /languages -> HTTP ${r.status}`);
  const list = await r.json();
  const codes = new Set(list.map((l) => l.code));
  LT_CODES = {};
  for (const L of LANGS) {
    if (codes.has(L)) LT_CODES[L] = L;
    else if (L === 'zh' && codes.has('zh-Hans')) LT_CODES[L] = 'zh-Hans';
  }
  return LANGS.filter((L) => !LT_CODES[L]);
}

async function ltTranslate(texts, source, target, format) {
  const body = { q: texts, source: LT_CODES[source], target: LT_CODES[target], format };
  if (LT_KEY) body.api_key = LT_KEY;
  const r = await fetch(`${LT_URL}/translate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const data = await r.json();
  const t = data.translatedText;
  return Array.isArray(t) ? t : [t];
}

// ───────────────────────────── main ─────────────────────────────
const keyOf = (e) => JSON.stringify([e.dict, ...e.path]);
const readJson = (f, d) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return d; } };

async function main() {
  const { missing } = loadMissing();
  const todoAll = ONLY_LANGS ? missing.filter((e) => ONLY_LANGS.includes(e.lang)) : missing;
  const byLang = {};
  for (const e of todoAll) byLang[e.lang] = (byLang[e.lang] || 0) + 1;
  console.log(`Missing translations: ${todoAll.length}`, byLang);

  const cache = readJson(CACHE_FILE, {});
  const fresh = [];
  const reuse = [];
  for (const e of todoAll) {
    const c = cache[keyOf(e)];
    if (!FORCE && c && c.src === e.src && nonEmpty(c.text)) reuse.push(e); else fresh.push(e);
  }
  console.log(`  from cache: ${reuse.length}, to translate: ${fresh.length}`);
  if (DRY) return;

  const failed = [];
  if (fresh.length) {
    const unsupported = await ltLanguages();
    if (unsupported.length) console.warn(`! LibreTranslate at ${LT_URL} does not offer: ${unsupported.join(', ')} (skipped)`);
    // group by (srcLang, lang, format)
    const groups = new Map();
    for (const e of fresh) {
      if (!LT_CODES[e.lang] || !LT_CODES[e.srcLang]) { failed.push({ ...e, reason: 'language not available on server' }); continue; }
      const p = protect(e.src);
      const g = `${e.srcLang}|${e.lang}|${p.html ? 'html' : 'text'}`;
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push({ e, p });
    }
    let done = 0;
    for (const [g, items] of groups) {
      const [srcLang, lang, format] = g.split('|');
      for (let i = 0; i < items.length; i += 25) {
        const batch = items.slice(i, i + 25);
        let outs;
        try {
          outs = await ltTranslate(batch.map((b) => b.p.s), srcLang, lang, format);
        } catch (err) {
          batch.forEach((b) => failed.push({ ...b.e, reason: String(err.message || err) }));
          continue;
        }
        batch.forEach((b, j) => {
          const raw = outs[j];
          const { s, ok } = restore(String(raw || ''), b.p.tokens);
          if (!ok || !nonEmpty(s)) { failed.push({ ...b.e, reason: 'placeholder lost or empty', got: raw }); return; }
          cache[keyOf(b.e)] = { src: b.e.src, text: s.trim(), lang, at: new Date().toISOString() };
        });
        done += batch.length;
        process.stdout.write(`\r  translated ${done}/${fresh.length}`);
      }
    }
    process.stdout.write('\n');
    fs.mkdirSync(path.dirname(CACHE_FILE), { recursive: true });
    fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 1));
  }

  // Runtime file: ALL currently-missing slots that have a cached translation
  // (not only the requested langs — a partial run must not drop other langs).
  const out = {};
  let written = 0;
  for (const e of missing) {
    const c = cache[keyOf(e)];
    if (c && c.src === e.src && nonEmpty(c.text)) {
      (out[e.dict] = out[e.dict] || []).push([e.path, c.text]);
      written += 1;
    }
  }
  fs.writeFileSync(OUT_FILE, JSON.stringify(out));
  const perLang = {};
  for (const e of missing) {
    const c = cache[keyOf(e)];
    if (!(c && c.src === e.src && nonEmpty(c.text))) perLang[e.lang] = (perLang[e.lang] || 0) + 1;
  }
  fs.writeFileSync(REPORT_FILE, JSON.stringify({
    generated_at: new Date().toISOString(), server: LT_URL,
    filled: written, still_missing_by_lang: perLang, failed,
  }, null, 1));
  console.log(`Saved ${written} translations -> ${path.relative(ROOT, OUT_FILE)}; failed: ${failed.length} (see ${path.relative(ROOT, REPORT_FILE)})`);
}

if (require.main === module) {
  main().catch((e) => { console.error(e); process.exit(1); });
}

module.exports = { scan, protect, restore, isLangFirst, isLangMap, LANGS };
