/** Small building blocks of the admin «Мини-игры» tabs (Russian UI, no translations). */
import { useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';

export const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api`;
export const BACKEND = process.env.REACT_APP_BACKEND_URL || '';
export const inp = 'rounded bg-black/40 border border-white/10 px-2 py-1.5 text-white text-sm w-full';
export const inpS = 'rounded bg-black/40 border border-white/10 px-2 py-1.5 text-white text-sm';   // with an explicit width
export const LANGS = ['en', 'ru', 'es', 'zh', 'fr', 'de', 'ja', 'ko', 'id'];
export const err = (e) => {
  const d = e?.response?.data?.detail;
  toast.error(typeof d === 'string' ? d : d?.code || e?.message || 'Ошибка');
};
export const img = (u) => (!u ? '' : u.startsWith('/') ? `${BACKEND}${u}` : u);
export const fmt = (n) => Number(n || 0).toLocaleString('ru-RU');
export const dt = (iso) => (iso ? new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—');

export function useApi(token) {
  const h = { headers: { Authorization: `Bearer ${token}` } };
  return {
    get: (p) => axios.get(`${API}${p}`, h).then((r) => r.data),
    post: (p, b) => axios.post(`${API}${p}`, b, h).then((r) => r.data),
    put: (p, b) => axios.put(`${API}${p}`, b, h).then((r) => r.data),
    del: (p) => axios.delete(`${API}${p}`, h).then((r) => r.data),
    upload: (file) => { const f = new FormData(); f.append('file', file); return axios.post(`${API}/admin/minigames/upload`, f, h).then((r) => r.data.url); },
  };
}

export function Card({ title, children, right }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-3">
      {(title || right) && <div className="flex items-center justify-between gap-2"><div className="font-bold text-white">{title}</div>{right}</div>}
      {children}
    </div>
  );
}

export function Field({ label, children, wide }) {
  return <label className={`space-y-1 text-xs text-text-muted ${wide ? 'md:col-span-2' : ''}`}><span>{label}</span>{children}</label>;
}

export function ImagePick({ api, value, onChange }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <div className="w-12 h-12 rounded-lg border border-white/10 bg-black/40 overflow-hidden flex items-center justify-center text-[10px] text-text-muted">
        {value ? <img src={img(value)} alt="" className="w-full h-full object-cover" /> : 'нет'}
      </div>
      <label className="text-xs text-cyan-300 underline cursor-pointer">
        {busy ? 'Загрузка…' : 'Загрузить картинку'}
        <input type="file" accept="image/*" className="hidden" onChange={async (e) => {
          const f = e.target.files?.[0]; if (!f) return;
          setBusy(true);
          try { onChange(await api.upload(f)); } catch (x) { err(x); } finally { setBusy(false); e.target.value = ''; }
        }} />
      </label>
      {value && <button type="button" className="text-xs text-red-300" onClick={() => onChange('')}>убрать</button>}
    </div>
  );
}

/** Player-facing name in the 9 project languages (the admin types them; the base name is the fallback). */
export function NamesI18n({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const v = value || {};
  return (
    <div className="md:col-span-2">
      <button type="button" className="text-xs text-cyan-300 underline" onClick={() => setOpen(!open)}>
        Название для игроков на 9 языках ({Object.keys(v).filter((k) => v[k]).length}/9) {open ? '▲' : '▼'}
      </button>
      {open && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-2">
          {LANGS.map((l) => (
            <label key={l} className="flex items-center gap-1 text-[11px] text-text-muted"><span className="w-6 uppercase">{l}</span>
              <input className={inp} value={v[l] || ''} onChange={(e) => onChange({ ...v, [l]: e.target.value })} />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function Row({ children, onEdit, off }) {
  return (
    <div className={`flex items-center gap-3 py-2 border-t border-white/5 text-sm ${off ? 'opacity-50' : ''}`}>
      {children}
      {onEdit && <Button size="sm" variant="outline" className="h-7 px-2 ml-auto shrink-0" onClick={onEdit}>Изменить</Button>}
    </div>
  );
}

export function Modal({ title, onClose, children, onSave, saving }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-white/10 bg-[#0b1020] p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between"><div className="font-bold text-white">{title}</div><button type="button" onClick={onClose} className="text-white/60">✕</button></div>
        {children}
        {onSave && <div className="flex gap-2 justify-end"><Button variant="outline" size="sm" onClick={onClose}>Отмена</Button><Button size="sm" disabled={saving} onClick={onSave}>Сохранить</Button></div>}
      </div>
    </div>
  );
}

export function Stat({ label, value }) {
  return <div className="rounded-xl border border-white/10 bg-white/5 p-3"><div className="text-[11px] text-text-muted">{label}</div><div className="text-lg font-bold text-white">{value}</div></div>;
}

export const EFFECTS = { auto_shift: 'Автозапуск смен', warehouse_guard: 'Защита склада', xp_x2: '×2 XP в City Pass' };
export const REWARD_TYPES = { container: 'Сундук', booster: 'Усилитель', nft: 'NFT' };
export const GRANT_ST = { waiting_stock: 'ждёт пополнения склада', reserved: 'закреплён (ждёт кошелёк/отправки)', sending: 'отправляется', delivered: 'в кошельке', failed: 'ошибка', };
export const ANOMALY = { too_late: 'Сессия старше 10 минут', impossible: 'Дольше реального времени', too_fast: 'Короче пауз между предметами', daily_cap: 'Дневной потолок партий', flat_reaction: 'Слишком ровная реакция (бот?)' };
