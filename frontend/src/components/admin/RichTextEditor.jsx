import { useRef, useEffect, useState } from 'react';
import { Bold, Italic, Underline, Palette, Image as ImageIcon, Eraser } from 'lucide-react';
import { toast } from 'sonner';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

/**
 * Lightweight WYSIWYG editor. The admin just types normally and can make text
 * bold / italic / underlined / coloured and drop an image anywhere in the text.
 * The value is stored as HTML; embedded pictures are inlined as data-URIs so
 * they survive the LibreTranslate pass on the user side.
 */
export const RichTextEditor = ({ value, onChange, placeholder = 'Введите текст правила…' }) => {
  const ref = useRef(null);
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  // Load initial value once (and when it changes from the outside, e.g. edit).
  useEffect(() => {
    if (ref.current && ref.current.innerHTML !== (value || '')) {
      ref.current.innerHTML = value || '';
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const emit = () => {
    if (ref.current && onChange) onChange(ref.current.innerHTML);
  };

  const exec = (cmd, arg = null) => {
    ref.current?.focus();
    document.execCommand(cmd, false, arg);
    emit();
  };

  const handleColor = (e) => exec('foreColor', e.target.value);

  const handlePickImage = () => fileRef.current?.click();

  const handleImage = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { toast.error('Изображение должно быть ≤ 2 МБ'); return; }
    setUploading(true);
    try {
      const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch(`${API}/admin/announcement/upload-image`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      });
      const d = await r.json();
      if (!r.ok || !d.url) throw new Error(d.detail || 'upload failed');
      ref.current?.focus();
      document.execCommand('insertHTML', false,
        `<img src="${d.url}" style="max-width:100%;border-radius:12px;margin:8px 0;" />`);
      emit();
    } catch (err) {
      toast.error('Не удалось загрузить изображение');
    } finally {
      setUploading(false);
    }
  };

  const Btn = ({ onClick, title, children, testid }) => (
    <button
      type="button"
      title={title}
      data-testid={testid}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      className="w-9 h-9 flex items-center justify-center rounded-lg bg-white/5 border border-white/10 text-text-muted hover:text-cyan-300 hover:border-cyan-500/40 transition-colors"
    >
      {children}
    </button>
  );

  return (
    <div className="rounded-xl border border-white/10 bg-black/30 overflow-hidden">
      <div className="flex items-center gap-1.5 p-2 border-b border-white/10 bg-white/[0.02] flex-wrap">
        <Btn onClick={() => exec('bold')} title="Жирный" testid="rte-bold"><Bold className="w-4 h-4" /></Btn>
        <Btn onClick={() => exec('italic')} title="Курсив" testid="rte-italic"><Italic className="w-4 h-4" /></Btn>
        <Btn onClick={() => exec('underline')} title="Подчёркнутый" testid="rte-underline"><Underline className="w-4 h-4" /></Btn>
        <label
          title="Цвет текста"
          className="w-9 h-9 flex items-center justify-center rounded-lg bg-white/5 border border-white/10 text-text-muted hover:text-cyan-300 hover:border-cyan-500/40 transition-colors cursor-pointer relative"
          onMouseDown={(e) => e.preventDefault()}
        >
          <Palette className="w-4 h-4" />
          <input type="color" onChange={handleColor} className="absolute inset-0 opacity-0 cursor-pointer" data-testid="rte-color" />
        </label>
        <Btn onClick={handlePickImage} title="Вставить фото" testid="rte-image">
          {uploading ? <span className="w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" /> : <ImageIcon className="w-4 h-4" />}
        </Btn>
        <div className="w-px h-6 bg-white/10 mx-1" />
        <Btn onClick={() => exec('removeFormat')} title="Очистить формат" testid="rte-clear"><Eraser className="w-4 h-4" /></Btn>
        <input ref={fileRef} type="file" accept="image/*" onChange={handleImage} className="hidden" />
      </div>
      <div
        ref={ref}
        contentEditable
        onInput={emit}
        onBlur={emit}
        data-placeholder={placeholder}
        data-testid="rte-content"
        className="rte-content min-h-[160px] max-h-[420px] overflow-y-auto p-4 text-sm text-text-main focus:outline-none leading-relaxed"
        suppressContentEditableWarning
      />
    </div>
  );
};

export default RichTextEditor;
