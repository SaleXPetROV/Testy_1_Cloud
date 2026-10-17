import { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MessageSquare, Activity, Archive, Info, Send, Image as ImageIcon,
  Copy, LogIn, X as XIcon, Search, RefreshCw, ShieldAlert, Lock, KeyRound,
  Languages, Building2, Loader2,
} from 'lucide-react';
import axios from 'axios';
import { toast } from 'sonner';
import ImageLightbox from '../components/ImageLightbox';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// Корректно определяем src для картинки в чате.
// image_url может приходить как data-URI (data:image/...;base64,...),
// абсолютный URL (http/https) или относительный путь. BACKEND_URL
// добавляем только к относительным путям — иначе картинка не отобразится.
const resolveImageSrc = (url) => {
  if (!url) return '';
  if (url.startsWith('data:') || url.startsWith('http://') || url.startsWith('https://') || url.startsWith('blob:')) {
    return url;
  }
  return `${BACKEND_URL}${url}`;
};

const fmtTime = (iso) => {
  try { return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }); } catch { return ''; }
};
// Full stamp with date + year + time. Agents asked for the year to
// be visible on every message so they can tell recent vs old chats
// apart at a glance.
const fmtDateTime = (iso) => {
  try {
    const d = new Date(iso);
    return d.toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return ''; }
};
const fmtDate = (iso) => {
  try { return new Date(iso).toLocaleString('ru-RU'); } catch { return ''; }
};

// Project languages available for the agent's "send in language" selector.
const SUPPORT_LANG_OPTIONS = [
  { code: 'ru', label: 'Русский' },
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Español' },
  { code: 'zh', label: '中文' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'ja', label: '日本語' },
  { code: 'ko', label: '한국어' },
];

// Returns the current auth token to use for sys-ops calls, preferring support_token
const getAuthToken = () => {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('support_token') || localStorage.getItem('token') || null;
};
const authHeaders = () => {
  const t = getAuthToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
};

// ─── Login Gate ──────────────────────────────────────────────────────────────
function LoginGate({ onLoggedIn }) {
  const [stage, setStage] = useState('checking'); // checking | password | done | error
  const [error, setError] = useState('');
  const [agentInfo, setAgentInfo] = useState(null); // { telegram_id, display_name, avatar_url, needs_password }
  const [loginSession, setLoginSession] = useState(null);
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;
    (async () => {
      try {
        const params = new URLSearchParams(window.location.search);
        const oneTime = params.get('login_token');
        if (oneTime) {
          // Strip login_token from URL ASAP
          params.delete('login_token');
          const qs = params.toString();
          const newUrl = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash;
          window.history.replaceState({}, '', newUrl);

          // Drop ANY stale tokens left over from a previous session — they
          // would otherwise let /whoami succeed/fail in unpredictable ways
          // while we're still in the middle of the password flow.
          try { localStorage.removeItem('support_token'); } catch {}
          try { localStorage.removeItem('token'); } catch {}
          try { localStorage.removeItem('ton_city_token'); } catch {}

          try {
            const res = await axios.post(`${API}/sys-ops/auth/exchange`, { token: oneTime });
            setAgentInfo(res.data);
            setLoginSession(res.data.login_session);
            setStage('password');
            return;
          } catch (e) {
            setError(e.response?.data?.detail || 'Ссылка недействительна или уже использована');
            setStage('error');
            return;
          }
        }
        // No login_token. If user already has support_token or main token, hand off control to parent
        // for whoami check. Otherwise show "access required" stage.
        if (getAuthToken()) {
          onLoggedIn();
        } else {
          setStage('error');
          setError('Доступ только по одноразовой ссылке от бота');
        }
      } catch (e) {
        setStage('error');
        setError(String(e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    setError('');
    if (password.length < 6) {
      setError('Пароль должен быть не короче 6 символов');
      return;
    }
    if (agentInfo?.needs_password && password !== password2) {
      setError('Пароли не совпадают');
      return;
    }
    setSubmitting(true);
    try {
      const url = agentInfo.needs_password ? `${API}/sys-ops/auth/set-password` : `${API}/sys-ops/auth/login`;
      const res = await axios.post(url, { login_session: loginSession, password });
      localStorage.setItem('support_token', res.data.support_token);
      // Remove regular main token for clean isolation on this device
      // (admin can still use main token elsewhere)
      toast.success(agentInfo.needs_password ? 'Пароль создан, добро пожаловать!' : 'Вход выполнен');
      onLoggedIn();
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка входа');
      // On 401 (consumed session), force re-issue
      if (e.response?.status === 401) {
        setStage('error');
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (stage === 'checking') {
    return (
      <div className="min-h-screen bg-void flex items-center justify-center text-white/40">
        <div className="text-center">
          <Lock className="w-8 h-8 mx-auto mb-2 animate-pulse" />
          <div>Проверяем доступ…</div>
        </div>
      </div>
    );
  }

  if (stage === 'error') {
    return (
      <div className="min-h-screen bg-void flex items-center justify-center text-white">
        <div className="text-center max-w-md p-6">
          <ShieldAlert className="w-12 h-12 text-red-400 mx-auto mb-3" />
          <div className="text-xl font-bold mb-2">404 — Not Found</div>
          {error && (
            <div className="text-sm text-white/50 mt-3 bg-white/5 border border-white/10 rounded-lg p-3">
              {error}
            </div>
          )}
          <div className="text-xs text-white/30 mt-4">
            Запросите новую одноразовую ссылку у бота: <span className="font-mono">/start</span>
          </div>
        </div>
      </div>
    );
  }

  // stage === 'password'
  return (
    <div className="min-h-screen bg-void flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white/5 border border-white/10 rounded-2xl p-6 shadow-2xl">
        <div className="text-center mb-5">
          {agentInfo?.avatar_url ? (
            <img src={`${BACKEND_URL}${agentInfo.avatar_url}`} alt="" className="w-16 h-16 mx-auto rounded-full object-cover mb-2" />
          ) : (
            <div className="w-16 h-16 mx-auto rounded-full bg-cyan-500/30 flex items-center justify-center text-2xl mb-2">
              {(agentInfo?.display_name || '?').slice(0, 2)}
            </div>
          )}
          <h2 className="text-xl font-bold text-white">{agentInfo?.display_name}</h2>
          <div className="text-xs text-white/40 font-mono">TG: {agentInfo?.telegram_id}</div>
        </div>

        <div className="mb-4 text-center">
          {agentInfo?.needs_password ? (
            <div className="text-cyan-300 text-sm font-semibold flex items-center justify-center gap-2">
              <KeyRound className="w-4 h-4" /> Создайте пароль для входа
            </div>
          ) : (
            <div className="text-cyan-300 text-sm">Введите пароль</div>
          )}
        </div>

        <div className="space-y-3">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={agentInfo?.needs_password ? 'Новый пароль (мин. 6 символов)' : 'Пароль'}
            className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2.5 text-sm text-white"
            data-testid="agent-password-input"
            autoFocus
          />
          {agentInfo?.needs_password && (
            <input
              type="password"
              value={password2}
              onChange={(e) => setPassword2(e.target.value)}
              placeholder="Повторите пароль"
              className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2.5 text-sm text-white"
              data-testid="agent-password2-input"
            />
          )}
          {error && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg p-2">{error}</div>
          )}
          <button
            onClick={submit}
            disabled={submitting || !password}
            className="w-full py-2.5 bg-gradient-to-r from-cyan-500 to-blue-500 text-white rounded-lg font-semibold disabled:opacity-40"
            data-testid="agent-submit-password"
          >
            {submitting ? 'Загрузка...' : (agentInfo?.needs_password ? 'Создать пароль и войти' : 'Войти')}
          </button>
        </div>

        <div className="text-[10px] text-white/30 text-center mt-4">
          Ссылка действует только один раз. Для повторного входа запросите новую через бот.
        </div>
      </div>
    </div>
  );
}

export default function SupportAgentPage() {
  const navigate = useNavigate();
  const [me, setMe] = useState(null); // { telegram_id, is_admin, agent }
  const [forbidden, setForbidden] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  // Capture WHETHER the page was opened with a one-time login_token at mount
  // time. We keep this flag in state for the entire lifetime of the page so
  // the LoginGate stays mounted even AFTER the URL has been stripped by
  // history.replaceState and parent re-renders (e.g. when checkAuth resolves
  // a stale token in localStorage as "forbidden"). Without this snapshot the
  // gate gets unmounted mid-exchange and the agent sees the outer 404 with
  // "Запросите ссылку у бота" instead of the password input.
  const [arrivedWithLoginToken] = useState(() => {
    try {
      if (typeof window === 'undefined') return false;
      return !!new URLSearchParams(window.location.search).get('login_token');
    } catch { return false; }
  });
  const [loginFlowDone, setLoginFlowDone] = useState(false);

  // Magic-link auto-login: ?auth=<jwt> → save to localStorage and strip from URL.
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const t = params.get('auth');
      if (t) {
        localStorage.setItem('token', t);
        params.delete('auth');
        const qs = params.toString();
        const newUrl = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash;
        window.history.replaceState({}, '', newUrl);
      }
    } catch {}
  }, []);
  const [tab, setTab] = useState('new'); // new | active | archive | info
  const [chats, setChats] = useState([]);
  const [selected, setSelected] = useState(null); // chat
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  // Локальное превью + спиннер, пока фото отправляется на сервер
  const [uploading, setUploading] = useState(null); // { previewUrl, name } | null
  // Полноэкранный просмотр картинки с зумом (лайтбокс)
  const [lightboxSrc, setLightboxSrc] = useState(null);
  // Per-message translation cache for the agent UI: { [msgId]: { text, loading, shown } }
  const [translations, setTranslations] = useState({});
  // Target language for outgoing agent messages (auto-set to the user's language).
  const [sendLang, setSendLang] = useState('ru');
  const [searchChatId, setSearchChatId] = useState('');
  const [searchUserId, setSearchUserId] = useState('');
  const [userInfo, setUserInfo] = useState(null);
  const [seizedList, setSeizedList] = useState([]);
  const fetchSeized = useCallback(async () => {
    try {
      const tok = getAuthToken();
      const res = await axios.get(`${API}/sys-ops/seized`, { headers: { Authorization: `Bearer ${tok}` } });
      setSeizedList(res.data.seized || []);
    } catch (e) { /* ignore */ }
  }, []);
  useEffect(() => { if (tab === 'seized') fetchSeized(); }, [tab, fetchSeized]);
  const seizedSetPrice = async (listingId, price) => {
    try {
      const tok = getAuthToken();
      await axios.post(`${API}/sys-ops/seized/${listingId}/price`, { price }, { headers: { Authorization: `Bearer ${tok}` } });
      toast.success('Цена обновлена'); fetchSeized();
    } catch (e) { toast.error(e.response?.data?.detail || 'Ошибка'); }
  };
  const seizedReturn = async (listingId) => {
    try {
      const tok = getAuthToken();
      await axios.post(`${API}/sys-ops/seized/${listingId}/return`, {}, { headers: { Authorization: `Bearer ${tok}` } });
      toast.success('Бизнес возвращён владельцу'); fetchSeized();
    } catch (e) { toast.error(e.response?.data?.detail || 'Ошибка'); }
  };
  const [searchTxId, setSearchTxId] = useState('');
  const [foundTx, setFoundTx] = useState(null);
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  // Auth check using support_token first, then main token
  const checkAuth = useCallback(async () => {
    const t = getAuthToken();
    if (!t) {
      setForbidden(true);
      setAuthChecked(true);
      return;
    }
    try {
      const res = await axios.get(`${API}/sys-ops/whoami`, { headers: { Authorization: `Bearer ${t}` } });
      setMe(res.data);
      setAuthChecked(true);
    } catch (e) {
      // If support_token is invalid, drop it and try main token
      if (e.response?.status === 401 || e.response?.status === 404) {
        if (localStorage.getItem('support_token')) {
          localStorage.removeItem('support_token');
          // try again with main token
          const t2 = localStorage.getItem('token');
          if (t2) {
            try {
              const r2 = await axios.get(`${API}/sys-ops/whoami`, { headers: { Authorization: `Bearer ${t2}` } });
              setMe(r2.data);
              setAuthChecked(true);
              return;
            } catch {}
          }
        }
        setForbidden(true);
      }
      setAuthChecked(true);
    }
  }, []);

  useEffect(() => { checkAuth(); }, [checkAuth]);

  const fetchChats = useCallback(async (statusOverride) => {
    if (!me) return;
    const status = statusOverride || tab;
    if (status === 'info') return;
    // Frontend tab key is 'archive' but backend expects 'archived'.
    const apiStatus = status === 'archive' ? 'archived' : status;
    try {
      const res = await axios.get(`${API}/sys-ops/chats?status=${apiStatus}`, { headers: authHeaders() });
      setChats(res.data.chats || []);
    } catch (e) {
      console.error(e);
    }
  }, [tab, me]);

  const messageIdsRef = useRef(new Set());
  const selectedRef = useRef(null);
  const wsReconnectTimerRef = useRef(null);
  const wsPingTimerRef = useRef(null);

  useEffect(() => { selectedRef.current = selected; }, [selected]);

  // Singleton-with-unlock droplet sound. Creating a new Audio() per message
  // (the previous behaviour) means autoplay-policy rejection on the FIRST
  // event before any user interaction — the agent gets new chats while sitting
  // idle on the panel and hears nothing. The module-level effect below
  // registers a one-time pointer/key gesture to unlock playback.
  const playDroplet = useCallback(() => {
    try {
      let a = window.__tc_agent_droplet;
      if (!a) {
        a = new Audio('/sounds/droplet.mp3');
        a.preload = 'auto';
        a.volume = 0.55;
        window.__tc_agent_droplet = a;
      }
      a.currentTime = 0;
      a.play().catch(() => {});
    } catch {}
  }, []);

  useEffect(() => {
    if (window.__tc_agent_droplet_unlocked) return;
    const unlock = () => {
      try {
        let a = window.__tc_agent_droplet;
        if (!a) {
          a = new Audio('/sounds/droplet.mp3');
          a.preload = 'auto';
          a.volume = 0.55;
          window.__tc_agent_droplet = a;
        }
        a.muted = true;
        const p = a.play();
        if (p && typeof p.then === 'function') {
          p.then(() => { a.pause(); a.currentTime = 0; a.muted = false; }).catch(() => {});
        } else {
          a.pause(); a.currentTime = 0; a.muted = false;
        }
      } catch (_) {}
      window.__tc_agent_droplet_unlocked = true;
      window.removeEventListener('pointerdown', unlock, true);
      window.removeEventListener('keydown', unlock, true);
      window.removeEventListener('touchstart', unlock, true);
    };
    window.addEventListener('pointerdown', unlock, true);
    window.addEventListener('keydown', unlock, true);
    window.addEventListener('touchstart', unlock, true);
    return () => {
      window.removeEventListener('pointerdown', unlock, true);
      window.removeEventListener('keydown', unlock, true);
      window.removeEventListener('touchstart', unlock, true);
    };
  }, []);

  const pushMessage = useCallback((m) => {
    if (!m || !m.id) return;
    if (messageIdsRef.current.has(m.id)) return;
    messageIdsRef.current.add(m.id);
    setMessages((prev) => [...prev, m]);
  }, []);

  const markRead = useCallback(async (chatId) => {
    if (!chatId) return;
    try {
      await axios.post(`${API}/sys-ops/chat/${chatId}/mark-read`, {}, { headers: authHeaders() });
    } catch {}
  }, []);

  const fetchMessages = useCallback(async (chatId) => {
    try {
      const res = await axios.get(`${API}/sys-ops/chat/${chatId}`, { headers: authHeaders() });
      setSelected(res.data.chat);
      const msgs = res.data.messages || [];
      messageIdsRef.current = new Set(msgs.map((m) => m.id));
      setMessages(msgs);
      markRead(chatId);
      fetchChats();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    }
  }, [markRead, fetchChats]);

  useEffect(() => { fetchChats(); }, [tab, fetchChats]);

  // WebSocket with reconnect + ping. We try `/api/ws/support/agent` first
  // because that path is reliably proxied with WebSocket upgrade by typical
  // production nginx configs (the legacy `/api/ws/...` location). On 404
  // (older backend without the alias) we fall back to `/api/support/ws/agent`.
  useEffect(() => {
    if (!me) return;
    let stopped = false;
    let aliasFailed = false;
    const connect = () => {
      const wsToken = getAuthToken();
      if (!wsToken || stopped) return;
      const wsBase = BACKEND_URL.replace('http', 'ws');
      const path = aliasFailed
        ? '/api/support/ws/agent'
        : '/api/ws/support/agent';
      const wsUrl = `${wsBase}${path}`;
      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;
        // If the alias 404s during handshake, immediately retry the legacy path.
        let openedOnce = false;
        ws.addEventListener('open', () => { openedOnce = true; });
        ws.addEventListener('close', (ev) => {
          // 1006 (abnormal close before open) typically signals an nginx 404
          // because the server never completed the WS handshake.
          if (!openedOnce && !aliasFailed && (ev.code === 1006 || ev.code === 1002)) {
            aliasFailed = true;
            if (!stopped) setTimeout(connect, 50);
          }
        });
        ws.onopen = () => {
          // F8: authenticate via the first frame (token no longer in the URL).
          try { ws.send(JSON.stringify({ action: 'auth', token: wsToken })); } catch {}
          if (wsPingTimerRef.current) clearInterval(wsPingTimerRef.current);
          wsPingTimerRef.current = setInterval(() => {
            try { ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ action: 'ping' })); } catch {}
          }, 10000);
        };
        ws.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data);
            const cur = selectedRef.current;
            if (data.type === 'new_chat') {
              fetchChats();
              playDroplet();
            } else if (data.type === 'chat_claimed' || data.type === 'chat_closed' || data.type === 'chat_updated') {
              fetchChats();
              if (cur && data.chat_id === cur.id) fetchMessages(cur.id);
            } else if (data.type === 'new_message') {
              if (cur && data.chat_id === cur.id) {
                pushMessage(data.message);
                if (data.message?.sender_type === 'user') {
                  playDroplet();
                  markRead(cur.id);
                }
              } else {
                playDroplet();
              }
              fetchChats();
            }
          } catch {}
        };
        ws.onclose = () => {
          wsRef.current = null;
          if (wsPingTimerRef.current) clearInterval(wsPingTimerRef.current);
          if (!stopped && !wsReconnectTimerRef.current) {
            wsReconnectTimerRef.current = setTimeout(() => {
              wsReconnectTimerRef.current = null;
              if (!stopped) connect();
            }, 3000);
          }
        };
        ws.onerror = () => { try { ws.close(); } catch {} };
      } catch (e) { console.error(e); }
    };
    connect();
    return () => {
      stopped = true;
      if (wsReconnectTimerRef.current) { clearTimeout(wsReconnectTimerRef.current); wsReconnectTimerRef.current = null; }
      if (wsPingTimerRef.current) { clearInterval(wsPingTimerRef.current); wsPingTimerRef.current = null; }
      try { wsRef.current && wsRef.current.close(); } catch {}
    };
  }, [me, fetchChats, fetchMessages, pushMessage, markRead, playDroplet]);

  // Resilient polling fallback every 7s — re-syncs chats + currently-open
  // chat messages so the agent never has to hit Refresh manually.
  useEffect(() => {
    if (!me) return;
    const id = setInterval(() => {
      try {
        fetchChats();
        const cur = selectedRef.current;
        if (cur && cur.id) {
          axios.get(`${API}/sys-ops/chat/${cur.id}`, { headers: authHeaders() })
            .then((res) => {
              const msgs = res.data.messages || [];
              msgs.forEach((m) => pushMessage(m));
              if (res.data.chat) setSelected((c) => c ? { ...c, ...res.data.chat } : res.data.chat);
            }).catch(() => {});
        }
      } catch {}
    }, 7000);
    return () => clearInterval(id);
  }, [me, fetchChats, pushMessage]);

  // Auto-scroll only inside messages container
  const messagesContainerRef = useRef(null);
  useEffect(() => {
    const el = messagesContainerRef.current;
    if (el) requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
  }, [messages]);

  // Lock body scroll on this page
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  const claimChat = async () => {
    if (!selected) return;
    try {
      const res = await axios.post(`${API}/sys-ops/chat/${selected.id}/claim`, {}, { headers: authHeaders() });
      toast.success('Подключено');
      setTab('active');
      setSelected(res.data.chat);
      fetchMessages(selected.id);
      fetchChats('active');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    }
  };

  const sendMessage = async (translate = false) => {
    if (!input.trim() || !selected) return;
    const content = input.trim();
    setInput('');
    try {
      const body = { content };
      // "Translate & send": agent typed Russian, deliver it in `sendLang`.
      if (translate && sendLang && sendLang !== 'ru') body.target_lang = sendLang;
      const res = await axios.post(`${API}/sys-ops/chat/${selected.id}/message`, body, { headers: authHeaders() });
      pushMessage(res.data.message);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
      setInput(content);
    }
  };

  // Auto-select the outgoing language to the user's project language when a
  // chat is opened; the agent can still change it in the selector.
  useEffect(() => {
    if (selected?.user_language) setSendLang(selected.user_language);
  }, [selected?.id, selected?.user_language]);

  // Translate an incoming user message (always to Russian for the agent).
  const translateMsg = async (m, target = 'ru') => {
    const ex = translations[m.id];
    if (ex && ex.text) {
      setTranslations((p) => ({ ...p, [m.id]: { ...ex, shown: !ex.shown } }));
      return;
    }
    setTranslations((p) => ({ ...p, [m.id]: { loading: true, shown: true } }));
    try {
      const res = await axios.post(`${API}/sys-ops/message/${m.id}/translate`, { target_lang: target }, { headers: authHeaders() });
      setTranslations((p) => ({ ...p, [m.id]: { text: res.data.translation, loading: false, shown: true } }));
    } catch (e) {
      setTranslations((p) => { const c = { ...p }; delete c[m.id]; return c; });
      toast.error(e.response?.data?.detail || 'Ошибка перевода');
    }
  };

  const uploadImage = async (file) => {
    if (!file || !selected) return;
    // Сразу показываем локальное превью + спиннер, пока идёт загрузка на сервер
    const previewUrl = URL.createObjectURL(file);
    setUploading({ previewUrl, name: file.name || 'image' });
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await axios.post(`${API}/sys-ops/chat/${selected.id}/upload`, fd, { headers: { ...authHeaders(), 'Content-Type': 'multipart/form-data' } });
      pushMessage(res.data.message);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    } finally {
      // Убираем индикатор и освобождаем blob-URL независимо от результата
      URL.revokeObjectURL(previewUrl);
      setUploading(null);
    }
  };

  const closeChat = async () => {
    if (!selected) return;
    if (!window.confirm('Завершить чат?')) return;
    try {
      await axios.post(`${API}/sys-ops/chat/${selected.id}/close`, {}, { headers: authHeaders() });
      toast.success('Чат завершён и перемещён в архив');
      // Auto-switch to Archive tab so the agent sees where the chat went,
      // and explicitly refresh the archive list (cannot rely on the tab-
      // change useEffect because React batches state and the fetch would
      // otherwise race the WS chat_closed broadcast that fires fetchChats
      // with the old tab value).
      setTab('archive');
      setSelected(null);
      try { await fetchChats('archive'); } catch {}
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    }
  };

  const fetchUserInfo = async () => {
    if (!searchUserId.trim()) return;
    try {
      const res = await axios.get(`${API}/sys-ops/user-info/${searchUserId.trim()}`, { headers: authHeaders() });
      setUserInfo(res.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
      setUserInfo(null);
    }
  };

  const fetchTx = async () => {
    if (!searchTxId.trim()) return;
    try {
      const res = await axios.get(`${API}/sys-ops/operation/${searchTxId.trim()}`, { headers: authHeaders() });
      setFoundTx(res.data.operation);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
      setFoundTx(null);
    }
  };

  const filteredChats = (tab === 'archive' && searchChatId)
    ? chats.filter((c) => (c.id || '').toLowerCase().includes(searchChatId.toLowerCase()) || (c.short_id || '').toLowerCase().includes(searchChatId.toLowerCase()))
    : chats;

  // Show LoginGate if the page was opened with a login_token (even after
  // the URL is stripped), or when authentication is missing entirely. We
  // also drop any stale support_token / main token on the way so a leftover
  // 401 from /whoami doesn't bounce the user to the outer 404 mid-flow.
  if (arrivedWithLoginToken && !loginFlowDone) {
    return <LoginGate onLoggedIn={() => {
      setLoginFlowDone(true);
      setForbidden(false);
      setAuthChecked(false);
      checkAuth();
    }} />;
  }
  if (authChecked && forbidden && !getAuthToken()) {
    return <LoginGate onLoggedIn={() => {
      setForbidden(false);
      setAuthChecked(false);
      checkAuth();
    }} />;
  }

  if (forbidden) {
    return (
      <div className="min-h-screen bg-void flex items-center justify-center text-white">
        <div className="text-center">
          <ShieldAlert className="w-12 h-12 text-red-400 mx-auto mb-2" />
          <div className="text-xl font-bold">404 — Not Found</div>
          <div className="text-xs text-white/40 mt-2">Запросите ссылку у бота: /start</div>
        </div>
      </div>
    );
  }
  if (!me) return <div className="min-h-screen bg-void flex items-center justify-center text-white/40">Loading...</div>;

  const TabBtn = ({ k, label, Icon }) => (
    <button
      onClick={() => { setTab(k); setSelected(null); }}
      className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition ${
        tab === k ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-400/40' : 'text-white/60 hover:text-white hover:bg-white/5'
      }`}
      data-testid={`agent-tab-${k}`}
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  );

  return (
    <div className="h-screen bg-void text-white flex flex-col overflow-hidden">
      {/* Top bar */}
      <div className="border-b border-white/10 bg-black/40 backdrop-blur px-4 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-5 h-5 text-cyan-400" />
          <span className="font-bold">Support Agent Panel</span>
        </div>
        <div className="flex items-center gap-3">
          <TabBtn k="new" label="Новые" Icon={MessageSquare} />
          <TabBtn k="active" label="Активные" Icon={Activity} />
          <TabBtn k="archive" label="Архив" Icon={Archive} />
          <TabBtn k="seized" label="Изъятые" Icon={Building2} />
          <TabBtn k="info" label="Информация" Icon={Info} />
        </div>
        <div className="text-right">
          <div className="text-[10px] text-white/40 uppercase">Agent ID</div>
          <div className="text-sm font-mono text-cyan-300" data-testid="agent-tg-id">{me.telegram_id}{me.is_admin ? ' (admin)' : ''}</div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {tab === 'seized' ? (
          /* SEIZED TAB — parity with admin «Кредиты → Изъятые» */
          <div className="flex-1 overflow-y-auto p-6" data-testid="agent-seized-panel">
            <div className="max-w-5xl mx-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-bold flex items-center gap-2"><Building2 className="w-5 h-5 text-red-400" /> Изъятые бизнесы ({seizedList.length})</h3>
                <button onClick={fetchSeized} className="px-3 py-1.5 bg-white/10 rounded text-xs" data-testid="agent-seized-refresh">Обновить</button>
              </div>
              <p className="text-xs text-white/50 mb-4">Изъяты системой (прочность 0% 7 дней или дефолт по кредиту), выставлены от имени GRAM CITY. Владелец не может снять с продажи. Можно изменить цену или вернуть владельцу (если не продан).</p>
              {seizedList.length === 0 ? (
                <p className="text-white/40 text-center py-10 text-sm">Изъятых бизнесов нет</p>
              ) : (
                <div className="space-y-3">
                  {seizedList.map((row) => (
                    <div key={row.listing_id} className="bg-white/5 border border-white/10 rounded-xl p-4" data-testid={`agent-seized-row-${row.business_id}`}>
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="font-bold">{row.business?.name?.ru || row.business?.name?.en || row.business?.type} · Lv{row.business?.level || 1}</div>
                          <div className="text-[11px] text-white/40 font-mono">ID: {row.business_id}</div>
                          <div className="text-[11px] text-white/40">Изъят: {row.seized_at ? new Date(row.seized_at).toLocaleString('ru-RU') : '—'} · Причина: {row.seizure_reason === 'credit_default' ? 'Кредит' : 'Прочность'}</div>
                          <div className="text-[11px] text-white/40">Бывший владелец: {row.former_owner_username || row.former_owner_id}</div>
                          {row.sold && <div className="text-[11px] text-emerald-300">Куплен: {row.buyer_username || row.buyer_id} · {row.sold_at ? new Date(row.sold_at).toLocaleString('ru-RU') : ''}</div>}
                        </div>
                        <div className="flex items-center gap-2">
                          {row.sold ? (
                            <span className="text-sm text-amber-400 font-bold">{(row.price || 0).toFixed(2)} TON</span>
                          ) : (
                            <>
                              <input type="number" step="0.01" defaultValue={(row.price || 0).toFixed(2)} id={`ag-seized-price-${row.listing_id}`}
                                className="w-24 bg-black/40 border border-white/20 rounded px-2 py-1 text-right text-sm" data-testid={`agent-seized-price-${row.business_id}`} />
                              <button className="px-2 py-1 rounded bg-cyan-500/30 text-cyan-200 text-xs" data-testid={`agent-seized-save-${row.business_id}`}
                                onClick={() => seizedSetPrice(row.listing_id, parseFloat(document.getElementById(`ag-seized-price-${row.listing_id}`).value))}>Сохранить</button>
                              <button className="px-2 py-1 rounded bg-green-500/30 text-green-200 text-xs" data-testid={`agent-seized-return-${row.business_id}`}
                                onClick={() => seizedReturn(row.listing_id)}>Вернуть владельцу</button>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : tab === 'info' ? (
          /* INFO TAB */
          <div className="flex-1 overflow-y-auto p-6">
            <div className="max-w-3xl mx-auto space-y-6">
              <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                <h3 className="text-lg font-bold mb-3">Поиск пользователя по ID</h3>
                <div className="flex gap-2">
                  <input
                    value={searchUserId}
                    onChange={(e) => setSearchUserId(e.target.value)}
                    placeholder="ID пользователя"
                    className="flex-1 bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm"
                    data-testid="agent-user-search-input"
                  />
                  <button onClick={fetchUserInfo} className="px-4 py-2 bg-cyan-500 rounded-lg text-sm font-semibold" data-testid="agent-user-search-btn">
                    Найти
                  </button>
                </div>
              </div>

              {userInfo && (
                <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3" data-testid="agent-user-info-panel">
                  <h3 className="text-lg font-bold">Информация о пользователе</h3>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <Info2 k="ID" v={userInfo.user.id} />
                    <Info2 k="Email" v={userInfo.user.email} />
                    <Info2 k="Никнейм" v={userInfo.user.username} />
                    <Info2 k="Display name" v={userInfo.user.display_name} />
                    <Info2 k="Баланс" v={`${(userInfo.user.balance_ton || 0).toFixed(4)} TON`} />
                    <Info2 k="Регистрация" v={fmtDate(userInfo.user.created_at)} />
                  </div>
                  <div>
                    <h4 className="font-bold mt-3 mb-1">Бизнесы ({userInfo.businesses?.length || 0})</h4>
                    <div className="space-y-1 max-h-40 overflow-y-auto">
                      {(userInfo.businesses || []).map((b) => (
                        <div key={b.id} className="text-xs bg-white/5 px-2 py-1 rounded flex justify-between">
                          <span>{b.business_type} — lvl {b.level}</span>
                          <span className="text-white/40 font-mono">{b.id?.slice(0, 8)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h4 className="font-bold mt-3 mb-1">Ресурсы</h4>
                    <div className="text-xs text-white/60 grid grid-cols-3 gap-2">
                      {Object.entries(userInfo.user.resources || {}).map(([k, v]) => (
                        <div key={k} className="bg-white/5 px-2 py-1 rounded">{k}: {v}</div>
                      ))}
                      {Object.keys(userInfo.user.resources || {}).length === 0 && <span className="text-white/30">—</span>}
                    </div>
                  </div>
                  <div>
                    <h4 className="font-bold mt-3 mb-1">История операций ({userInfo.transactions?.length || 0})</h4>
                    <div className="flex gap-2 mb-2">
                      <input
                        value={searchTxId}
                        onChange={(e) => setSearchTxId(e.target.value)}
                        placeholder="Поиск по ID операции"
                        className="flex-1 bg-black/40 border border-white/15 rounded-lg px-2 py-1 text-xs"
                        data-testid="agent-tx-search-input"
                      />
                      <button onClick={fetchTx} className="px-3 py-1 bg-cyan-500/30 rounded text-xs">
                        <Search className="w-3 h-3 inline" />
                      </button>
                    </div>
                    {foundTx && (
                      <pre className="bg-black/40 p-2 rounded text-[10px] overflow-x-auto max-h-40">{JSON.stringify(foundTx, null, 2)}</pre>
                    )}
                    <div className="space-y-1 max-h-60 overflow-y-auto">
                      {(userInfo.transactions || []).map((tx) => (
                        <div key={tx.id} className="text-[11px] bg-white/5 px-2 py-1 rounded">
                          <div className="flex justify-between">
                            <span className="text-cyan-300">{tx.tx_type || tx.type}</span>
                            <span className="text-white/40">{(tx.amount_ton || tx.amount || 0).toFixed(4)} TON</span>
                          </div>
                          <div className="text-white/30 font-mono">{tx.id?.slice(0, 12)}... — {fmtDate(tx.created_at)}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <>
            {/* LEFT 30% — chat list */}
            <div className="w-[30%] border-r border-white/10 flex flex-col min-h-0">
              {tab === 'archive' && (
                <div className="p-3 border-b border-white/10">
                  <div className="flex gap-1">
                    <input
                      value={searchChatId}
                      onChange={(e) => setSearchChatId(e.target.value)}
                      placeholder="Поиск по ID чата"
                      className="flex-1 bg-black/40 border border-white/15 rounded-lg px-2 py-1.5 text-xs"
                      data-testid="agent-archive-search"
                    />
                    <button onClick={() => fetchChats()} className="px-2 py-1.5 bg-white/10 rounded text-xs">
                      <RefreshCw className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              )}
              <div className="flex-1 overflow-y-auto p-2 space-y-1">
                {filteredChats.length === 0 ? (
                  <div className="text-center text-white/30 text-sm py-6">Пусто</div>
                ) : (
                  filteredChats.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => fetchMessages(c.id)}
                      className={`w-full text-left p-2 rounded-lg border transition relative ${
                        selected?.id === c.id ? 'bg-cyan-500/15 border-cyan-400/40' : 'bg-white/5 border-white/10 hover:bg-white/10'
                      }`}
                      data-testid={`agent-chat-${c.id}`}
                    >
                      {(c.unread_for_agent > 0) && (
                        <span
                          className="absolute top-1.5 right-1.5 min-w-[18px] h-[18px] px-1 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center shadow-md"
                          data-testid={`agent-unread-${c.id}`}
                        >
                          {c.unread_for_agent > 9 ? '9+' : c.unread_for_agent}
                        </span>
                      )}
                      <div className="flex items-center justify-between pr-5">
                        <span className="text-xs font-mono text-cyan-300">#{c.short_id}</span>
                        <span className="text-[10px] text-white/40">{fmtDateTime(c.created_at)}</span>
                      </div>
                      <div className="text-xs text-white/70 mt-0.5">{c.user_username}</div>
                      {c.agent_name && <div className="text-[10px] text-emerald-300">→ {c.agent_name}</div>}
                    </button>
                  ))
                )}
              </div>
            </div>

            {/* RIGHT 70% — chat view */}
            <div className="flex-1 flex flex-col min-h-0 min-w-0">
              {!selected ? (
                <div className="flex-1 flex items-center justify-center text-white/30">
                  Выберите чат
                </div>
              ) : (
                <>
                  {/* Chat header */}
                  <div className="p-3 border-b border-white/10 bg-black/30 flex items-center justify-between flex-shrink-0">
                    <div>
                      <div className="text-sm font-semibold">{selected.user_username}</div>
                      <div className="text-[10px] text-white/40 font-mono flex items-center gap-1">
                        {selected.id}
                        <button onClick={() => { navigator.clipboard.writeText(selected.id); toast.success('Скопировано'); }}>
                          <Copy className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {tab === 'new' && (
                        <button onClick={claimChat} className="px-3 py-1.5 bg-emerald-500 hover:bg-emerald-400 rounded-lg text-xs font-semibold flex items-center gap-1" data-testid="agent-claim-btn">
                          <LogIn className="w-3 h-3" /> Подключиться
                        </button>
                      )}
                      {tab === 'active' && (
                        <button onClick={closeChat} className="px-3 py-1.5 bg-red-500/80 hover:bg-red-500 rounded-lg text-xs font-semibold flex items-center gap-1" data-testid="agent-close-btn">
                          <XIcon className="w-3 h-3" /> Завершить чат
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Messages — isolated scroll so the page never moves */}
                  <div
                    ref={messagesContainerRef}
                    className="flex-1 overflow-y-auto overscroll-contain p-4 bg-black/20"
                    style={{ touchAction: 'pan-y', WebkitOverflowScrolling: 'touch' }}
                    onTouchMove={(e) => e.stopPropagation()}
                    onWheel={(e) => e.stopPropagation()}
                  >
                    {messages.map((m) =>
                      m.sender_type === 'system' ? (
                        <div key={m.id} className="flex justify-center my-3">
                          <div className="text-[11px] text-cyan-300/70 bg-cyan-500/5 border border-cyan-500/15 rounded-full px-3 py-1">
                            {m.content} — {fmtDateTime(m.created_at)}
                          </div>
                        </div>
                      ) : (
                        <div key={m.id} className={`flex ${m.sender_type === 'agent' ? 'justify-end' : 'justify-start'} mb-2`}>
                          <div className={`max-w-[70%] rounded-2xl px-3 py-2 ${m.sender_type === 'agent' ? 'bg-cyan-500/20 border border-cyan-400/30' : 'bg-white/8 border border-white/10'}`}>
                            {m.sender_type !== 'agent' && <div className="text-[11px] font-semibold text-cyan-300 mb-1">{m.sender_name}</div>}
                            {m.image_url ? (
                              <img
                                src={resolveImageSrc(m.image_url)}
                                alt=""
                                className="max-w-full rounded-lg cursor-zoom-in hover:opacity-90 transition-opacity"
                                onClick={() => setLightboxSrc(resolveImageSrc(m.image_url))}
                                data-testid={`agent-chat-image-${m.id}`}
                              />
                            ) : (
                              <>
                                <div className="text-sm whitespace-pre-wrap break-words">{m.content}</div>
                                {/* Agent-sent translated message: show the Russian original too (both at once). */}
                                {m.sender_type === 'agent' && m.original_content && (
                                  <div className="mt-1.5 pt-1.5 border-t border-white/10 text-[11px] text-white/55 whitespace-pre-wrap break-words" data-testid={`agent-msg-original-${m.id}`}>
                                    <span className="text-white/35">RU: </span>{m.original_content}
                                  </div>
                                )}
                                {/* Translation of an incoming user message (to Russian). */}
                                {m.sender_type === 'user' && translations[m.id] && translations[m.id].shown && (translations[m.id].loading || translations[m.id].text) && (
                                  <div className="mt-1.5 pt-1.5 border-t border-white/10 text-[13px] text-white/90 italic whitespace-pre-wrap break-words" data-testid={`agent-msg-translation-${m.id}`}>
                                    {translations[m.id].loading ? '…' : translations[m.id].text}
                                  </div>
                                )}
                              </>
                            )}
                            <div className="flex items-center justify-between gap-2 mt-1">
                              {(m.sender_type === 'user' && !m.image_url) ? (
                                <button
                                  onClick={() => translateMsg(m, 'ru')}
                                  title="Перевести на русский"
                                  aria-label="Перевести на русский"
                                  data-testid={`agent-translate-btn-${m.id}`}
                                  className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 backdrop-blur-sm transition-colors ${
                                    translations[m.id]?.shown ? 'bg-cyan-500/25 text-cyan-300' : 'bg-white/10 text-white/70 hover:bg-white/20 hover:text-white'
                                  }`}
                                >
                                  <Languages className="w-3.5 h-3.5" />
                                </button>
                              ) : <span />}
                              <div className="text-[10px] text-white/40">{fmtDateTime(m.created_at)}</div>
                            </div>
                          </div>
                        </div>
                      )
                    )}
                    <div ref={messagesEndRef} />
                  </div>

                  {/* Input (only if active and assigned to me) */}
                  {selected.status === 'active' && (
                    <div className="p-3 border-t border-white/10 bg-black/40 flex-shrink-0">
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
                        <span className="text-[11px] text-white/40">Язык отправки:</span>
                        <select
                          value={sendLang}
                          onChange={(e) => setSendLang(e.target.value)}
                          className="bg-black/40 border border-white/15 rounded-lg px-2 py-1 text-xs text-white"
                          data-testid="agent-send-lang-select"
                        >
                          {SUPPORT_LANG_OPTIONS.map((o) => (
                            <option key={o.code} value={o.code} className="bg-[#0b0f1a] text-white">{o.label}</option>
                          ))}
                        </select>
                        <span className="text-[10px] text-white/30">Введите текст на русском — «Перевести и отправить» отправит его на выбранном языке</span>
                      </div>
                      {/* Превью загружаемого фото со спиннером */}
                      {uploading && (
                        <div className="mb-2 relative inline-block" data-testid="agent-upload-preview">
                          <img src={uploading.previewUrl} alt="" className="max-w-[120px] max-h-[120px] rounded-lg opacity-70" />
                          <div className="absolute inset-0 flex items-center justify-center">
                            <Loader2 className="w-6 h-6 text-cyan-300 animate-spin" data-testid="agent-upload-spinner" />
                          </div>
                        </div>
                      )}
                      <div className="flex items-end gap-2">
                        <button onClick={() => fileInputRef.current?.click()} disabled={!!uploading} className="w-10 h-10 rounded-full bg-white/5 hover:bg-white/10 flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed" data-testid="agent-upload-btn">
                          {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ImageIcon className="w-4 h-4" />}
                        </button>
                        <input ref={fileInputRef} type="file" accept="image/*,.heic,.heif" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadImage(f); e.target.value = ''; }} />
                        <textarea
                          value={input}
                          onChange={(e) => setInput(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(false); } }}
                          placeholder="Ваш ответ (на русском)..."
                          rows={1}
                          className="flex-1 bg-white/5 border border-white/15 rounded-xl px-3 py-2 text-sm resize-none max-h-24"
                          data-testid="agent-message-input"
                        />
                        <button
                          onClick={() => sendMessage(true)}
                          disabled={!input.trim() || sendLang === 'ru'}
                          title="Перевести и отправить на выбранном языке"
                          aria-label="Перевести и отправить"
                          className="w-10 h-10 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center disabled:opacity-30"
                          data-testid="agent-translate-send-btn"
                        >
                          <Languages className="w-4 h-4" />
                        </button>
                        <button onClick={() => sendMessage(false)} disabled={!input.trim()} className="w-10 h-10 rounded-full bg-cyan-500 hover:bg-cyan-400 flex items-center justify-center disabled:opacity-30" data-testid="agent-send-btn">
                          <Send className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </>
        )}
      </div>
      {/* Полноэкранный просмотр фото с зумом (рендерится portal'ом поверх всего) */}
      {lightboxSrc && (
        <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} testIdPrefix="agent" />
      )}
    </div>
  );
}

const Info2 = ({ k, v }) => (
  <div className="bg-black/30 rounded-lg p-2">
    <div className="text-[10px] uppercase text-white/40">{k}</div>
    <div className="text-sm text-white break-all">{v || '—'}</div>
  </div>
);
