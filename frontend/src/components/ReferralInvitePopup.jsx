import React, { useEffect, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Share2, Copy, Users, Sparkles } from 'lucide-react';
import { toast } from '@/components/ui/sonner';
import { useLanguage } from '@/context/LanguageContext';
import './ReferralInvitePopup.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const STORAGE_FLAG = 'pending_referral_invite';

// Локализация уведомления. Держим здесь, чтобы не редактировать
// огромный общий словарь. Ключи ограничены необходимым минимумом.
const I18N = {
  en: {
    title: 'Build your empire together!',
    messageBefore:
      'Invite your friends to Gram City with your personal link and collect ',
    messageHighlight: '5%',
    messageAfter:
      ' of their income to your balance! Building cities together is way more profitable.',
    yourLink: 'Your referral link',
    share: 'Share',
    copy: 'Copy link',
    copied: 'Link copied!',
    close: 'Close',
    shareText: 'Join me in Gram City — build your empire!',
  },
  ru: {
    title: 'Стройте империю вместе!',
    messageBefore:
      'Приглашайте друзей в Gram City по своей персональной ссылке и забирайте ',
    messageHighlight: '5%',
    messageAfter:
      ' от их дохода себе на баланс! Развивать города вместе — в разы выгоднее.',
    yourLink: 'Твоя реферальная ссылка',
    share: 'Поделиться',
    copy: 'Скопировать',
    copied: 'Ссылка скопирована!',
    close: 'Закрыть',
    shareText: 'Присоединяйся ко мне в Gram City — построй свою империю!',
  },
  es: {
    title: '¡Construye tu imperio juntos!',
    messageBefore:
      'Invita a tus amigos a Gram City con tu enlace personal y recibe el ',
    messageHighlight: '5%',
    messageAfter:
      ' de sus ingresos en tu saldo. ¡Desarrollar ciudades juntos es mucho más rentable!',
    yourLink: 'Tu enlace de referido',
    share: 'Compartir',
    copy: 'Copiar enlace',
    copied: '¡Enlace copiado!',
    close: 'Cerrar',
    shareText: '¡Únete a mí en Gram City — construye tu imperio!',
  },
  zh: {
    title: '一起建立你的帝国！',
    messageBefore:
      '通过你的专属链接邀请朋友加入 Gram City，把他们收入的 ',
    messageHighlight: '5%',
    messageAfter:
      ' 收入你的账户。一起发展城市，收益翻倍！',
    yourLink: '你的推荐链接',
    share: '分享',
    copy: '复制链接',
    copied: '链接已复制！',
    close: '关闭',
    shareText: '加入我一起玩 Gram City — 建立你的帝国！',
  },
  fr: {
    title: 'Bâtis ton empire ensemble !',
    messageBefore:
      'Invite tes amis sur Gram City avec ton lien personnel et récolte ',
    messageHighlight: '5 %',
    messageAfter:
      ' de leurs revenus sur ton solde ! Développer des villes ensemble est bien plus rentable.',
    yourLink: 'Ton lien de parrainage',
    share: 'Partager',
    copy: 'Copier le lien',
    copied: 'Lien copié !',
    close: 'Fermer',
    shareText: 'Rejoins-moi sur Gram City — bâtis ton empire !',
  },
  de: {
    title: 'Baut euer Imperium gemeinsam!',
    messageBefore:
      'Lade deine Freunde mit deinem persönlichen Link zu Gram City ein und erhalte ',
    messageHighlight: '5 %',
    messageAfter:
      ' ihres Einkommens auf dein Guthaben! Städte gemeinsam aufzubauen ist um ein Vielfaches lohnender.',
    yourLink: 'Dein Empfehlungslink',
    share: 'Teilen',
    copy: 'Link kopieren',
    copied: 'Link kopiert!',
    close: 'Schließen',
    shareText: 'Komm mit mir zu Gram City — bau dein Imperium!',
  },
  ja: {
    title: '一緒に帝国を築こう！',
    messageBefore:
      '自分専用リンクで Gram City に友達を招待して、彼らの収入の ',
    messageHighlight: '5%',
    messageAfter:
      ' をあなたの残高にゲット！一緒に街を育てるほうが何倍もお得。',
    yourLink: 'あなたの紹介リンク',
    share: 'シェア',
    copy: 'リンクをコピー',
    copied: 'リンクをコピーしました！',
    close: '閉じる',
    shareText: 'Gram City で一緒に帝国を築こう！',
  },
  ko: {
    title: '함께 제국을 만들어보자!',
    messageBefore:
      '나만의 링크로 친구를 Gram City에 초대하고 그들 수입의 ',
    messageHighlight: '5%',
    messageAfter:
      '를 잔액으로 받아가세요! 함께 도시를 키우면 수익이 몇 배!',
    yourLink: '나의 초대 링크',
    share: '공유',
    copy: '링크 복사',
    copied: '링크가 복사되었습니다!',
    close: '닫기',
    shareText: 'Gram City에 함께 참여해서 제국을 만들어봐!',
  },
};

function getStrings(lang) {
  return I18N[lang] || I18N.en;
}

export default function ReferralInvitePopup({ user }) {
  const { language: lang } = useLanguage();
  const [visible, setVisible] = useState(false);
  const [referralLink, setReferralLink] = useState('');

  const strings = getStrings(lang);

  const hasPendingFlag = () => {
    try {
      return window.localStorage.getItem(STORAGE_FLAG) === '1';
    } catch {
      return false;
    }
  };

  const clearFlag = () => {
    try { window.localStorage.removeItem(STORAGE_FLAG); } catch { /* noop */ }
  };

  // Fetch referral link from backend (fallback to /?ref=user.id if API fails)
  const fetchReferralLink = useCallback(async () => {
    const token = (() => { try { return localStorage.getItem('token'); } catch { return null; } })();
    if (!token) return '';
    try {
      const res = await fetch(`${API}/referrals/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        const path = data.referral_path || (data.referral_id ? `/?ref=${data.referral_id}` : '');
        if (path) return `${window.location.origin}${path}`;
      }
    } catch { /* fall through */ }
    if (user?.id) return `${window.location.origin}/?ref=${user.id}`;
    return '';
  }, [user?.id]);

  const openPopup = useCallback(async () => {
    // Only when the user is authenticated
    let token = null;
    try { token = localStorage.getItem('token'); } catch { /* noop */ }
    if (!token) return;

    // v2.3.x: if the user hasn't completed the tutorial yet, defer the
    // referral popup so we don't overlap with the TutorialStartModal on
    // first login. In that case the popup will be re-triggered by
    // TutorialContext right after tutorial finish/skip (T3 reward path).
    try {
      const statusRes = await fetch(`${API}/tutorial/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (statusRes.ok) {
        const status = await statusRes.json();
        if (!status.completed) {
          // Leave the flag intact — do NOT show yet; wait for tutorial
          // finish/skip to re-trigger via the `referral-invite-show` event.
          return;
        }
      }
    } catch { /* best-effort — fall through to show */ }

    const link = await fetchReferralLink();
    if (!link) return;
    setReferralLink(link);
    setVisible(true);
    // Flag is one-shot — remove immediately so navigation/re-mount doesn't loop.
    clearFlag();
  }, [fetchReferralLink]);

  // Show on mount if the pending flag is set (e.g. after login redirect
  // to /ton-island or after tutorial completion).
  useEffect(() => {
    if (hasPendingFlag()) {
      // Slight delay so T3 reward banner mounts first — the invite popup
      // then overlays on top with a smooth entry.
      const t = setTimeout(() => { openPopup(); }, 500);
      return () => clearTimeout(t);
    }
  }, [openPopup]);

  // Listen for a global event so contexts (TutorialContext, etc.) can also
  // trigger the popup instantly without a page reload.
  useEffect(() => {
    const handler = () => { openPopup(); };
    window.addEventListener('referral-invite-show', handler);
    return () => window.removeEventListener('referral-invite-show', handler);
  }, [openPopup]);

  const handleShare = async () => {
    if (!referralLink) return;
    // Native share (mobile + supported desktop browsers)
    if (navigator.share) {
      try {
        await navigator.share({
          title: 'GRAM City',
          text: strings.shareText,
          url: referralLink,
        });
        return;
      } catch (e) {
        // User cancelled or share not available — fall back to copy below
        if (e?.name === 'AbortError') return;
      }
    }
    // Fallback: copy to clipboard
    try {
      await navigator.clipboard.writeText(referralLink);
      toast.success(strings.copied);
    } catch {
      // Very old browsers: legacy fallback
      try {
        const el = document.createElement('textarea');
        el.value = referralLink;
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        toast.success(strings.copied);
      } catch { /* silent */ }
    }
  };

  const handleCopy = async () => {
    if (!referralLink) return;
    try {
      await navigator.clipboard.writeText(referralLink);
      toast.success(strings.copied);
    } catch { /* silent */ }
  };

  const handleClose = () => {
    setVisible(false);
    clearFlag();
  };

  if (!visible) return null;

  const popupNode = (
    <div
      className="referral-invite-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="referral-invite-title"
      data-testid="referral-invite-overlay"
      onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
    >
      <div className="referral-invite-legendary" data-testid="referral-invite-popup">
        <div className="referral-invite-inner">
          <button
            type="button"
            className="referral-invite-close"
            onClick={handleClose}
            aria-label={strings.close}
            data-testid="referral-invite-close"
          >
            <X size={18} strokeWidth={2.5} />
          </button>

          <div className="referral-invite-icon" aria-hidden="true">
            <Users size={26} strokeWidth={2} />
            <Sparkles className="referral-invite-icon-sparkle" size={14} />
          </div>

          <h3
            id="referral-invite-title"
            className="referral-invite-title"
            data-testid="referral-invite-title"
          >
            {strings.title}
          </h3>

          <p
            className="referral-invite-message"
            data-testid="referral-invite-message"
          >
            {strings.messageBefore}
            <strong
              className="referral-invite-highlight"
              data-testid="referral-invite-highlight"
            >
              {strings.messageHighlight}
            </strong>
            {strings.messageAfter}
          </p>

          <div className="referral-invite-link-row">
            <div className="referral-invite-link-label">
              {strings.yourLink}
            </div>
            <div className="referral-invite-link-box">
              <input
                type="text"
                readOnly
                value={referralLink}
                className="referral-invite-link-input"
                data-testid="referral-invite-link"
                onFocus={(e) => e.target.select()}
              />
              <button
                type="button"
                className="referral-invite-copy-btn"
                onClick={handleCopy}
                aria-label={strings.copy}
                data-testid="referral-invite-copy-btn"
              >
                <Copy size={16} strokeWidth={2} />
              </button>
            </div>
          </div>

          <button
            type="button"
            className="referral-invite-share-btn"
            onClick={handleShare}
            data-testid="referral-invite-share-btn"
          >
            <Share2 size={16} strokeWidth={2.5} />
            <span>{strings.share}</span>
          </button>
        </div>
      </div>
    </div>
  );

  // Portal to document.body so we escape any ancestor stacking context
  // (e.g. transformed game canvas containers) and float above Radix
  // dialogs (tutorial-start-modal at z-50) reliably.
  if (typeof document === 'undefined') return null;
  return createPortal(popupNode, document.body);
}
