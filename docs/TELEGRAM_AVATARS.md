# Аватар из Telegram

Игроки, которые зарегистрировались (или входят) через Telegram — Mini App, виджет входа, бот, привязка Telegram, — получают фото профиля Telegram как аватар. Если игрок сам поменял аватар в проекте (`/api/auth/upload-avatar` ставит `custom_avatar_uploaded`), показывается его аватар, Telegram его больше не трогает.

## Как работает
- Фото берётся через Bot API (`getUserProfilePhotos` → `getFile`). Ссылка на файл содержит токен бота, поэтому фото скачивается на сервер, обрезается до квадрата 256 px, сохраняется в WebP в `uploads/avatars/` и отдаётся по `GET /api/avatars/tg_<id>_<хеш>.webp` (новое фото — новый адрес, старый файл удаляется).
- Если бот фото не видит (настройки приватности Telegram), берётся `photo_url`, который Telegram передал при входе.
- У игрока: `avatar = {"type": "url", "url": "/api/avatars/…"}`, `avatar_source = "telegram"`.
- Заменяются только «пустые» аватары: нет аватара, инициалы, сгенерированная картинка, старая ссылка Telegram. Фото Google и загруженные фото не заменяются.
- Когда: при каждом входе через Telegram (в фоне, не чаще раза в 12 ч) и фоновая задача каждые 30 минут — игроки с Telegram, не проверенные 7 дней (до 150 за проход).

## Что нужно на сервере
`TELEGRAM_BOT_TOKEN` (и при необходимости `TELEGRAM_API_BASE`, `TELEGRAM_PROXY_URL`). Без токена фоновая задача ничего не делает, при входе используется только `photo_url`.

## Файлы
- `backend/core/tg_avatar.py` — логика и `/api/avatars`;
- `backend/routes/telegram_auth.py` — вызов при входе;
- `backend/server.py` — задача `_tg_avatars`;
- `frontend/src/components/SmartAvatar.jsx` — показ (адреса `/api/…` идут на бэкенд);
- тесты: `backend/tests/test_tg_avatar.py`.
