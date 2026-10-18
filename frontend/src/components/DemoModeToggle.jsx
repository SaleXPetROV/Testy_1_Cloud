import React from 'react';
import { Repeat } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { getGameMode, setGameMode } from '@/lib/gameMode';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

// REAL / DEMO toggle. On desktop it sits directly under the project name in the
// sidebar as a real switch: the switch is ON => REAL; flipping it OFF switches
// to DEMO mode (label changes REAL -> DEMO and the whole app reloads into the
// demo sandbox). On mobile the compact pill is used in the burger header.
//
// variant:
//   • "compact" (default) — small pill (mobile burger header).
//   • "sidebar" — switch + REAL/DEMO label (desktop). When the sidebar is
//     collapsed (isExpanded=false) it renders a compact icon button instead.
export default function DemoModeToggle({ className = '', variant = 'compact', isExpanded = true }) {
  const isDemo = getGameMode() === 'demo';

  const doToggle = async () => {
    const next = isDemo ? 'real' : 'demo';
    try {
      const token = localStorage.getItem('token');
      await fetch(`${BACKEND_URL}/api/demo/${next === 'demo' ? 'enter' : 'exit'}`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch (e) { /* ignore network errors — mode still flips locally */ }
    setGameMode(next);
    try { localStorage.setItem('ton_city_mode_toast', next); } catch (e) { /* ignore */ }
    // Entering DEMO mode → always land on the demo hub (/my-businesses),
    // regardless of the page the user was on. Exiting DEMO mode just reloads
    // the current page.
    if (next === 'demo') {
      window.location.href = '/my-businesses';
    } else {
      window.location.reload();
    }
  };

  if (variant === 'sidebar') {
    // Collapsed sidebar: compact icon button (no room for the switch).
    if (!isExpanded) {
      return (
        <button
          type="button"
          onClick={doToggle}
          data-testid="game-mode-toggle"
          aria-label={isDemo ? 'DEMO' : 'REAL'}
          title={isDemo ? 'DEMO' : 'REAL'}
          className={`w-full flex items-center justify-center py-1.5 transition-all text-white/80 hover:text-white ${className}`}
        >
          <span className="relative flex items-center justify-center">
            <Repeat className="w-5 h-5" />
            <span
              className={`absolute -top-1.5 -right-2 w-2.5 h-2.5 rounded-full ring-2 ring-[#12121f] ${
                isDemo ? 'bg-amber-400' : 'bg-emerald-400'
              }`}
            />
          </span>
        </button>
      );
    }
    // Expanded sidebar: label + real switch (ON = REAL, OFF = DEMO). No box.
    return (
      <div
        data-testid="game-mode-toggle"
        className={`flex items-center justify-between gap-2 px-2 ${className}`}
      >
        <span
          className={`font-extrabold text-xs uppercase tracking-widest ${
            isDemo ? 'text-amber-400' : 'text-emerald-400'
          }`}
        >
          {isDemo ? 'DEMO' : 'REAL'}
        </span>
        <Switch
          checked={!isDemo}
          onCheckedChange={doToggle}
          data-testid="game-mode-switch"
          aria-label={isDemo ? 'Switch to real mode' : 'Switch to demo mode'}
          className="data-[state=checked]:bg-emerald-500 data-[state=unchecked]:bg-amber-400"
        />
      </div>
    );
  }

  // Default compact pill (mobile burger header).
  return (
    <button
      type="button"
      onClick={doToggle}
      data-testid="game-mode-toggle"
      title={isDemo ? 'DEMO' : 'REAL'}
      className={`h-10 px-3 rounded-xl font-extrabold text-xs tracking-widest transition-colors flex-shrink-0 ${
        isDemo
          ? 'bg-amber-400 text-black hover:bg-amber-300'
          : 'bg-emerald-500 text-black hover:bg-emerald-400'
      } ${className}`}
    >
      {isDemo ? 'DEMO' : 'REAL'}
    </button>
  );
}
