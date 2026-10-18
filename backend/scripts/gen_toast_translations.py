"""Генерация переводов toast-сообщений фронта (9 языков) → frontend/src/lib/translationsToasts.js"""
import asyncio, json, os, sys, uuid
sys.path.insert(0, '/app/backend'); os.chdir('/app/backend')
from dotenv import load_dotenv; load_dotenv('.env')

RU = {
    "toastNotEnoughResources": "Недостаточно ресурсов. Доступно: {n}",
    "toastMaxAmount": "Максимум: {n}",
    "toastFillAllFields": "Заполните все поля",
    "toastContractCreated": "Контракт создан!",
    "toastContractAccepted": "Контракт принят!",
    "toastContractCancelled": "Контракт отменён",
    "toastChooseBuffAndType": "Выберите баф и тип контракта",
    "toastOfferPublished": "Оффер опубликован!",
    "toastOfferNotFound": "Оффер не найден",
    "toastNoBusinessForOffer": "Нет доступного бизнеса для этого оффера",
    "toastOfferCancelled": "Оффер отменён",
    "toastWarehouseNoSpace": "На складе нет места для этого ресурса. Освободите место или прокачайте бизнес.",
    "toastCodeSentCurrentEmail": "Код отправлен на вашу текущую почту",
    "toastEnter6DigitCode": "Введите 6-значный код",
    "toastCodeConfirmedEnterEmail": "Код подтверждён! Введите новый email",
    "toastEnterValidEmail": "Введите корректный email",
    "toastCodeSentNewEmail": "Код отправлен на новую почту",
    "toastEmailChanged": "Email успешно изменён!",
    "toastGoToBotStart": "Перейдите в бота и нажмите /start",
    "toastTelegramLinked": "Telegram успешно привязан!",
    "toastTelegramLinkTimeout": "Время ожидания привязки истекло",
    "toastEnterTelegramUsername": "Укажите Telegram username",
    "toastTelegramLinkedShort": "Telegram привязан!",
    "toastTelegramUnlinked": "Telegram отвязан",
    "toastIdCopied": "ID скопирован!",
    "toastAddressCopied": "Адрес скопирован!",
    "toastSecurityStatusError": "Ошибка загрузки статуса безопасности",
    "toastConnectionError": "Ошибка соединения",
    "toast2faEnabled": "2FA успешно активирована!",
    "toastCodeSentEmail": "Код отправлен на email",
    "toast2faDisabled": "2FA отключена. Вывод заблокирован на 3 минуты.",
    "toastPasskeyRegistered": "Passkey успешно зарегистрирован!",
    "toastRegistrationCancelled": "Регистрация отменена пользователем",
    "toastPasskeyUnavailable": "Passkey недоступен на этом домене.",
    "toastActionCancelled": "Действие отменено",
    "toast2faRequired": "Требуется код 2FA",
    "toastPasskeyDeleted": "Passkey удалён",
    "toastBackupCodesCopied": "Резервные коды скопированы",
    "toastSkinsLoadError": "Ошибка загрузки скинов",
    "toastCreditApproved": "Кредит одобрен! Получено {n} $CITY",
    "toastRateLimited": "Сервер временно ограничивает запросы. Попробуйте через несколько секунд.",
    "toastDetailsLoadError": "Ошибка загрузки деталей",
}
LANGS = ["en", "es", "zh", "fr", "de", "ja", "ko", "id"]
NAMES = {"en": "English", "es": "Spanish", "zh": "Chinese (Simplified)", "fr": "French", "de": "German", "ja": "Japanese", "ko": "Korean", "id": "Indonesian"}


async def translate_batch(lang: str) -> dict:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"t-{uuid.uuid4()}",
                   system_message=(f"Translate the JSON values from Russian into {NAMES[lang]}. Keep keys unchanged, keep "
                                   "placeholders like {n}, '$CITY', '2FA', 'Passkey', 'Telegram', 'Email', '/start' as is. "
                                   "Output ONLY valid JSON, no code fences.")).with_model("openai", "gpt-5.4-mini")
    out = await chat.send_message(UserMessage(text=json.dumps(RU, ensure_ascii=False)))
    out = out.strip().strip("`")
    if out.startswith("json"):
        out = out[4:]
    return json.loads(out)


async def main():
    result = {"ru": RU}
    for lang in LANGS:
        for attempt in range(3):
            try:
                d = await translate_batch(lang)
                missing = [k for k in RU if k not in d]
                if missing:
                    raise ValueError(f"missing {missing[:3]}")
                result[lang] = {k: d[k] for k in RU}
                print(lang, "ok")
                break
            except Exception as e:
                print(lang, "retry", attempt, e)
        else:
            result[lang] = dict(RU)
    js = "// Переводы toast-сообщений (сгенерировано, 9 языков). Плейсхолдер {n}.\nexport const translationsToasts = " + json.dumps(result, ensure_ascii=False, indent=2) + ";\n"
    open('/app/frontend/src/lib/translationsToasts.js', 'w').write(js)
    print("written")

asyncio.run(main())
