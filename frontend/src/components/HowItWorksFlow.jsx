/**
 * HowItWorksFlow — visual flow that shows the core gameplay loop.
 * Cycle (continuous): buy resources → produce → sell → earn TON → upgrade
 * NOTE: "buy business" sits at the very entry point of the cycle and is rendered
 * separately as the cycle's seed, NOT inside the looping arrows (per UX spec —
 * user shouldn't be told to "re-buy business" on each cycle).
 *
 * v2.2.1: removed the "↻ Cycle repeats" badges (per UX request) and added
 * hover-driven interactivity — hovering a node grows its icon, brightens the
 * ring/halo and the adjacent arrows glow.
 */
import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Building2, ShoppingCart, Cog, Coins, Gem, TrendingUp, ArrowRight, ArrowDown,
} from 'lucide-react';
import { useTranslation } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';

const STEP_COLORS = [
  { ring: 'ring-amber-500/30',    bg: 'bg-amber-500/10',    fg: 'text-amber-300',
    hoverRing: 'ring-amber-400/80', hoverBg: 'bg-amber-500/25',   glow: 'shadow-amber-500/40'   },
  { ring: 'ring-cyan-500/30',     bg: 'bg-cyan-500/10',     fg: 'text-cyan-300',
    hoverRing: 'ring-cyan-400/80', hoverBg: 'bg-cyan-500/25',   glow: 'shadow-cyan-500/40'   },
  { ring: 'ring-purple-500/30',   bg: 'bg-purple-500/10',   fg: 'text-purple-300',
    hoverRing: 'ring-purple-400/80', hoverBg: 'bg-purple-500/25', glow: 'shadow-purple-500/40' },
  { ring: 'ring-emerald-500/30',  bg: 'bg-emerald-500/10',  fg: 'text-emerald-300',
    hoverRing: 'ring-emerald-400/80', hoverBg: 'bg-emerald-500/25', glow: 'shadow-emerald-500/40' },
  { ring: 'ring-yellow-500/30',   bg: 'bg-yellow-500/10',   fg: 'text-yellow-300',
    hoverRing: 'ring-yellow-400/80', hoverBg: 'bg-yellow-500/25', glow: 'shadow-yellow-500/40' },
  { ring: 'ring-pink-500/30',     bg: 'bg-pink-500/10',     fg: 'text-pink-300',
    hoverRing: 'ring-pink-400/80', hoverBg: 'bg-pink-500/25',   glow: 'shadow-pink-500/40'   },
];

function FlowNode({ Icon, title, desc, color, delay, testid, spin = false, isActive, onEnter, onLeave }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9, y: 16 }}
      whileInView={{ opacity: 1, scale: 1, y: 0 }}
      viewport={{ once: true, amount: 0.4 }}
      transition={{ duration: 0.45, delay }}
      whileHover={{ y: -6 }}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      onTouchStart={onEnter}
      className="relative flex flex-col items-center text-center w-[150px] sm:w-[160px] flex-shrink-0 cursor-pointer select-none"
      data-testid={testid}
    >
      <div
        className={[
          'relative w-16 h-16 sm:w-20 sm:h-20 rounded-2xl ring-2 mb-3 backdrop-blur-sm',
          'flex items-center justify-center shadow-lg shadow-black/40',
          'transition-all duration-300 ease-out',
          isActive ? `${color.hoverBg} ${color.hoverRing} ${color.glow} shadow-xl scale-110` : `${color.bg} ${color.ring}`,
        ].join(' ')}
        style={{ willChange: 'transform' }}
      >
        {/* soft pulsing halo while hovered */}
        {isActive && (
          <span
            className={`absolute inset-0 rounded-2xl ${color.hoverBg} animate-ping opacity-40 pointer-events-none`}
            aria-hidden
          />
        )}
        <Icon
          className={[
            'relative z-[1] transition-transform duration-300',
            isActive ? 'w-9 h-9 sm:w-11 sm:h-11' : 'w-7 h-7 sm:w-9 sm:h-9',
            color.fg,
            spin ? 'animate-spin-slow' : '',
          ].join(' ')}
          aria-hidden
        />
      </div>
      <div
        className={[
          'font-bold text-[12px] sm:text-[13px] uppercase tracking-wider leading-tight mb-1 transition-colors duration-300',
          isActive ? 'text-white' : 'text-white/90',
        ].join(' ')}
      >
        {title}
      </div>
      <div
        className={[
          'text-[10px] sm:text-[11px] leading-snug px-1 transition-colors duration-300',
          isActive ? 'text-white/85' : 'text-text-muted',
        ].join(' ')}
      >
        {desc}
      </div>
    </motion.div>
  );
}

function ArrowH({ delay, active = false }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      whileInView={{ opacity: 1, x: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.4, delay }}
      className={[
        'flex-shrink-0 flex items-center justify-center mt-[-16px] sm:mt-[-20px] transition-all duration-300',
        active ? 'text-cyber-cyan drop-shadow-[0_0_8px_rgba(34,211,238,0.7)] scale-125' : 'text-cyber-cyan/70',
      ].join(' ')}
      aria-hidden
    >
      <ArrowRight className="w-5 h-5 sm:w-6 sm:h-6" />
    </motion.div>
  );
}

function ArrowV({ delay, active = false }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.4, delay }}
      className={[
        'flex items-center justify-center my-1 transition-all duration-300',
        active ? 'text-cyber-cyan drop-shadow-[0_0_8px_rgba(34,211,238,0.7)] scale-125' : 'text-cyber-cyan/70',
      ].join(' ')}
      aria-hidden
    >
      <ArrowDown className="w-5 h-5" />
    </motion.div>
  );
}

export default function HowItWorksFlow() {
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  // -1 = none. 0 = Buy Business (seed). 1..5 = loop steps.
  const [activeIdx, setActiveIdx] = useState(-1);

  // The 5 looping steps. "Buy business" is rendered separately as the seed.
  const loop = [
    { Icon: ShoppingCart, title: t('flowStepBuyResources') || 'Закупка ресурсов',
      desc: t('flowStepBuyResourcesDesc') || 'Купите сырьё, нужное вашему бизнесу для работы.' },
    { Icon: Cog,          title: t('flowStepProduce') || 'Производство',
      desc: t('flowStepProduceDesc') || 'Бизнес перерабатывает ресурсы в готовый товар.', spin: true },
    { Icon: Coins,        title: t('flowStepSell') || 'Продажа',
      desc: t('flowStepSellDesc') || 'Выставляете товар на биржу или закрываете тендеры.' },
    { Icon: Gem,          title: t('flowStepEarnTon') || 'Получение TON',
      desc: t('flowStepEarnTonDesc') || 'Доход в реальной криптовалюте поступает на ваш баланс.' },
    { Icon: TrendingUp,   title: t('flowStepUpgrade') || 'Прокачка бизнеса',
      desc: t('flowStepUpgradeDesc') || 'Повышаете уровень — производство и прибыль растут.' },
  ];

  // Arrow at position k (between node k and k+1) is "active" when the
  // hovered node is at index k or k+1 — gives a satisfying glow on both
  // sides of the focused step.
  const arrowActive = (k) => activeIdx === k || activeIdx === k + 1;

  return (
    <div className="max-w-6xl mx-auto" data-testid="how-it-works-flow" onMouseLeave={() => setActiveIdx(-1)}>
      {/* Desktop: horizontal row */}
      <div className="hidden lg:block">
        <div className="flex items-start justify-center gap-1 px-2 flex-wrap">
          {/* Seed step — Buy Business — sits outside the loop */}
          <FlowNode
            Icon={Building2}
            title={t('flowStepBuyBusiness') || 'Покупка бизнеса'}
            desc={t('flowStepBuyBusinessDesc') || 'Стартовая инвестиция — покупка участка с бизнесом.'}
            color={STEP_COLORS[0]}
            delay={0}
            testid="flow-node-buy-business"
            isActive={activeIdx === 0}
            onEnter={() => setActiveIdx(0)}
            onLeave={() => setActiveIdx(-1)}
          />
          <ArrowH delay={0.1} active={arrowActive(0)} />
          {loop.flatMap((s, i) => {
            const nodeIdx = i + 1;
            const nodes = [
              <FlowNode
                key={`n-${i}`}
                Icon={s.Icon}
                title={s.title}
                desc={s.desc}
                color={STEP_COLORS[(i + 1) % STEP_COLORS.length]}
                spin={s.spin}
                delay={0.15 + i * 0.1}
                testid={`flow-node-${i}`}
                isActive={activeIdx === nodeIdx}
                onEnter={() => setActiveIdx(nodeIdx)}
                onLeave={() => setActiveIdx(-1)}
              />,
            ];
            if (i < loop.length - 1) {
              nodes.push(<ArrowH key={`a-${i}`} delay={0.2 + i * 0.1} active={arrowActive(nodeIdx)} />);
            }
            return nodes;
          })}
        </div>
      </div>

      {/* Mobile: vertical stack with arrows */}
      <div className="lg:hidden flex flex-col items-center gap-2">
        <FlowNode
          Icon={Building2}
          title={t('flowStepBuyBusiness') || 'Покупка бизнеса'}
          desc={t('flowStepBuyBusinessDesc') || 'Стартовая инвестиция — покупка участка с бизнесом.'}
          color={STEP_COLORS[0]}
          delay={0}
          testid="flow-node-buy-business-m"
          isActive={activeIdx === 0}
          onEnter={() => setActiveIdx(0)}
          onLeave={() => setActiveIdx(-1)}
        />
        <ArrowV delay={0.1} active={arrowActive(0)} />
        {loop.map((s, i) => {
          const nodeIdx = i + 1;
          return (
            <div key={i} className="flex flex-col items-center gap-1">
              <FlowNode
                Icon={s.Icon}
                title={s.title}
                desc={s.desc}
                color={STEP_COLORS[(i + 1) % STEP_COLORS.length]}
                spin={s.spin}
                delay={0.15 + i * 0.08}
                testid={`flow-node-m-${i}`}
                isActive={activeIdx === nodeIdx}
                onEnter={() => setActiveIdx(nodeIdx)}
                onLeave={() => setActiveIdx(-1)}
              />
              {i < loop.length - 1 && <ArrowV delay={0.2 + i * 0.08} active={arrowActive(nodeIdx)} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
