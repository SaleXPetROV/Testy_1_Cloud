import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowLeft, BookOpen, ChevronDown } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const TITLE = { ru: 'Правила игры', en: 'Game rules', es: 'Reglas del juego', zh: '游戏规则', fr: 'Règles du jeu', de: 'Spielregeln', ja: 'ゲームルール', ko: '게임 규칙', id: 'Aturan permainan' };
const EMPTY = { ru: 'Правила пока не добавлены.', en: 'No rules added yet.', es: 'Aún no hay reglas.', zh: '暂无规则。', fr: 'Aucune règle pour le moment.', de: 'Noch keine Regeln.', ja: 'まだルールがありません。', ko: '아직 규칙이 없습니다.', id: 'Belum ada aturan.' };

export default function RulesPage() {
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`${API}/rules?lang=${encodeURIComponent(lang || 'ru')}`)
      .then((r) => r.json())
      .then((d) => { if (!cancelled) setRules(Array.isArray(d.rules) ? d.rules : []); })
      .catch(() => { if (!cancelled) setRules([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [lang]);

  return (
    <div className="min-h-screen bg-void" data-testid="rules-page">
      <div
        className="max-w-2xl mx-auto px-4 pb-32"
        style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 1.25rem)' }}
      >
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={() => navigate(-1)}
            data-testid="rules-back-btn"
            className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center text-text-muted hover:text-white transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-cyber-cyan" />
            <h1 className="font-unbounded text-xl font-bold text-text-main">{TITLE[lang] || TITLE.ru}</h1>
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="w-8 h-8 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : rules.length === 0 ? (
          <p className="text-sm text-text-muted text-center py-16" data-testid="rules-page-empty">{EMPTY[lang] || EMPTY.ru}</p>
        ) : (
          <div className="space-y-3">
            {rules.map((rule, idx) => {
              const isOpen = openId === rule.id;
              return (
                <motion.div
                  key={rule.id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: idx * 0.03 }}
                  className="rounded-2xl border border-white/10 bg-white/[0.02] overflow-hidden"
                  data-testid={`rules-page-item-${rule.id}`}
                >
                  <button
                    type="button"
                    onClick={() => setOpenId(isOpen ? null : rule.id)}
                    aria-expanded={isOpen}
                    data-testid={`rules-page-toggle-${rule.id}`}
                    className="w-full flex items-center gap-3 p-5 text-left hover:bg-white/[0.03] transition-colors"
                  >
                    <span className="flex-1 text-base font-bold text-cyber-cyan">
                      {idx + 1}. {rule.title || ''}
                    </span>
                    <motion.span
                      animate={{ rotate: isOpen ? 180 : 0 }}
                      transition={{ duration: 0.25 }}
                      className="shrink-0 text-text-muted"
                    >
                      <ChevronDown className="w-5 h-5" />
                    </motion.span>
                  </button>
                  <AnimatePresence initial={false}>
                    {isOpen && (
                      <motion.div
                        key="content"
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.3, ease: 'easeInOut' }}
                        className="overflow-hidden"
                        data-testid={`rules-page-content-${rule.id}`}
                      >
                        <div
                          className="rte-content text-sm text-text-main leading-relaxed px-5 pb-5"
                          dangerouslySetInnerHTML={{ __html: rule.content_html || '' }}
                        />
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
