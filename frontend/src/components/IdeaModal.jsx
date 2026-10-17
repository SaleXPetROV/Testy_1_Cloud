import { useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Lightbulb, Send, Loader2 } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;
const MAX_CHARS = 500;

const L = {
  title:   { ru: 'Предложить идею', en: 'Suggest an idea', es: 'Sugerir una idea', zh: '提出想法', fr: 'Proposer une idée', de: 'Idee vorschlagen', ja: 'アイデアを提案', ko: '아이디어 제안', id: 'Sarankan ide' },
  desc:    { ru: 'Опишите вашу идею. Она будет передана команде.', en: 'Describe your idea. It will be sent to the team.', es: 'Describe tu idea. Se enviará al equipo.', zh: '描述你的想法，它将发送给团队。', fr: 'Décrivez votre idée. Elle sera transmise à l’équipe.', de: 'Beschreibe deine Idee. Sie wird an das Team gesendet.', ja: 'アイデアを説明してください。チームに送信されます。', ko: '아이디어를 설명하세요. 팀에 전달됩니다.', id: 'Jelaskan ide Anda. Ini akan dikirim ke tim.' },
  ph:      { ru: 'Ваша идея...', en: 'Your idea...', es: 'Tu idea...', zh: '你的想法...', fr: 'Votre idée...', de: 'Deine Idee...', ja: 'あなたのアイデア...', ko: '아이디어...', id: 'Ide Anda...' },
  send:    { ru: 'Отправить', en: 'Send', es: 'Enviar', zh: '发送', fr: 'Envoyer', de: 'Senden', ja: '送信', ko: '보내기', id: 'Kirim' },
  ok:      { ru: 'Спасибо! Ваша идея отправлена.', en: 'Thanks! Your idea was sent.', es: '¡Gracias! Tu idea fue enviada.', zh: '谢谢！你的想法已发送。', fr: 'Merci ! Votre idée a été envoyée.', de: 'Danke! Deine Idee wurde gesendet.', ja: 'ありがとう！アイデアを送信しました。', ko: '감사합니다! 아이디어가 전송되었습니다.', id: 'Terima kasih! Ide Anda terkirim.' },
  err:     { ru: 'Не удалось отправить. Попробуйте позже.', en: 'Failed to send. Try again later.', es: 'No se pudo enviar. Inténtalo más tarde.', zh: '发送失败，请稍后再试。', fr: 'Échec de l’envoi. Réessayez plus tard.', de: 'Senden fehlgeschlagen. Versuche es später.', ja: '送信に失敗しました。後でお試しください。', ko: '전송 실패. 나중에 다시 시도하세요.', id: 'Gagal mengirim. Coba lagi nanti.' },
  empty:   { ru: 'Введите текст идеи', en: 'Enter your idea', es: 'Escribe tu idea', zh: '请输入想法', fr: 'Saisissez votre idée', de: 'Idee eingeben', ja: 'アイデアを入力', ko: '아이디어를 입력', id: 'Masukkan ide' },
};

export default function IdeaModal({ open, onOpenChange, language = 'ru' }) {
  const lang = language;
  const tr = (k) => (L[k] && (L[k][lang] || L[k].ru)) || '';
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);

  const submit = async () => {
    const value = text.trim();
    if (!value) { toast.error(tr('empty')); return; }
    setSending(true);
    try {
      const token = localStorage.getItem('token');
      await axios.post(`${API}/ideas`, { text: value.slice(0, MAX_CHARS) }, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      toast.success(tr('ok'));
      setText('');
      onOpenChange(false);
    } catch (e) {
      toast.error(tr('err'));
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!sending) onOpenChange(v); }}>
      <DialogContent className="glass-panel border-grid-border text-text-main max-w-md" data-testid="idea-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Lightbulb className="w-5 h-5 text-yellow-400" /> {tr('title')}
          </DialogTitle>
          <DialogDescription className="text-text-muted text-sm">{tr('desc')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <textarea
            data-testid="idea-textarea"
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
            maxLength={MAX_CHARS}
            placeholder={tr('ph')}
            rows={6}
            className="w-full h-40 resize-none overflow-y-auto rounded-xl bg-black/40 border border-white/10 p-3 text-sm text-text-main outline-none focus:border-cyber-cyan/60 break-words whitespace-pre-wrap"
            style={{ wordBreak: 'break-word' }}
          />
          <div className="flex justify-end">
            <span className="text-xs text-text-muted" data-testid="idea-char-count">{text.length}/{MAX_CHARS}</span>
          </div>
        </div>

        <Button
          className="btn-cyber w-full"
          onClick={submit}
          disabled={sending}
          data-testid="idea-submit-btn"
        >
          {sending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
          {tr('send')}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
