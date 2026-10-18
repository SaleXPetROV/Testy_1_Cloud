import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import axios from 'axios';
import { ChevronLeft, CheckCircle2, Clock, Map, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useLanguage } from '@/context/LanguageContext';
import IdeaModal from '@/components/IdeaModal';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const L = {
  title:  { ru: 'Дорожная карта', en: 'Roadmap', es: 'Hoja de ruta', zh: '路线图', fr: 'Feuille de route', de: 'Roadmap', ja: 'ロードマップ', ko: '로드맵', id: 'Peta jalan' },
  idea:   { ru: '💡 Предложить идею', en: '💡 Suggest an idea', es: '💡 Sugerir una idea', zh: '💡 提出想法', fr: '💡 Proposer une idée', de: '💡 Idee vorschlagen', ja: '💡 アイデアを提案', ko: '💡 아이디어 제안', id: '💡 Sarankan ide' },
  empty:  { ru: 'Дорожная карта скоро появится.', en: 'The roadmap is coming soon.', es: 'La hoja de ruta llegará pronto.', zh: '路线图即将推出。', fr: 'La feuille de route arrive bientôt.', de: 'Die Roadmap kommt bald.', ja: 'ロードマップは近日公開。', ko: '로드맵이 곧 제공됩니다.', id: 'Peta jalan segera hadir.' },
};

export default function RoadmapPage() {
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const tr = (k) => (L[k] && (L[k][lang] || L[k].ru)) || '';

  const [loading, setLoading] = useState(true);
  const [phases, setPhases] = useState([]);
  const [footer, setFooter] = useState('');
  const [showIdea, setShowIdea] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    axios.get(`${API}/roadmap`, { params: { lang } })
      .then((r) => {
        if (!alive) return;
        setPhases(r.data.phases || []);
        setFooter(r.data.footer_text || '');
      })
      .catch(() => {})
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [lang]);

  return (
    <div className="min-h-screen bg-void" data-testid="roadmap-page">
      <div
        className="max-w-xl mx-auto px-4 pb-28 min-h-screen flex flex-col"
        style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 1.25rem)' }}
      >
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={() => navigate('/my-businesses')}
            data-testid="roadmap-back-btn"
            className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center hover:bg-white/20 transition-colors"
          >
            <ChevronLeft className="w-5 h-5 text-text-main" />
          </button>
          <h1 className="font-unbounded text-2xl font-bold text-text-main flex items-center gap-2">
            <Map className="w-6 h-6 text-cyber-cyan" /> {tr('title')}
          </h1>
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-cyber-cyan" /></div>
        ) : phases.length === 0 ? (
          <p className="text-center text-text-muted py-20">{tr('empty')}</p>
        ) : (
          <div className="space-y-6">
            {phases.map((ph, pi) => (
              <motion.div
                key={ph.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: pi * 0.06 }}
                className="relative rounded-2xl border border-cyber-cyan/20 bg-gradient-to-br from-cyber-cyan/5 to-neon-purple/5 p-5"
                data-testid={`roadmap-phase-${ph.id}`}
              >
                <h2 className="font-unbounded text-lg font-bold text-cyber-cyan mb-4">{ph.title}</h2>
                <div className="space-y-3">
                  {(ph.items || []).map((it) => (
                    <div
                      key={it.id}
                      className="flex items-start gap-3"
                      data-testid={`roadmap-item-${it.id}`}
                    >
                      {it.done ? (
                        <CheckCircle2 className="w-5 h-5 text-green-400 shrink-0 mt-0.5" data-testid={`roadmap-item-done-${it.id}`} />
                      ) : (
                        <Clock className="w-5 h-5 text-yellow-400 shrink-0 mt-0.5" data-testid={`roadmap-item-pending-${it.id}`} />
                      )}
                      <span className={`text-sm leading-relaxed ${it.done ? 'text-text-muted line-through' : 'text-text-main'}`}>
                        {it.text}
                      </span>
                    </div>
                  ))}
                  {(ph.items || []).length === 0 && (
                    <p className="text-xs text-text-muted/60">—</p>
                  )}
                </div>
              </motion.div>
            ))}
          </div>
        )}

        {!loading && footer && (
          <p className="text-sm text-text-muted text-center mt-8 whitespace-pre-wrap break-words">{footer}</p>
        )}

        <div className="mt-6">
          <Button
            className="btn-cyber w-full h-12"
            onClick={() => setShowIdea(true)}
            data-testid="roadmap-idea-btn"
          >
            {tr('idea')}
          </Button>
        </div>

        <p className="text-[10px] text-text-muted/60 uppercase tracking-widest text-center mt-auto pt-6">GRAM City Builder © 2026</p>
      </div>

      <IdeaModal open={showIdea} onOpenChange={setShowIdea} language={lang} />
    </div>
  );
}
