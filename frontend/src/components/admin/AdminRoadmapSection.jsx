import { useState, useEffect, useCallback } from 'react';
import { Map, Plus, Trash2, Pencil, X, Save, CheckCircle2, Clock, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const authHeaders = () => {
  const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

/**
 * Admin sub-panel (inside the «Объявления» tab → «Дорожная карта»).
 * Admin writes everything IN RUSSIAN; users read it auto-translated via
 * LibreTranslate. Phases → items (done / pending), plus a footer text.
 */
export default function AdminRoadmapSection() {
  const [phases, setPhases] = useState([]);
  const [footer, setFooter] = useState('');
  const [loading, setLoading] = useState(false);
  const [savingFooter, setSavingFooter] = useState(false);

  const [newPhaseTitle, setNewPhaseTitle] = useState('');
  const [editingPhaseId, setEditingPhaseId] = useState(null);
  const [editingPhaseTitle, setEditingPhaseTitle] = useState('');

  const [newItemText, setNewItemText] = useState({});   // {phaseId: text}
  const [editingItemId, setEditingItemId] = useState(null);
  const [editingItemText, setEditingItemText] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/admin/roadmap`, { headers: authHeaders() });
      const d = await r.json();
      setPhases(Array.isArray(d.phases) ? d.phases : []);
      setFooter(d.footer_text || '');
    } catch (e) {
      toast.error('Не удалось загрузить дорожную карту');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const api = async (path, method, body) => {
    const r = await fetch(`${API}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'error');
    return r.json().catch(() => ({}));
  };

  const saveFooter = async () => {
    setSavingFooter(true);
    try {
      await api('/admin/roadmap/footer', 'PUT', { text: footer });
      toast.success('Текст внизу сохранён');
    } catch { toast.error('Ошибка сохранения'); } finally { setSavingFooter(false); }
  };

  const addPhase = async () => {
    const title = newPhaseTitle.trim();
    if (!title) { toast.error('Введите название фазы'); return; }
    try {
      await api('/admin/roadmap/phase', 'POST', { title });
      setNewPhaseTitle('');
      await load();
    } catch { toast.error('Не удалось добавить фазу'); }
  };

  const savePhase = async (id) => {
    const title = editingPhaseTitle.trim();
    if (!title) { toast.error('Название не может быть пустым'); return; }
    try {
      await api(`/admin/roadmap/phase/${id}`, 'PUT', { title });
      setEditingPhaseId(null); setEditingPhaseTitle('');
      await load();
    } catch { toast.error('Ошибка сохранения'); }
  };

  const deletePhase = async (id) => {
    if (!window.confirm('Удалить фазу и все её пункты?')) return;
    try { await api(`/admin/roadmap/phase/${id}`, 'DELETE'); await load(); }
    catch { toast.error('Ошибка удаления'); }
  };

  const addItem = async (phaseId) => {
    const text = (newItemText[phaseId] || '').trim();
    if (!text) { toast.error('Введите текст пункта'); return; }
    try {
      await api('/admin/roadmap/item', 'POST', { phase_id: phaseId, text });
      setNewItemText((p) => ({ ...p, [phaseId]: '' }));
      await load();
    } catch { toast.error('Не удалось добавить пункт'); }
  };

  const saveItem = async (id) => {
    const text = editingItemText.trim();
    if (!text) { toast.error('Текст не может быть пустым'); return; }
    try {
      await api(`/admin/roadmap/item/${id}`, 'PUT', { text });
      setEditingItemId(null); setEditingItemText('');
      await load();
    } catch { toast.error('Ошибка сохранения'); }
  };

  const toggleItem = async (item) => {
    try { await api(`/admin/roadmap/item/${item.id}`, 'PUT', { done: !item.done }); await load(); }
    catch { toast.error('Ошибка'); }
  };

  const deleteItem = async (id) => {
    if (!window.confirm('Удалить пункт?')) return;
    try { await api(`/admin/roadmap/item/${id}`, 'DELETE'); await load(); }
    catch { toast.error('Ошибка удаления'); }
  };

  return (
    <div className="glass-panel rounded-2xl p-6 space-y-6" data-testid="admin-roadmap-section">
      <div className="flex items-center gap-2">
        <Map className="w-5 h-5 text-cyber-cyan" />
        <h2 className="font-unbounded text-lg font-bold text-text-main">Дорожная карта</h2>
      </div>
      <p className="text-xs text-text-muted">
        Пишите на русском — пользователи увидят перевод на своём языке автоматически (LibreTranslate).
      </p>

      {/* Add phase */}
      <div className="flex gap-2">
        <Input
          value={newPhaseTitle}
          onChange={(e) => setNewPhaseTitle(e.target.value)}
          placeholder="Название фазы (напр. «Фаза 1: Запуск»)"
          className="bg-black/40 border-white/10"
          data-testid="roadmap-new-phase-input"
        />
        <Button className="btn-cyber shrink-0" onClick={addPhase} data-testid="roadmap-add-phase-btn">
          <Plus className="w-4 h-4 mr-1" /> Фаза
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-8"><Loader2 className="w-6 h-6 animate-spin text-cyber-cyan" /></div>
      ) : (
        <div className="space-y-4">
          {phases.map((ph) => (
            <div key={ph.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-4" data-testid={`admin-roadmap-phase-${ph.id}`}>
              <div className="flex items-center gap-2 mb-3">
                {editingPhaseId === ph.id ? (
                  <>
                    <Input
                      value={editingPhaseTitle}
                      onChange={(e) => setEditingPhaseTitle(e.target.value)}
                      className="bg-black/40 border-white/10 h-8"
                      data-testid={`roadmap-edit-phase-input-${ph.id}`}
                    />
                    <Button size="sm" className="btn-cyber h-8" onClick={() => savePhase(ph.id)}><Save className="w-4 h-4" /></Button>
                    <Button size="sm" variant="outline" className="h-8 border-white/10" onClick={() => { setEditingPhaseId(null); setEditingPhaseTitle(''); }}><X className="w-4 h-4" /></Button>
                  </>
                ) : (
                  <>
                    <span className="flex-1 font-bold text-cyber-cyan">{ph.title}</span>
                    <button className="text-text-muted hover:text-white" onClick={() => { setEditingPhaseId(ph.id); setEditingPhaseTitle(ph.title || ''); }} data-testid={`roadmap-edit-phase-btn-${ph.id}`}><Pencil className="w-4 h-4" /></button>
                    <button className="text-red-400 hover:text-red-300" onClick={() => deletePhase(ph.id)} data-testid={`roadmap-delete-phase-btn-${ph.id}`}><Trash2 className="w-4 h-4" /></button>
                  </>
                )}
              </div>

              {/* Items */}
              <div className="space-y-2 mb-3">
                {(ph.items || []).map((it) => (
                  <div key={it.id} className="flex items-center gap-2" data-testid={`admin-roadmap-item-${it.id}`}>
                    <button onClick={() => toggleItem(it)} title="Выполнено / не выполнено" data-testid={`roadmap-toggle-item-${it.id}`}>
                      {it.done
                        ? <CheckCircle2 className="w-5 h-5 text-green-400" />
                        : <Clock className="w-5 h-5 text-yellow-400" />}
                    </button>
                    {editingItemId === it.id ? (
                      <>
                        <Input
                          value={editingItemText}
                          onChange={(e) => setEditingItemText(e.target.value)}
                          className="bg-black/40 border-white/10 h-8 flex-1"
                          data-testid={`roadmap-edit-item-input-${it.id}`}
                        />
                        <Button size="sm" className="btn-cyber h-8" onClick={() => saveItem(it.id)}><Save className="w-4 h-4" /></Button>
                        <Button size="sm" variant="outline" className="h-8 border-white/10" onClick={() => { setEditingItemId(null); setEditingItemText(''); }}><X className="w-4 h-4" /></Button>
                      </>
                    ) : (
                      <>
                        <span className={`flex-1 text-sm ${it.done ? 'text-text-muted line-through' : 'text-text-main'}`}>{it.text}</span>
                        <button className="text-text-muted hover:text-white" onClick={() => { setEditingItemId(it.id); setEditingItemText(it.text || ''); }} data-testid={`roadmap-edit-item-btn-${it.id}`}><Pencil className="w-4 h-4" /></button>
                        <button className="text-red-400 hover:text-red-300" onClick={() => deleteItem(it.id)} data-testid={`roadmap-delete-item-btn-${it.id}`}><Trash2 className="w-4 h-4" /></button>
                      </>
                    )}
                  </div>
                ))}
              </div>

              {/* Add item */}
              <div className="flex gap-2">
                <Input
                  value={newItemText[ph.id] || ''}
                  onChange={(e) => setNewItemText((p) => ({ ...p, [ph.id]: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === 'Enter') addItem(ph.id); }}
                  placeholder="Новый пункт..."
                  className="bg-black/40 border-white/10 h-8"
                  data-testid={`roadmap-new-item-input-${ph.id}`}
                />
                <Button size="sm" className="btn-cyber shrink-0 h-8" onClick={() => addItem(ph.id)} data-testid={`roadmap-add-item-btn-${ph.id}`}>
                  <Plus className="w-4 h-4" />
                </Button>
              </div>
            </div>
          ))}
          {phases.length === 0 && <p className="text-sm text-text-muted text-center py-4">Пока нет фаз. Добавьте первую фазу выше.</p>}
        </div>
      )}

      {/* Footer text */}
      <div className="space-y-2 border-t border-white/10 pt-4">
        <label className="text-xs uppercase tracking-widest text-text-muted">Текст внизу дорожной карты</label>
        <textarea
          value={footer}
          onChange={(e) => setFooter(e.target.value)}
          rows={3}
          placeholder="Например: «Есть идея? Поделитесь с нами!»"
          className="w-full resize-none rounded-xl bg-black/40 border border-white/10 p-3 text-sm text-text-main outline-none focus:border-cyber-cyan/60"
          data-testid="roadmap-footer-input"
        />
        <p className="text-[11px] text-text-muted">
          Ниже этого текста пользователю всегда показывается кнопка «💡 Предложить идею» (переведена автоматически).
        </p>
        <Button className="btn-cyber" onClick={saveFooter} disabled={savingFooter} data-testid="roadmap-save-footer-btn">
          {savingFooter ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
          Сохранить текст
        </Button>
      </div>
    </div>
  );
}
