/**
 * A chest flies onto the screen after a game. Chests are opened by the server at once (they are never left
 * closed), so it opens by itself: it flies in, shakes, bursts — and the rewards appear with their PICTURES:
 * the resource itself, or the very puzzle piece that dropped. «Забрать» → the next chest.
 */
import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { fill } from '@/lib/translationsMore';
import { getResource } from '@/lib/resourceConfig';
import { imgUrl, nm } from '@/components/minigames/mgShared';

function RewardCard({ x, lang, t, i }) {
  const isPiece = x.kind === 'puzzle';
  const res = !isPiece ? getResource(x.resource, lang) : null;
  return (
    <motion.div initial={{ opacity: 0, y: 30, scale: 0.6 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ delay: 0.15 + i * 0.18, type: 'spring', stiffness: 260, damping: 18 }}
      className={`relative w-32 rounded-2xl border p-2 text-center ${isPiece ? 'border-fuchsia-400/60 bg-fuchsia-500/15' : 'border-amber-300/50 bg-amber-400/10'}`}
      data-testid="chest-reward">
      <div className="h-24 flex items-center justify-center">
        {x.image_url
          ? <img src={imgUrl(x.image_url)} alt="" className={`max-h-24 max-w-full object-contain ${isPiece ? 'rounded-lg border border-white/20' : ''}`} />
          : <span className="text-5xl">{isPiece ? '🧩' : res?.icon}</span>}
      </div>
      <div className="text-[11px] text-white/85 leading-tight mt-1 min-h-[28px]">{isPiece ? (nm(x, lang) || '') : res?.name}</div>
      <div className={`text-sm font-black ${isPiece ? 'text-fuchsia-200' : 'text-emerald-300'}`}>
        {isPiece ? fill(t('ch_piece_short'), { n: x.have }) : `+${Number(x.amount).toLocaleString('ru-RU')}`}
      </div>
    </motion.div>
  );
}

export default function ChestReveal({ chests, lang, t, onClose }) {
  const [i, setI] = useState(0);
  const [phase, setPhase] = useState('idle');          // idle (flies in) → opening (shakes) → opened
  const chest = chests[i];
  const result = chest ? { results: chest.results || [] } : null;

  // opens by itself: fly in → shake → burst
  useEffect(() => {
    if (!chest) return undefined;
    setPhase('idle');
    const a = setTimeout(() => setPhase('opening'), 900);
    const b = setTimeout(() => setPhase('opened'), 1750);
    return () => { clearTimeout(a); clearTimeout(b); };
  }, [i, chest]);
  if (!chest) return null;

  const open = () => { if (phase === 'idle') setPhase('opening'); };   // a tap only speeds it up
  const next = () => {
    if (i + 1 < chests.length) setI(i + 1);
    else onClose(true);
  };

  return (
    <div className="fixed inset-0 z-[95] bg-black/80 backdrop-blur-sm flex flex-col items-center justify-center px-4" data-testid="chest-reveal">
      <AnimatePresence mode="wait">
        {phase !== 'opened' ? (
          <motion.div key={`c${i}`} className="flex flex-col items-center gap-4"
            initial={{ y: -420, scale: 0.3, rotate: -25, opacity: 0 }} animate={{ y: 0, scale: 1, rotate: 0, opacity: 1 }}
            exit={{ scale: 1.6, opacity: 0 }} transition={{ type: 'spring', stiffness: 140, damping: 14 }}>
            <div className="text-amber-200 font-unbounded text-xl font-bold">{t('ch_new')}</div>
            <button type="button" onClick={open} className="relative focus:outline-none" data-testid="chest-reveal-open" aria-label={t('ch_open')}>
              <span className="absolute inset-0 -m-8 rounded-full bg-amber-400/25 blur-2xl animate-pulse" />
              <motion.div animate={phase === 'opening' ? { rotate: [0, -10, 10, -12, 12, -6, 6, 0], scale: [1, 1.05, 1.08, 1.1, 1.12, 1.15, 1.2, 1.25] }
                : { y: [0, -8, 0] }}
                transition={phase === 'opening' ? { duration: 0.85 } : { repeat: Infinity, duration: 1.6, ease: 'easeInOut' }}
                className="relative w-44 h-44 flex items-center justify-center">
                {chest.image_url ? <img src={imgUrl(chest.image_url)} alt="" className="w-full h-full object-contain" /> : <span className="text-[120px] leading-none">🎁</span>}
              </motion.div>
            </button>
            <div className="text-sm text-white/80">{nm(chest, lang)}</div>
            {chests.length > 1 && <div className="text-[11px] text-white/40">{i + 1} / {chests.length}</div>}
          </motion.div>
        ) : (
          <motion.div key={`r${i}`} className="flex flex-col items-center gap-4 w-full max-w-sm"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div initial={{ scale: 0.2, opacity: 1 }} animate={{ scale: 3, opacity: 0 }} transition={{ duration: 0.6 }}
              className="absolute w-40 h-40 rounded-full bg-amber-300/60 blur-xl pointer-events-none" />
            <div className="text-amber-200 font-unbounded text-lg font-bold">✨ {t('ch_got')}</div>
            <div className="flex flex-wrap justify-center gap-3">
              {(result?.results || []).length === 0 && <div className="text-sm text-white/70">{t('ch_empty_result')}</div>}
              {(result?.results || []).map((x, k) => <RewardCard key={k} x={x} lang={lang} t={t} i={k} />)}
            </div>
            <button type="button" onClick={next} data-testid="chest-reveal-take"
              className="mt-2 w-full h-12 rounded-xl bg-gradient-to-r from-amber-400 to-orange-500 text-black font-black">
              {i + 1 < chests.length ? t('ch_next') : t('ch_take')}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
