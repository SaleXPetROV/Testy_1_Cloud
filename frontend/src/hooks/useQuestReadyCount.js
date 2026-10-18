import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const getToken = () => localStorage.getItem('token') || localStorage.getItem('ton_city_token');

/**
 * Number of in-game quests whose reward is ready to claim (red dot on «Задания»).
 * Polls GET /api/quests/ready-count every 60 s and on every route change.
 * Fails silently: the badge is a nicety, never an error source.
 */
export default function useQuestReadyCount(user) {
  const [count, setCount] = useState(0);
  const location = useLocation();

  useEffect(() => {
    if (!user) { setCount(0); return undefined; }
    let alive = true;
    const load = async () => {
      const token = getToken();
      if (!token) return;
      try {
        const res = await fetch(`${BACKEND_URL}/api/quests/ready-count`, { headers: { Authorization: `Bearer ${token}` } });
        if (!res.ok) return;
        const data = await res.json();
        if (alive) setCount(Number(data?.ready) || 0);
      } catch { /* ignore */ }
    };
    load();
    const id = setInterval(load, 60000);
    return () => { alive = false; clearInterval(id); };
  }, [user, location.pathname]);

  return count;
}
