/**
 * Telegram Mini App biometry card — visible on the Security page ONLY when
 * the user is running inside a Telegram mobile client with BiometricManager
 * available.
 *
 * Handles the three lifecycle states:
 *  1. Not available (desktop TG / regular browser) — card is hidden.
 *  2. Available on device but not enrolled with our server — CTA "Set up".
 *  3. Enrolled — shows device list + "Remove" per device.
 */
import { useEffect, useState } from 'react';
import { Fingerprint, ShieldCheck, Trash2, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { toast } from 'sonner';
import {
  isTelegramMiniApp,
  isBiometryPlatformSupported,
  getBiometryState,
  requestBiometryAccess,
  authenticateBiometry,
  fetchBiometryStatus,
  verifyIdentity,
  registerBiometry,
  removeBiometryDevice,
} from '@/lib/telegramBiometry';

// Full translations of the Telegram-biometry card + setup modal for every
// language the project supports (must match SUPPORTED in LanguageContext.js).
// {bio} is interpolated with the localized biometric type label.
const BIO_I18N = {
  en: {
    bioFingerprint: 'Fingerprint', bioGeneric: 'Biometry',
    cardTitle: 'Telegram biometry',
    cardSubtitle: 'Confirm withdrawals with {bio} right inside Telegram.',
    setup: 'Set up', enableDeviceFirst: 'Enable device biometry first',
    enable2faFirst: 'Enable 2FA in security settings first',
    confirmIdentityReason: 'Confirm identity to set up biometry',
    accessDenied: 'Biometry access denied',
    enter6: 'Enter the 6-digit 2FA code',
    enabledOk: 'Telegram biometry enabled', invalidCode: 'Invalid 2FA code',
    removeConfirm: 'Remove biometry from this device?', removed: 'Removed',
    need2faBanner: 'To enable biometry, first turn on two-factor authentication (2FA) below — it is used to confirm the setup.',
    webBiometryBanner: 'You already use biometry on the web (Passkey). Set it up below to also use it inside Telegram — the browser key cannot be shared with Telegram for security reasons.',
    enrolled: 'Enrolled:', lastUsed: 'Last used:',
    modalTitle: '2FA confirmation',
    modalBody: 'To enable {bio}, enter the 6-digit code from your authenticator app.',
    cancel: 'Cancel', settingUp: 'Setting up…', confirm: 'Confirm',
    scanReason: 'Scan your {bio} to finish setup',
    scanFailed: 'Biometric scan failed. Please try again.',
  },
  ru: {
    bioFingerprint: 'Отпечаток пальца', bioGeneric: 'Биометрия',
    cardTitle: 'Биометрия Telegram',
    cardSubtitle: 'Подтверждайте вывод средств через {bio} прямо внутри Telegram.',
    setup: 'Настроить', enableDeviceFirst: 'Включите отпечаток на устройстве',
    enable2faFirst: 'Сначала включите 2FA в настройках безопасности',
    confirmIdentityReason: 'Подтвердите личность для настройки биометрии',
    accessDenied: 'Доступ к биометрии не разрешён',
    enter6: 'Введите 6-значный код 2FA',
    enabledOk: 'Биометрия Telegram включена', invalidCode: 'Неверный код 2FA',
    removeConfirm: 'Удалить биометрию с этого устройства?', removed: 'Удалено',
    need2faBanner: 'Для подключения биометрии сначала включите двухфакторную аутентификацию (2FA) ниже — она используется для подтверждения настройки.',
    webBiometryBanner: 'Вы уже настроили биометрию в браузере (Passkey). Пройдите настройку ниже, чтобы также использовать её внутри Telegram — Telegram не может напрямую использовать браузерный ключ по соображениям безопасности.',
    enrolled: 'Настроено:', lastUsed: 'Последнее использование:',
    modalTitle: 'Подтверждение 2FA',
    modalBody: 'Чтобы включить вход по биометрии, введите 6-значный код из приложения-аутентификатора.',
    cancel: 'Отмена', settingUp: 'Настройка…', confirm: 'Подтвердить',
    scanReason: 'Отсканируйте биометрию, чтобы завершить настройку',
    scanFailed: 'Не удалось отсканировать биометрию. Попробуйте ещё раз.',
  },
  es: {
    bioFingerprint: 'Huella dactilar', bioGeneric: 'Biometría',
    cardTitle: 'Biometría de Telegram',
    cardSubtitle: 'Confirma los retiros con {bio} directamente en Telegram.',
    setup: 'Configurar', enableDeviceFirst: 'Activa la biometría en el dispositivo primero',
    enable2faFirst: 'Primero activa 2FA en los ajustes de seguridad',
    confirmIdentityReason: 'Confirma tu identidad para configurar la biometría',
    accessDenied: 'Acceso a la biometría denegado',
    enter6: 'Introduce el código 2FA de 6 dígitos',
    enabledOk: 'Biometría de Telegram activada', invalidCode: 'Código 2FA no válido',
    removeConfirm: '¿Eliminar la biometría de este dispositivo?', removed: 'Eliminado',
    need2faBanner: 'Para activar la biometría, primero activa la autenticación en dos pasos (2FA) más abajo: se usa para confirmar la configuración.',
    webBiometryBanner: 'Ya usas biometría en la web (Passkey). Configúrala abajo para usarla también dentro de Telegram; la clave del navegador no se puede compartir con Telegram por seguridad.',
    enrolled: 'Configurado:', lastUsed: 'Último uso:',
    modalTitle: 'Confirmación 2FA',
    modalBody: 'Para activar {bio}, introduce el código de 6 dígitos de tu app de autenticación.',
    cancel: 'Cancelar', settingUp: 'Configurando…', confirm: 'Confirmar',
    scanReason: 'Escanea tu {bio} para finalizar la configuración',
    scanFailed: 'Error al escanear la biometría. Inténtalo de nuevo.',
  },
  zh: {
    bioFingerprint: '指纹', bioGeneric: '生物识别',
    cardTitle: 'Telegram 生物识别',
    cardSubtitle: '在 Telegram 内直接使用{bio}确认提现。',
    setup: '设置', enableDeviceFirst: '请先在设备上启用生物识别',
    enable2faFirst: '请先在安全设置中启用 2FA',
    confirmIdentityReason: '确认身份以设置生物识别',
    accessDenied: '生物识别访问被拒绝',
    enter6: '请输入 6 位 2FA 验证码',
    enabledOk: '已启用 Telegram 生物识别', invalidCode: '2FA 验证码无效',
    removeConfirm: '从此设备移除生物识别？', removed: '已移除',
    need2faBanner: '要启用生物识别，请先在下方开启两步验证（2FA）——它用于确认设置。',
    webBiometryBanner: '您已在网页端使用生物识别（Passkey）。请在下方设置，以便在 Telegram 内也能使用——出于安全原因，浏览器密钥无法与 Telegram 共享。',
    enrolled: '已设置：', lastUsed: '最近使用：',
    modalTitle: '2FA 确认',
    modalBody: '要启用{bio}，请输入身份验证器应用中的 6 位验证码。',
    cancel: '取消', settingUp: '设置中…', confirm: '确认',
    scanReason: '扫描您的{bio}以完成设置',
    scanFailed: '生物识别扫描失败，请重试。',
  },
  fr: {
    bioFingerprint: 'Empreinte digitale', bioGeneric: 'Biométrie',
    cardTitle: 'Biométrie Telegram',
    cardSubtitle: 'Confirmez les retraits avec {bio} directement dans Telegram.',
    setup: 'Configurer', enableDeviceFirst: "Activez d'abord la biométrie sur l'appareil",
    enable2faFirst: "Activez d'abord la 2FA dans les paramètres de sécurité",
    confirmIdentityReason: 'Confirmez votre identité pour configurer la biométrie',
    accessDenied: 'Accès à la biométrie refusé',
    enter6: 'Saisissez le code 2FA à 6 chiffres',
    enabledOk: 'Biométrie Telegram activée', invalidCode: 'Code 2FA invalide',
    removeConfirm: 'Supprimer la biométrie de cet appareil ?', removed: 'Supprimé',
    need2faBanner: "Pour activer la biométrie, activez d'abord l'authentification à deux facteurs (2FA) ci-dessous — elle sert à confirmer la configuration.",
    webBiometryBanner: "Vous utilisez déjà la biométrie sur le web (Passkey). Configurez-la ci-dessous pour l'utiliser aussi dans Telegram — la clé du navigateur ne peut pas être partagée avec Telegram pour des raisons de sécurité.",
    enrolled: 'Configuré :', lastUsed: 'Dernière utilisation :',
    modalTitle: 'Confirmation 2FA',
    modalBody: "Pour activer {bio}, saisissez le code à 6 chiffres de votre application d'authentification.",
    cancel: 'Annuler', settingUp: 'Configuration…', confirm: 'Confirmer',
    scanReason: 'Scannez votre {bio} pour terminer la configuration',
    scanFailed: 'Échec du scan biométrique. Veuillez réessayer.',
  },
  de: {
    bioFingerprint: 'Fingerabdruck', bioGeneric: 'Biometrie',
    cardTitle: 'Telegram-Biometrie',
    cardSubtitle: 'Bestätige Auszahlungen mit {bio} direkt in Telegram.',
    setup: 'Einrichten', enableDeviceFirst: 'Aktiviere zuerst die Biometrie auf dem Gerät',
    enable2faFirst: 'Aktiviere zuerst 2FA in den Sicherheitseinstellungen',
    confirmIdentityReason: 'Bestätige deine Identität, um die Biometrie einzurichten',
    accessDenied: 'Zugriff auf Biometrie verweigert',
    enter6: 'Gib den 6-stelligen 2FA-Code ein',
    enabledOk: 'Telegram-Biometrie aktiviert', invalidCode: 'Ungültiger 2FA-Code',
    removeConfirm: 'Biometrie von diesem Gerät entfernen?', removed: 'Entfernt',
    need2faBanner: 'Um die Biometrie zu aktivieren, schalte zuerst unten die Zwei-Faktor-Authentifizierung (2FA) ein — sie wird zur Bestätigung der Einrichtung verwendet.',
    webBiometryBanner: 'Du nutzt Biometrie bereits im Web (Passkey). Richte sie unten ein, um sie auch in Telegram zu verwenden — der Browser-Schlüssel kann aus Sicherheitsgründen nicht mit Telegram geteilt werden.',
    enrolled: 'Eingerichtet:', lastUsed: 'Zuletzt verwendet:',
    modalTitle: '2FA-Bestätigung',
    modalBody: 'Um {bio} zu aktivieren, gib den 6-stelligen Code aus deiner Authenticator-App ein.',
    cancel: 'Abbrechen', settingUp: 'Wird eingerichtet…', confirm: 'Bestätigen',
    scanReason: 'Scanne deinen {bio}, um die Einrichtung abzuschließen',
    scanFailed: 'Biometrischer Scan fehlgeschlagen. Bitte versuche es erneut.',
  },
  ja: {
    bioFingerprint: '指紋', bioGeneric: '生体認証',
    cardTitle: 'Telegram 生体認証',
    cardSubtitle: 'Telegram 内で{bio}を使って出金を確認できます。',
    setup: '設定', enableDeviceFirst: '先に端末で生体認証を有効にしてください',
    enable2faFirst: '先にセキュリティ設定で 2FA を有効にしてください',
    confirmIdentityReason: '生体認証を設定するために本人確認を行ってください',
    accessDenied: '生体認証へのアクセスが拒否されました',
    enter6: '6桁の 2FA コードを入力してください',
    enabledOk: 'Telegram 生体認証を有効にしました', invalidCode: '無効な 2FA コード',
    removeConfirm: 'この端末から生体認証を削除しますか？', removed: '削除しました',
    need2faBanner: '生体認証を有効にするには、まず下の二段階認証（2FA）を有効にしてください。設定の確認に使用します。',
    webBiometryBanner: 'すでにウェブ（パスキー）で生体認証を使用しています。Telegram 内でも使うには下で設定してください。セキュリティ上の理由から、ブラウザの鍵を Telegram と共有することはできません。',
    enrolled: '設定日:', lastUsed: '最終使用:',
    modalTitle: '2FA 確認',
    modalBody: '{bio}を有効にするには、認証アプリの6桁のコードを入力してください。',
    cancel: 'キャンセル', settingUp: '設定中…', confirm: '確認',
    scanReason: '設定を完了するには{bio}をスキャンしてください',
    scanFailed: '生体認証のスキャンに失敗しました。もう一度お試しください。',
  },
  ko: {
    bioFingerprint: '지문', bioGeneric: '생체 인증',
    cardTitle: 'Telegram 생체 인증',
    cardSubtitle: 'Telegram 안에서 {bio}(으)로 출금을 확인하세요.',
    setup: '설정', enableDeviceFirst: '먼저 기기에서 생체 인증을 활성화하세요',
    enable2faFirst: '먼저 보안 설정에서 2FA를 활성화하세요',
    confirmIdentityReason: '생체 인증을 설정하려면 본인 확인을 해주세요',
    accessDenied: '생체 인증 접근이 거부되었습니다',
    enter6: '6자리 2FA 코드를 입력하세요',
    enabledOk: 'Telegram 생체 인증이 활성화되었습니다', invalidCode: '잘못된 2FA 코드',
    removeConfirm: '이 기기에서 생체 인증을 삭제할까요?', removed: '삭제됨',
    need2faBanner: '생체 인증을 활성화하려면 먼저 아래에서 2단계 인증(2FA)을 켜세요. 설정 확인에 사용됩니다.',
    webBiometryBanner: '이미 웹(패스키)에서 생체 인증을 사용 중입니다. Telegram 안에서도 사용하려면 아래에서 설정하세요. 보안상의 이유로 브라우저 키는 Telegram과 공유할 수 없습니다.',
    enrolled: '설정됨:', lastUsed: '마지막 사용:',
    modalTitle: '2FA 확인',
    modalBody: '{bio}을(를) 활성화하려면 인증 앱의 6자리 코드를 입력하세요.',
    cancel: '취소', settingUp: '설정 중…', confirm: '확인',
    scanReason: '설정을 완료하려면 {bio}을(를) 스캔하세요',
    scanFailed: '생체 인증 스캔에 실패했습니다. 다시 시도하세요.',
  },
  id: {
    bioFingerprint: 'Sidik jari', bioGeneric: 'Biometrik',
    cardTitle: 'Biometrik Telegram',
    cardSubtitle: 'Konfirmasi penarikan dengan {bio} langsung di dalam Telegram.',
    setup: 'Atur', enableDeviceFirst: 'Aktifkan biometrik di perangkat terlebih dahulu',
    enable2faFirst: 'Aktifkan 2FA di pengaturan keamanan terlebih dahulu',
    confirmIdentityReason: 'Konfirmasi identitas untuk mengatur biometrik',
    accessDenied: 'Akses biometrik ditolak',
    enter6: 'Masukkan kode 2FA 6 digit',
    enabledOk: 'Biometrik Telegram diaktifkan', invalidCode: 'Kode 2FA tidak valid',
    removeConfirm: 'Hapus biometrik dari perangkat ini?', removed: 'Dihapus',
    need2faBanner: 'Untuk mengaktifkan biometrik, aktifkan dulu autentikasi dua faktor (2FA) di bawah — digunakan untuk mengonfirmasi pengaturan.',
    webBiometryBanner: 'Anda sudah memakai biometrik di web (Passkey). Atur di bawah agar bisa dipakai juga di dalam Telegram — kunci browser tidak dapat dibagikan ke Telegram demi keamanan.',
    enrolled: 'Diatur:', lastUsed: 'Terakhir dipakai:',
    modalTitle: 'Konfirmasi 2FA',
    modalBody: 'Untuk mengaktifkan {bio}, masukkan kode 6 digit dari aplikasi autentikator Anda.',
    cancel: 'Batal', settingUp: 'Mengatur…', confirm: 'Konfirmasi',
    scanReason: 'Pindai {bio} Anda untuk menyelesaikan pengaturan',
    scanFailed: 'Pemindaian biometrik gagal. Silakan coba lagi.',
  },
};

export default function TelegramBiometryCard({ lang = 'en', has2FA = false }) {
  const [devState, setDevState] = useState(null);
  const [srvState, setSrvState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showSetup, setShowSetup] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [registering, setRegistering] = useState(false);

  const dict = BIO_I18N[lang] || BIO_I18N.en;
  const t = (key, vars) => {
    let s = dict[key] ?? BIO_I18N.en[key] ?? key;
    if (vars) Object.keys(vars).forEach((k) => { s = s.replace(`{${k}}`, vars[k]); });
    return s;
  };

  const refresh = async () => {
    setLoading(true);
    try {
      const d = await getBiometryState();
      setDevState(d);
      if (d.supported) {
        try {
          const s = await fetchBiometryStatus();
          setSrvState(s);
        } catch (_) { setSrvState({ enabled: false }); }
      }
    } finally { setLoading(false); }
  };

  useEffect(() => { refresh(); }, []);

  // Card is completely hidden on unsupported platforms (desktop TG, browsers)
  if (!isTelegramMiniApp() || !isBiometryPlatformSupported()) return null;
  if (loading) return null;

  const enabled = !!srvState?.enabled;
  const available = !!devState?.available;
  const bioType = (devState?.biometricType || '').toLowerCase();
  const bioLabel = bioType === 'face' ? 'Face ID' : (bioType === 'finger' ? t('bioFingerprint') : t('bioGeneric'));

  const openSetup = async () => {
    // Biometry setup is verified with the account's 2FA code ONLY (many
    // Telegram Mini App users signed up without a password). If the user has
    // no 2FA yet, guide them to enable it first.
    if (!has2FA) {
      toast.error(t('enable2faFirst'));
      return;
    }
    // Ensure access is granted at the OS level first.
    const granted = await requestBiometryAccess(t('confirmIdentityReason'));
    if (!granted) {
      toast.error(t('accessDenied'));
      return;
    }
    setTotpCode('');
    setShowSetup(true);
  };

  const doRegister = async () => {
    if (!totpCode || totpCode.length < 6) {
      toast.error(t('enter6'));
      return;
    }
    setRegistering(true);
    try {
      const verify = await verifyIdentity({ totpCode });
      // Fresh biometric scan — the user re-scans their fingerprint / Face ID
      // right now to confirm the setup. This (plus the short-lived
      // setup_challenge) is what guarantees freshness, so the server no longer
      // needs Telegram's initData to be recent (fixes "initData too old").
      const scan = await authenticateBiometry(t('scanReason', { bio: bioLabel }));
      if (!scan.authenticated) {
        toast.error(t('scanFailed'));
        return;
      }
      await registerBiometry({
        setupChallenge: verify.setup_challenge,
        deviceName: bioLabel,
      });
      toast.success(t('enabledOk'));
      setShowSetup(false);
      setTotpCode('');
      refresh();
    } catch (e) {
      toast.error(e?.message || t('invalidCode'));
    } finally { setRegistering(false); }
  };

  const doRemove = async (deviceId) => {
    if (!window.confirm(t('removeConfirm'))) return;
    try {
      await removeBiometryDevice(deviceId);
      toast.success(t('removed'));
      refresh();
    } catch (e) {
      toast.error(e?.message || 'Error');
    }
  };

  return (
    <div className="glass-panel rounded-2xl p-4 sm:p-8 border border-white/10" data-testid="tg-biometry-card">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <Fingerprint className="w-6 h-6 text-cyber-cyan" />
          <div>
            <h3 className="text-lg font-bold text-white uppercase tracking-wide">
              {t('cardTitle')}
            </h3>
            <p className="text-text-muted text-sm">
              {t('cardSubtitle', { bio: bioLabel })}
            </p>
          </div>
        </div>
        {!enabled && (
          <Button
            data-testid="tg-biometry-setup-btn"
            onClick={openSetup}
            disabled={!available}
            className="bg-cyber-cyan text-black hover:brightness-110 w-full sm:w-auto justify-center"
          >
            <ShieldCheck className="w-4 h-4 mr-2" />
            {available ? t('setup') : t('enableDeviceFirst')}
          </Button>
        )}
      </div>

      {!enabled && available && !has2FA && (
        <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-400/30 text-amber-200 text-sm flex items-start gap-2 mb-3" data-testid="tg-biometry-need-2fa">
          <Info className="w-4 h-4 mt-0.5 shrink-0" />
          <div>{t('need2faBanner')}</div>
        </div>
      )}

      {srvState?.has_web_biometry && !enabled && (
        <div className="p-3 rounded-lg bg-cyan-500/10 border border-cyan-400/30 text-cyan-200 text-sm flex items-start gap-2 mb-3">
          <Info className="w-4 h-4 mt-0.5 shrink-0" />
          <div>{t('webBiometryBanner')}</div>
        </div>
      )}

      {enabled && (srvState?.devices || []).length > 0 && (
        <div className="space-y-3">
          {srvState.devices.map((d) => (
            <div key={d.device_id} className="flex items-center justify-between p-4 bg-white/5 rounded-xl border border-white/10">
              <div className="flex items-center gap-3">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                <div>
                  <p className="text-white font-medium">{d.device_name || bioLabel}</p>
                  <p className="text-text-muted text-xs">
                    {t('enrolled')} {d.created_at ? new Date(d.created_at).toLocaleDateString() : '—'}
                    {d.last_used_at && ` • ${t('lastUsed')} ${new Date(d.last_used_at).toLocaleDateString()}`}
                  </p>
                </div>
              </div>
              <Button
                data-testid={`tg-biometry-remove-${d.device_id}`}
                variant="ghost"
                size="sm"
                onClick={() => doRemove(d.device_id)}
                className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      <Dialog open={showSetup} onOpenChange={setShowSetup}>
        <DialogContent className="bg-void border-white/10 text-white max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldCheck className="w-5 h-5 text-cyber-cyan" />
              {t('modalTitle')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="flex flex-col items-center text-center gap-2">
              <div className="w-14 h-14 rounded-full bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center">
                <Fingerprint className="w-7 h-7 text-cyber-cyan" />
              </div>
              <p className="text-sm text-text-muted">
                {t('modalBody', { bio: bioLabel })}
              </p>
            </div>
            <InputOTP
              maxLength={6}
              value={totpCode}
              onChange={(val) => setTotpCode((val || '').replace(/\D+/g, '').slice(0, 6))}
              containerClassName="justify-center"
              data-testid="tg-biometry-totp"
              autoFocus
            >
              <InputOTPGroup className="gap-2">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <InputOTPSlot
                    key={i}
                    index={i}
                    data-testid={`tg-biometry-otp-slot-${i}`}
                    className="h-14 w-11 text-2xl font-mono text-white bg-white/5 border-white/20 !border-l !rounded-lg"
                  />
                ))}
              </InputOTPGroup>
            </InputOTP>
          </div>
          <DialogFooter className="flex-col sm:flex-row gap-2">
            <Button variant="ghost" onClick={() => setShowSetup(false)} className="w-full sm:w-auto bg-transparent text-text-muted hover:text-white hover:bg-white/5 border border-white/10">
              {t('cancel')}
            </Button>
            <Button
              onClick={doRegister}
              disabled={registering || totpCode.length < 6}
              data-testid="tg-biometry-confirm"
              className="bg-cyber-cyan text-black hover:brightness-110 w-full sm:w-auto"
            >
              {registering ? t('settingUp') : t('confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
