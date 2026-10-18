import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Map, Package, Building2, Scale, MessagesSquare } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { hapticSelection } from '@/lib/telegramHaptic';
import { showDevNotice } from '@/lib/devNotice';

const LABELS = {
  map:       { ru: 'Карта',    en: 'Map',       es: 'Mapa',     zh: '地图',   fr: 'Carte',    de: 'Karte',    ja: 'マップ',   ko: '지도',     id: 'Peta' },
  resources: { ru: 'Ресурсы',  en: 'Resources', es: 'Recursos', zh: '资源',   fr: 'Ressources', de: 'Ressourcen', ja: 'リソース', ko: '자원',   id: 'Sumber' },
  business:  { ru: 'Бизнесы',  en: 'Business',  es: 'Negocios', zh: '企业',   fr: 'Business', de: 'Business', ja: 'ビジネス', ko: '비즈니스', id: 'Bisnis' },
  trading:   { ru: 'Торговля', en: 'Trading',   es: 'Comercio', zh: '交易',   fr: 'Trading',  de: 'Handel',   ja: '取引',     ko: '거래',     id: 'Dagang' },
  chat:      { ru: 'Общение',  en: 'Chat',      es: 'Chat',     zh: '交流',   fr: 'Discussion', de: 'Chat',   ja: 'チャット', ko: '소통',     id: 'Obrolan' },
};

const HIDDEN_PREFIXES = ['/auth', '/tutorial', '/forgot-password'];

export default function BottomNav({ user }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const L = (key) => LABELS[key][lang] || LABELS[key].ru;
  const navRef = useRef(null);

  // --bottom-nav-h = the REAL space the floating bar takes from the bottom edge (bar + gap + iOS home indicator),
  // so sheets / modals put their buttons above it on every device (was a fixed 46px: hidden on iOS).
  useEffect(() => {
    const el = navRef.current;
    const root = document.documentElement;
    if (!el) { root.style.setProperty('--bottom-nav-h', '0px'); return undefined; }
    const measure = () => {
      const r = el.getBoundingClientRect();
      const h = Math.max(0, Math.round(window.innerHeight - r.top));
      if (h > 0 && h < 240) root.style.setProperty('--bottom-nav-h', `${h}px`);
    };
    measure();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    ro && ro.observe(el);
    window.addEventListener('resize', measure);
    return () => { ro && ro.disconnect(); window.removeEventListener('resize', measure); root.style.removeProperty('--bottom-nav-h'); };
  });

  const path = location.pathname;
  if (!user) return null;
  if (path === '/') return null;
  if (HIDDEN_PREFIXES.some((p) => path.startsWith(p))) return null;

  const items = [
    { key: 'map',       icon: Map,           to: '/maps',          active: path === '/maps' || path === '/map' },
    { key: 'resources', icon: Package,       to: '/resources',     active: path === '/resources' },
    { key: 'business',  icon: Building2,     to: '/my-businesses', active: path === '/my-businesses', center: true },
    { key: 'trading',   icon: Scale,         to: '/trading',       active: path === '/trading' },
    { key: 'chat',      icon: MessagesSquare, to: '/community',    active: path === '/community' || path === '/chat' },
  ];

  const go = (it) => {
    hapticSelection();
    if (it.disabled || !it.to) { showDevNotice(lang); return; }
    navigate(it.to);
  };

  return (
    <nav
      className="lg:hidden fixed left-0 right-0 z-[70] flex justify-center pointer-events-none"
      style={{ bottom: 'calc(env(safe-area-inset-bottom, 0px) + 10px)' }}
      data-testid="bottom-nav"
      ref={navRef}
    >
      <div className="pointer-events-auto flex items-center justify-between gap-0.5 px-2 py-[3px] rounded-[18px] bg-[#12121c]/90 backdrop-blur-2xl border border-white/10 shadow-2xl shadow-black/50 w-[min(94vw,440px)]">
        {items.map((it) => {
          const Icon = it.icon;
          const active = it.active;
          return (
            <button
              key={it.key}
              onClick={() => go(it)}
              data-testid={`bottom-nav-${it.key}`}
              aria-current={active ? 'page' : undefined}
              aria-disabled={it.disabled || undefined}
              className={`relative flex-1 flex flex-col items-center justify-center gap-0.5 py-0.5 min-w-0 ${it.disabled ? 'opacity-40' : ''}`}
            >
              <div className="relative flex items-center justify-center">
                {active && (
                  <motion.span
                    layoutId="bottom-nav-highlight"
                    transition={{ type: 'spring', stiffness: 420, damping: 32 }}
                    className={`absolute rounded-xl ${it.center ? 'w-8 h-8' : 'w-7 h-7'} bg-cyber-cyan/20 border border-cyber-cyan/40 shadow-lg shadow-cyber-cyan/20`}
                  />
                )}
                <motion.div
                  animate={{ scale: active ? 1.08 : 1 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 26 }}
                  className={`relative flex items-center justify-center rounded-xl transition-colors duration-300
                    ${it.center ? 'w-8 h-8' : 'w-7 h-7'}
                    ${it.center && !active ? 'bg-gradient-to-br from-cyber-cyan to-neon-purple shadow-md shadow-cyber-cyan/30' : ''}`}
                >
                  <Icon
                    className={`transition-colors duration-300 ${it.center ? 'w-[18px] h-[18px]' : 'w-4 h-4'} ${
                      active ? 'text-cyber-cyan' : it.center ? 'text-black' : 'text-white/55'
                    }`}
                  />
                </motion.div>
              </div>
              <span
                className={`text-[8px] leading-none font-semibold tracking-wide truncate max-w-full transition-colors duration-300 ${
                  active ? 'text-cyber-cyan' : 'text-white/50'
                }`}
              >
                {L(it.key)}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
