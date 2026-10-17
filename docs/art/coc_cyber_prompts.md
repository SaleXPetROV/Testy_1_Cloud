# Промпты: здания GRAM City в стиле Clash of Clans × киберпанк

Цель — 21 здание × 3 стадии роста = 63 картинки, которые заменят заглушки в
`frontend/public/sprites/city/<тип>/stage<1|2|3>.webp` (имена файлов те же — движку ничего менять не нужно).

## 1. Общий стиль (вставлять в КАЖДЫЙ промпт)

```
mobile strategy game building asset, Clash of Clans art style, Supercell style, stylized 3D render,
chunky exaggerated proportions, soft rounded bevelled edges, hand-painted textures, cyberpunk neon city theme,
dark navy metal plating with rivets and panel seams, glowing neon accents in {TIER_COLOR},
building stands on a thick raised square foundation made of metal blocks,
warm key light from the upper left, soft ambient occlusion, subtle colored rim light,
isometric view, 2:1 isometric angle, camera 30 degrees elevation, rotated 45 degrees,
single building centered, full building visible, nothing cut off, plain transparent background,
no text, no letters, no logos, no people, no ground around the foundation
```

`{TIER_COLOR}`: тир 1 — `cyan (#00F0FF)`, тир 2 — `violet (#B36BFF)`, тир 3 — `gold (#FFD84D)`.

**Негативный промпт:** `photorealistic, realistic, blurry, low detail, text, watermark, signature, logo, letters, people, characters, cropped, cut off, multiple buildings, background scenery, top-down view, side view, front view, perspective distortion, fisheye`

## 2. Технические условия (одинаковые для всех 63)
- Формат: PNG с прозрачным фоном, 1024×1280 (портрет 4:5).
- Ракурс у всех строго одинаковый (изометрия 2:1). Сначала сгенерировать **эталон** (Банк Gram, стадия 2), затем для остальных использовать его как референс стиля/композиции (style reference / image prompt), если сервис это поддерживает.
- Фундамент занимает ~80% ширины картинки, его нижний угол — примерно на 85% высоты; здание по центру.
- Размер участка задаёт фундамент: тир 1 — квадрат 1×1, тир 2 — квадрат 2×2 или **вытянутый 1×2** (Кибер-кафе, Ремзона, VR-клуб — фундамент прямоугольный, длинная сторона уходит вправо-вниз), тир 3 — квадрат 3×3 (самые массивные).
- После генерации: убрать фон (если не прозрачный), прогнать нормализацию (обрезка, центровка по фундаменту, 320×400 WEBP) — скрипт подготовлю под ваши файлы.

## 3. Стадии роста (добавлять к описанию здания)
| Стадия | Уровни | Модификатор |
|---|---|---|
| 1 | 0–3 | `small early version, compact, basic details, few neon lights` |
| 2 | 4–6 | `upgraded version, taller, more floors and equipment, more neon lights, neon lamp posts on the foundation corners` |
| 3 | 7–10 | `maximum level version, tallest and most impressive, rich details, golden trims, holographic halo ring floating above the roof, glowing energy effects` |

## 4. Описание зданий
### Тир 1 (участок 1×1, неон cyan)
| Тип | Название | Описание для промпта |
|---|---|---|
| helios | Солнечная станция | `solar power station: tilted glowing blue solar panel arrays around a small control tower with a bright energy core on top` |
| nano_dc | Нано-ЦОД | `compact data center block with vertical green and cyan LED server strips on the walls, rooftop satellite dish and cooling vents` |
| quartz_mine | Шахта кварца | `crystal mine: cluster of large glowing cyan and violet quartz crystals, small mining building and a drilling derrick with a neon beam` |
| signal_tower | Вышка трафика | `telecom tower: tall steel lattice antenna mast emitting neon signal rings, small equipment hut at its base` |
| hydro_cooling | Хладокомбинат | `cooling plant: two big white cooling towers releasing glowing icy vapor, frosted pipes, small pump house` |
| bio_farm | Биоферма | `bio farm: glass dome greenhouse with glowing neon plants inside, hydroponic trays, green neon trim` |
| scrap_yard | Свалка | `cyber scrapyard: piles of metal scrap and crates, a yellow crane with a magnet, small orange-lit workshop` |

### Тир 2 (неон violet)
| Тип | Участок | Название | Описание для промпта |
|---|---|---|---|
| chips_factory | 2×2 | Фабрика чипов | `microchip factory hall with saw-tooth roof, two chimneys with violet smoke, giant glowing chip emblem on the wall` |
| nft_studio | 2×2 | NFT-студия | `digital art studio with huge glowing gradient art frames on the walls (magenta to cyan), rooftop hologram projector` |
| ai_lab | 2×2 | ИИ-лаборатория | `AI research lab with a glass dome containing a glowing holographic brain, bubbling neon flasks, server racks` |
| logistics_hub | 2×2 | Логистический хаб | `logistics hangar with curved roof, open gate, stacked colorful cargo containers, helipad with a delivery drone` |
| cyber_cafe | 1×2 | Кибер-кафе | `cozy cyber cafe with magenta striped awning, big neon coffee cup sign, warm window light, outdoor tables` |
| repair_shop | 1×2 | Ремзона | `mechanic garage with roller door, glowing neon wrench sign, tool racks, a small robot arm` |
| vr_club | 1×2 | VR-клуб | `VR gaming club with a giant neon VR headset sculpture on the roof, magenta and cyan window strips` |

### Тир 3 (участок 3×3, неон gold — самые массивные)
| Тип | Название | Описание для промпта |
|---|---|---|
| validator | Валидатор | `blockchain validator node: tall dark monolith with golden circuit lines and a glowing shield emblem, four energy pylons` |
| gram_bank | Банк Gram | `futuristic bank: classical white columns, golden pyramid roof, big glowing golden coin emblem, vault door` |
| dex | DEX-биржа | `crypto exchange tower with giant screens showing glowing green and red candlestick charts, rooftop beacon` |
| casino | Казино | `neon casino with a huge glowing marquee sign with 777, giant white dice on the roof, gold windows` |
| arena | Арена | `oval cyber stadium with glowing green field, golden rim lights, floodlight masts` |
| incubator | Инкубатор | `startup incubator: platform with large glowing egg-shaped capsules (gold, violet, mint), energy cables` |
| bridge | Мост | `cable-stayed bridge segment with two tall pylons and golden neon cables over a short deck` |

## 5. Пример полного промпта
`[общий стиль с {TIER_COLOR} = gold (#FFD84D)], futuristic bank: classical white columns, golden pyramid roof, big glowing golden coin emblem, vault door, upgraded version, taller, more floors and equipment, more neon lights, neon lamp posts on the foundation corners, square 3x3 foundation`

## 6. Где генерировать
Подходят Midjourney (`--ar 4:5 --style raw`, `--sref` с эталоном), Leonardo, Scenario (умеет обучаться на своём стиле — хороший вариант для 63 одинаковых по стилю ассетов), Stable Diffusion с LoRA «game asset isometric». Для единообразия важнее всего один эталон и один набор настроек на все 63 генерации.
