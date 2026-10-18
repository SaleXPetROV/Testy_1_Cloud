/**
 * CityBackground — the island's isometric grid with resource pulses flowing on it.
 *
 * The map of GRAM City is an isometric diamond grid where businesses move
 * resources around; the background echoes that: a faint static lattice and a
 * few glowing pulses travelling along its diagonals, like goods between
 * businesses. Styles: src/styles/cityBackground.css.
 *
 * Kept light on purpose: ~8 tiny elements animating transform/opacity only,
 * paused when the tab is hidden, static on reduced-motion and weak devices.
 */
import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import '@/styles/cityBackground.css';

const CYAN = '#00F0FF';
const PURPLE = '#9B5CFF';   // neon-purple lifted a little so it reads on #030304
const TON = '#0098EA';

// x/y = start, a = travel angle (±30° = isometric axes), d = distance,
// dur/delay in seconds. Fixed list -> identical on every render, no RNG.
const PULSES = [
  { x: '8%',  y: '22%', a: '30deg',   d: '46vw', dur: 22, delay: 0,  c: CYAN },
  { x: '62%', y: '78%', a: '-30deg',  d: '38vw', dur: 26, delay: 4,  c: PURPLE },
  { x: '30%', y: '58%', a: '-30deg',  d: '42vw', dur: 24, delay: 9,  c: TON },
  { x: '78%', y: '18%', a: '150deg',  d: '40vw', dur: 28, delay: 2,  c: CYAN },
  { x: '14%', y: '84%', a: '-30deg',  d: '50vw', dur: 30, delay: 13, c: CYAN },
  { x: '88%', y: '60%', a: '-150deg', d: '44vw', dur: 25, delay: 7,  c: PURPLE },
  { x: '45%', y: '12%', a: '30deg',   d: '36vw', dur: 21, delay: 16, c: TON },
  { x: '54%', y: '40%', a: '150deg',  d: '34vw', dur: 27, delay: 11, c: CYAN },
];

function isWeakDevice() {
  try {
    const conn = navigator.connection || {};
    if (conn.saveData) return true;
    // only truly minimal devices: the pulses are a few tiny compositor layers,
    // and many ordinary phones report 2 cores
    if (typeof navigator.hardwareConcurrency === 'number' && navigator.hardwareConcurrency <= 1) return true;
    if (typeof navigator.deviceMemory === 'number' && navigator.deviceMemory < 1) return true;
  } catch { /* ignore */ }
  return false;
}

// Pages with a lot of text / lists: the background is blurred and veiled so
// it stays alive but never competes with the content. Businesses keep it sharp.
const SOFT_PAGES = /^\/(resources|trading|community|chat|marketplace|city-pass)(\/|$)/;

/** The living background itself — no router needed (used by the preloader too). */
export function CityBackdrop({ soft = false }) {
  const [paused, setPaused] = useState(() => typeof document !== 'undefined' && document.hidden);
  const [weak] = useState(isWeakDevice);

  useEffect(() => {
    const onVis = () => setPaused(document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  const cls = ['city-bg', paused && 'city-bg--paused', weak && 'city-bg--static', soft && 'city-bg--soft'].filter(Boolean).join(' ');

  return (
    <div className={cls} aria-hidden="true" data-testid="city-background">
      <div className="city-bg__grid" />
      <div className="city-bg__glow" />
      {!weak && PULSES.map((p, i) => (
        <span
          key={i}
          className="city-bg__pulse"
          style={{
            '--x': p.x, '--y': p.y, '--a': p.a, '--d': p.d, '--c': p.c,
            '--dur': `${p.dur}s`, '--delay': `${p.delay}s`,
          }}
        />
      ))}
    </div>
  );
}

/** Page background: softer on the busy pages (depends on the route). */
export default function CityBackground() {
  const { pathname } = useLocation();
  return <CityBackdrop soft={SOFT_PAGES.test(pathname || '')} />;
}
