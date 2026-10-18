# GRAM City (TON_CITY v2.3)

Экономическая стратегия на TON: веб и Telegram WebApp. Бэкенд — FastAPI + MongoDB, фронтенд — React (CRA/craco).

## Запуск одной командой (Docker)

```bash
cp .env.example .env                    # публичный адрес, порт, путь админки
cp backend/.env.example backend/.env    # секреты (openssl rand -hex 32), TON, Telegram
docker compose up -d --build
```

- Сайт: `http://localhost:8080` (или ваш `PUBLIC_URL`), API: `/api/`.
- Внутри: MongoDB 7 (данные в томе `mongo_data`), бэкенд, nginx с фронтендом, который проксирует `/api` и WebSocket на бэкенд.
- Переводы: `docker compose --profile translate up -d` поднимет LibreTranslate; укажите `LIBRETRANSLATE_URL=http://libretranslate:5000` в `backend/.env`, затем один раз `cd frontend && LIBRETRANSLATE_URL=http://localhost:5000 npm run i18n:autofill`.
- С `ENV=production` сервер **не запустится** без сильных `ADMIN_SECRET` / `JWT_SECRET_KEY`.

Тестовые пользователи (только для разработки):
```bash
docker compose exec -e SEED_ADMIN_PASSWORD=... -e SEED_USER_PASSWORD=... backend python create_test_users.py
```

## Запуск без Docker

```bash
# MongoDB 7 должна быть запущена локально
cd backend && pip install -r requirements.txt && uvicorn server:app --port 8001
cd frontend && npm install --legacy-peer-deps && npm start      # REACT_APP_BACKEND_URL=http://localhost:8001
```

## Тесты

```bash
cd backend && pip install mongomock-motor pytest && python -m pytest tests/test_*.py -q -p no:cacheprovider
```

## Что где
- Описание всех доработок: `CHANGES_QUESTS.md`
- Награды мини-игры (сундуки, пазлы NFT, склад NFT, лидеры): `docs/MINIGAME_REWARDS.md`
- Альянсы (команда, казна, роли, уровни, чат альянса): `docs/ALLIANCES.md`
- Аватар из Telegram: `docs/TELEGRAM_AVATARS.md`
- Карта города: участки, покупка, восстановление после повторной миграции, пресейл: `docs/CITY_MAP.md`
- Нехватка ресурса у бизнеса (мигающая плашка, окно «Купить»): `docs/BUSINESS_SHORTAGE.md`
- Часовой бэкап и восстановление: `deploy/backup/RESTORE.md`
- Админка: путь задаётся `ADMIN_PATH` (вкладки «Сверка», «Городской рынок», «Лиги», «Бонус возвращения», «Удержание» и др.)
- Скриншоты: `docs/screenshots/`

## Перед выкладкой в прод
1. Сменить пароль администратора и задать новые секреты (старые были в истории git).
2. Задать `TONCENTER_API_KEY`, кошелёк выплат `TON_WALLET_MNEMONIC`, адреса кошельков во вкладке «Сверка».
3. Проверить на тестовой копии с **настоящей MongoDB** (разработка проверялась на совместимой FerretDB и in-memory Mongo).

## Безопасность данных

- **База с паролем.** В `.env` обязательно задать `MONGO_ROOT_PASSWORD` и `MONGO_APP_PASSWORD` (длинные случайные: `openssl rand -base64 32`). При первом запуске создаётся пользователь игры с правами только на базу игры (`deploy/mongo-init.js`); root — только для обслуживания. База во внутренней сети Docker без выхода наружу — до неё может достучаться только бэкенд.
  Если база уже была создана без пароля, пароль добавится только на новом пустом томе: сделайте зашифрованную копию → удалите том → `docker compose up` → восстановите копию.
- **Шифрование диска.** Храните том базы и резервные копии на зашифрованном диске (LUKS / зашифрованный том у хостинга) — так данные нечитаемы даже при краже диска или снимка.
- **Зашифрованные резервные копии** (AES-256-GCM): `python -m scripts.backup_encrypted --new-key` — ключ храните ВНЕ сервера (менеджер паролей, офлайн). Копия: `BACKUP_KEY=... python -m scripts.backup_encrypted backup файл.enc`, проверка: `verify`, восстановление в пустую базу: `restore`. Без ключа файл бесполезен, любое изменение файла обнаруживается.
- **Секреты 2FA** хранятся зашифрованными (`TOTP_ENC_KEY`).
- **Шифрование личных данных в базе** (`core/pii_crypto.py`): почта, кошельки, Telegram-ID, IP, браузер, устройство хранятся зашифрованными (AES-256-GCM), поиск — по слепому индексу (HMAC). Ключи `PII_ENC_KEY` и `PII_INDEX_KEY` в `backend/.env`, копия — вне сервера. Уже существующие данные: зашифрованная копия → `python -m scripts.encrypt_pii --apply` (откат: `--decrypt --apply`). Поиск по части почты/кошелька в админке становится точным совпадением.
- **Отзыв входа:** смена/сброс пароля, отключение 2FA и «Выйти на всех устройствах» (страница «Безопасность») завершают все остальные сессии.
- Отчёт аудита: `docs/SECURITY_AUDIT.md`.
