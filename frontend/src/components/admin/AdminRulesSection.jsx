import { useState, useEffect, useCallback } from 'react';
import { BookOpen, Plus, Trash2, Pencil, X, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import RichTextEditor from './RichTextEditor';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const authHeaders = () => {
  const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

/**
 * Admin sub-panel (inside the «Объявления» tab) to manage the «Правила игры».
 * Admin writes in Russian with a simple rich editor (bold/italic/colour/photo);
 * users read it auto-translated into their language via LibreTranslate.
 */
export default function AdminRulesSection() {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(false);
  const [editingId, setEditingId] = useState(null); // null = closed, 'new' = create
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/admin/rules`, { headers: authHeaders() });
      const d = await r.json();
      setRules(Array.isArray(d.rules) ? d.rules : []);
    } catch (e) {
      toast.error('Не удалось загрузить правила');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openNew = () => { setEditingId('new'); setTitle(''); setContent(''); };
  const openEdit = (rule) => { setEditingId(rule.id); setTitle(rule.title || ''); setContent(rule.content_html || ''); };
  const closeEditor = () => { setEditingId(null); setTitle(''); setContent(''); };

  const save = async () => {
    if (!content || !content.replace(/<[^>]+>/g, '').trim()) {
      toast.error('Добавьте текст правила');
      return;
    }
    setSaving(true);
    try {
      const isNew = editingId === 'new';
      const url = isNew ? `${API}/admin/rules` : `${API}/admin/rules/${editingId}`;
      const r = await fetch(url, {
        method: isNew ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ title, content_html: content }),
      });
      if (!r.ok) throw new Error('save failed');
      toast.success(isNew ? 'Пункт правил добавлен' : 'Пункт правил обновлён');
      closeEditor();
      load();
    } catch (e) {
      toast.error('Не удалось сохранить');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id) => {
    if (!window.confirm('Удалить этот пункт правил?')) return;
    try {
      const r = await fetch(`${API}/admin/rules/${id}`, { method: 'DELETE', headers: authHeaders() });
      if (!r.ok) throw new Error('delete failed');
      toast.success('Удалено');
      setRules((prev) => prev.filter((x) => x.id !== id));
    } catch (e) {
      toast.error('Не удалось удалить');
    }
  };

  return (
    <div className="mt-8 pt-6 border-t border-white/10" data-testid="admin-rules-section">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-cyan-300" />
          <h3 className="font-unbounded text-base font-bold text-text-main">Правила игры</h3>
        </div>
        {editingId === null && (
          <Button className="btn-cyber" onClick={openNew} data-testid="rules-add-btn">
            <Plus className="w-4 h-4 mr-2" />Добавить пункт
          </Button>
        )}
      </div>

      <p className="text-xs text-text-muted mb-4">
        Пишите на русском языке. Пользователю правила показываются на его языке (перевод через LibreTranslate),
        а вставленные фото сохраняются как есть.
      </p>

      {editingId !== null && (
        <div className="mb-5 rounded-xl border border-cyan-500/20 bg-cyan-500/[0.03] p-4 space-y-3" data-testid="rules-editor">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-text-main">
              {editingId === 'new' ? 'Новый пункт' : 'Редактирование пункта'}
            </p>
            <button onClick={closeEditor} className="text-text-muted hover:text-white" data-testid="rules-editor-close">
              <X className="w-4 h-4" />
            </button>
          </div>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Заголовок пункта (необязательно)"
            className="bg-black/30 border-white/10"
            data-testid="rules-title-input"
          />
          <RichTextEditor value={content} onChange={setContent} />
          <div className="flex gap-2 justify-end">
            <Button variant="outline" className="border-white/10" onClick={closeEditor}>Отмена</Button>
            <Button className="btn-cyber" onClick={save} disabled={saving} data-testid="rules-save-btn">
              <Save className="w-4 h-4 mr-2" />{saving ? 'Сохранение…' : 'Сохранить'}
            </Button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-text-muted">Загрузка…</p>
      ) : rules.length === 0 ? (
        <p className="text-sm text-text-muted" data-testid="rules-empty">Пунктов правил пока нет.</p>
      ) : (
        <div className="space-y-3" data-testid="rules-list">
          {rules.map((rule, idx) => (
            <div key={rule.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-4" data-testid={`rules-item-${rule.id}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-bold text-text-main mb-1">
                    {idx + 1}. {rule.title || 'Без заголовка'}
                  </p>
                  <div
                    className="rte-content text-xs text-text-muted max-h-32 overflow-hidden"
                    dangerouslySetInnerHTML={{ __html: rule.content_html || '' }}
                  />
                </div>
                <div className="flex gap-1.5 flex-shrink-0">
                  <button
                    onClick={() => openEdit(rule)}
                    className="w-8 h-8 flex items-center justify-center rounded-lg bg-white/5 border border-white/10 text-text-muted hover:text-cyan-300"
                    data-testid={`rules-edit-${rule.id}`}
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => remove(rule.id)}
                    className="w-8 h-8 flex items-center justify-center rounded-lg bg-white/5 border border-white/10 text-red-400 hover:text-red-300"
                    data-testid={`rules-delete-${rule.id}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
