import { useState, useEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Plus, Trash2, Sparkles, Eye, Check, Rocket, Calendar, Users,
  RotateCcw, X, Map as MapIcon,
} from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// UNIX ISO → HTML datetime-local (MSK). Same helper style as AdminPage.
const utcIsoToMskLocal = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const mskMs = d.getTime() + (3 * 3600 * 1000) - (-d.getTimezoneOffset() * 60000);
  const m = new Date(mskMs);
  const pad = (n) => String(n).padStart(2, '0');
  return `${m.getFullYear()}-${pad(m.getMonth() + 1)}-${pad(m.getDate())}T${pad(m.getHours())}:${pad(m.getMinutes())}`;
};
const mskLocalToUtcIso = (localStr) => {
  if (!localStr) return null;
  // localStr is "YYYY-MM-DDTHH:mm" as MSK — treat as MSK, convert to UTC ISO.
  const [date, time] = localStr.split('T');
  const [Y, M, D] = date.split('-').map(Number);
  const [h, m] = time.split(':').map(Number);
  const utc = Date.UTC(Y, M - 1, D, h - 3, m, 0);
  return new Date(utc).toISOString();
};

const LABEL_OPTIONS = [
  { value: 'coming_epoch_2', label: '🔒 Скоро (Эпоха 2)' },
  { value: 'sold_out', label: '🔥 SOLD OUT' },
  { value: 'unavailable', label: '🔒 Недоступно' },
];

const MAP_OPTIONS = [
  { value: 'ton_island', label: 'GRAM Island' },
];

import { DistrictsCard } from '@/components/admin/CitySpritesPanel';

export default function PresalePanel({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const [mapId, setMapId] = useState('ton_island');
  const [inventory, setInventory] = useState([]); // [{type,name_ru,icon,tier,free,total}]
  const [rows, setRows] = useState([{ type: '', count: 1 }]);
  const [selectedPlots, setSelectedPlots] = useState([]); // last selection
  const [unavailableLabel, setUnavailableLabel] = useState('coming_epoch_2');
  const [opensAtLocal, setOpensAtLocal] = useState(''); // MSK local
  const [active, setActive] = useState(false);
  const [readyBuyers, setReadyBuyers] = useState(0);
  const [buyButtonText, setBuyButtonText] = useState('');
  const [savingButtonText, setSavingButtonText] = useState(false);

  const [showPreview, setShowPreview] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [approving, setApproving] = useState(false);
  const [resetting, setResetting] = useState(false);

  const loadInventory = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/admin/presale/inventory?map_id=${mapId}`, { headers });
      setInventory(res.data.businesses || []);
    } catch (e) {
      toast.error('Не удалось загрузить список бизнесов');
    }
  }, [mapId, headers]);

  const loadConfig = useCallback(async () => {
    try {
      const [cfgRes, buyersRes] = await Promise.all([
        axios.get(`${API}/admin/presale`, { headers }),
        axios.get(`${API}/admin/presale/ready-buyers`, { headers }),
      ]);
      const cfg = cfgRes.data || {};
      setMapId(cfg.map_id || 'ton_island');
      setUnavailableLabel(cfg.unavailable_label || 'coming_epoch_2');
      setSelectedPlots(cfg.selected_plots || []);
      setActive(!!cfg.active);
      setOpensAtLocal(utcIsoToMskLocal(cfg.opens_at));
      setBuyButtonText(cfg.buy_button_text || '');
      if (Array.isArray(cfg.businesses) && cfg.businesses.length) {
        setRows(cfg.businesses.map((b) => ({ type: b.type, count: b.count })));
      }
      setReadyBuyers(buyersRes.data?.count || 0);
    } catch (e) {
      /* first-run: no config yet — silent */
    }
  }, [headers]);

  useEffect(() => { loadInventory(); }, [loadInventory]);
  useEffect(() => { loadConfig(); }, [loadConfig]);

  const inventoryByType = useMemo(() => {
    const m = {};
    inventory.forEach((it) => { m[it.type] = it; });
    return m;
  }, [inventory]);

  // Types already picked in other rows — cannot be selected again to avoid
  // duplicate business entries in a single presale.
  const usedTypes = useMemo(() => {
    const s = new Set();
    rows.forEach((r) => { if (r.type) s.add(r.type); });
    return s;
  }, [rows]);

  const addRow = () => setRows((r) => [...r, { type: '', count: 1 }]);
  const removeRow = (i) => setRows((r) => r.filter((_, idx) => idx !== i));
  const patchRow = (i, patch) => setRows((r) => r.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));

  // Count input handler: clamps the value to the free supply of the chosen
  // business type (0 < count ≤ inv.free). Empty string is preserved so the
  // user can clear the field while typing.
  const patchCount = (i, raw) => {
    if (raw === '') {
      patchRow(i, { count: '' });
      return;
    }
    const row = rows[i];
    const inv = row && row.type ? inventoryByType[row.type] : null;
    let n = Math.floor(Number(raw));
    if (!Number.isFinite(n) || n < 1) n = 1;
    if (inv && n > inv.free) {
      n = inv.free;
      toast.warning(`Максимум ${inv.free} свободных полей для этого бизнеса`);
    }
    patchRow(i, { count: n });
  };

  // When switching to a new business type, clamp the current count to the
  // new max free supply so the field never has an invalid pre-filled value.
  const patchType = (i, newType) => {
    setRows((r) => r.map((row, idx) => {
      if (idx !== i) return row;
      const inv = inventoryByType[newType];
      const current = Number(row.count) || 1;
      const maxFree = inv ? inv.free : current;
      const clamped = Math.max(1, Math.min(current, maxFree || 1));
      return { ...row, type: newType, count: clamped };
    }));
  };

  const totalRequested = rows.reduce((s, r) => s + (Number(r.count) || 0), 0);

  const handleSelectPlots = async () => {
    const cleaned = rows
      .filter((r) => r.type && Number(r.count) > 0)
      .map((r) => ({ type: r.type, count: Number(r.count) }));
    if (!cleaned.length) {
      toast.error('Укажите хотя бы один бизнес и количество');
      return;
    }
    setSelecting(true);
    try {
      const res = await axios.post(
        `${API}/admin/presale/select-plots`,
        { map_id: mapId, businesses: cleaned },
        { headers },
      );
      setSelectedPlots(res.data.selected_plots || []);
      if ((res.data.warnings || []).length) {
        res.data.warnings.forEach((w) => toast.warning(w));
      } else {
        toast.success(`Выбрано ${res.data.selected_plots?.length || 0} полей`);
      }
      await loadInventory();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Не удалось выбрать поля');
    } finally {
      setSelecting(false);
    }
  };

  const handleApprove = async () => {
    if (!selectedPlots.length) {
      toast.error('Сначала нажмите «Выбрать поля»');
      return;
    }
    setApproving(true);
    try {
      const body = {
        opens_at: opensAtLocal ? mskLocalToUtcIso(opensAtLocal) : null,
        unavailable_label: unavailableLabel,
        map_id: mapId,
      };
      await axios.post(`${API}/admin/presale/approve`, body, { headers });
      toast.success('Пресейл активирован — конфигурация применена');
      await loadConfig();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Не удалось утвердить пресейл');
    } finally {
      setApproving(false);
    }
  };

  const handleSaveButtonText = async () => {
    setSavingButtonText(true);
    try {
      await axios.post(`${API}/admin/presale/button-text`, { buy_button_text: buyButtonText }, { headers });
      toast.success('Текст кнопки сохранён');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Не удалось сохранить текст кнопки');
    } finally {
      setSavingButtonText(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm('Сбросить пресейл целиком? Выбранные поля и дата будут удалены.')) return;
    if (!window.confirm('Сбросить пресейл целиком? Выбранные поля и дата будут удалены.')) return;
    setResetting(true);
    try {
      await axios.post(`${API}/admin/presale/reset`, {}, { headers });
      setSelectedPlots([]);
      setActive(false);
      setOpensAtLocal('');
      setRows([{ type: '', count: 1 }]);
      toast.success('Пресейл сброшен');
      await loadConfig();
      await loadInventory();
    } catch (e) {
      toast.error('Не удалось сбросить');
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="space-y-5" data-testid="presale-panel">
      {/* which lots are on sale: districts open / lots per district (the map shows prices only for these + presale plots) */}
      <div className="mb-4"><DistrictsCard token={token} /></div>
      {/* Header */}
      <div className="glass-panel rounded-2xl p-5 border border-amber-500/25">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-500/15 flex items-center justify-center">
              <Rocket className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h3 className="font-unbounded text-base font-bold text-white">Пресейл-раздел</h3>
              <p className="text-xs text-text-muted">
                Точечная продажа бизнесов на карте с датой открытия и золотистой подсветкой выбранных полей.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`px-3 py-1 rounded-full text-xs font-bold border ${
                active
                  ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                  : 'bg-gray-500/15 border-gray-500/40 text-gray-300'
              }`}
              data-testid="presale-status-badge"
            >
              {active ? '🟢 Активен' : '⚪ Черновик'}
            </span>
          </div>
        </div>

        {/* Ready buyers */}
        <div className="mt-4 flex items-center gap-3 p-3 rounded-lg bg-cyan-500/8 border border-cyan-500/25" data-testid="presale-ready-buyers">
          <Users className="w-4 h-4 text-cyan-300" />
          <span className="text-sm text-white">
            Пополненных балансов: <span className="font-mono font-bold text-cyan-300">{readyBuyers}</span>
          </span>
          <span className="text-xs text-text-muted">(баланс ≥ 5 TON)</span>
        </div>
      </div>

      {/* Map + businesses config */}
      <div className="glass-panel rounded-2xl p-5 border border-white/10 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
          <MapIcon className="w-4 h-4 text-white/70" />
          <label className="text-sm text-white/80 min-w-[80px]">Карта:</label>
          <Select value={mapId} onValueChange={setMapId}>
            <SelectTrigger className="w-full sm:w-64 bg-panel border-grid-border text-white" data-testid="presale-map-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#0d0e1c] border-white/10 text-white">
              {MAP_OPTIONS.map((m) => (
                <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <h4 className="text-sm font-bold text-white mb-2">Виды бизнесов и количество к продаже</h4>
          <div className="space-y-2" data-testid="presale-business-rows">
            {rows.map((row, i) => {
              const inv = inventoryByType[row.type];
              // Options shown in this row's dropdown: all inventory items EXCEPT
              // those already picked in other rows (keep the row's own current
              // selection so it can be re-selected/kept as-is).
              const availableOptions = inventory.filter((it) => (
                it.type === row.type || !usedTypes.has(it.type)
              ));
              return (
                <div key={i} className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center" data-testid={`presale-row-${i}`}>
                  <Select value={row.type} onValueChange={(v) => patchType(i, v)}>
                    <SelectTrigger className="w-full sm:flex-1 bg-panel border-grid-border text-white" data-testid={`presale-row-type-${i}`}>
                      <SelectValue placeholder="Выберите бизнес…" />
                    </SelectTrigger>
                    <SelectContent className="bg-[#0d0e1c] border-white/10 text-white max-h-80">
                      {availableOptions.map((it) => (
                        <SelectItem key={it.type} value={it.type} disabled={it.free <= 0 && it.type !== row.type}>
                          {it.icon} {it.name_ru} <span className="text-white/50">— T{it.tier}, свободно {it.free}/{it.total}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    type="number"
                    min="1"
                    max={inv ? inv.free : undefined}
                    value={row.count}
                    onChange={(e) => patchCount(i, e.target.value)}
                    className="w-full sm:w-28 bg-panel border-grid-border text-white"
                    data-testid={`presale-row-count-${i}`}
                    placeholder="кол-во"
                    disabled={!row.type}
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => removeRow(i)}
                    className="border-red-500/30 text-red-300 hover:bg-red-500/10"
                    disabled={rows.length <= 1}
                    data-testid={`presale-row-remove-${i}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex items-center justify-between">
            <Button
              variant="outline"
              size="sm"
              onClick={addRow}
              className="border-white/20 text-white hover:bg-white/10"
              data-testid="presale-add-row"
            >
              <Plus className="w-4 h-4 mr-1" /> Добавить бизнес
            </Button>
            <span className="text-xs text-text-muted">Всего к продаже: <span className="font-mono text-white">{totalRequested}</span></span>
          </div>
        </div>

        {/* Custom Buy-button text (global, no i18n) */}
        <div className="flex flex-col gap-2 pt-2 border-t border-white/10">
          <label className="text-sm text-white/80">
            Текст замены кнопки «Купить» для полей вне пресейла (одно глобальное значение):
          </label>
          <div className="flex flex-col sm:flex-row gap-2">
            <Input
              value={buyButtonText}
              onChange={(e) => setBuyButtonText(e.target.value)}
              placeholder="Напр.: Скоро в продаже (пусто → «Купить»)"
              className="w-full sm:flex-1 bg-panel border-grid-border text-white"
              data-testid="presale-button-text-input"
              maxLength={60}
            />
            <Button
              onClick={handleSaveButtonText}
              disabled={savingButtonText}
              variant="outline"
              className="border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 shrink-0"
              data-testid="presale-button-text-save"
            >
              <Check className="w-4 h-4 mr-1" /> {savingButtonText ? 'Сохраняем…' : 'Сохранить текст'}
            </Button>
          </div>
          <p className="text-xs text-text-muted">
            Кнопка на не-пресейл участках будет задизейблена с этим текстом. Пустое значение → стандартная «Купить».
          </p>
        </div>

        {/* Placeholder label */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
          <label className="text-sm text-white/80 min-w-[220px]">Замена кнопки «Купить» на прочих полях:</label>
          <Select value={unavailableLabel} onValueChange={setUnavailableLabel}>
            <SelectTrigger className="w-full sm:w-64 bg-panel border-grid-border text-white" data-testid="presale-label-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#0d0e1c] border-white/10 text-white">
              {LABEL_OPTIONS.map((l) => (
                <SelectItem key={l.value} value={l.value}>{l.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Opens at */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
          <Calendar className="w-4 h-4 text-white/70" />
          <label className="text-sm text-white/80 min-w-[200px]">Дата и время открытия (МСК):</label>
          <Input
            type="datetime-local"
            value={opensAtLocal}
            onChange={(e) => setOpensAtLocal(e.target.value)}
            className="w-full sm:w-64 bg-panel border-grid-border text-white"
            data-testid="presale-opens-at"
          />
          {opensAtLocal && (
            <button
              type="button"
              onClick={() => setOpensAtLocal('')}
              className="text-xs text-red-400 hover:underline"
              data-testid="presale-opens-at-clear"
            >
              Сбросить
            </button>
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-3 pt-2 border-t border-white/10">
          <Button
            onClick={handleSelectPlots}
            disabled={selecting}
            className="btn-cyber"
            data-testid="presale-select-btn"
          >
            <Sparkles className="w-4 h-4 mr-1" /> {selecting ? 'Выбираем…' : 'Выбрать поля'}
          </Button>
          <Button
            variant="outline"
            onClick={() => setShowPreview(true)}
            disabled={!selectedPlots.length}
            className="border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 disabled:opacity-40"
            data-testid="presale-preview-btn"
          >
            <Eye className="w-4 h-4 mr-1" /> Просмотр полей ({selectedPlots.length})
          </Button>
          <Button
            onClick={handleApprove}
            disabled={approving || !selectedPlots.length}
            className="bg-gradient-to-r from-amber-500 to-pink-500 hover:from-amber-400 hover:to-pink-400 text-black font-bold"
            data-testid="presale-approve-btn"
          >
            <Check className="w-4 h-4 mr-1" /> {approving ? 'Активируем…' : 'Утвердить'}
          </Button>
          <Button
            variant="outline"
            onClick={handleReset}
            disabled={resetting}
            className="border-red-500/40 text-red-300 hover:bg-red-500/10 ml-auto"
            data-testid="presale-reset-btn"
          >
            <RotateCcw className="w-4 h-4 mr-1" /> Сбросить
          </Button>
        </div>
      </div>

      {/* Preview modal */}
      {showPreview && createPortal(
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 p-4"
          data-testid="presale-preview-modal"
          onClick={() => setShowPreview(false)}
        >
          <div
            className="glass-panel w-full max-w-2xl rounded-2xl border border-amber-500/40 bg-[#12101a] max-h-[85vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-4 border-b border-white/10 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Eye className="w-5 h-5 text-amber-300" />
                <h3 className="font-unbounded text-base font-bold text-white">Выбранные поля пресейла</h3>
              </div>
              <button onClick={() => setShowPreview(false)} className="text-white/60 hover:text-white" data-testid="presale-preview-close">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 overflow-y-auto">
              {selectedPlots.length === 0 ? (
                <p className="text-text-muted text-center py-8">Пусто. Сначала нажмите «Выбрать поля».</p>
              ) : (
                <div className="space-y-2">
                  {Object.entries(
                    selectedPlots.reduce((acc, p) => {
                      (acc[p.business_type] = acc[p.business_type] || []).push(p);
                      return acc;
                    }, {})
                  ).map(([biz, plots]) => (
                    <div key={biz} className="rounded-lg border border-white/10 bg-white/5 p-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm text-white font-bold">
                          {inventoryByType[biz]?.icon || '🏢'} {inventoryByType[biz]?.name_ru || biz}
                        </span>
                        <span className="text-xs text-text-muted">{plots.length} полей</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {plots.map((p, i) => (
                          <span
                            key={i}
                            className="px-2 py-1 rounded bg-amber-500/15 border border-amber-500/40 text-amber-200 text-xs font-mono"
                            data-testid={`presale-preview-plot-${biz}-${i}`}
                          >
                            ({p.x}, {p.y})
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="p-4 border-t border-white/10 flex justify-end">
              <Button onClick={() => setShowPreview(false)} className="btn-cyber" data-testid="presale-preview-close-btn">
                Закрыть
              </Button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
