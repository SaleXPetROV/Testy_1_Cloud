# Часовой бэкап и восстановление GRAM City

## Что делает бэкап (каждый час, `gram-backup.timer`)
1. Коммитит изменения кода и пушит их в приватный репозиторий GitHub (`.env` в репозиторий не попадают — они в `.gitignore`).
2. Делает зашифрованную копию всей базы (AES-256-GCM, `backend/scripts/backup_encrypted.py`) и сразу проверяет, что она читается.
3. Хранит 48 часовых и 30 суточных копий (суточная — копия, сделанная в `DAILY_HOUR` по UTC), старые удаляет.
4. Зеркалирует папки копий в облачное хранилище через `rclone` (S3, Backblaze B2 или Яндекс Object Storage).
5. При любой ошибке присылает сообщение админу в Telegram.

## Установка на сервере (один раз)
```bash
curl https://rclone.org/install.sh | sudo bash
rclone config                                   # добавить хранилище, например с именем b2
cd /opt/gram-city
git remote -v                                   # origin — приватный репозиторий, токен с правом записи только в него
sudo bash deploy/backup/install.sh              # первый запуск создаст /etc/gram-backup.env
sudo nano /etc/gram-backup.env                  # PROJECT_DIR, RCLONE_REMOTE, BACKUP_KEY, Telegram
sudo bash deploy/backup/install.sh              # включит таймер и сделает первую копию
```
Ключ для `BACKUP_KEY`: `cd backend && python -m scripts.backup_encrypted --new-key`. **Сохраните его ещё и вне сервера** (менеджер паролей): без ключа копии не прочитать.

Проверка: `systemctl list-timers gram-backup.timer`, `journalctl -t gram-backup -n 20`, `ls /var/backups/gram/hourly`.

## Восстановление на чистой машине
```bash
# 1. код
git clone <приватный репозиторий> /opt/gram-city && cd /opt/gram-city
cp .env.example .env && cp backend/.env.example backend/.env    # заполнить секреты (из менеджера паролей)

# 2. последняя копия базы
rclone copy b2:gram-city-backups/hourly /tmp/restore --max-age 2h   # или daily/ для суточной
ls /tmp/restore

# 3. поднять проект с ПУСТОЙ базой и залить копию
docker compose up -d --build
docker compose cp /tmp/restore/gram_YYYY-MM-DD_HHMM.enc backend:/tmp/restore.enc
docker compose exec -e BACKUP_KEY=... backend python -m scripts.backup_encrypted verify  /tmp/restore.enc
docker compose exec -e BACKUP_KEY=... backend python -m scripts.backup_encrypted restore /tmp/restore.enc
docker compose restart backend
```
`restore` работает только в пустую базу и отказывается от файла, если ключ неверный или файл изменён.

## Без Docker
В `/etc/gram-backup.env` поставьте `BACKUP_MODE=host`, `MONGO_URL` и `DB_NAME` — как у сервера. Восстановление: `cd backend && BACKUP_KEY=... python -m scripts.backup_encrypted restore файл.enc`.

## Проверка восстановления (раз в месяц)
Скачайте последнюю копию на отдельную машину, выполните шаги 1–3 и откройте сайт: вход админом, карта, баланс игрока.
