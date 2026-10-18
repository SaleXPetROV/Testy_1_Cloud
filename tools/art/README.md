# Генерация спрайтов зданий через Nano Banana (Gemini 2.5 Flash Image)

1. Ключ Google AI Studio: https://aistudio.google.com → Get API key.
2. `pip install requests pillow numpy`
3. Проверить промпты без запросов: `python tools/art/gen_sprites_nanobanana.py --dry-run`
4. Пробный прогон одного здания: `GEMINI_API_KEY=... python tools/art/gen_sprites_nanobanana.py --only gram_bank`
5. Всё (63 картинки): `GEMINI_API_KEY=... python tools/art/gen_sprites_nanobanana.py` — уже готовые пропускаются, можно прерывать и продолжать.
6. Перегенерировать неудачную: удалить `art/raw/<тип>_stage<N>.png` (или `--force --only <тип>`).
7. Только переобработать сырые картинки (вырезание фона, масштаб): `--reprocess`.

Сначала генерируется эталон (Банк Gram, стадия 2) — он передаётся в каждый следующий запрос, чтобы все 63 картинки были в одном стиле и ракурсе. Фон — чистый зелёный #00FF00 (Nano Banana не делает прозрачный), скрипт вырезает его и ставит фундамент на те же точки, что в `frontend/public/sprites/city/manifest.json`, поэтому карта подхватывает новые картинки без правок.

## Свои картинки зданий → спрайты карты
`python tools/art/process_owner_art.py <папка с картинками>` — вырезает тёмный фон (по силуэту, свечение сохраняется), убирает водяной знак, находит фундамент и пишет `frontend/public/sprites/city/<тип>/stage<N>.webp` + данные в `manifest.json` (точка привязки, ширина фундамента, верх здания, ось вытянутости). Соответствие файлов бизнесам и стадиям — словарь `MAP` в скрипте. Тонкая подгонка — в админке, вкладка «Спрайты карты».
