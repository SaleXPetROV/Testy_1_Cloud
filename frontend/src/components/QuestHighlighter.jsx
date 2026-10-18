/**
 * QuestHighlighter — after the player taps «Перейти» on a quest, the screen it
 * opens scrolls the button that does the job into view and pulses it in gold
 * for a few seconds. The quest passes its event in the URL: ?quest_hl=<event>.
 */
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

// quest event -> buttons that fulfil it (first one found on the page wins)
const TARGETS = {
  shift_start: ['[data-testid^="start-shift-btn-"]'],
  repair: ['[data-testid^="action-repair-"]'],
  maintain: ['[data-testid^="action-repair-"]', '[data-testid^="action-upgrade-"]'],
  upgrade: ['[data-testid^="action-upgrade-"]'],
  market_buy: ['[data-testid="tutorial-trading-tab-buy"]'],
  market_list: ['[data-testid="tutorial-create-lot-btn"]', '[data-testid="tutorial-trading-tab-my"]'],
  market_sell: ['[data-testid="tutorial-create-lot-btn"]', '[data-testid="tutorial-trading-tab-my"]'],
};

export default function QuestHighlighter() {
  const { search, pathname } = useLocation();
  const navigate = useNavigate();
  const [target, setTarget] = useState(null);           // {ev, n} — n forces a re-run for the same event

  // step 1: read ?quest_hl=…, remember it, clean the URL (a reload must not highlight again)
  useEffect(() => {
    const params = new URLSearchParams(search);
    const ev = params.get('quest_hl');
    if (!ev || !TARGETS[ev]) return;
    setTarget((t) => ({ ev, n: (t?.n || 0) + 1 }));
    params.delete('quest_hl');
    navigate({ pathname, search: params.toString() ? `?${params}` : '' }, { replace: true });
  }, [search, pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  // step 2: find the button (the page may still be loading) and pulse it — independent of the URL
  useEffect(() => {
    if (!target) return undefined;
    let tries = 0, timer = null, el = null;
    const find = () => {
      for (const sel of TARGETS[target.ev]) { const e = document.querySelector(sel); if (e && e.offsetParent !== null) return e; }
      return null;
    };
    const tick = () => {
      el = find();
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('quest-highlight');
        timer = setTimeout(() => { el && el.classList.remove('quest-highlight'); setTarget(null); }, 6000);
        return;
      }
      if (++tries < 40) timer = setTimeout(tick, 200); // up to 8 s
      else setTarget(null);
    };
    timer = setTimeout(tick, 150);
    return () => { clearTimeout(timer); if (el) el.classList.remove('quest-highlight'); };
  }, [target]);
  return null;
}
