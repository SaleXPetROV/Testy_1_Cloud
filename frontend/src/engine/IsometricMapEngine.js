/**
 * GRAM Island 2.5D Isometric Map Engine v4.0
 * Professional pixel-perfect rendering with fixed anchor points
 */

import { 
  Application, 
  Container, 
  Graphics, 
  Sprite, 
  Text, 
  TextStyle,
  Texture,
  Assets,
  Color,
  Rectangle
} from 'pixi.js';
import { getSpriteUrl, BUSINESSES } from '../lib/buildingSprites';

// ==============================================
// CONSTANTS
// ==============================================

export const TILE_WIDTH = 64;
export const TILE_HEIGHT = 32;
export const GRID_COLS = 35;
export const GRID_ROWS = 35;
export const MIN_ZOOM = 0.5;
export const MAX_ZOOM = 4.0;

// SPRITE CONFIGURATION (per TD v2)
// All sprites are 256x256 PNG with visual hierarchy baked into the image:
//   Tier 1: building 30-40% of frame height (small, grounded)
//   Tier 2: building 60% of frame height (medium factory)
//   Tier 3: building 85-90% of frame height (dominant skyscraper)
// Single uniform scale for ALL sprites — NO per-tier scaling in code.
const SPRITE_SCALE = 0.25; // 256 * 0.25 = 64px = exactly one tile width

// Global height trim applied to regular business sprites (main PNG only),
// width unchanged (Y axis only). EXCLUDED: bio_farm and any uploaded skin
// (per art request they keep their existing sizing untouched).
//   • request 1: −3%   → factor 0.97
// Net height reduction for a regular PNG business: −3.00% (factor 0.97).
const BUSINESS_HEIGHT_SCALE = 0.97;
// Additional global −5% HEIGHT reduction for ALL sprites/skins shown on the
// map (Y axis only, width unchanged) — per request to make buildings a bit
// shorter/flatter on the tiles.
const MAP_HEIGHT_SHRINK = 0.95;
// Plot fill is drawn smaller than its cell footprint so there is a visible gap
// between neighbouring fields; the glowing energy edges (full cell size) run
// through those gaps as continuous translucent streams.
const PLOT_INSET = 0.66;
// Building/skin sprites are scaled to fit INSIDE the (inset) plot diamond.
const SPRITE_FIT = PLOT_INSET;

// Color palette
export const TINTS = {
  free_core: 0x7dd3fc,
  free_inner: 0x60a5fa,
  free_middle: 0x3b82f6,
  free_outer: 0x2563eb,
  owned: 0x4ade80,
  other: 0xc084fc,
  selected: 0xfcd34d,
  hovered: 0xf0f9ff,
  // Amber-400 — gold tint for admin-picked presale plots (before any
  // buyer takes them).
  presale: 0xfacc15,
  presaleNight: 0xb8860b,
};

export const COLORS = {
  water: 0x0c4a6e,
  waterDeep: 0x082f49,
  nightOverlay: 0x1a1a2e, // Deep blue-black for night tint
};

// Building icons for legacy support
export const BUILDING_ICONS = {
  helios: '☀️', nano_dc: '💾', quartz_mine: '💎', signal: '📡',
  cooler: '❄️', bio_farm: '🌱', scrap: '♻️', chip_fab: '🏭',
  nft_studio: '🎨', ai_lab: '🧠', hangar: '🚁', cafe: '☕',
  repair: '🔧', vr_club: '🎮', validator: '⚡', gram_bank: '🏦',
  dex: '📊', casino: '🎰', arena: '🏟️', incubator: '🚀', bridge: '🌉'
};

// ==============================================
// UTILITIES
// ==============================================

export function gridToIso(x, y) {
  return {
    x: (x - y) * (TILE_WIDTH / 2),
    y: (x + y) * (TILE_HEIGHT / 2)
  };
}

export function isoToGrid(screenX, screenY) {
  const x = (screenX / (TILE_WIDTH / 2) + screenY / (TILE_HEIGHT / 2)) / 2;
  const y = (screenY / (TILE_HEIGHT / 2) - screenX / (TILE_WIDTH / 2)) / 2;
  return { x: Math.round(x), y: Math.round(y) };
}

// Pixel Perfect Snapping
function snapToGrid(value) {
  return Math.round(value);
}

export function getZone(x, y, centerX, centerY) {
  const dist = Math.abs(x - centerX) + Math.abs(y - centerY);
  const maxDist = Math.max(centerX, centerY);
  if (dist <= maxDist * 0.15) return 'core';
  if (dist <= maxDist * 0.35) return 'inner';
  if (dist <= maxDist * 0.6) return 'middle';
  return 'outer';
}

// ==============================================
// MAP STORE
// ==============================================

class MapStore {
  constructor() {
    this.state = {
      cells: new Map(),
      selectedCell: null,
      hoveredCell: null,
      userId: null,
      userWallet: null,
      isNight: false, // Night mode state
      // Presale: coord-set of admin-picked cells that must render with a
      // gold tint (before an owner buys them). Written from
      // TonIslandPage.jsx via `SET_PRESALE_SET`.
      presaleSet: null,
      // new city map (CityMapEngine)
      layout: null, layoutVersion: 0, cellsVersion: 0,
      viewer: null, trading: null, districts: null, listings: null, rentOffers: null, labels: null,
    };
    this.listeners = [];
    this.dirtySet = new Set();
  }
  
  subscribe(listener) {
    this.listeners.push(listener);
    return () => { this.listeners = this.listeners.filter(l => l !== listener); };
  }
  
  getState() { return this.state; }
  
  dispatch(action) {
    switch (action.type) {
      case 'SET_CELLS':
        this.state.cellsVersion += 1;
        this.state.cells.clear();
        action.cells.forEach(cell => {
          const key = `${cell.q},${cell.r}`;
          this.state.cells.set(key, cell);
          this.dirtySet.add(key);
        });
        break;
      case 'UPDATE_CELL':
        this.state.cellsVersion += 1;
        const key = `${action.cell.q},${action.cell.r}`;
        this.state.cells.set(key, { ...this.state.cells.get(key), ...action.cell });
        this.dirtySet.add(key);
        break;
      case 'SET_SELECTED':
        if (this.state.selectedCell) this.dirtySet.add(`${this.state.selectedCell.q},${this.state.selectedCell.r}`);
        this.state.selectedCell = action.cell;
        if (action.cell) this.dirtySet.add(`${action.cell.q},${action.cell.r}`);
        break;
      case 'SET_HOVERED':
        if (this.state.hoveredCell) this.dirtySet.add(`${this.state.hoveredCell.q},${this.state.hoveredCell.r}`);
        this.state.hoveredCell = action.cell;
        if (action.cell) this.dirtySet.add(`${action.cell.q},${action.cell.r}`);
        break;
      case 'SET_USER':
        this.state.userId = action.userId;
        this.state.userWallet = action.userWallet;
        this.state.cells.forEach((_, k) => this.dirtySet.add(k));
        break;
      case 'SET_NIGHT_MODE':
        this.state.isNight = action.isNight;
        // Mark ALL cells dirty — tiles AND buildings need re-tinting
        this.state.cells.forEach((_, k) => this.dirtySet.add(k));
        break;
      case 'SET_LAYOUT':                       // parks / districts / grid of the city map
        this.state.layout = action.layout || null; this.state.layoutVersion += 1;
        break;
      case 'SET_VIEWER':                       // 'newbie' | 'zero' | 'level1' — how prices are shown
        this.state.viewer = action.viewer || null;
        break;
      case 'SET_TRADING':                      // zone -> ISO open time (admin trading schedule)
        this.state.trading = action.trading || null;
        break;
      case 'SET_RENT_OFFERS':                  // "x,y" -> {id, price_city} (businesses offered for rent)
        this.state.rentOffers = action.rentOffers || null;
        break;
      case 'SET_LABELS':                       // translated map texts
        this.state.labels = action.labels || null;
        break;
      case 'SET_LISTINGS':                     // "x,y" -> {id, price_city, seller} (marketplace lots)
        this.state.listings = action.listings || null;
        break;
      case 'SET_DISTRICTS':                    // {unlocked, open_count} (admin district settings)
        this.state.districts = action.districts || null;
        break;
      case 'SET_PRESALE_SET':
        // Coord-set of "gold" (presale) cells; null clears the highlight.
        this.state.presaleSet = action.presaleSet || null;
        // Every cell needs a re-tint pass.
        this.state.cells.forEach((_, k) => this.dirtySet.add(k));
        break;
      default:
        break;
    }
    this.listeners.forEach(l => l(this.state));
  }
  
  getCell(q, r) { return this.state.cells.get(`${q},${r}`); }
  getDirtyAndClear() {
    const dirty = new Set(this.dirtySet);
    this.dirtySet.clear();
    return dirty;
  }
}

export const mapStore = new MapStore();

// ==============================================
// BUILDING SPRITE CLASS (Multi-layer)
// ==============================================

class BuildingSprite extends Container {
  constructor(buildingData, texture) {
    super();
    
    this.buildingData = buildingData;
    this.buildingType = buildingData.type;
    this.level = buildingData.level || 1;
    
    // Main building sprite
    this.buildingSprite = null;
    // Night glow overlay (windows/neon)
    this.glowSprite = null;
    
    // Add building sprite
    if (texture) {
      this.buildingSprite = new Sprite(texture);

      // Anchor at bottom-center: base of building sits on bottom tip of diamond
      this.buildingSprite.anchor.set(0.5, 1.0);

      this.glowSprite = new Sprite(texture);
      this.glowSprite.anchor.set(0.5, 1.0);

      if (buildingData.skinUrl) {
        // Skin sprites (uploaded webp) can be ANY source resolution. Size them
        // to FIT INSIDE the inset plot: width = TILE_WIDTH * SPRITE_FIT, height
        // derived from the texture aspect ratio.
        const tw = texture.width || TILE_WIDTH;
        const th = texture.height || tw;
        const targetW = TILE_WIDTH * SPRITE_FIT;
        let targetH = targetW * (th / tw);
        // Trim skin height by 5% so a square (256×256) skin lays flat on the
        // isometric plot instead of standing too tall.
        targetH *= 0.95;
        // NOTE: the global −3% business trim is intentionally NOT applied to
        // skins (per art request) — skins keep only the 0.95 flatten.
        // bio_farm: cumulative height trim (art requests: 2% +5% +3% +2%) and raise 3px.
        if (this.buildingType === 'bio_farm') targetH *= 0.885;
        // Global −5% map height reduction (see MAP_HEIGHT_SHRINK).
        targetH *= MAP_HEIGHT_SHRINK;
        // Admin-configured per-skin display size (percent of the resolved size,
        // 100 = default). Height and width are adjustable independently.
        const _hPct = (buildingData.skinHeightPct == null ? 100 : buildingData.skinHeightPct) / 100;
        const _wPct = (buildingData.skinWidthPct == null ? 100 : buildingData.skinWidthPct) / 100;
        const finalW = targetW * _wPct;
        const finalH = targetH * _hPct;
        this.buildingSprite.width = finalW;
        this.buildingSprite.height = finalH;
        this.glowSprite.width = finalW;
        this.glowSprite.height = finalH;
      } else {
        // PNG sprites: uniform scale, reduced by SPRITE_FIT so they fit the cell.
        this.buildingSprite.scale.set(SPRITE_SCALE * SPRITE_FIT);
        this.glowSprite.scale.set(SPRITE_SCALE * SPRITE_FIT);
        // Global −3% business-sprite height trim (Y axis only, width unchanged).
        // Applied ONLY to regular businesses — bio_farm is excluded (per art
        // request) and keeps its own 0.885 trim without the extra 3%.
        if (this.buildingType === 'bio_farm') {
          this.buildingSprite.scale.y = SPRITE_SCALE * SPRITE_FIT * 0.885 * MAP_HEIGHT_SHRINK;
          this.glowSprite.scale.y = SPRITE_SCALE * SPRITE_FIT * 0.885 * MAP_HEIGHT_SHRINK;
        } else {
          this.buildingSprite.scale.y = SPRITE_SCALE * SPRITE_FIT * BUSINESS_HEIGHT_SCALE * MAP_HEIGHT_SHRINK;
          this.glowSprite.scale.y = SPRITE_SCALE * SPRITE_FIT * BUSINESS_HEIGHT_SCALE * MAP_HEIGHT_SHRINK;
        }
      }

      // Raise every building sprite 5px so it sits a little higher on the tile.
      this.buildingSprite.y = -5;
      this.glowSprite.y = -5;

      this.addChild(this.buildingSprite);

      // Night glow overlay (same texture, additive blend)
      this.glowSprite.alpha = 0;
      this.glowSprite.tint = 0x44aaff; // Cyan-blue window glow
      this.glowSprite.blendMode = 'add';
      this.addChild(this.glowSprite);
    }
    
    // UI Overlay (Level badge, etc)
    this.uiLayer = new Container();
    this.addChild(this.uiLayer);
    
    // Add level badge for level 3+
    this.createLevelBadge();
    
    // Apply initial state
    this.updateAppearance(mapStore.getState().isNight);
  }
  
  createLevelBadge() {
    if (this.level < 3) return;
    
    const tier = BUSINESSES[this.buildingType]?.tier || 1;
    const badgeColors = { 1: 0x22c55e, 2: 0x3b82f6, 3: 0xa855f7 };
    // Badge at bottom-right, offset up by ~20% of rendered sprite height
    const badgeX = 10;
    const badgeY = -(256 * SPRITE_SCALE * 0.2);
    
    const badgeG = new Graphics();
    const radius = 5 + Math.floor(this.level / 4);
    badgeG.circle(0, 0, radius);
    badgeG.fill({ color: badgeColors[tier] || 0x666666 });
    badgeG.stroke({ color: 0xffffff, width: 1 });
    
    badgeG.x = badgeX;
    badgeG.y = badgeY;
    this.uiLayer.addChild(badgeG);
    
    const lvlText = new Text({
      text: String(this.level),
      style: new TextStyle({ 
        fontSize: 7 + Math.floor(this.level / 4),
        fill: 0xffffff,
        fontWeight: 'bold'
      }),
      resolution: 4,
    });
    lvlText.anchor.set(0.5);
    lvlText.x = badgeX;
    lvlText.y = badgeY;
    this.uiLayer.addChild(lvlText);
  }
  
  updateAppearance(isNight) {
    if (!this.buildingSprite) return;
    
    if (isNight) {
      // Night: moderate dark tint, buildings still recognizable
      this.buildingSprite.tint = 0x556688;
      if (this.glowSprite) {
        this.glowSprite.alpha = 0.5;
        this.glowSprite.tint = 0x66ccff; // Bright cyan glow for windows
      }
    } else {
      // Day: full color, no glow
      this.buildingSprite.tint = 0xffffff;
      if (this.glowSprite) {
        this.glowSprite.alpha = 0;
      }
    }
  }
  
  setOwnershipTint(isOwn) {
    if (!this.buildingSprite) return;
    
    // Only apply ownership tint in day mode (night mode overrides)
    if (!mapStore.getState().isNight) {
        this.buildingSprite.tint = isOwn ? 0xffffff : 0xdddddd;
    }
  }
}

// ==============================================
// OPTIMIZED MAP ENGINE v4.0
// ==============================================

export class IsometricMapEngine {
  constructor(container, options = {}) {
    this.container = container;
    this.options = {
      width: options.width || 800,
      height: options.height || 600,
      onCellClick: options.onCellClick || (() => {}),
      onCellHover: options.onCellHover || (() => {}),
    };
    
    this.app = null;
    this.world = null;
    this.layers = {};
    this.canvas = null;
    this.initialized = false;
    
    // Texture cache
    this.tileTexture = null;
    this.buildingTextures = new Map();
    this.avatarTextures = new Map();
    // Map<key, Promise<texture>> — when two `setupAllTiles` runs overlap (which
    // happens on quick consecutive SET_CELLS dispatches) the SECOND call must
    // not just SKIP a texture that is already mid-load; it must AWAIT the same
    // promise so that `createBuilding(cell)` runs only after the texture is in
    // `buildingTextures`. The previous implementation used a Set and silently
    // skipped concurrent loaders → "no icons" until the user refreshed again.
    this.loadingTextures = new Map();
    
    // Object pools
    this.tilePool = new Map();
    this.glowPool = new Map();
    this.borderPool = new Map();
    this.buildingPool = new Map();
    this.avatarPool = new Map();
    
    // Interaction
    this.isDragging = false;
    this.dragStart = { x: 0, y: 0 };
    this.lastMouse = { x: 0, y: 0 };
    // When `interactionLocked` is true, all pan/zoom/wheel/pinch input is
    // ignored. Single click → handleClick still fires (so the tutorial can
    // accept clicks on the highlighted cell). Used during the tutorial
    // `fake_buy_plot` step to lock the camera onto the HELIOS plot.
    this.interactionLocked = false;
    
    // Viewport
    this.viewport = { left: -Infinity, right: Infinity, top: -Infinity, bottom: Infinity };
    
    // Render loop
    this.rafId = null;
    this.needsUpdate = false;
    // Tracks whether the one-time "open zoomed-in" camera view has been applied.
    this.initialViewApplied = false;
    // Guards the one-time automatic emoji re-render (see _scheduleEmojiRerender).
    this._emojiRerenderDone = false;
  }
  
  async init() {
    if (this.initialized) return;
    
    try {
      this.app = new Application();
      await this.app.init({
        width: this.options.width,
        height: this.options.height,
        backgroundColor: COLORS.water,
        antialias: true,           // MSAA — сглаживает Graphics (аватарки, подиумы, бордюры)
        resolution: 1,             // SSAA для тайлов делается через 4× source-текстуру
        powerPreference: 'low-power',
      });
      
      this.canvas = this.app.canvas;
      if (!this.canvas) return;
      
      this.container.innerHTML = '';
      this.container.appendChild(this.canvas);
      this.initialized = true;
      
      this.generateTileTexture();
      
      this.world = new Container();
      this.world.sortableChildren = true;
      this.app.stage.addChild(this.world);
      
      this.createLayers();
      this.setupInput();
      
      // Hold on to the unsubscribe handle so we can detach this engine's
      // listener in `destroy()`. Without this, every destroyed engine left
      // a dead listener in mapStore.listeners that fired on every dispatch
      // forever — minor leak, but it also meant `needsUpdate` was being
      // set on already-destroyed engines (harmless but noisy).
      this._unsubscribeStore = mapStore.subscribe(() => { this.needsUpdate = true; });

      // Emoji preview icons (🏢, 🌾, …) are rasterised onto the PIXI canvas via
      // Text. On a COLD page load the color-emoji font is not yet warm in the
      // browser's canvas glyph cache, so the very first setupAllTiles() draws
      // blank/tofu glyphs — the user only saw icons after hitting the in-app
      // Refresh button (which re-rasterised once the font was warm). We now
      // block the first render until the emoji font is ready (bounded by a
      // timeout so a stuck fonts.ready never leaves the map blank).
      await this.ensureEmojiFontReady();

      this.startRenderLoop();
      
    } catch (error) {
      console.error('IsometricMapEngine init error:', error);
    }
  }

  // Warm the browser's color-emoji glyph cache before the first canvas render.
  // On a cold page load the color-emoji font is not rasterised yet, so PIXI's
  // canvas-backed Text draws blank glyphs (the icons only appeared after the
  // in-app Refresh). We warm the cache two ways and bound the whole thing with
  // a timeout so the map never hangs on a slow fonts.ready.
  async ensureEmojiFontReady() {
    if (typeof document === 'undefined' || !document.fonts) return;
    const EMOJI_SAMPLE = '🏢🌾🏭🏦🏪🏬🍔☕🐟🌳💎🛰️🌴❄️☀️🎨🔧';
    const warm = (async () => {
      // 1) Wait for declared web-fonts, then best-effort load emoji families
      //    (no-op for system emoji fonts, but harmless).
      try {
        await document.fonts.ready;
        const families = ['Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji'];
        await Promise.all(
          families.map((f) => document.fonts.load(`44px "${f}"`, EMOJI_SAMPLE).catch(() => {}))
        );
      } catch (_) { /* ignore */ }

      // 2) Render the emoji in a REAL (off-screen) DOM node. This forces the
      //    browser to load + rasterise the color-emoji glyphs through the same
      //    text pipeline that the <canvas> 2D context uses afterwards — the
      //    single most reliable way to guarantee warm glyphs before PIXI Text.
      try {
        const probe = document.createElement('div');
        probe.textContent = EMOJI_SAMPLE;
        probe.setAttribute('aria-hidden', 'true');
        probe.style.cssText =
          'position:absolute;left:-9999px;top:-9999px;font-size:44px;' +
          'line-height:1;white-space:nowrap;pointer-events:none;opacity:0;';
        document.body.appendChild(probe);
        // Force synchronous layout so glyphs are actually rasterised now.
        // eslint-disable-next-line no-unused-expressions
        probe.offsetWidth;
        // Give the raster pass one frame, then clean up.
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        probe.remove();
      } catch (_) { /* ignore */ }

      // 3) Prime the canvas glyph cache too.
      try {
        const c = document.createElement('canvas');
        const ctx = c.getContext('2d');
        if (ctx) { ctx.font = '44px sans-serif'; ctx.fillText(EMOJI_SAMPLE, 0, 40); }
      } catch (_) { /* ignore */ }
    })();
    const timeout = new Promise((resolve) => setTimeout(resolve, 2000));
    await Promise.race([warm, timeout]);
  }
  
  generateTileTexture() {
    if (!this.app?.renderer) return;

    // Diamond geometry at 4× super-sample (256×128 → displayed 64×32) for
    // SSAA-style anti-aliased edges.
    const verts = [128, 0, 256, 64, 128, 128, 0, 64];

    // --- Plot tile (the buildable cell). Kept clean; tinted at runtime. -------
    const tileG = new Graphics();
    tileG.poly(verts);
    tileG.fill({ color: 0xffffff });
    this.tileTexture = this.app.renderer.generateTexture({ target: tileG, resolution: 1 });
    tileG.destroy();

    // --- Glowing energy edge (edge only, transparent centre). ----------------
    // Drawn white so a constant cyan tint + additive blend turns overlapping
    // tile borders into continuous glowing energy streams. Layered strokes
    // (wide+faint → thin+bright) create the soft neon glow falloff.
    const glowG = new Graphics();
    const strokes = [
      { w: 38, a: 0.06 },  // outer haze (fills the gap between fields)
      { w: 26, a: 0.10 },
      { w: 16, a: 0.16 },
      { w: 8,  a: 0.28 },
      { w: 3,  a: 0.45 },  // soft translucent core (no opaque line)
    ];
    for (const s of strokes) {
      glowG.poly(verts);
      glowG.stroke({ color: 0xffffff, width: s.w, alpha: s.a, alignment: 0.5 });
    }
    // Pin the texture to the exact 256×128 tile bounds so the glow lines up
    // pixel-perfectly with the base tile edges when both are scaled to 64×32
    // (the outer haze that overflows the diamond tips is clipped — neighbours
    // fill it back in, keeping the streams continuous).
    this.glowTexture = this.app.renderer.generateTexture({
      target: glowG,
      resolution: 1,
      frame: new Rectangle(0, 0, 256, 128),
    });
    glowG.destroy();

    // --- Thin translucent blue field border. ---------------------------------
    // A very thin outline drawn on the plot edge; rendered as its own sprite
    // (constant blue tint, not affected by the plot's runtime tint).
    const borderG = new Graphics();
    borderG.poly(verts);
    borderG.stroke({ color: 0xffffff, width: 3, alpha: 0.9, alignment: 0 });
    this.borderTexture = this.app.renderer.generateTexture({
      target: borderG,
      resolution: 1,
      frame: new Rectangle(0, 0, 256, 128),
    });
    borderG.destroy();
  }
  
  createLayers() {
    this.layers.tiles = new Container();
    this.layers.tiles.zIndex = 1;
    this.layers.tiles.sortableChildren = true;
    this.world.addChild(this.layers.tiles);
    
    this.layers.buildings = new Container();
    this.layers.buildings.zIndex = 2;
    this.layers.buildings.sortableChildren = true;
    this.world.addChild(this.layers.buildings);
    
    // Owner avatars share the SAME container as buildings/skins so they are
    // depth-sorted together by (q+r): a plot that is HIGHER on screen (smaller
    // q+r) always renders UNDER a plot that is LOWER (larger q+r). A separate
    // top avatar layer used to draw back-row avatars on top of front-row skins.
    this.layers.avatars = this.layers.buildings;
  }
  
  setupInput() {
    const canvas = this.canvas;
    
    // Touch pinch-to-zoom support
    let touches = [];
    let lastPinchDistance = 0;
    
    const getTouchDistance = (t1, t2) => {
      const dx = t1.clientX - t2.clientX;
      const dy = t1.clientY - t2.clientY;
      return Math.sqrt(dx * dx + dy * dy);
    };
    
    const getTouchCenter = (t1, t2) => ({
      x: (t1.clientX + t2.clientX) / 2,
      y: (t1.clientY + t2.clientY) / 2
    });
    
    canvas.addEventListener('touchstart', (e) => {
      if (this.interactionLocked) {
        // Still record single-finger tap origin so handleClick on the
        // highlighted cell works on mobile. Two-finger pinch is ignored.
        if (e.touches.length === 1) {
          this.dragStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        }
        return;
      }
      touches = [...e.touches];
      if (touches.length === 2) {
        lastPinchDistance = getTouchDistance(touches[0], touches[1]);
      } else if (touches.length === 1) {
        this.isDragging = true;
        this.dragStart = { x: touches[0].clientX, y: touches[0].clientY };
        this.lastMouse = { x: touches[0].clientX, y: touches[0].clientY };
      }
    }, { passive: true });
    
    canvas.addEventListener('touchmove', (e) => {
      if (this.interactionLocked) { e.preventDefault(); return; }
      e.preventDefault();
      touches = [...e.touches];
      
      if (touches.length === 2 && this.world) {
        // Pinch-to-zoom
        const newDistance = getTouchDistance(touches[0], touches[1]);
        const center = getTouchCenter(touches[0], touches[1]);
        const rect = canvas.getBoundingClientRect();
        const centerX = center.x - rect.left;
        const centerY = center.y - rect.top;
        
        if (lastPinchDistance > 0) {
          const scaleFactor = newDistance / lastPinchDistance;
          const oldZoom = this.world.scale.x;
          const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, oldZoom * scaleFactor));
          
          const worldX = (centerX - this.world.x) / oldZoom;
          const worldY = (centerY - this.world.y) / oldZoom;
          this.world.scale.set(newZoom);
          this.world.x = centerX - worldX * newZoom;
          this.world.y = centerY - worldY * newZoom;
          this.updateViewportBounds();
        }
        lastPinchDistance = newDistance;
      } else if (touches.length === 1 && this.isDragging && this.world) {
        // Single finger drag
        const dx = touches[0].clientX - this.lastMouse.x;
        const dy = touches[0].clientY - this.lastMouse.y;
        this.world.x += dx;
        this.world.y += dy;
        this.lastMouse = { x: touches[0].clientX, y: touches[0].clientY };
        this.updateViewportBounds();
      }
    }, { passive: false });
    
    canvas.addEventListener('touchend', (e) => {
      if (this.interactionLocked) {
        if (e.touches.length === 0) {
          // Was a single tap — forward to click handler so the user can
          // tap the highlighted tutorial cell.
          const rect = canvas.getBoundingClientRect();
          const t0 = e.changedTouches?.[0];
          if (t0) this.handleClick(t0.clientX - rect.left, t0.clientY - rect.top);
        }
        touches = [];
        return;
      }
      if (e.touches.length === 0 && touches.length === 1) {
        // Was single touch - check for tap
        const dx = Math.abs(touches[0].clientX - this.dragStart.x);
        const dy = Math.abs(touches[0].clientY - this.dragStart.y);
        if (dx < 10 && dy < 10) {
          const rect = canvas.getBoundingClientRect();
          this.handleClick(touches[0].clientX - rect.left, touches[0].clientY - rect.top);
        }
      }
      touches = [...e.touches];
      lastPinchDistance = 0;
      this.isDragging = false;
    }, { passive: true });
    
    // Mouse/pointer events
    canvas.addEventListener('pointerdown', (e) => {
      if (e.pointerType === 'touch') return; // Handled by touch events
      if (this.interactionLocked) {
        // Still record so click on locked target works.
        this.dragStart = { x: e.clientX, y: e.clientY };
        return;
      }
      this.isDragging = true;
      this.dragStart = { x: e.clientX, y: e.clientY };
      this.lastMouse = { x: e.clientX, y: e.clientY };
    });
    
    canvas.addEventListener('pointermove', (e) => {
      if (e.pointerType === 'touch') return; // Handled by touch events
      if (this.interactionLocked) return;
      if (this.isDragging && this.world) {
        const dx = e.clientX - this.lastMouse.x;
        const dy = e.clientY - this.lastMouse.y;
        this.world.x += dx;
        this.world.y += dy;
        this.lastMouse = { x: e.clientX, y: e.clientY };
        this.updateViewportBounds();
      } else {
        const rect = canvas.getBoundingClientRect();
        this.handleHover(e.clientX - rect.left, e.clientY - rect.top);
      }
    });
    
    canvas.addEventListener('pointerup', (e) => {
      if (e.pointerType === 'touch') return; // Handled by touch events
      const dx = Math.abs(e.clientX - this.dragStart.x);
      const dy = Math.abs(e.clientY - this.dragStart.y);
      if (dx < 5 && dy < 5) {
        const rect = canvas.getBoundingClientRect();
        this.handleClick(e.clientX - rect.left, e.clientY - rect.top);
      }
      this.isDragging = false;
    });
    
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      if (this.interactionLocked) return;
      if (!this.world) return;
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      const oldZoom = this.world.scale.x;
      const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, oldZoom + delta));
      const worldX = (mouseX - this.world.x) / oldZoom;
      const worldY = (mouseY - this.world.y) / oldZoom;
      this.world.scale.set(newZoom);
      this.world.x = mouseX - worldX * newZoom;
      this.world.y = mouseY - worldY * newZoom;
      this.updateViewportBounds();
    }, { passive: false });
  }
  
  updateViewportBounds() {
    if (!this.world || !this.world.scale) return;
    const scale = this.world.scale.x;
    const margin = 200;
    this.viewport = {
      left: (-this.world.x / scale) - margin,
      right: (this.options.width - this.world.x) / scale + margin,
      top: (-this.world.y / scale) - margin,
      bottom: (this.options.height - this.world.y) / scale + margin
    };
    this.applyCulling();
  }
  
  applyCulling() {
    this.tilePool.forEach((sprite) => {
      const visible = sprite.x >= this.viewport.left && sprite.x <= this.viewport.right &&
                      sprite.y >= this.viewport.top && sprite.y <= this.viewport.bottom;
      sprite.visible = visible;
    });
    this.glowPool.forEach((glow) => {
      glow.visible = glow.x >= this.viewport.left && glow.x <= this.viewport.right &&
                     glow.y >= this.viewport.top && glow.y <= this.viewport.bottom;
    });
    this.borderPool.forEach((border) => {
      border.visible = border.x >= this.viewport.left && border.x <= this.viewport.right &&
                       border.y >= this.viewport.top && border.y <= this.viewport.bottom;
    });
    this.buildingPool.forEach((container) => {
      const visible = container.x >= this.viewport.left && container.x <= this.viewport.right &&
                      container.y >= this.viewport.top && container.y <= this.viewport.bottom;
      container.visible = visible;
    });
    this.avatarPool.forEach((container) => {
      const visible = container.x >= this.viewport.left && container.x <= this.viewport.right &&
                      container.y >= this.viewport.top && container.y <= this.viewport.bottom;
      container.visible = visible;
    });
  }
  
  startRenderLoop() {
    const loop = () => {
      this.rafId = requestAnimationFrame(loop);
      if (this.needsUpdate) {
        this.needsUpdate = false;
        this.processUpdates();
      }
    };
    loop();
  }
  
  // One-time automatic re-render to fix cold-load emoji. On the very first
  // setupAllTiles the color-emoji glyph cache is often not warm yet, so PIXI
  // Text rasterises blank glyphs. Re-running setupAllTiles once (after
  // document.fonts.ready + a short delay) redraws them with the warm font —
  // this is exactly what the manual Refresh button did, now automatic.
  _scheduleEmojiRerender() {
    if (this._emojiRerenderDone) return;
    this._emojiRerenderDone = true;
    const rebuild = () => {
      if (!this.initialized || !this.layers?.buildings) return;
      const st = mapStore.getState();
      if (st.cells.size === 0) return;
      this.setupAllTiles(st);
    };
    const fontsReady = (typeof document !== 'undefined' && document.fonts && document.fonts.ready)
      ? document.fonts.ready
      : Promise.resolve();
    fontsReady
      .then(() => setTimeout(rebuild, 400))
      .catch(() => setTimeout(rebuild, 400));
  }

  processUpdates() {
    const state = mapStore.getState();
    const dirty = mapStore.getDirtyAndClear();
    
    // Update background color for night mode
    if (this.app?.renderer) {
      this.app.renderer.background.color = state.isNight ? COLORS.waterDeep : COLORS.water;
    }
    
    // FULL REBUILD only when pools are empty — i.e., the very first frame for
    // this engine instance. Every subsequent dispatch (SET_USER, SET_NIGHT_MODE,
    // SET_HOVERED, SET_SELECTED, SET_CELLS after data refresh, …) goes through
    // the incremental `updateCell` path which is idempotent and safe to call
    // concurrently. The previous "rebuild whenever all cells are dirty" branch
    // raced with itself: a SET_USER dispatched while setupAllTiles' textures
    // were still loading triggered a second setupAllTiles that wiped the
    // buildings layer before the first finished populating it → empty map,
    // icons only appearing after a hover (which routes through updateCell and
    // lazily loads textures per-cell).
    if (this.tilePool.size === 0 && state.cells.size > 0) {
      this.setupAllTiles(state);
      if (!this.initialViewApplied) {
        const isMobile = (typeof window !== 'undefined' && window.innerWidth < 768);
        if (isMobile) {
          this.centerCamera(1.5);
        } else {
          this.centerCamera(); // auto-fit (≈ default fit × 0.85)
        }
        this.initialViewApplied = true;
      }
      // Emoji preview icons (🏢, 🌾, …) are rasterised onto the PIXI canvas via
      // Text. On a COLD page load the browser's color-emoji glyph cache is not
      // warm when this FIRST setupAllTiles runs, so the glyphs come out blank —
      // the user previously had to hit the in-app Refresh (which re-runs
      // setupAllTiles once the font is warm). We now do that automatically,
      // exactly once, a short moment after the first render.
      this._scheduleEmojiRerender();
      return;
    }
    
    // Incremental: per-cell updates handle tint, building add/remove/replace,
    // avatar load/replace, and lazy texture loading via updateCell →
    // loadBuildingSprites([cell]).
    for (const key of dirty) {
      const cell = state.cells.get(key);
      if (cell) this.updateCell(cell, state);
    }
  }
  
  async setupAllTiles(state) {
    this.layers.tiles.removeChildren();
    this.layers.buildings.removeChildren();
    this.layers.avatars.removeChildren();
    this.tilePool.clear();
    this.glowPool.clear();
    this.borderPool.clear();
    this.buildingPool.clear();
    this.avatarPool.clear();
    
    // Sort cells by Z (top-left to bottom-right)
    const sortedCells = Array.from(state.cells.values()).sort((a, b) => (a.q + a.r) - (b.q + b.r));
    const buildingsToLoad = [];
    const cellsWithAvatars = [];
    
    for (const cell of sortedCells) {
      this.createTile(cell, state);
      if (cell.building) buildingsToLoad.push(cell);
      // Show avatars ONLY on owned tiles. Empty plots stay clean
      // (no GRAM City system badge anymore).
      // If a building SPRITE (skin) is shown on the plot, hide the owner avatar.
      if (cell.owner && !this._spriteShown(cell)) {
        cellsWithAvatars.push(cell);
      }
    }
    
    this.layers.tiles.sortChildren();
    await this.loadBuildingSprites(buildingsToLoad, state);
    await this.loadAvatarSprites(cellsWithAvatars, state);
    this.layers.buildings.sortChildren();
    this.layers.avatars.sortChildren();
    this.updateViewportBounds();

    // Post-setup reconciliation — safeguards against a race between the async
    // texture/avatar loading above and concurrent store dispatches (SET_CELLS
    // re-fetch, SET_USER on user prop change, WebSocket cell_update, …).
    // If any cell in the *current* store state has a building/owner but is
    // missing its sprite in the pool, run the incremental path for it now so
    // the map isn't left with a blank state that only fills in after the user
    // interacts. `updateCell` is idempotent — a no-op when the sprite already
    // matches the cell data.
    try {
      const finalState = mapStore.getState();
      for (const cell of finalState.cells.values()) {
        const key = `${cell.q},${cell.r}`;
        const hasBuilding = this.buildingPool.has(key);
        const wantsBuilding = !!cell.building;
        const hasAvatar = this.avatarPool.has(key);
        const wantsAvatar = !!cell.owner && !this._spriteShown(cell);
        if (hasBuilding !== wantsBuilding || hasAvatar !== wantsAvatar) {
          this.updateCell(cell, finalState);
        }
      }
    } catch (_e) { /* defensive: never let reconciliation break the render */ }
  }
  
  createTile(cell, state) {
    const key = `${cell.q},${cell.r}`;
    const pos = gridToIso(cell.q, cell.r);
    
    if (!this.tileTexture) return;

    const cx = snapToGrid(pos.x + TILE_WIDTH / 2);
    const cy = snapToGrid(pos.y + TILE_HEIGHT / 2);

    // Base plot tile — drawn smaller than the cell so a gap opens up between
    // neighbouring fields.
    const sprite = new Sprite(this.tileTexture);
    sprite.anchor.set(0.5, 0.5);
    sprite.width = TILE_WIDTH * PLOT_INSET;
    sprite.height = TILE_HEIGHT * PLOT_INSET;
    sprite.x = cx;
    sprite.y = cy;
    sprite.zIndex = (cell.q + cell.r);
    sprite.tint = this.getTint(cell, state);
    this.layers.tiles.addChild(sprite);
    this.tilePool.set(key, sprite);

    // Very thin, translucent blue border tracing the field edge.
    if (this.borderTexture) {
      const border = new Sprite(this.borderTexture);
      border.anchor.set(0.5, 0.5);
      border.width = TILE_WIDTH * PLOT_INSET;
      border.height = TILE_HEIGHT * PLOT_INSET;
      border.x = cx;
      border.y = cy;
      border.zIndex = (cell.q + cell.r) + 0.1; // just above the plot fill
      border.tint = 0x4aa6ff;                  // blue
      border.alpha = 0.4;                      // semi-transparent
      this.layers.tiles.addChild(border);
      this.borderPool.set(key, border);
    }

    // Glowing energy edges — full cell footprint (edge-to-edge) so neighbouring
    // glows meet and form continuous translucent streams that sit in the gaps
    // between the smaller plots. Uses NORMAL blend so the alpha reads as a real
    // semi-transparent glow instead of blowing out to solid white.
    if (this.glowTexture) {
      const glow = new Sprite(this.glowTexture);
      glow.anchor.set(0.5, 0.5);
      glow.width = TILE_WIDTH;
      glow.height = TILE_HEIGHT;
      glow.x = cx;
      glow.y = cy;
      glow.zIndex = (cell.q + cell.r) - 0.5; // behind the plots
      glow.tint = 0x63e6ff;                  // cyan energy
      glow.alpha = 0.55;                     // clearly translucent
      this.layers.tiles.addChild(glow);
      this.glowPool.set(key, glow);
    }
  }
  
  async loadBuildingSprites(cells, state) {
    // ============================================================
    // Sprite manifest gate.
    // Building art (PNG) is optional: many/most business types ship
    // NO sprite and the map is meant to fall back to the emoji icon.
    // Previously the engine blindly fetched `/sprites/buildings/<type>_lvl<n>.png`
    // for every owned building, producing a burst of red 404s in DevTools
    // (plus a `data:` CSP fetch from PIXI's ImageBitmap probe) even though
    // the emoji fallback is the intended, correct result.
    //
    // We now consult a static manifest (`/sprites/buildings/manifest.json`,
    // an array of existing filenames) and ONLY request sprites that actually
    // exist. Everything else goes straight to the emoji renderer — zero
    // network requests, zero 404s. To (re)enable art for a building, add its
    // file to that folder and list the filename in manifest.json.
    // ============================================================
    const manifest = await this._getSpriteManifest();

    // Collect every texture key referenced by these cells, but skip any
    // sprite that isn't present in the manifest (→ emoji fallback, no fetch).
    const neededKeys = new Map(); // key → url
    for (const cell of cells) {
      const building = cell.building;
      if (building.isPreview) continue;           // previews already use emoji
      // Applied skin (webp) — bypass the PNG manifest gate and load directly.
      if (building.skinUrl) {
        const skinKey = `skin::${building.skinUrl}`;
        if (this.buildingTextures.has(skinKey) || neededKeys.has(skinKey)) continue;
        neededKeys.set(skinKey, building.skinUrl);
        continue;
      }
      const key = `${building.type}_${building.level || 1}`;
      if (this.buildingTextures.has(key)) continue;
      if (neededKeys.has(key)) continue;
      const url = getSpriteUrl(building.type, building.level || 1);
      const filename = url.split('/').pop();
      if (!manifest.has(filename)) continue;       // no such sprite → emoji
      neededKeys.set(key, url);
    }

    // Load only the sprites we KNOW exist. Reuse any in-flight promise.
    await Promise.all(Array.from(neededKeys.entries()).map(async ([key, url]) => {
      let p = this.loadingTextures.get(key);
      if (!p) {
        p = this._loadTextureFromUrl(url)
          .then((texture) => { if (texture) this.buildingTextures.set(key, texture); return texture; })
          .catch(() => { /* manifest lied / transient — silently fall back to emoji */ })
          .finally(() => { this.loadingTextures.delete(key); });
        this.loadingTextures.set(key, p);
      }
      await p;
    }));

    for (const cell of cells) this.createBuilding(cell, state);
  }

  // Loads a texture from a URL. `data:` URIs (admin-uploaded skins are stored
  // as base64 data URIs) are decoded via an <img> element because PixiJS v8
  // Assets.load cannot reliably resolve a loader for schemeless data URIs.
  async _loadTextureFromUrl(url) {
    if (typeof url === 'string' && url.startsWith('data:')) {
      const img = new Image();
      img.src = url;
      try { await img.decode(); }
      catch (_e) {
        await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });
      }
      return Texture.from(img);
    }
    return Assets.load(url);
  }

  // Fetches (once) the list of building sprites that actually exist on the
  // server. Missing/empty manifest → empty set → everything renders as emoji.
  async _getSpriteManifest() {
    if (IsometricMapEngine._spriteManifest) return IsometricMapEngine._spriteManifest;
    if (!IsometricMapEngine._spriteManifestPromise) {
      IsometricMapEngine._spriteManifestPromise = fetch('/sprites/buildings/manifest.json', { cache: 'force-cache' })
        .then((r) => (r.ok ? r.json() : []))
        .then((list) => {
          IsometricMapEngine._spriteManifest = new Set(Array.isArray(list) ? list : []);
          return IsometricMapEngine._spriteManifest;
        })
        .catch(() => {
          IsometricMapEngine._spriteManifest = new Set();
          return IsometricMapEngine._spriteManifest;
        });
    }
    return IsometricMapEngine._spriteManifestPromise;
  }
  
  // Renders a business as a 2.5D emoji icon on a small podium. Used both for
  // preview (unowned pre-assigned) plots and for owned buildings that have no
  // PNG sprite — the emoji is the intended visual, not a placeholder-for-error.
  _addEmojiBuilding(key, building, pos, cell) {
    const container = new Container();

    // Subtle isometric podium under the icon (gives the 2.5D feel)
    const podium = new Graphics();
    podium.beginFill(0x000000, 0.3);
    podium.drawEllipse(0, -10, 7, 3);
    podium.endFill();
    container.addChild(podium);

    const icon = building.icon || BUSINESSES[building.type]?.icon || '🏢';
    // Emoji is rasterised by the canvas2d backend behind PIXI.Text.
    // We render at 4× resolution AND oversample the font size 4× then
    // scale the sprite down 0.25× — gives ~16× more pixels for the
    // glyph and yields crisp emoji art on retina screens.
    const iconText = new Text({
      text: icon,
      style: new TextStyle({
        fontSize: 44,        // 11 * 4 — oversample
        align: 'center',
      }),
      resolution: 4,
    });
    iconText.scale.set(0.25);   // visual size stays the same as before
    iconText.anchor.set(0.5, 1.0);
    iconText.y = -13;
    container.addChild(iconText);

    container.x = snapToGrid(pos.x + TILE_WIDTH / 2);
    container.y = snapToGrid(pos.y + TILE_HEIGHT);
    container.zIndex = (cell.q + cell.r);
    container.alpha = 0.9;
    container.isPreviewIcon = true;

    this.layers.buildings.addChild(container);
    this.buildingPool.set(key, container);
  }

  createBuilding(cell, state) {
    const key = `${cell.q},${cell.r}`;
    const building = cell.building;
    const pos = gridToIso(cell.q, cell.r);
    
    // PREVIEW MODE: unowned plot with pre-assigned business — show emoji icon
    // in 2.5D style (instead of full building sprite). Helps user spot which
    // tiles have a business available without random-clicking.
    if (building.isPreview) {
      this._addEmojiBuilding(key, building, pos, cell);
      return;
    }
    
    const textureKey = building.skinUrl ? `skin::${building.skinUrl}` : `${building.type}_${building.level || 1}`;
    const texture = this.buildingTextures.get(textureKey);

    // No skin/sprite texture for this OWNED business: render NOTHING here so the
    // owner AVATAR (drawn on the avatar layer) is what shows on the plot. The
    // emoji podium is only used for unowned PREVIEW plots (handled above).
    if (!texture) {
      return;
    }

    const buildingSprite = new BuildingSprite(building, texture);
    
    // CRITICAL POSITIONING:
    // x = center of tile
    // y = bottom tip of tile (pos.y + TILE_HEIGHT/2 + TILE_HEIGHT/2)
    // The previous logic put it at center. With anchor(0.5, 1.0), we need it at the BOTTOM tip.
    // TILE_HEIGHT is 32. 
    // pos.y is the top-left of the bounding box. 
    // Center is pos.y + 16. Bottom tip is pos.y + 32.
    
    buildingSprite.x = snapToGrid(pos.x + TILE_WIDTH / 2);
    buildingSprite.y = snapToGrid(pos.y + TILE_HEIGHT); 
    
    // Strict Z-Index for proper depth sorting (per TD)
    buildingSprite.zIndex = (cell.q + cell.r);
    
    // Apply ownership tint or night mode
    const isOwn = cell.owner && (cell.owner === state.userId || cell.owner === state.userWallet);
    buildingSprite.setOwnershipTint(isOwn);
    buildingSprite.updateAppearance(state.isNight);
    
    this.layers.buildings.addChild(buildingSprite);
    this.buildingPool.set(key, buildingSprite);
  }
  
  async loadAvatarSprites(cells, state) {
    const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
    
    // Load unique avatar textures for owned plots only
    const uniqueAvatars = new Map();
    for (const cell of cells) {
      const url = this._avatarUrl(cell.ownerAvatar);
      // Only URL/data-URI avatars are loadable as textures. Object initials
      // avatars ({type:'initials',...}) have no URL → createAvatar draws the
      // colored initials diamond fallback, so skip texture loading here.
      if (url && !this.avatarTextures.has(url)) {
        if (url.startsWith('data:') || url.startsWith('http')) {
          uniqueAvatars.set(url, url);
        } else if (url.startsWith('/')) {
          uniqueAvatars.set(url, `${BACKEND_URL}${url}`);
        }
      }
    }
    
    await Promise.all(Array.from(uniqueAvatars.entries()).map(async ([key, url]) => {
      if (this.avatarTextures.has(key)) return;
      const loadKey = `avatar_${key}`;
      let p = this.loadingTextures.get(loadKey);
      if (!p) {
        p = (async () => {
          // For data: URLs (incl. SVG) AND for cross-origin HTTP URLs
          // (e.g. Google `lh3.googleusercontent.com/...`) we render the
          // image into a fixed-size canvas first. Direct Assets.load() on
          // Google avatar URLs sometimes silently fails (PIXI texture is
          // not created if the browser blocks WebGL upload due to canvas
          // tainting). The canvas step with crossOrigin='anonymous' is
          // robust: if the server sends CORS we get a usable texture; if
          // not, we cleanly fall back to the initials avatar.
          const useCanvas = url.startsWith('data:') || url.startsWith('http');
          if (useCanvas) {
            const img = new Image();
            if (!url.startsWith('data:')) img.crossOrigin = 'anonymous';
            img.src = url;
            await new Promise((resolve, reject) => {
              img.onload = resolve;
              img.onerror = reject;
            });
            const SIZE = 128;
            const canvas = document.createElement('canvas');
            canvas.width = SIZE;
            canvas.height = SIZE;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, SIZE, SIZE);
            const texture = Texture.from(canvas);
            this.avatarTextures.set(key, texture);
          } else {
            const texture = await Assets.load(url);
            this.avatarTextures.set(key, texture);
          }
        })()
          .catch(() => {
            // Avatar URL is unreachable / CORS-blocked / 404 — keep silent;
            // createAvatar() falls back to the green initials diamond.
          })
          .finally(() => {
            this.loadingTextures.delete(loadKey);
          });
        this.loadingTextures.set(loadKey, p);
      }
      await p;
    }));
    
    for (const cell of cells) this.createAvatar(cell, state);
  }
  
  // Normalize any avatar shape to a loadable URL/data-URI string, or null.
  //   • "https://…" / "data:…" / "/uploads/…"     → the string itself
  //   • { type:'url', url }                        → url
  //   • { url }                                    → url
  //   • { type:'initials', … } / null / other      → null (drawn as initials)
  _avatarUrl(av) {
    if (typeof av === 'string' && av) return av;
    if (av && typeof av === 'object') {
      if (av.type === 'initials') return null;
      if (av.type === 'url' && av.url) return av.url;
      if (typeof av.url === 'string' && av.url) return av.url;
    }
    return null;
  }

  createAvatar(cell, state) {
    const key = `${cell.q},${cell.r}`;
    const pos = gridToIso(cell.q, cell.r);
    // Avatars are only drawn on owned tiles now
    if (!cell.owner) return;
    const av = cell.ownerAvatar;
    const texKey = this._avatarUrl(av);
    const texture = texKey ? this.avatarTextures.get(texKey) : null;
    
    // Create avatar container
    const avatarContainer = new Container();
    
    // Размеры изометрического ромба (на всё поле)
    const halfW = TILE_WIDTH / 2;
    const halfH = TILE_HEIGHT / 2;
    
    if (!texture) {
      // No photo texture → draw the SYSTEM/default avatar as a coloured
      // isometric diamond with the user's initials. When the avatar is an
      // {type:'initials', initials, color} object we honour ITS colour and
      // initials (so it matches the profile avatar everywhere); otherwise we
      // fall back to the first letter of the username on a green tile.
      let initial = (cell.ownerUsername || 'U')[0].toUpperCase();
      let fillColor = 0x4ade80;
      let textColor = '#000000';
      if (av && typeof av === 'object' && av.type === 'initials') {
        initial = (av.initials || initial).toString().toUpperCase();
        if (typeof av.color === 'string' && av.color) {
          const hex = av.color.replace('#', '').trim();
          const parsed = parseInt(hex.length === 3
            ? hex.split('').map(c => c + c).join('') : hex, 16);
          if (!Number.isNaN(parsed)) fillColor = parsed;
        }
      }
      
      // Ромбовидный фон (изометрический алмаз) на всё поле
      const diamond = new Graphics();
      diamond.poly([
        0, -halfH,      // Верхняя точка
        halfW, 0,       // Правая точка
        0, halfH,       // Нижняя точка
        -halfW, 0       // Левая точка
      ]);
      diamond.fill({ color: fillColor, alpha: 0.95 });
      diamond.stroke({ color: 0xffffff, width: 2 });
      avatarContainer.addChild(diamond);
      
      // Initial letter - крупнее, рисуется на 4× resolution для четкости
      const style = new TextStyle({
        fontFamily: 'Arial',
        fontSize: initial.length > 1 ? 13 : 16,
        fontWeight: 'bold',
        fill: textColor,
      });
      const text = new Text({ text: initial, style, resolution: 4 });
      text.anchor.set(0.5, 0.5);
      avatarContainer.addChild(text);
    } else {
      // Ромбовидная рамка на всё поле — точно повторяет форму тайла
      const diamondBorder = new Graphics();
      diamondBorder.poly([
        0, -halfH - 1,
        halfW + 1, 0,
        0, halfH + 1,
        -halfW - 1, 0
      ]);
      diamondBorder.fill({ color: 0xffffff, alpha: 1 });
      avatarContainer.addChild(diamondBorder);
      
      // Внутренний ромб для заливки (фон под фото)
      const diamondFill = new Graphics();
      diamondFill.poly([
        0, -halfH,
        halfW, 0,
        0, halfH,
        -halfW, 0
      ]);
      diamondFill.fill({ color: 0x333333, alpha: 1 });
      avatarContainer.addChild(diamondFill);
      
      // Загружаем ОРИГИНАЛЬНОЕ квадратное фото пользователя (как загружено).
      // Спрайт = квадрат halfW*√2. После rotate(45°) его углы попадают точно
      // в правую/левую вершины ромба, и в (0, ±halfW). Затем обёртка squish-ит
      // по вертикали в halfH/halfW раз → все 4 угла фото совпадают с углами
      // тайла (top/bottom/left/right ромба). Результат: фото заполняет ВЕСЬ
      // ромб без зазоров, изометрически «уложенное» на клетку.
      const side = halfW * Math.SQRT2;
      const avatarSprite = new Sprite(texture);
      avatarSprite.anchor.set(0.5, 0.5);
      avatarSprite.width = side;
      avatarSprite.height = side;
      avatarSprite.rotation = Math.PI / 4;
      
      const photoWrap = new Container();
      photoWrap.scale.set(1, halfH / halfW); // изометрический squish по Y
      photoWrap.addChild(avatarSprite);
      avatarContainer.addChild(photoWrap);
    }
    
    // Position at center of tile
    avatarContainer.x = snapToGrid(pos.x + TILE_WIDTH / 2);
    avatarContainer.y = snapToGrid(pos.y + TILE_HEIGHT / 2);
    // zIndex ниже чем у зданий, чтобы здание было сверху
    avatarContainer.zIndex = (cell.q + cell.r) + 0.1;
    // Store avatar key for change detection (stable string so object avatars
    // don't get needlessly recreated every background refresh).
    avatarContainer.avatarKey = this._avatarKeyStr(cell.ownerAvatar);
    
    this.layers.avatars.addChild(avatarContainer);
    this.avatarPool.set(key, avatarContainer);
  }
  
  // Stable string identity for an avatar (any shape) for change-detection.
  _avatarKeyStr(av) {
    if (typeof av === 'string') return av;
    if (av && typeof av === 'object') {
      if (av.type === 'initials') return `initials:${av.initials || ''}:${av.color || ''}`;
      if (av.url) return av.url;
    }
    return '';
  }
  
  _spriteShown(cell) {
    // True whenever a business has a skin ASSIGNED (webp sprite). We no longer
    // require the texture to be fully loaded first — otherwise the owner avatar
    // is briefly (or permanently, on a load race) rendered ON TOP of the skin.
    // Requirement: if a business has a skin, the owner avatar must NOT show.
    const b = cell && cell.building;
    if (!b || b.isPreview || !b.skinUrl) return false;
    return true;
  }

  updateCell(cell, state) {
    const key = `${cell.q},${cell.r}`;
    
    // Tile update
    const tileSprite = this.tilePool.get(key);
    if (tileSprite) tileSprite.tint = this.getTint(cell, state);
    
    // Building update
    const buildingSprite = this.buildingPool.get(key);
    if (cell.building) {
      // If sprite type changed (preview ↔ real) — rebuild from scratch
      const isPreviewNow = !!cell.building.isPreview;
      const wasPreview = !!buildingSprite?.isPreviewIcon;
      if (buildingSprite && wasPreview === isPreviewNow) {
        // Same kind, just refresh tint (only meaningful for real BuildingSprite)
        if (!isPreviewNow && buildingSprite.setOwnershipTint) {
          const isOwn = cell.owner && (cell.owner === state.userId || cell.owner === state.userWallet);
          buildingSprite.setOwnershipTint(isOwn);
          buildingSprite.updateAppearance(state.isNight);
        }
      } else {
        if (buildingSprite) {
          this.layers.buildings.removeChild(buildingSprite);
          buildingSprite.destroy();
          this.buildingPool.delete(key);
        }
        // Load the (possibly skin) sprite; once ready, if a skin sprite is now
        // shown, drop the owner avatar so it doesn't sit under the building.
        this.loadBuildingSprites([cell], state).then(() => {
          const av = this.avatarPool.get(key);
          if (av && this._spriteShown(cell)) {
            this.layers.avatars.removeChild(av);
            av.destroy();
            this.avatarPool.delete(key);
          }
        }).catch(() => {});
      }
    } else if (buildingSprite) {
      this.layers.buildings.removeChild(buildingSprite);
      buildingSprite.destroy();
      this.buildingPool.delete(key);
    }
    
    // Avatar update — show only for owned tiles (no system project avatar
    // on empty plots anymore).
    const avatarSprite = this.avatarPool.get(key);
    const wantsOwnerAvatar = !!cell.owner && !this._spriteShown(cell);
    if (wantsOwnerAvatar) {
      const desiredKey = this._avatarKeyStr(cell.ownerAvatar);
      const currentAvatarKey = avatarSprite?.avatarKey;
      if (!avatarSprite || currentAvatarKey !== desiredKey) {
        if (avatarSprite) {
          this.layers.avatars.removeChild(avatarSprite);
          avatarSprite.destroy();
          this.avatarPool.delete(key);
        }
        if (currentAvatarKey && currentAvatarKey !== desiredKey) {
          this.avatarTextures.delete(currentAvatarKey);
        }
        this.loadAvatarSprites([cell], state);
      }
    } else if (avatarSprite) {
      this.layers.avatars.removeChild(avatarSprite);
      avatarSprite.destroy();
      this.avatarPool.delete(key);
    }
  }
  
  getTint(cell, state) {
    // Presale gold — highest-priority "free" state (below selected/hovered
    // so admin picks still respond to interaction), applied only when the
    // cell has no owner yet.
    const presaleSet = state?.presaleSet;
    const isPresale = !!(presaleSet && !cell.owner && presaleSet.has(`${cell.q},${cell.r}`));

    if (state.isNight) {
      // Night mode: darker version of zone colors
      const { selectedCell, hoveredCell, userId, userWallet } = state;
      if (selectedCell?.q === cell.q && selectedCell?.r === cell.r) return 0x886622;
      if (hoveredCell?.q === cell.q && hoveredCell?.r === cell.r) return 0x445566;
      if (cell.owner && (cell.owner === userId || cell.owner === userWallet)) return 0x226644;
      if (cell.owner) return 0x443366;
      if (isPresale) return TINTS.presaleNight;
      // Darker zone colors
      const nightZones = { core: 0x334466, inner: 0x2d3d5c, middle: 0x263350, outer: 0x1f2944 };
      return nightZones[cell.zone || 'outer'] || 0x1f2944;
    }
    
    const { selectedCell, hoveredCell, userId, userWallet } = state;
    if (selectedCell?.q === cell.q && selectedCell?.r === cell.r) return TINTS.selected;
    if (hoveredCell?.q === cell.q && hoveredCell?.r === cell.r) return TINTS.hovered;
    if (cell.owner && (cell.owner === userId || cell.owner === userWallet)) return TINTS.owned;
    if (cell.owner) return TINTS.other;
    if (isPresale) return TINTS.presale;
    return TINTS[`free_${cell.zone || 'outer'}`] || TINTS.free_outer;
  }
  
  screenToWorld(screenX, screenY) {
    if (!this.world) return { x: 0, y: 0 };
    return {
      x: (screenX - this.world.x) / this.world.scale.x,
      y: (screenY - this.world.y) / this.world.scale.y
    };
  }
  
  findCellAt(screenX, screenY) {
    const world = this.screenToWorld(screenX, screenY);
    const grid = isoToGrid(world.x, world.y);
    // Search neighborhood for precise rhombus hit
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        const cell = mapStore.getCell(grid.x + dx, grid.y + dy);
        if (cell) {
          const pos = gridToIso(cell.q, cell.r);
          if (this.isInDiamond(world.x, world.y, pos.x + TILE_WIDTH / 2, pos.y + TILE_HEIGHT / 2)) {
            return cell;
          }
        }
      }
    }
    return null;
  }
  
  isInDiamond(px, py, cx, cy) {
    const dx = Math.abs(px - cx) / (TILE_WIDTH / 2);
    const dy = Math.abs(py - cy) / (TILE_HEIGHT / 2);
    return dx + dy <= 1;
  }
  
  handleClick(screenX, screenY) {
    const cell = this.findCellAt(screenX, screenY);
    if (cell) {
      mapStore.dispatch({ type: 'SET_SELECTED', cell });
      this.options.onCellClick(cell);
    }
  }
  
  handleHover(screenX, screenY) {
    const cell = this.findCellAt(screenX, screenY);
    const currentHovered = mapStore.getState().hoveredCell;
    if (cell !== currentHovered) {
      mapStore.dispatch({ type: 'SET_HOVERED', cell });
      if (cell) this.options.onCellHover(cell);
    }
    // Show a finger/pointer cursor when hovering a BUSINESS (a plot that has a
    // building), same affordance as the trash-pile ("Завал") overlay. Empty map
    // space keeps the default (grab) cursor for panning.
    if (this.canvas && !this.interactionLocked && !this.isDragging) {
      this.canvas.style.cursor = (cell && cell.building) ? 'pointer' : '';
    }
  }
  
  centerCamera(fixedZoom = null) {
    if (!this.world) return;
    const cells = Array.from(mapStore.getState().cells.values());
    if (cells.length === 0) return;
    
    // Find bounds
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    cells.forEach(cell => {
      const pos = gridToIso(cell.q, cell.r);
      minX = Math.min(minX, pos.x);
      maxX = Math.max(maxX, pos.x + TILE_WIDTH);
      minY = Math.min(minY, pos.y);
      maxY = Math.max(maxY, pos.y + TILE_HEIGHT);
    });
    
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const mapWidth = maxX - minX;
    const mapHeight = maxY - minY;
    
    const scaleX = (this.options.width - 40) / mapWidth;
    const scaleY = (this.options.height - 40) / mapHeight;
    // When a fixed zoom is requested (initial view), honour it (clamped to the
    // allowed range). Otherwise fall back to the auto-fit behaviour used by the
    // "reset camera" button.
    const zoom = (typeof fixedZoom === 'number')
      ? Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, fixedZoom))
      : Math.min(scaleX, scaleY, MAX_ZOOM) * 0.85;
    
    this.world.scale.set(zoom);
    this.world.x = this.options.width / 2 - centerX * zoom;
    this.world.y = this.options.height / 2 - centerY * zoom;
    
    this.updateViewportBounds();
  }
  
  // Smoothly pan the camera so the given grid cell sits at a target screen point.
  // If `screenX`/`screenY` are provided, use those. Otherwise center the cell.
  panToCell(gridX, gridY, zoom, screenX, screenY) {
    if (!this.world) return;
    const pos = gridToIso(gridX, gridY);
    const tileCx = pos.x + TILE_WIDTH / 2;
    const tileCy = pos.y + TILE_HEIGHT / 2;
    const targetZoom = (typeof zoom === 'number')
      ? Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom))
      : this.world.scale.x;
    const sx = (typeof screenX === 'number') ? screenX : (this.options.width / 2);
    const sy = (typeof screenY === 'number') ? screenY : (this.options.height / 2);
    this.world.scale.set(targetZoom);
    this.world.x = sx - tileCx * targetZoom;
    this.world.y = sy - tileCy * targetZoom;
    this.updateViewportBounds();
  }

  zoomIn() { this.setZoom(this.world.scale.x * 1.2); }
  zoomOut() { this.setZoom(this.world.scale.x / 1.2); }
  setZoom(z) {
    if (this.world) {
      this.world.scale.set(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z)));
      this.updateViewportBounds();
    }
  }
  resetCamera() { this.centerCamera(); }
  // Re-arm the one-time "initial view" so the next full cell update (e.g. a
  // data refresh triggered by the on-page Refresh button) re-applies the exact
  // same zoom/centring the user gets on a full site reload, instead of the
  // plain auto-fit used for subsequent refreshes.
  applyInitialView() { this.initialViewApplied = false; }
  resize(width, height) {
    if (!this.app?.renderer) return;
    this.options.width = width;
    this.options.height = height;
    this.app.renderer.resize(width, height);
    this.updateViewportBounds();
  }
  
  setNightMode(isNight) {
    mapStore.dispatch({ type: 'SET_NIGHT_MODE', isNight });
  }

  /**
   * Lock / unlock all camera input (drag, pinch, wheel-zoom).
   * Single-tap clicks still work — so the tutorial can accept a click on
   * the highlighted HELIOS plot while keeping the camera anchored.
   */
  setInteractionLock(locked) {
    this.interactionLocked = !!locked;
    if (this.interactionLocked) {
      this.isDragging = false;
    }
    if (this.canvas) {
      this.canvas.style.cursor = this.interactionLocked ? 'default' : '';
    }
  }
  
  // ===========================
  // TUTORIAL HIGHLIGHT (animated pulsating ring on a single tile)
  // ===========================
  setTutorialHighlight(plot) {
    if (!this.world) return;

    // Tear down previous highlight (if any)
    if (this.tutorialHighlight) {
      try {
        if (this.tutorialHighlightTicker) {
          this.app?.ticker?.remove(this.tutorialHighlightTicker);
          this.tutorialHighlightTicker = null;
        }
        this.tutorialHighlight.destroy({ children: true });
      } catch { /* noop */ }
      this.tutorialHighlight = null;
    }

    if (!plot || plot.x === undefined || plot.y === undefined) return;

    // Create a Graphics ring that mirrors the diamond tile shape (PixiJS v8 API)
    const ring = new Graphics();
    const w = TILE_WIDTH;
    const h = TILE_HEIGHT;
    const drawDiamond = (lineWidth, color, alpha) => {
      ring.clear();
      ring.moveTo(w / 2, 0);
      ring.lineTo(w, h / 2);
      ring.lineTo(w / 2, h);
      ring.lineTo(0, h / 2);
      ring.lineTo(w / 2, 0);
      ring.stroke({ width: lineWidth, color, alpha, alignment: 0.5 });
    };
    drawDiamond(5, 0xFFD24A, 1);

    // Position it on the target tile (top-left corner of the diamond bbox)
    const pos = gridToIso(plot.x, plot.y);
    ring.x = snapToGrid(pos.x);
    ring.y = snapToGrid(pos.y);
    // Render on TOP of everything so the ring is always visible
    ring.zIndex = 9999;
    ring.alpha = 1;

    // Attach to the avatars layer (highest zIndex among existing layers)
    (this.layers.avatars || this.layers.buildings || this.layers.tiles)?.addChild(ring);
    this.tutorialHighlight = ring;
    console.log('[tutorial-highlight] placed at grid', plot.x, plot.y, '→ iso', pos);

    // Pulsation: oscillate scale 1.0 → 1.18 and alpha 1.0 → 0.55
    const startTime = performance.now();
    const period = 1200; // ms full cycle
    const ticker = () => {
      if (!this.tutorialHighlight) return;
      const t = (performance.now() - startTime) / period;
      const phase = (Math.sin(t * Math.PI * 2) + 1) / 2; // 0..1
      const scale = 1 + 0.3 * phase;
      const alpha = 0.6 + 0.4 * (1 - phase);
      // Pivot at center of the diamond so scale pulses outward symmetrically
      this.tutorialHighlight.pivot.set(w / 2, h / 2);
      this.tutorialHighlight.position.set(snapToGrid(pos.x) + w / 2, snapToGrid(pos.y) + h / 2);
      this.tutorialHighlight.scale.set(scale);
      this.tutorialHighlight.alpha = alpha;
      // Cycle color slightly between gold and cyan for "tutorial" vibe
      const color = phase > 0.5 ? 0x00FFFF : 0xFFD24A;
      drawDiamond(5, color, 1);
    };
    this.tutorialHighlightTicker = ticker;
    this.app?.ticker?.add(ticker);
  }

  clearTutorialHighlight() {
    this.setTutorialHighlight(null);
  }

  /**
   * Compute the screen-space position (in canvas coordinates) of a given
   * grid cell (q, r). Returns the center-X and BOTTOM-tip-Y of the diamond
   * plus the current world scale so HTML overlays (e.g. animated WebP
   * decorations that PIXI cannot play natively) can be anchored on top of
   * a specific tile and follow pan/zoom.
   */
  getCellScreenPosition(q, r) {
    if (!this.world || !this.canvas) return null;
    const pos = gridToIso(q, r);
    // Diamond bounding box: top-left = (pos.x, pos.y), size = TILE_WIDTH × TILE_HEIGHT.
    // Center X = pos.x + TILE_WIDTH/2, bottom tip Y = pos.y + TILE_HEIGHT.
    const worldX = pos.x + TILE_WIDTH / 2;
    const worldY = pos.y + TILE_HEIGHT;
    const scale = this.world.scale.x;
    return {
      x: this.world.x + worldX * scale,
      y: this.world.y + worldY * scale,
      scale,
      tileWidth: TILE_WIDTH * scale,
      tileHeight: TILE_HEIGHT * scale,
    };
  }

  destroy() {
    if (this.rafId) cancelAnimationFrame(this.rafId);
    this.initialized = false;
    if (typeof this._unsubscribeStore === 'function') {
      try { this._unsubscribeStore(); } catch { /* noop */ }
      this._unsubscribeStore = null;
    }
    if (this.tutorialHighlightTicker) {
      try { this.app?.ticker?.remove(this.tutorialHighlightTicker); } catch { /* noop */ }
      this.tutorialHighlightTicker = null;
    }
    if (this.tutorialHighlight) {
      try { this.tutorialHighlight.destroy({ children: true }); } catch { /* noop */ }
      this.tutorialHighlight = null;
    }
    if (this.tileTexture) this.tileTexture.destroy(true);
    if (this.glowTexture) this.glowTexture.destroy(true);
    if (this.borderTexture) this.borderTexture.destroy(true);
    this.buildingTextures.clear();
    this.tilePool.clear();
    this.glowPool.clear();
    this.borderPool.clear();
    this.buildingPool.forEach(b => b.destroy());
    this.buildingPool.clear();
    if (this.canvas?.parentNode) this.canvas.parentNode.removeChild(this.canvas);
    if (this.app) this.app.destroy(true, { children: true });
  }
}

export default IsometricMapEngine;
