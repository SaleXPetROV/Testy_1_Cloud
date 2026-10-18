# TON_CITY v2.3 — PRD / Work Log

## Source
Cloned from https://github.com/SaleXPetROV/TON_CITY_v2.3.git into /app.
Stack: React 19 (CRA/craco) + FastAPI + MongoDB. Telegram WebApp mobile game.
Backend entry: server.py (uvicorn server:app @8001). Frontend @3000 (supervisor).

## Test users (seeded)
- Admin:   (см. переменные SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD)  (is_admin=true)
- Regular: (см. переменные SEED_USER_EMAIL / SEED_USER_PASSWORD)
- Seed:    `cd /app/backend && python -m scripts.seed_test_users`
- Each user has 1 `bio_farm` business: `python -m scripts.seed_test_business`
- Both have resource neuro_core:2 -> "System Overclock" buff (shown in modal).

## Task (Business screen = /my-businesses = MyBusinessesPage.jsx)
Adaptive, no-scroll layout for any screen height/width (short Android -> tall iPhone).

### Implemented (2026-06)
- Root `.app-screen` = `flex h-[100dvh]`; main column `flex flex-col
  justify-between` + `pb-[calc(68px+env(safe-area-inset-bottom))]` (safe-area).
- Header (BusinessProfileHeader) wrapped shrink-0 (data-testid=biz-header).
- Central section flex-1, vertically centered, fluid gaps clamp(4-16px).
- Business art `.biz-skin-img`: `max-height: min(100%, <vh>)` so it fits its
  flex box (never overlaps title/status) + width>400 bigger, height<750 smaller.
- Footer (durability/warehouse/income chips + Repair/Start-shift/Upgrade) is
  shrink-0 and pinned; bottom tab-bar (BottomNav) fixed w/ safe-area.
- ACTIVE BUFFS banner MOVED from page into the Business-details modal.
- Business title nudged lower (mt clamp).
- Verified by testing_agent iteration_1 (layout) + iteration_2 (overlap) = 100%.

## Backlog / Next
- MyBusinessesPage.jsx is 2400+ lines — could split modal/header/footer components.

## Iteration 2 (2026-06) — Business screen polish
- Skins bug FIXED: routes/skins.py now alias-aware (SKIN_TYPE_ALIASES) so admin
  skins stored under e.g. `signal` show for `signal_tower` in /skins/my + /skins/apply.
- Active business title is a single centered heading on the SAME top line as the
  ЗАДАНИЯ/МАРКЕТ side buttons (data-testid='active-business-name'), animates on swipe.
- Production/consumption now use backend-authoritative `production` object
  (production/24 per hour, consumption_breakdown per day) — removed buggy client recompute.
- Panels (biz-fixed-panels) wrapped in keyed motion.div -> refresh animation on swipe.
- Business art has subtle breathing animation (.biz-art-float).
- Empty state (no business): center button 'Открыть бизнес' (acquire-business-btn) -> /maps.
- Verified: testing_agent iteration_3 (skins/title/swipe/data/dots/breathing) &
  iteration_4 (title level + empty state) = 100%.
- Extra QA account: emptyuser@example.com / (redacted) (no business).

## Iteration 3 (2026-06) — Empty-state redesign
- No-business Business screen now mirrors the full layout: center shows a COMPACT
  GLOWING 'Открыть бизнес' button (data-testid='acquire-business-btn', .biz-open-glow
  animated glow) -> navigates to /maps; side buttons biz-side-tasks/biz-side-marketplace kept.
- Lower panels always render; empty placeholders: Durability 0.0%, Warehouse '— / —',
  income chip 0, expense chip 0 (data-testid suffix 'empty'). No action buttons when empty.
- Verified by testing_agent iteration_5 = 100%.
