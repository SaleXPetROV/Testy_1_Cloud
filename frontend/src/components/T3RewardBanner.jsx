import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { resourceI18n } from '@/lib/translationsExtra';
import './T3RewardBanner.css';

/**
 * T3 Reward notification banner.
 *
 * Behaviour (P0 spec, 2026-01):
 *  - Appears AFTER the user exits tutorial mode.
 *  - Pinned to the top of the screen, mobile-optimised.
 *  - Has a close ("X") button in the top-right corner.
 *  - Uses a shimmering / iridescent "legendary" style.
 *  - Shown only ONCE PER USER FOREVER (persisted via localStorage).
 *  - Dynamically substitutes the actual T3 resource name
 *    (energy / titanium / neuro_core / ...) instead of a static "t3".
 *
 * Trigger source:
 *  - localStorage key "tutorial_reward_banner" stores the resource code
 *    that the user picked (set by TutorialContext when the tutorial
 *    completes with a T3 reward).
 *  - localStorage key "t3_reward_banner_shown_v1" makes sure the banner
 *    is shown only once per browser/user — even if the flag is set
 *    again in the future, it will not re-appear.
 */
const STORAGE_KEY_PENDING = 'tutorial_reward_banner';
const STORAGE_KEY_SHOWN = 't3_reward_banner_shown_v1';

export default function T3RewardBanner() {
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [visible, setVisible] = useState(false);
  const [resourceCode, setResourceCode] = useState('');

  useEffect(() => {
    let pending = null;
    try {
      // P0: read from localStorage (persistent) AND fall back to legacy
      // sessionStorage value so users mid-tutorial don't lose their banner.
      pending =
        window.localStorage.getItem(STORAGE_KEY_PENDING) ||
        window.sessionStorage.getItem(STORAGE_KEY_PENDING);
    } catch (e) {
      pending = null;
    }
    if (!pending) return;

    let alreadyShown = false;
    try {
      alreadyShown = window.localStorage.getItem(STORAGE_KEY_SHOWN) === '1';
    } catch (e) {
      alreadyShown = false;
    }
    if (alreadyShown) {
      try { window.localStorage.removeItem(STORAGE_KEY_PENDING); } catch (e) { /* noop */ }
      try { window.sessionStorage.removeItem(STORAGE_KEY_PENDING); } catch (e) { /* noop */ }
      return;
    }
    setResourceCode(pending);
    setVisible(true);
  }, []);

  const handleClose = () => {
    setVisible(false);
    try { window.localStorage.removeItem(STORAGE_KEY_PENDING); } catch (e) { /* noop */ }
    try { window.sessionStorage.removeItem(STORAGE_KEY_PENDING); } catch (e) { /* noop */ }
    try { window.localStorage.setItem(STORAGE_KEY_SHOWN, '1'); } catch (e) { /* noop */ }
  };

  if (!visible) return null;

  // Resolve a human-readable, localised resource name.
  // Falls back to the raw code if no translation is found.
  const resourceName =
    (resourceCode && resourceI18n[resourceCode]?.[lang]) ||
    (resourceCode && resourceI18n[resourceCode]?.en) ||
    resourceCode ||
    '';

  // Defensive: if we somehow have no resource name, never render the banner
  // — otherwise we'd display raw "{resource}" to the user.
  if (!resourceName) return null;

  const message = (t('t3RewardNoticeText') || '').replace('{resource}', resourceName);

  return (
    <div
      className="t3-reward-banner"
      role="status"
      aria-live="polite"
      data-testid="t3-reward-banner"
    >
      <div className="t3-reward-banner__inner">
        <div className="t3-reward-banner__shimmer" aria-hidden="true" />
        <div className="t3-reward-banner__content">
          <span className="t3-reward-banner__icon" aria-hidden="true">★</span>
          <span
            className="t3-reward-banner__text"
            data-testid="t3-reward-banner-text"
            data-resource={resourceCode}
          >
            {message}
          </span>
        </div>
        <button
          type="button"
          onClick={handleClose}
          className="t3-reward-banner__close"
          aria-label={t('close')}
          data-testid="t3-reward-banner-close"
        >
          <X size={18} strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}
