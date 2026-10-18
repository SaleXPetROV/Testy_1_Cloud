# Скины «Неон» — исходники

Здания нарисованы кодом (SVG): `kit.js` — изометрические примитивы, `buildings.js` — 21 здание.
Пересборка: `python3 render_skins.py helios,nano_dc,...` → `out/*.png` (512×512, прозрачный фон),
затем экспорт в `frontend/public/sprites/neon/<business_type>.webp` (384×384) и регистрация:
`cd backend && python -m scripts.seed_neon_skins` (группа `neon`, «Неон», для всех 21 типа).
Цвет неона по тиру: 1 — бирюзовый, 2 — фиолетовый, 3 — золотой.
