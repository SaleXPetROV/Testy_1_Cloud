// Export the city layout (the approved district plan) as static JSON for the server:
//   node tools/map/export_layout.js > backend/data/city_layout_v1.json
// Every slot gets a fixed business type (even mix inside each size class, as on the map).
const fs = require('fs'), path = require('path'), vm = require('vm');
const code = fs.readFileSync(path.join(__dirname, 'layout_gen.js'), 'utf8');
const ctx = { Math, console };
vm.createContext(ctx);
vm.runInContext(code + '\n;this.__out = { grid, buildings, DISTRICTS, N, R, C, CORE_R, parkCount };', ctx);
const { grid, buildings, DISTRICTS, N, R, C, parkCount } = ctx.__out;
const TYPE_POOL = {
  '1x1': ['helios', 'nano_dc', 'quartz_mine', 'signal_tower', 'hydro_cooling', 'bio_farm', 'scrap_yard'],
  '2x2': ['chips_factory', 'nft_studio', 'ai_lab', 'logistics_hub'],
  '1x2': ['cyber_cafe', 'repair_shop', 'vr_club'],
  '3x3': ['validator', 'gram_bank', 'dex', 'casino', 'arena', 'incubator', 'bridge'],
};
const counters = {};
const slots = buildings.map(b => {
  counters[b.type] = (counters[b.type] || 0) + 1;
  const pool = TYPE_POOL[b.type];
  return { slot_id: b.id, district: b.districtId, size: b.type, x: b.x, y: b.y, w: b.width, h: b.height,
           business_type: pool[(counters[b.type] * 5 + b.districtId * 3) % pool.length] };
});
const parks = [];
for (const row of grid) for (const c of row) if (c.park) parks.push([c.x, c.y]);
process.stdout.write(JSON.stringify({
  version: 'city_v1', grid: N, center: C,
  districts: DISTRICTS.map(d => ({ id: d.id, key: d.key, name: d.name, center: [Math.round(d.center.x * 10) / 10, Math.round(d.center.y * 10) / 10] })),
  slots, parks,
}));
