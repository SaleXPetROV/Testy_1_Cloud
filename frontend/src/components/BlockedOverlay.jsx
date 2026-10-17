import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ShieldX, MessageCircle, LogOut } from 'lucide-react';
import SupportModal from './SupportModal';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Full localization of the "account blocked" screen for every supported
// language. The block REASON itself is translated server-side via
// LibreTranslate (see /api/auth/me → block_reason) into the user's language.
const BLOCK_I18N = {
  en: { title: 'Account blocked', reasonLabel: 'Reason for blocking:', desc: 'Your account has been blocked. If you believe this is a mistake, contact support below.', support: 'Contact support', logout: 'Log out', defaultReason: 'Rule violation' },
  ru: { title: 'Аккаунт заблокирован', reasonLabel: 'Причина блокировки:', desc: 'Ваш аккаунт заблокирован. Если вы считаете, что это ошибка, обратитесь в поддержку ниже.', support: 'Написать в поддержку', logout: 'Выйти', defaultReason: 'Нарушение правил' },
  es: { title: 'Cuenta bloqueada', reasonLabel: 'Motivo del bloqueo:', desc: 'Tu cuenta ha sido bloqueada. Si crees que es un error, contacta con soporte abajo.', support: 'Contactar soporte', logout: 'Salir', defaultReason: 'Violación de las reglas' },
  zh: { title: '账户已被封禁', reasonLabel: '封禁原因：', desc: '您的账户已被封禁。如果您认为这是错误，请通过下方联系客服。', support: '联系客服', logout: '退出', defaultReason: '违反规则' },
  fr: { title: 'Compte bloqué', reasonLabel: 'Raison du blocage :', desc: 'Votre compte a été bloqué. Si vous pensez que c\'est une erreur, contactez le support ci-dessous.', support: 'Contacter le support', logout: 'Se déconnecter', defaultReason: 'Violation des règles' },
  de: { title: 'Konto gesperrt', reasonLabel: 'Grund der Sperrung:', desc: 'Dein Konto wurde gesperrt. Wenn du glaubst, dass dies ein Fehler ist, kontaktiere den Support unten.', support: 'Support kontaktieren', logout: 'Abmelden', defaultReason: 'Regelverstoß' },
  ja: { title: 'アカウントがブロックされました', reasonLabel: 'ブロックの理由：', desc: 'あなたのアカウントはブロックされました。誤りだと思われる場合は、下のサポートにご連絡ください。', support: 'サポートに連絡', logout: 'ログアウト', defaultReason: '規約違反' },
  ko: { title: '계정이 차단되었습니다', reasonLabel: '차단 사유:', desc: '귀하의 계정이 차단되었습니다. 오류라고 생각되면 아래 고객지원에 문의하세요.', support: '고객지원 문의', logout: '로그아웃', defaultReason: '규칙 위반' },
  id: { title: 'Akun diblokir', reasonLabel: 'Alasan pemblokiran:', desc: 'Akun Anda telah diblokir. Jika menurut Anda ini kesalahan, hubungi dukungan di bawah.', support: 'Hubungi dukungan', logout: 'Keluar', defaultReason: 'Pelanggaran aturan' },
};

export default function BlockedOverlay({ user }) {
  const [isBlocked, setIsBlocked] = useState(false);
  const [blockReason, setBlockReason] = useState('');
  const [lang, setLang] = useState('ru');
  const [supportOpen, setSupportOpen] = useState(false);

  const tr = BLOCK_I18N[lang] || BLOCK_I18N.en;

  const applyState = useCallback((data) => {
    if (data?.is_blocked) {
      setIsBlocked(true);
      setBlockReason(data.block_reason || data.block_reason_original || '');
      if (data.language) setLang(data.language);
    } else {
      setIsBlocked(false);
    }
  }, []);

  useEffect(() => {
    if (user) applyState(user);
  }, [user, applyState]);

  // Poll /auth/me so a block/unblock that happens while the user is online is
  // reflected within a minute (and immediately once fetched).
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      if (!token) return;
      try {
        const res = await fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) applyState(data);
        }
      } catch (e) { /* background poll — ignore */ }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [applyState]);

  const reasonText = blockReason || tr.defaultReason;

  return (
    <>
      <AnimatePresence>
        {isBlocked && (
          <motion.div
            data-testid="blocked-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/95 backdrop-blur-lg"
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              transition={{ type: 'spring', damping: 20 }}
              className="text-center px-6 max-w-md mx-auto"
            >
              <motion.div
                animate={{ scale: [1, 1.05, 1] }}
                transition={{ repeat: Infinity, duration: 2 }}
                className="w-24 h-24 mx-auto mb-8 rounded-full bg-red-500/20 border border-red-500/30 flex items-center justify-center"
              >
                <ShieldX className="w-12 h-12 text-red-500" />
              </motion.div>

              <h1 className="text-3xl font-unbounded font-bold text-red-500 mb-4" data-testid="blocked-title">
                {tr.title}
              </h1>

              <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-6">
                <p className="text-white/80 text-sm mb-2">{tr.reasonLabel}</p>
                <p className="text-white font-medium whitespace-pre-wrap" data-testid="blocked-reason">{reasonText}</p>
              </div>

              <p className="text-white/60 text-sm mb-8">{tr.desc}</p>

              <button
                onClick={() => setSupportOpen(true)}
                data-testid="blocked-open-support-btn"
                className="w-full flex items-center justify-center gap-2 p-3 bg-gradient-to-r from-cyan-500 to-blue-500 hover:opacity-90 rounded-xl text-white font-semibold transition-opacity"
              >
                <MessageCircle className="w-4 h-4" />
                <span>{tr.support}</span>
              </button>

              <button
                onClick={() => {
                  localStorage.removeItem('token');
                  localStorage.removeItem('ton_city_token');
                  window.location.href = '/';
                }}
                data-testid="blocked-logout-btn"
                className="mt-4 inline-flex items-center justify-center gap-2 text-white/50 hover:text-white text-sm transition-colors"
              >
                <LogOut className="w-4 h-4" />
                {tr.logout}
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Support chat opens ABOVE the overlay (z-[10000]) so a blocked user can
          message support from THEIR OWN account — the only action allowed. */}
      {isBlocked && (
        <SupportModal open={supportOpen} onOpenChange={setSupportOpen} language={lang} />
      )}
    </>
  );
}
