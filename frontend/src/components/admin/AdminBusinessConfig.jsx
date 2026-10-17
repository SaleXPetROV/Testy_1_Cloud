import { useState, useEffect, useMemo, useCallback } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Loader2, Save, RefreshCw, Factory, Boxes, ArrowUpCircle } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const L = {
  ru: {
    title: 'Экономика бизнесов',
    subtitle: 'Производство и потребление по уровням (1–10). Изменения применяются ко ВСЕМ бизнесам этого вида.',
    tier: 'Тир', level: 'Ур.', produces: 'Производит', consumes: 'Потребляет', storage: 'Склад',
    upgCity: 'Апгрейд 🪙', upgRes: 'Апгрейд (ресурс)', upgLevelHint: 'цена перехода на этот уровень',
    save: 'Применить ко всем', saving: 'Сохранение…', reload: 'Обновить',
    saved: 'Изменения применены ко всем бизнесам вида', error: 'Ошибка сохранения',
    loadError: 'Не удалось загрузить конфигурацию', empty: 'Выберите вид бизнеса слева',
    perDay: 'ед./сутки',
  },
  en: {
    title: 'Business economy',
    subtitle: 'Per-level production & consumption (1–10). Changes apply to ALL businesses of this type.',
    tier: 'Tier', level: 'Lvl', produces: 'Produces', consumes: 'Consumes', storage: 'Storage',
    upgCity: 'Upgrade 🪙', upgRes: 'Upgrade (resource)', upgLevelHint: 'price to reach this level',
    save: 'Apply to all', saving: 'Saving…', reload: 'Reload',
    saved: 'Changes applied to all businesses of this type', error: 'Save failed',
    loadError: 'Failed to load configuration', empty: 'Pick a business type on the left',
    perDay: 'units/day',
  },
};

export default function AdminBusinessConfig({ token, lang = 'ru' }) {
  const t = L[lang] || L.ru;
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null); // business_type
  const [draft, setDraft] = useState(null);        // editable copy of selected entry

  const resName = useCallback((r) => (r ? (lang === 'ru' ? r.name_ru : r.name_en) || r.id : ''), [lang]);
  const bizName = useCallback((b) => (b?.name?.[lang] || b?.name?.en || b?.business_type), [lang]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/business-config`, { headers });
      const list = r.data?.businesses || [];
      setItems(list);
      setSelected((prev) => prev || (list[0]?.business_type ?? null));
    } catch (e) {
      toast.error(t.loadError);
    } finally {
      setLoading(false);
    }
  }, [headers, t.loadError]);

  useEffect(() => { load(); }, [load]);

  // Build an editable draft whenever the selection or source list changes.
  useEffect(() => {
    if (!selected) { setDraft(null); return; }
    const entry = items.find((i) => i.business_type === selected);
    setDraft(entry ? JSON.parse(JSON.stringify(entry)) : null);
  }, [selected, items]);

  const setProd = (levelIdx, value) => {
    setDraft((d) => {
      const copy = { ...d, levels: d.levels.map((l) => ({ ...l, consumption: { ...l.consumption } })) };
      copy.levels[levelIdx].production = value === '' ? '' : Math.max(0, parseInt(value, 10) || 0);
      return copy;
    });
  };

  const setStor = (levelIdx, value) => {
    setDraft((d) => {
      const copy = { ...d, levels: d.levels.map((l) => ({ ...l, consumption: { ...l.consumption } })) };
      copy.levels[levelIdx].storage = value === '' ? '' : Math.max(0, parseInt(value, 10) || 0);
      return copy;
    });
  };

  const setUpg = (levelIdx, field, value) => {
    setDraft((d) => {
      const copy = { ...d, levels: d.levels.map((l) => ({ ...l, consumption: { ...l.consumption }, upgrade: l.upgrade ? { ...l.upgrade } : l.upgrade })) };
      if (copy.levels[levelIdx].upgrade) {
        copy.levels[levelIdx].upgrade[field] = value === '' ? '' : Math.max(0, parseInt(value, 10) || 0);
      }
      return copy;
    });
  };

  const setCons = (levelIdx, rid, value) => {
    setDraft((d) => {
      const copy = { ...d, levels: d.levels.map((l) => ({ ...l, consumption: { ...l.consumption } })) };
      copy.levels[levelIdx].consumption[rid] = value === '' ? '' : Math.max(0, parseInt(value, 10) || 0);
      return copy;
    });
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const production = {};
      const consumption = {};
      const storage = {};
      const upgrade = {};
      draft.levels.forEach((l) => {
        production[l.level] = parseInt(l.production, 10) || 0;
        storage[l.level] = parseInt(l.storage, 10) || 0;
        consumption[l.level] = {};
        Object.entries(l.consumption || {}).forEach(([rid, amt]) => {
          consumption[l.level][rid] = parseInt(amt, 10) || 0;
        });
        if (l.upgrade) {
          upgrade[l.level] = {
            city: parseInt(l.upgrade.city, 10) || 0,
            resource: l.upgrade.resource,
            qty: parseInt(l.upgrade.qty, 10) || 0,
          };
        }
      });
      const dur = draft.durability || {};
      const num = (v) => (v === '' || v == null ? null : String(v).replace(',', '.'));     // decimals kept as typed
      const r = await axios.put(`${API}/admin/business-config/${draft.business_type}`,
        { production, consumption, storage, upgrade,
          durability: { shifts_per_100: num(dur.shifts_per_100), repair_cost_per_pct_city: num(dur.repair_cost_per_pct_city) } }, { headers });
      const updated = r.data?.business;
      if (updated) {
        setItems((prev) => prev.map((i) => (i.business_type === updated.business_type ? updated : i)));
      }
      toast.success(t.saved);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t.error);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="glass-panel rounded-2xl p-10 flex items-center justify-center text-text-muted">
        <Loader2 className="w-5 h-5 mr-2 animate-spin" /> …
      </div>
    );
  }

  const consumed = draft?.consumed_resources || [];

  return (
    <div className="glass-panel rounded-2xl p-4 sm:p-6">
      <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
        <div>
          <h2 className="font-unbounded text-lg font-bold text-text-main flex items-center gap-2">
            <Factory className="w-5 h-5 text-cyber-cyan" /> {t.title}
          </h2>
          <p className="text-sm text-text-muted mt-1 max-w-2xl">{t.subtitle}</p>
        </div>
        <Button size="sm" variant="outline" onClick={load} className="border-white/20">
          <RefreshCw className="w-4 h-4 mr-1" /> {t.reload}
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-4">
        {/* Business type list */}
        <ScrollArea className="h-[320px] lg:h-[560px] rounded-xl border border-white/10 bg-black/20 p-2">
          <div className="flex flex-col gap-1">
            {items.map((b) => (
              <button
                key={b.business_type}
                onClick={() => setSelected(b.business_type)}
                data-testid={`bizcfg-item-${b.business_type}`}
                className={`text-left px-3 py-2 rounded-lg text-sm transition flex items-center gap-2 ${
                  selected === b.business_type
                    ? 'bg-cyber-cyan/15 text-cyber-cyan border border-cyber-cyan/40'
                    : 'text-text-muted hover:bg-white/5 border border-transparent'
                }`}
              >
                <span>{b.icon || '🏢'}</span>
                <span className="flex-1 truncate">{bizName(b)}</span>
                <span className="text-[10px] opacity-60">{t.tier} {b.tier}</span>
              </button>
            ))}
          </div>
        </ScrollArea>

        {/* Editor table */}
        {!draft ? (
          <Card className="glass-panel border-white/10">
            <CardContent className="p-8 text-center text-text-muted">{t.empty}</CardContent>
          </Card>
        ) : (
          <div className="rounded-xl border border-white/10 bg-black/20 overflow-hidden">
            <div className="flex items-center justify-between gap-3 p-3 border-b border-white/10 flex-wrap">
              <div className="flex items-center gap-2 text-text-main font-semibold">
                <span className="text-xl">{draft.icon || '🏢'}</span>
                {bizName(draft)}
                <span className="text-xs text-text-muted">({draft.business_type})</span>
              </div>
              <Button size="sm" onClick={save} disabled={saving} data-testid="bizcfg-save-btn"
                className="bg-cyber-cyan/20 text-cyber-cyan border border-cyber-cyan/40 hover:bg-cyber-cyan/30">
                {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Save className="w-4 h-4 mr-1" />}
                {saving ? t.saving : t.save}
              </Button>
            </div>

            {/* durability: shifts that wear 100% + $CITY per 1% of repair (decimals like 0.3 allowed) */}
            <div className="grid sm:grid-cols-2 gap-3 mb-4" data-testid="bizcfg-durability">
              <label className="rounded-xl border border-white/10 bg-white/5 p-3 space-y-1 text-xs text-text-muted">
                <span className="text-white font-semibold">Смен до износа 100% прочности</span>
                <input type="text" inputMode="decimal" data-testid="bizcfg-shifts-100"
                  value={draft.durability?.shifts_per_100 ?? ''}
                  placeholder={String(draft.durability?.default_shifts_per_100 ?? 10)}
                  onChange={(e) => { const v = e.target.value.replace(',', '.'); if (/^\d*\.?\d*$/.test(v)) setDraft((d) => ({ ...d, durability: { ...(d.durability || {}), shifts_per_100: v } })); }}
                  className="w-full rounded bg-black/40 border border-white/10 px-2 py-1.5 text-white text-sm" />
                <span className="block">Смена = 8 ч. Пусто — по умолчанию ({draft.durability?.default_shifts_per_100 ?? 10}). Можно дробное: 12.5</span>
              </label>
              <label className="rounded-xl border border-white/10 bg-white/5 p-3 space-y-1 text-xs text-text-muted">
                <span className="text-white font-semibold">Стоимость ремонта 1% прочности, $CITY</span>
                <input type="text" inputMode="decimal" data-testid="bizcfg-cost-1pct"
                  value={draft.durability?.repair_cost_per_pct_city ?? ''}
                  placeholder={String(draft.durability?.default_repair_cost_per_pct_city ?? 1)}
                  onChange={(e) => { const v = e.target.value.replace(',', '.'); if (/^\d*\.?\d*$/.test(v)) setDraft((d) => ({ ...d, durability: { ...(d.durability || {}), repair_cost_per_pct_city: v } })); }}
                  className="w-full rounded bg-black/40 border border-white/10 px-2 py-1.5 text-white text-sm" />
                <span className="block">Пусто — по умолчанию для тира ({draft.durability?.default_repair_cost_per_pct_city ?? 1}). Можно дробное: 0.3</span>
              </label>
            </div>

            <ScrollArea className="max-h-[500px]">
              <table className="w-full text-sm border-collapse">
                <thead className="sticky top-0 bg-[#0e1526] z-10">
                  <tr className="text-left text-text-muted">
                    <th className="p-2 font-medium">{t.level}</th>
                    <th className="p-2 font-medium">
                      <span className="inline-flex items-center gap-1 text-emerald-400">
                        <Factory className="w-3.5 h-3.5" /> {t.produces}
                        {draft.produced_resource && (
                          <span className="opacity-80">· {draft.produced_resource.icon} {resName(draft.produced_resource)}</span>
                        )}
                      </span>
                    </th>
                    <th className="p-2 font-medium">
                      <span className="inline-flex items-center gap-1 text-sky-400">
                        <Boxes className="w-3.5 h-3.5" /> {t.storage}
                      </span>
                    </th>
                    {consumed.map((r) => (
                      <th key={r.id} className="p-2 font-medium">
                        <span className="inline-flex items-center gap-1 text-amber-400">
                          <Boxes className="w-3.5 h-3.5" /> {r.icon} {resName(r)}
                        </span>
                      </th>
                    ))}
                    <th className="p-2 font-medium" title={t.upgLevelHint}>
                      <span className="inline-flex items-center gap-1 text-fuchsia-400">
                        <ArrowUpCircle className="w-3.5 h-3.5" /> {t.upgCity}
                      </span>
                    </th>
                    <th className="p-2 font-medium" title={t.upgLevelHint}>
                      <span className="inline-flex items-center gap-1 text-fuchsia-400">
                        <ArrowUpCircle className="w-3.5 h-3.5" /> {t.upgRes}
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {draft.levels.map((l, idx) => (
                    <tr key={l.level} className="border-t border-white/5 hover:bg-white/5">
                      <td className="p-2 font-mono text-text-muted">{l.level}</td>
                      <td className="p-2">
                        <Input
                          type="number" min="0"
                          value={l.production}
                          onChange={(e) => setProd(idx, e.target.value)}
                          data-testid={`bizcfg-prod-${l.level}`}
                          className="h-8 w-24 bg-black/30 border-emerald-500/30 text-emerald-300"
                        />
                      </td>
                      <td className="p-2">
                        <Input
                          type="number" min="0"
                          value={l.storage}
                          onChange={(e) => setStor(idx, e.target.value)}
                          data-testid={`bizcfg-storage-${l.level}`}
                          className="h-8 w-24 bg-black/30 border-sky-500/30 text-sky-300"
                        />
                      </td>
                      {consumed.map((r) => (
                        <td key={r.id} className="p-2">
                          <Input
                            type="number" min="0"
                            value={l.consumption?.[r.id] ?? 0}
                            onChange={(e) => setCons(idx, r.id, e.target.value)}
                            data-testid={`bizcfg-cons-${l.level}-${r.id}`}
                            className="h-8 w-24 bg-black/30 border-amber-500/30 text-amber-300"
                          />
                        </td>
                      ))}
                      {/* Upgrade cost to REACH this level (levels 2..10) */}
                      <td className="p-2">
                        {l.upgrade ? (
                          <Input
                            type="number" min="0"
                            value={l.upgrade.city}
                            onChange={(e) => setUpg(idx, 'city', e.target.value)}
                            data-testid={`bizcfg-upgcity-${l.level}`}
                            className="h-8 w-28 bg-black/30 border-fuchsia-500/30 text-fuchsia-300"
                          />
                        ) : (
                          <span className="text-text-muted/50">—</span>
                        )}
                      </td>
                      <td className="p-2">
                        {l.upgrade ? (
                          <div className="flex items-center gap-1.5">
                            <Input
                              type="number" min="0"
                              value={l.upgrade.qty}
                              onChange={(e) => setUpg(idx, 'qty', e.target.value)}
                              data-testid={`bizcfg-upgqty-${l.level}`}
                              className="h-8 w-20 bg-black/30 border-fuchsia-500/30 text-fuchsia-300"
                            />
                            <span className="text-xs text-text-muted whitespace-nowrap">
                              {l.upgrade.resource_meta?.icon} {resName(l.upgrade.resource_meta)}
                            </span>
                          </div>
                        ) : (
                          <span className="text-text-muted/50">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollArea>
          </div>
        )}
      </div>
    </div>
  );
}
