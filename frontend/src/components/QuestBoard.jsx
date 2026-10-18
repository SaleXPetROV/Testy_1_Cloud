/**
 * QuestBoard — in-game quests on the «Задания» page.
 *
 *  • «Путь новичка» (one-time chain), «Сегодня» (3 daily goals), «Неделя» (3 weekly goals)
 *  • Tap a card  → go to the screen where the goal is done (deep_link).
 *  • Progress grows by itself (no «Выполнить» button — the server counts real actions).
 *  • When done the card shows «Забрать» → POST /api/quests/{id}/claim (atomic).
 *  • After the whole chain: pick a free tier-3 resource (same reward as the old tutorial).
 *
 * Backend: backend/quests.py
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { toast } from 'sonner';
import { motion } from 'framer-motion';
import { CheckCircle2, ChevronRight, Gift, Rocket, Sun, CalendarDays, Sparkles } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { getResource } from '@/lib/resourceConfig';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;
const getToken = () => localStorage.getItem('token') || localStorage.getItem('ton_city_token');
const authHeaders = () => ({ headers: { Authorization: `Bearer ${getToken()}` } });

// UI labels in every project language (quest titles come from the backend).
const L = {
  onboarding: { en: 'Newcomer path', ru: 'Путь новичка', es: 'Camino del novato', zh: '新手之路', fr: 'Parcours du débutant', de: 'Einsteigerpfad', ja: '初心者の道', ko: '초보자의 길', id: 'Jalur pemula' },
  today: { en: 'Today', ru: 'Сегодня', es: 'Hoy', zh: '今日', fr: "Aujourd'hui", de: 'Heute', ja: '今日', ko: '오늘', id: 'Hari ini' },
  week: { en: 'This week', ru: 'Неделя', es: 'Esta semana', zh: '本周', fr: 'Cette semaine', de: 'Diese Woche', ja: '今週', ko: '이번 주', id: 'Minggu ini' },
  claim: { en: 'Claim', ru: 'Забрать', es: 'Reclamar', zh: '领取', fr: 'Récupérer', de: 'Abholen', ja: '受け取る', ko: '받기', id: 'Klaim' },
  go: { en: 'Go', ru: 'Перейти', es: 'Ir', zh: '前往', fr: 'Aller', de: 'Los', ja: '移動', ko: '이동', id: 'Buka' },
  done: { en: 'Done', ru: 'Получено', es: 'Hecho', zh: '已完成', fr: 'Fait', de: 'Erledigt', ja: '完了', ko: '완료', id: 'Selesai' },
  next: { en: 'What to do next', ru: 'Что делать дальше', es: 'Qué hacer ahora', zh: '下一步', fr: 'Que faire ensuite', de: 'Was als Nächstes', ja: '次にやること', ko: '다음 할 일', id: 'Langkah berikutnya' },
  noBiz: { en: 'Daily and weekly goals appear after you open your first business.', ru: 'Ежедневные и недельные цели появятся, когда вы откроете первый бизнес.', es: 'Los objetivos diarios y semanales aparecen cuando abras tu primer negocio.', zh: '开设第一家企业后将出现每日和每周目标。', fr: 'Les objectifs quotidiens et hebdomadaires apparaissent après votre première entreprise.', de: 'Tages- und Wochenziele erscheinen nach deinem ersten Unternehmen.', ja: '最初のビジネスを開くとデイリー・ウィークリー目標が表示されます。', ko: '첫 사업을 열면 일일 및 주간 목표가 나타납니다.', id: 'Target harian dan mingguan muncul setelah Anda membuka bisnis pertama.' },
  allDaily: { en: 'All goals for today are done — come back tomorrow!', ru: 'Все цели на сегодня выполнены — возвращайтесь завтра!', es: '¡Objetivos de hoy completados, vuelve mañana!', zh: '今日目标全部完成——明天再来！', fr: 'Objectifs du jour terminés — revenez demain !', de: 'Alle Tagesziele erledigt — komm morgen wieder!', ja: '今日の目標はすべて完了 — また明日！', ko: '오늘의 목표 완료 — 내일 다시 오세요!', id: 'Semua target hari ini selesai — kembali besok!' },
  bonusNote: { en: 'Rewards go to your bonus balance: spend them in the game.', ru: 'Награды идут на бонусный баланс — их можно тратить в игре.', es: 'Las recompensas van al saldo de bonificación para gastar en el juego.', zh: '奖励进入奖励余额，可在游戏中使用。', fr: 'Les récompenses vont sur le solde bonus, à dépenser en jeu.', de: 'Belohnungen landen im Bonusguthaben und sind im Spiel nutzbar.', ja: '報酬はボーナス残高に入り、ゲーム内で使えます。', ko: '보상은 보너스 잔액으로 지급되어 게임에서 사용할 수 있습니다.', id: 'Hadiah masuk ke saldo bonus dan bisa dipakai di game.' },
  finalTitle: { en: 'Newcomer path complete! Choose your free tier-3 resource:', ru: 'Путь новичка пройден! Выберите бесплатный ресурс тира 3:', es: '¡Camino completado! Elige tu recurso gratuito de nivel 3:', zh: '新手之路完成！选择一个免费的三级资源：', fr: 'Parcours terminé ! Choisissez votre ressource gratuite de rang 3 :', de: 'Pfad abgeschlossen! Wähle deine kostenlose Tier-3-Ressource:', ja: '初心者の道クリア！無料のティア3資源を選択：', ko: '초보자의 길 완료! 무료 3티어 자원을 선택하세요:', id: 'Jalur pemula selesai! Pilih sumber daya tier 3 gratis:' },
  finalGot: { en: 'Reward received', ru: 'Награда получена', es: 'Recompensa recibida', zh: '已获得奖励', fr: 'Récompense reçue', de: 'Belohnung erhalten', ja: '報酬を受け取りました', ko: '보상을 받았습니다', id: 'Hadiah diterima' },
  capped: { en: 'Daily bonus limit reached — part of the reward was not credited.', ru: 'Достигнут дневной лимит бонусов — часть награды не начислена.', es: 'Límite diario alcanzado: parte de la recompensa no se acreditó.', zh: '已达每日奖励上限，部分奖励未发放。', fr: 'Limite quotidienne atteinte : une partie non créditée.', de: 'Tageslimit erreicht — ein Teil wurde nicht gutgeschrieben.', ja: '1日の上限に達したため一部未付与です。', ko: '일일 한도 도달 — 일부 보상이 지급되지 않았습니다.', id: 'Batas harian tercapai — sebagian hadiah tidak dikreditkan.' },
};
const tl = (key, lang) => L[key]?.[lang] || L[key]?.en || key;

function QuestCard({ q, lang, onClaim, onGo, busy }) {
  const pct = Math.min(100, Math.round((q.progress / Math.max(1, q.target)) * 100));
  const ready = q.status === 'ready';
  const claimed = q.status === 'claimed';
  const clickable = !claimed && !ready && q.deep_link;
  return (
    <div
      role={clickable ? 'link' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={() => clickable && onGo(q)}
      onKeyDown={(e) => { if (clickable && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onGo(q); } }}
      className={`rounded-xl border p-3 transition-all ${
        claimed ? 'bg-white/5 border-white/10 opacity-60'
        : ready ? 'bg-emerald-500/10 border-emerald-400/50 ring-1 ring-emerald-400/40'
        : 'bg-white/5 border-white/10 hover:border-yellow-400/40 cursor-pointer'}`}
      data-testid={`quest-card-${q.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-sm font-semibold text-white">
            {claimed && <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />}
            <span className="truncate">{q.title}</span>
          </div>
          <p className="text-[11px] text-text-muted mt-0.5 line-clamp-2">{q.description}</p>
        </div>
        <div className="text-right flex-shrink-0">
          <div className="text-xs font-bold text-yellow-400 whitespace-nowrap">+{q.reward.city} $CITY</div>
          {q.reward.xp > 0 && <div className="text-[10px] text-cyan-300">+{q.reward.xp} XP</div>}
        </div>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="flex-1 h-1.5 rounded-full bg-white/10 overflow-hidden">
          <div className={`h-full ${ready || claimed ? 'bg-emerald-400' : 'bg-yellow-400'} transition-all`} style={{ width: `${claimed ? 100 : pct}%` }} />
        </div>
        <span className="text-[11px] font-mono text-white/80 w-14 text-right">{claimed ? q.target : q.progress}/{q.target}</span>
        {ready ? (
          <Button size="sm" disabled={busy} onClick={(e) => { e.stopPropagation(); onClaim(q); }}
            className="h-7 px-3 text-xs font-bold bg-emerald-500 hover:bg-emerald-400 text-black" data-testid={`quest-claim-${q.id}`}>
            <Gift className="w-3.5 h-3.5 mr-1" />{tl('claim', lang)}
          </Button>
        ) : claimed ? (
          <span className="text-[11px] text-emerald-400 w-16 text-right">{tl('done', lang)}</span>
        ) : q.deep_link ? (
          <ChevronRight className="w-4 h-4 text-white/50" />
        ) : null}
      </div>
    </div>
  );
}

function Section({ icon, title, extra, children, testId }) {
  return (
    <Card className="glass-panel border-white/10" data-testid={testId}>
      <CardContent className="p-3 sm:p-4 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-bold text-white uppercase text-xs sm:text-sm tracking-wide">{icon}{title}</div>
          {extra}
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

export default function QuestBoard({ lang = 'en', onChanged }) {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/quests`, authHeaders());
      setData(r.data);
    } catch (e) {
      // quests are additive: never break the page if the endpoint is unavailable
      setData(null);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const claim = async (q) => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/quests/${q.id}/claim`, {}, authHeaders());
      const g = r.data?.granted || {};
      toast.success(`${q.title}: +${g.city || 0} $CITY${g.xp ? ` · +${g.xp} XP` : ''}`);
      if (g.capped) toast.message(tl('capped', lang));
      await load();
      onChanged && onChanged();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Error');
      await load();
    } finally {
      setBusy(false);
    }
  };

  const pickReward = async (choice) => {
    setBusy(true);
    try {
      await axios.post(`${API}/quests/onboarding/reward`, { choice }, authHeaders());
      const res = getResource(choice, lang);
      toast.success(`${tl('finalGot', lang)}: ${res.icon} ${res.name}`);
      await load();
      onChanged && onChanged();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Error');
    } finally {
      setBusy(false);
    }
  };

  // open the quest's screen and ask it to highlight the button that does the job
  const go = (q) => {
    if (!q.deep_link) return;
    const sep = q.deep_link.includes('?') ? '&' : '?';
    navigate(q.event ? `${q.deep_link}${sep}quest_hl=${encodeURIComponent(q.event)}` : q.deep_link);
  };

  if (!data) return null;
  const ob = data.onboarding || {};
  // Finished (claimed) steps are hidden. The section disappears when no step
  // is left — except the final tier-3 reward choice, which stays until picked.
  const obLeft = (ob.items || []).filter((q) => q.status !== 'claimed');
  const showOnboarding = obLeft.length > 0 || !!ob.reward?.available;
  const next = data.next;

  return (
    <div className="space-y-3" data-testid="quest-board">
      {next && (
        <motion.button type="button" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
          onClick={() => (next.action === 'claim' ? claim(next) : go(next))} disabled={busy}
          className="w-full text-left rounded-xl p-3 border border-yellow-400/50 bg-gradient-to-r from-yellow-500/15 to-orange-500/10 flex items-center gap-3"
          data-testid="quest-next">
          <Sparkles className="w-5 h-5 text-yellow-300 flex-shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase tracking-wide text-yellow-300 font-semibold">{tl('next', lang)}</div>
            <div className="text-sm text-white font-semibold truncate">{next.title}</div>
          </div>
          <span className="text-xs font-bold text-black bg-yellow-400 rounded-lg px-2.5 py-1">
            {next.action === 'claim' ? tl('claim', lang) : tl('go', lang)}
          </span>
        </motion.button>
      )}

      {showOnboarding ? (
        <Section testId="quest-onboarding" icon={<Rocket className="w-4 h-4 text-yellow-400" />} title={tl('onboarding', lang)}
          extra={<span className="text-xs font-mono text-white/70">{ob.done}/{ob.total}</span>}>
          {obLeft.map((q) => <QuestCard key={q.id} q={q} lang={lang} busy={busy} onClaim={claim} onGo={go} />)}
          {ob.reward?.available && (
            <div className="rounded-xl border border-purple-400/50 bg-purple-500/10 p-3" data-testid="quest-final-reward">
              <div className="text-xs text-purple-200 font-semibold mb-2">{tl('finalTitle', lang)}</div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                {(ob.reward.options || []).map((id) => {
                  const r = getResource(id, lang);
                  return (
                    <button key={id} type="button" disabled={busy} onClick={() => pickReward(id)}
                      className="rounded-lg bg-white/5 hover:bg-purple-500/20 border border-white/10 p-2 text-xs text-white flex items-center gap-1.5"
                      data-testid={`quest-final-reward-${id}`}>
                      <span>{r.icon}</span><span className="truncate">{r.name}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </Section>
      ) : null}

      {!data.has_business && (
        <p className="text-xs text-text-muted px-1" data-testid="quest-no-business">{tl('noBiz', lang)}</p>
      )}

      {data.daily?.items?.length > 0 && (
        <Section testId="quest-daily" icon={<Sun className="w-4 h-4 text-orange-400" />} title={tl('today', lang)}>
          {data.daily.all_claimed && <p className="text-xs text-emerald-300">{tl('allDaily', lang)}</p>}
          {data.daily.items.map((q) => <QuestCard key={q.id} q={q} lang={lang} busy={busy} onClaim={claim} onGo={go} />)}
        </Section>
      )}

      {data.weekly?.items?.length > 0 && (
        <Section testId="quest-weekly" icon={<CalendarDays className="w-4 h-4 text-cyan-400" />} title={tl('week', lang)}>
          {data.weekly.items.map((q) => <QuestCard key={q.id} q={q} lang={lang} busy={busy} onClaim={claim} onGo={go} />)}
        </Section>
      )}

      {(data.daily?.items?.length > 0 || showOnboarding) && (
        <p className="text-[11px] text-text-muted px-1">{tl('bonusNote', lang)}</p>
      )}
    </div>
  );
}
