import { useEffect, useState, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { X, MessageCircle, Send, Image as ImageIcon, Copy, Star, Loader2 } from 'lucide-react';
import { useTranslation } from '@/lib/translations';
import { toast } from 'sonner';
import axios from 'axios';
import ImageLightbox from './ImageLightbox';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// Корректно определяем src для картинки в чате.
// Бэкенд может присылать image_url как data-URI (data:image/...;base64,...)
// или как абсолютный URL (http/https), либо как относительный путь (/api/...).
// BACKEND_URL добавляем ТОЛЬКО к относительным путям, иначе картинка ломается.
const resolveImageSrc = (url) => {
  if (!url) return '';
  if (url.startsWith('data:') || url.startsWith('http://') || url.startsWith('https://') || url.startsWith('blob:')) {
    return url;
  }
  return `${BACKEND_URL}${url}`;
};

const fmtTime = (iso) => {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
};

// Full timestamp with date + time — shown on every chat bubble so users know
// when the message was sent (Issue #8 from user feedback). Includes the year
// on every message per follow-up request.
const fmtDateTime = (iso) => {
  try {
    const d = new Date(iso);
    return d.toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return '';
  }
};

// Droplet sound — short pre-rendered "одинокая капля" file shipped under /sounds/.
const dropletSrc = '/sounds/droplet.mp3';
let _dropletAudio = null;
const getDropletAudio = () => {
  if (typeof window === 'undefined') return null;
  if (!_dropletAudio) {
    try {
      _dropletAudio = new Audio(dropletSrc);
      _dropletAudio.preload = 'auto';
      _dropletAudio.volume = 0.55;
    } catch { _dropletAudio = null; }
  }
  return _dropletAudio;
};

// Unlock audio on the FIRST user gesture — browsers' autoplay policies
// silently reject .play() calls until the user has interacted with the
// page. Without this, the droplet would never sound on new messages.
if (typeof window !== 'undefined' && !window.__tc_droplet_unlocked) {
  const unlock = () => {
    try {
      const a = getDropletAudio();
      if (a) {
        a.muted = true;
        const p = a.play();
        if (p && typeof p.then === 'function') {
          p.then(() => { a.pause(); a.currentTime = 0; a.muted = false; }).catch(() => {});
        } else {
          a.pause(); a.currentTime = 0; a.muted = false;
        }
      }
    } catch (_) {}
    window.__tc_droplet_unlocked = true;
    window.removeEventListener('pointerdown', unlock, true);
    window.removeEventListener('keydown', unlock, true);
    window.removeEventListener('touchstart', unlock, true);
  };
  window.addEventListener('pointerdown', unlock, true);
  window.addEventListener('keydown', unlock, true);
  window.addEventListener('touchstart', unlock, true);
}

const playDroplet = () => {
  const a = getDropletAudio();
  if (!a) return;
  try {
    a.currentTime = 0;
    a.play().catch(() => {});
  } catch {}
};

const SystemRow = ({ text, time }) => (
  <div className="flex justify-center my-3">
    <div className="text-[11px] text-cyan-300/70 bg-cyan-500/5 border border-cyan-500/15 rounded-full px-3 py-1">
      {text} {time ? `— ${time}` : ''}
    </div>
  </div>
);

const Bubble = ({ msg, isMine, onImageClick }) => {
  const isImg = !!msg.image_url;
  return (
    <div className={`flex ${isMine ? 'justify-end' : 'justify-start'} mb-2`}>
      <div className={`max-w-[78%] rounded-2xl px-3 py-2 ${isMine ? 'bg-cyan-500/20 border border-cyan-400/30 text-white' : 'bg-white/8 border border-white/10 text-white'}`}>
        {!isMine && msg.sender_name && (
          <div className="text-[11px] font-semibold text-cyan-300 mb-1">{msg.sender_name}</div>
        )}
        {isImg ? (
          <img
            src={resolveImageSrc(msg.image_url)}
            alt="attached"
            className="max-w-full rounded-lg cursor-zoom-in hover:opacity-90 transition-opacity"
            onClick={() => onImageClick?.(resolveImageSrc(msg.image_url))}
            data-testid={`support-chat-image-${msg.id}`}
          />
        ) : (
          <div className="text-sm whitespace-pre-wrap break-words">{msg.content}</div>
        )}
        <div className="text-[10px] text-white/40 mt-1 text-right">{fmtDateTime(msg.created_at)}</div>
      </div>
    </div>
  );
};

export default function SupportModal({ open, onOpenChange, language = 'ru', forceFullscreen = false, disablePortal = false }) {
  const { t } = useTranslation(language);
  const [tab, setTab] = useState('active'); // active | closed
  const [chats, setChats] = useState([]);
  const [activeChat, setActiveChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [rating, setRating] = useState(0);
  // Локальное превью + спиннер, пока фото отправляется на сервер
  const [uploading, setUploading] = useState(null); // { previewUrl, name } | null
  // Полноэкранный просмотр картинки с зумом (лайтбокс)
  const [lightboxSrc, setLightboxSrc] = useState(null);
  const wsRef = useRef(null);
  const wsReconnectTimerRef = useRef(null);
  const wsPingTimerRef = useRef(null);
  const pollTimerRef = useRef(null);
  const wsOpenRef = useRef(false);
  const messagesEndRef = useRef(null);
  const scrollContainerRef = useRef(null);
  const fileInputRef = useRef(null);
  const activeChatRef = useRef(null);
  const messageIdsRef = useRef(new Set()); // dedupe
  const isMobile = typeof window !== 'undefined' && window.innerWidth < 768;
  // `forceFullscreen` prop lets the dedicated /support-only route render the
  // chat edge-to-edge on desktop too (Telegram Mini App style). Without it,
  // desktop viewports get the 400 px left sidebar variant.
  const fullscreen = forceFullscreen || isMobile;
  // Telegram WebApp detection — Telegram overlays a top header AND
  // (on phones) a thick bottom panel for the main button. We give the
  // sheet generous safe-area padding so the chat input + close button
  // are never covered by Telegram's UI.
  const isTelegramWebApp = typeof window !== 'undefined' && !!window.Telegram?.WebApp?.initData;

  const token = (typeof window !== 'undefined') ? localStorage.getItem('token') : null;

  // Keep ref in sync
  useEffect(() => { activeChatRef.current = activeChat; }, [activeChat]);

  const fetchChats = useCallback(async () => {
    if (!token) return;
    try {
      const res = await axios.get(`${API}/support/chats`, { headers: { Authorization: `Bearer ${token}` } });
      setChats(res.data.chats || []);
    } catch (e) {
      console.error('[Support] fetchChats:', e);
    }
  }, [token]);

  const markRead = useCallback(async (chatId) => {
    if (!chatId || !token) return;
    try {
      await axios.post(`${API}/support/chat/${chatId}/mark-read`, {}, { headers: { Authorization: `Bearer ${token}` } });
    } catch {}
  }, [token]);

  const fetchMessages = useCallback(async (chatId, opts = {}) => {
    if (!token || !chatId) return;
    try {
      const res = await axios.get(`${API}/support/chat/${chatId}/messages`, { headers: { Authorization: `Bearer ${token}` } });
      const msgs = res.data.messages || [];
      // Reset dedupe set
      messageIdsRef.current = new Set(msgs.map((m) => m.id));
      setMessages(msgs);
      setActiveChat(res.data.chat);
      if (!opts.skipMarkRead) markRead(chatId);
      fetchChats();
    } catch (e) {
      console.error('[Support] fetchMessages:', e);
    }
  }, [token, markRead, fetchChats]);

  // Add a message with dedupe
  const pushMessage = useCallback((m) => {
    if (!m || !m.id) return;
    if (messageIdsRef.current.has(m.id)) return;
    messageIdsRef.current.add(m.id);
    setMessages((prev) => [...prev, m]);
  }, []);

  // ─── WebSocket with auto-reconnect + ping ───────────────────────────────────
  const wsUseLegacyPathRef = useRef(false);
  const connectWS = useCallback(() => {
    if (!token) return;
    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
    }
    // Try /api/ws/support/user FIRST — that path is the one nginx already
    // upgrades for WebSockets on most production deployments. Fall back to
    // /api/support/ws/user only if the alias is unavailable.
    const path = wsUseLegacyPathRef.current
      ? '/api/support/ws/user'
      : '/api/ws/support/user';
    const wsUrl = `${BACKEND_URL.replace('http', 'ws')}${path}`;
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      let openedOnce = false;
      ws.addEventListener('open', () => { openedOnce = true; });
      ws.addEventListener('close', (ev) => {
        if (!openedOnce && !wsUseLegacyPathRef.current && (ev.code === 1006 || ev.code === 1002)) {
          wsUseLegacyPathRef.current = true;
          setTimeout(() => connectWS(), 50);
        }
      });
      ws.onopen = () => {
        wsOpenRef.current = true;
        // F8: authenticate via the first frame (token no longer in the URL).
        try { ws.send(JSON.stringify({ action: 'auth', token })); } catch {}
        // Start ping every 10s to keep alive
        if (wsPingTimerRef.current) clearInterval(wsPingTimerRef.current);
        wsPingTimerRef.current = setInterval(() => {
          try { ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ action: 'ping' })); } catch {}
        }, 10000);
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === 'new_message') {
            const cur = activeChatRef.current;
            if (cur && data.chat_id === cur.id) {
              pushMessage(data.message);
              if (data.message?.sender_type === 'agent') {
                playDroplet();
                markRead(cur.id);
              }
            } else {
              // Different chat or no chat open — refresh list
              playDroplet();
            }
            fetchChats();
          } else if (data.type === 'agent_joined') {
            const cur = activeChatRef.current;
            if (cur && data.chat_id === cur.id) {
              pushMessage(data.message);
              setActiveChat((c) => c ? { ...c, status: 'active', agent_name: data.agent_name } : c);
            }
            fetchChats();
          } else if (data.type === 'chat_closed') {
            const cur = activeChatRef.current;
            if (cur && data.chat_id === cur.id) {
              pushMessage(data.message);
              setActiveChat((c) => c ? { ...c, status: 'archived' } : c);
            }
            fetchChats();
          }
        } catch {}
      };
      ws.onclose = () => {
        wsRef.current = null;
        wsOpenRef.current = false;
        if (wsPingTimerRef.current) clearInterval(wsPingTimerRef.current);
        // Auto-reconnect after 3 sec
        if (!wsReconnectTimerRef.current) {
          wsReconnectTimerRef.current = setTimeout(() => {
            wsReconnectTimerRef.current = null;
            if (open) connectWS();
          }, 3000);
        }
      };
      ws.onerror = () => {
        try { ws.close(); } catch {}
      };
    } catch (e) {
      console.error('[Support] WS connect failed:', e);
    }
  }, [token, open, pushMessage, fetchChats, markRead]);

  useEffect(() => {
    if (!open) return;
    connectWS();
    return () => {
      if (wsReconnectTimerRef.current) { clearTimeout(wsReconnectTimerRef.current); wsReconnectTimerRef.current = null; }
      if (wsPingTimerRef.current) { clearInterval(wsPingTimerRef.current); wsPingTimerRef.current = null; }
      try { wsRef.current && wsRef.current.close(); } catch {}
      wsRef.current = null;
    };
  }, [open, connectWS]);

  useEffect(() => {
    if (open) fetchChats();
  }, [open, fetchChats]);

  // ─── Resilient polling fallback every 7s ─────────────────────────────────
  // Even if the WebSocket is up, we cheaply re-sync once every 7s so the
  // user never has to refresh manually. When WS is down the same loop keeps
  // the chat live until reconnect.
  useEffect(() => {
    if (!open) return;
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(() => {
      try {
        fetchChats();
        const cur = activeChatRef.current;
        if (cur && cur.id) {
          // Re-fetch messages silently — pushMessage dedupes any duplicates.
          axios.get(`${API}/support/chat/${cur.id}/messages`, { headers: { Authorization: `Bearer ${token}` } })
            .then((res) => {
              const msgs = res.data.messages || [];
              msgs.forEach((m) => pushMessage(m));
              if (res.data.chat) setActiveChat((c) => c ? { ...c, ...res.data.chat } : res.data.chat);
            })
            .catch(() => {});
        }
      } catch {}
    }, 7000);
    return () => { if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null; } };
  }, [open, token, fetchChats, pushMessage]);

  // Lock body scroll while modal is open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  // Auto-scroll to bottom on new messages (only the chat container, never the body)
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (el) {
      requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
    }
  }, [messages]);

  const startNewChat = async () => {
    // P1.5: Do NOT create the chat on the server yet. We open a local draft
    // compose view; the chat is only created once the user actually sends
    // their first message (see sendMessage). This prevents empty chats.
    messageIdsRef.current = new Set();
    setMessages([]);
    setActiveChat({ id: null, status: 'draft', isDraft: true });
    setTab('active');
  };

  const sendMessage = async () => {
    if (!input.trim() || !activeChat) return;
    const content = input.trim();
    setInput('');

    // P1.5: First message of a draft creates the chat (with initial_message).
    if (activeChat.isDraft || !activeChat.id) {
      setLoading(true);
      try {
        const res = await axios.post(
          `${API}/support/chat/create`,
          { initial_message: content },
          { headers: { Authorization: `Bearer ${token}` } }
        );
        messageIdsRef.current = new Set();
        setActiveChat(res.data.chat);
        await fetchMessages(res.data.chat.id);
        await fetchChats();
      } catch (e) {
        toast.error(e.response?.data?.detail || t('error'));
        setInput(content); // restore so the user doesn't lose their text
      } finally {
        setLoading(false);
      }
      return;
    }

    try {
      const res = await axios.post(
        `${API}/support/chat/${activeChat.id}/message`,
        { content },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      pushMessage(res.data.message);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
      setInput(content);
    }
  };

  const uploadImage = async (file) => {
    if (!file || !activeChat) return;
    // Сразу показываем локальное превью + спиннер, пока идёт загрузка на сервер
    const previewUrl = URL.createObjectURL(file);
    setUploading({ previewUrl, name: file.name || 'image' });
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await axios.post(`${API}/support/chat/${activeChat.id}/upload`, fd, {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'multipart/form-data' },
      });
      pushMessage(res.data.message);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    } finally {
      // Убираем индикатор и освобождаем blob-URL независимо от результата
      URL.revokeObjectURL(previewUrl);
      setUploading(null);
    }
  };

  const copyId = () => {
    if (!activeChat) return;
    navigator.clipboard.writeText(activeChat.id);
    toast.success(t('supportCopyId'));
  };

  const submitRating = async () => {
    if (!activeChat || !rating) return;
    try {
      await axios.post(
        `${API}/support/chat/${activeChat.id}/rate`,
        { rating },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      toast.success('✓');
      setRating(0);
      await fetchMessages(activeChat.id);
      await fetchChats();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    }
  };

  const activeChats = chats.filter((c) => c.status === 'new' || c.status === 'active');
  const closedChats = chats.filter((c) => c.status === 'archived');
  const visibleChats = tab === 'active' ? activeChats : closedChats;

  // Telegram Web App viewport: expand to full height, use Telegram's stable
  // viewport height so we never have to guess header/footer padding. When
  // outside Telegram we use plain safe-area insets.
  //
  // We also keep `viewportH` in state so that when the on-screen keyboard
  // opens on Android/iOS Telegram, the modal shrinks to `viewportHeight`
  // (which excludes the keyboard). This lets the input scroll into view
  // instead of hiding behind the keyboard (Issue #1 from user feedback).
  const [tgViewport, setTgViewport] = useState(null);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const tg = window.Telegram?.WebApp;
    if (!tg) return;
    try {
      tg.ready();
      tg.expand();
      if (typeof tg.disableVerticalSwipes === 'function') {
        tg.disableVerticalSwipes();
      }
    } catch (_) { /* ignore */ }
    const update = () => {
      // viewportHeight shrinks when keyboard opens; viewportStableHeight
      // keeps the "no-keyboard" size — we want the current one so the
      // input stays visible above the keyboard.
      setTgViewport(tg.viewportHeight || tg.viewportStableHeight || null);
    };
    update();
    try { tg.onEvent('viewportChanged', update); } catch (_) { /* ignore */ }
    return () => { try { tg.offEvent('viewportChanged', update); } catch (_) { /* ignore */ } };
  }, [open]);

  if (!open) return null;

  // Safe-area for the modal.
  // • Non-Telegram: obey CSS env() insets only — no extra padding.
  // • Telegram Web App: on Android the client always overlays its own
  //   ~56 px chrome (back + kebab menu) on top of the WebApp, and iOS has
  //   the notch. We push the header down so it doesn't get covered.
  //   Bottom stays at 10 px so there is a tiny breathing room above the
  //   Telegram gesture bar / send button.
  const topSafeArea = isTelegramWebApp
    ? 'calc(env(safe-area-inset-top, 0px) + 56px)'
    : 'env(safe-area-inset-top, 0px)';
  const bottomSafeArea = isTelegramWebApp
    ? 'calc(env(safe-area-inset-bottom, 0px) + 24px)'  // +24 px lifts the input above Telegram's gesture bar (user asked to raise by 10-15 px)
    : 'env(safe-area-inset-bottom, 0px)';
  // When running inside Telegram we anchor the modal height to the app's
  // viewport height so it never overflows Telegram's chrome.
  const modalHeightStyle = isTelegramWebApp && tgViewport
    ? { height: `${tgViewport}px` }
    : {};

  const content = (
    <motion.div
      initial={{ x: fullscreen ? 0 : -380, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: fullscreen ? 0 : -380, opacity: 0 }}
      transition={{ type: 'spring', stiffness: 320, damping: 30 }}
      className={
        fullscreen
          ? (disablePortal
              ? 'absolute inset-0 bg-void z-[10000] flex flex-col'
              : 'fixed inset-0 bg-void z-[10000] flex flex-col')
          : 'fixed left-0 top-0 h-screen w-[400px] bg-void border-r border-cyan-500/20 z-[10000] flex flex-col shadow-2xl'
      }
      style={{ paddingTop: topSafeArea, paddingBottom: bottomSafeArea, ...modalHeightStyle }}
      data-testid="support-modal"
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-white/10 bg-gradient-to-r from-cyan-500/10 to-transparent">
        <div className="flex items-center gap-2">
          <MessageCircle className="w-5 h-5 text-cyan-400" />
          <h2 className="text-white font-bold">{t('supportChatTitle')}</h2>
        </div>
        <button
          onClick={() => { setActiveChat(null); onOpenChange(false); }}
          className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-white/10 text-white/60 hover:text-white"
          data-testid="support-close-btn"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {!activeChat ? (
        <>
          {/* Tabs */}
          <div className="flex border-b border-white/10">
            {[
              { k: 'active', l: t('supportTabActive') },
              { k: 'closed', l: t('supportTabClosed') },
            ].map((tt) => (
              <button
                key={tt.k}
                onClick={() => setTab(tt.k)}
                className={`flex-1 px-3 py-2 text-sm font-medium transition ${tab === tt.k ? 'text-cyan-300 border-b-2 border-cyan-400' : 'text-white/50'}`}
                data-testid={`support-tab-${tt.k}`}
              >
                {tt.l}
              </button>
            ))}
          </div>

          {/* Chat list */}
          <div className="flex-1 overflow-y-auto overscroll-contain p-3 space-y-2">
            {visibleChats.length === 0 ? (
              <div className="text-center text-white/40 text-sm py-8">{t('supportClosedNoActive')}</div>
            ) : (
              visibleChats.map((c) => (
                <button
                  key={c.id}
                  onClick={() => fetchMessages(c.id)}
                  className="w-full text-left p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 transition relative"
                  data-testid={`support-chat-item-${c.id}`}
                >
                  {(c.unread_for_user > 0) && (
                    <span className="absolute top-2 right-2 min-w-[18px] h-[18px] px-1 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center" data-testid={`support-unread-${c.id}`}>
                      {c.unread_for_user > 9 ? '9+' : c.unread_for_user}
                    </span>
                  )}
                  <div className="flex items-center justify-between mb-1 pr-6">
                    <span className="text-xs text-cyan-300 font-mono">#{c.short_id || (c.id || '').slice(0, 8).toUpperCase()}</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full ${
                      c.status === 'new' ? 'bg-amber-500/20 text-amber-300' :
                      c.status === 'active' ? 'bg-emerald-500/20 text-emerald-300' :
                      'bg-white/10 text-white/50'
                    }`}>
                      {c.status === 'new' ? (t('ticketWaiting') || 'Waiting') : c.status === 'active' ? (t('ticketActiveStatus') || 'Active') : (t('ticketDoneStatus') || 'Completed')}
                    </span>
                  </div>
                  <div className="text-[11px] text-white/60">
                    {c.agent_name ? `${t('agentLabel') || 'Agent'}: ${c.agent_name}` : (t('waitingForAgent') || 'Waiting for agent...')}
                  </div>
                  <div className="text-[10px] text-white/30 mt-1">{fmtDateTime(c.created_at)}</div>
                </button>
              ))
            )}
          </div>

          {/* Start chat button */}
          {tab === 'active' && activeChats.length === 0 && (
            <div className="p-3 border-t border-white/10">
              <button
                onClick={startNewChat}
                disabled={loading}
                className="w-full py-3 bg-gradient-to-r from-cyan-500 to-blue-500 text-white rounded-xl font-semibold hover:opacity-90 transition disabled:opacity-50"
                data-testid="support-start-chat-btn"
              >
                {loading ? <Loader2 className="w-4 h-4 mx-auto animate-spin" /> : t('supportStartChat')}
              </button>
            </div>
          )}
        </>
      ) : (
        <>
          {/* Active chat header */}
          <div className="p-3 border-b border-white/10 bg-white/[0.02]">
            {activeChat.isDraft ? (
              <div className="text-xs text-cyan-300">{t('supportChatTitle')}</div>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <div className="text-xs text-white/50">{t('supportChatIdLabel')}:</div>
                  <button onClick={copyId} className="flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200" data-testid="support-copy-chat-id">
                    <span className="font-mono">{(activeChat.id || '').slice(0, 18)}...</span>
                    <Copy className="w-3 h-3" />
                  </button>
                </div>
                {activeChat.agent_name && (
                  <div className="text-[11px] text-emerald-300 mt-1">Агент: {activeChat.agent_name}</div>
                )}
              </>
            )}
            <button onClick={() => { setActiveChat(null); fetchChats(); }} className="text-[11px] text-cyan-400 hover:text-cyan-200 mt-1" data-testid="support-back-btn">
              {t('supportBackToList')}
            </button>
          </div>

          {/* Messages — isolated scroll so we never drag the whole page */}
          <div
            ref={scrollContainerRef}
            className="flex-1 overflow-y-auto overscroll-contain p-3 bg-black/20"
            style={{ touchAction: 'pan-y', WebkitOverflowScrolling: 'touch' }}
            onTouchMove={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
          >
            {messages.map((m) =>
              m.sender_type === 'system' ? (
                <SystemRow
                  key={m.id}
                  text={
                    (m.system_key === 'chat_created' && t('supportSystemChatCreated')) ||
                    m.content
                  }
                  time={fmtDateTime(m.created_at)}
                />
              ) : (
                <Bubble key={m.id} msg={m} isMine={m.sender_type === 'user'} onImageClick={setLightboxSrc} />
              )
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Footer */}
          {activeChat.status !== 'archived' ? (
            <div className="p-3 border-t border-white/10 bg-void">
              {activeChat.isDraft ? (
                <div className="text-[11px] text-cyan-300 mb-2" data-testid="support-draft-hint">{t('supportEnterQuestion')}</div>
              ) : activeChat.status === 'new' && !activeChat.agent_name ? (
                <div className="text-[11px] text-amber-300 mb-2">{t('supportWaitMessage')}</div>
              ) : null}
              {/* Превью загружаемого фото со спиннером */}
              {uploading && (
                <div className="mb-2 relative inline-block" data-testid="support-upload-preview">
                  <img src={uploading.previewUrl} alt="" className="max-w-[120px] max-h-[120px] rounded-lg opacity-70" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <Loader2 className="w-6 h-6 text-cyan-300 animate-spin" data-testid="support-upload-spinner" />
                  </div>
                </div>
              )}
              <div className="flex items-end gap-2">
                {!activeChat.isDraft && (
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={!!uploading}
                    className="w-10 h-10 rounded-full bg-white/5 hover:bg-white/10 flex items-center justify-center text-white/60 disabled:opacity-40 disabled:cursor-not-allowed"
                    data-testid="support-upload-btn"
                    title={t('supportSendImage')}
                  >
                    {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ImageIcon className="w-4 h-4" />}
                  </button>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,.heic,.heif"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) uploadImage(f);
                    e.target.value = '';
                  }}
                />
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      sendMessage();
                    }
                  }}
                  onFocus={(e) => {
                    // Ensure the textarea is visible above the on-screen
                    // keyboard on mobile. Delay the scroll a beat so the
                    // WebView has time to shrink the viewport.
                    setTimeout(() => {
                      try {
                        e.target.scrollIntoView({ block: 'end', behavior: 'smooth' });
                      } catch (_) { /* ignore */ }
                    }, 250);
                  }}
                  placeholder={t('supportEnterQuestion')}
                  rows={1}
                  className="flex-1 bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white placeholder:text-white/30 resize-none max-h-24"
                  data-testid="support-message-input"
                />
                <button
                  onClick={sendMessage}
                  disabled={!input.trim()}
                  className="w-10 h-10 rounded-full bg-cyan-500 hover:bg-cyan-400 flex items-center justify-center text-white disabled:opacity-30"
                  data-testid="support-send-btn"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          ) : (
            <div className="p-4 border-t border-white/10 bg-void">
              {activeChat.rating ? (
                <div className="text-center text-sm text-white/60">
                  Ваша оценка: {'⭐'.repeat(activeChat.rating)}
                </div>
              ) : (
                <>
                  <div className="text-center text-sm text-white/70 mb-2">{t('supportRateAgent')}</div>
                  <div className="flex justify-center gap-1 mb-3">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button
                        key={n}
                        onClick={() => setRating(n)}
                        className="text-2xl transition transform hover:scale-110"
                        data-testid={`support-rate-${n}`}
                      >
                        <Star className={`w-7 h-7 ${n <= rating ? 'fill-yellow-400 text-yellow-400' : 'text-white/30'}`} />
                      </button>
                    ))}
                  </div>
                  <button
                    onClick={submitRating}
                    disabled={!rating}
                    className="w-full py-2 bg-cyan-500 text-white rounded-xl font-semibold disabled:opacity-40"
                    data-testid="support-submit-rating-btn"
                  >
                    {t('supportRateSubmit')}
                  </button>
                </>
              )}
            </div>
          )}
        </>
      )}
      {/* Полноэкранный просмотр фото с зумом (рендерится portal'ом поверх всего) */}
      {lightboxSrc && (
        <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} testIdPrefix="support" />
      )}
    </motion.div>
  );

  if (disablePortal) {
    return (
      <AnimatePresence>
        {open && content}
      </AnimatePresence>
    );
  }
  return createPortal(
    <AnimatePresence>
      {open && content}
    </AnimatePresence>,
    document.body
  );
}
