import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  MessageCircle, Send, Globe, MapPin, User,
  RefreshCw, X, Languages, Bell, BellOff, Paperclip, Shield
} from 'lucide-react';
import { fill } from '@/lib/translationsMore';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import Sidebar from '@/components/Sidebar';
import SmartAvatar from '@/components/SmartAvatar';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { isSoundEnabled, setSoundEnabled, playSound } from '@/components/NotificationCenter';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;
const WS_URL = BACKEND_URL.replace('http', 'ws').replace('https', 'wss');

// Map project language -> BCP-47 locale for localized date headers.
const LOCALE_MAP = {
  ru: 'ru-RU', en: 'en-US', es: 'es-ES', zh: 'zh-CN',
  fr: 'fr-FR', de: 'de-DE', ja: 'ja-JP', ko: 'ko-KR',
};

// Localized labels for the translate button / states (all 8 project langs).
const CHAT_UI_I18N = {
  en: { translate: 'Translate', translating: 'Translating…', showOriginal: 'Show original', unavailable: 'Translation is unavailable right now' },
  ru: { translate: 'Перевести', translating: 'Перевод…', showOriginal: 'Показать оригинал', unavailable: 'Перевод сейчас недоступен' },
  es: { translate: 'Traducir', translating: 'Traduciendo…', showOriginal: 'Ver original', unavailable: 'La traducción no está disponible ahora' },
  zh: { translate: '翻译', translating: '翻译中…', showOriginal: '显示原文', unavailable: '翻译暂时不可用' },
  fr: { translate: 'Traduire', translating: 'Traduction…', showOriginal: "Voir l'original", unavailable: 'La traduction est indisponible pour le moment' },
  de: { translate: 'Übersetzen', translating: 'Übersetze…', showOriginal: 'Original anzeigen', unavailable: 'Übersetzung ist gerade nicht verfügbar' },
  ja: { translate: '翻訳', translating: '翻訳中…', showOriginal: '原文を表示', unavailable: '現在翻訳は利用できません' },
  ko: { translate: '번역', translating: '번역 중…', showOriginal: '원문 보기', unavailable: '지금은 번역을 사용할 수 없습니다' },
  id: { translate: 'Terjemahkan', translating: 'Menerjemahkan…', showOriginal: 'Lihat asli', unavailable: 'Terjemahan sedang tidak tersedia' },
};

// Stable per-day key from an ISO date (local time).
const dayKey = (dateStr) => {
  const d = new Date(dateStr);
  if (isNaN(d)) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

// "18 июля" / "July 18" — day (number) + month (word) in the user's language.
// Adds the year only when it differs from the current year.
const formatDayLabel = (dateStr, language) => {
  const d = new Date(dateStr);
  if (isNaN(d)) return '';
  const locale = LOCALE_MAP[language] || 'en-US';
  const opts = { day: 'numeric', month: 'long' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  try {
    return new Intl.DateTimeFormat(locale, opts).format(d);
  } catch (_) {
    return new Intl.DateTimeFormat('en-US', opts).format(d);
  }
};

export default function ChatPage({ user }) {
  const navigate = useNavigate();
  const { language } = useLanguage();
  const { t } = useTranslation(language);
  const cui = CHAT_UI_I18N[language] || CHAT_UI_I18N.en;
  // ?channel=alliance opens the alliance channel (the «Чат альянса» button)
  const [activeTab, setActiveTab] = useState(() => (new URLSearchParams(window.location.search).get('channel') === 'alliance' ? 'alliance' : 'global'));
  const [allianceMember, setAllianceMember] = useState(null);   // null = unknown yet
  const [soundOn, setSoundOn] = useState(isSoundEnabled());
  const [messages, setMessages] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [newMessage, setNewMessage] = useState('');
  const [cooldownUntil, setCooldownUntil] = useState(0);        // one message per 15 s (the server checks it too)
  const [, setCooldownTick] = useState(0);
  useEffect(() => {
    if (cooldownUntil <= Date.now()) return undefined;
    const id = setInterval(() => { setCooldownTick((x) => x + 1); if (Date.now() >= cooldownUntil) clearInterval(id); }, 500);
    return () => clearInterval(id);
  }, [cooldownUntil]);
  const cooldownLeft = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
  const [isLoading, setIsLoading] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const [cities, setCities] = useState([]);
  const [selectedCity, setSelectedCity] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [stickyDay, setStickyDay] = useState('');
  // Per-message translation state: { [msgId]: { text, loading, shown } }
  const [translations, setTranslations] = useState({});
  // Photo upload state — kept out of `newMessage` so an image-only message
  // can be sent without any text. `pendingPhoto` holds the data URI + a
  // preview URL until the user hits Send. `isUploadingPhoto` disables the
  // paperclip button while a file is uploading.
  const [pendingPhoto, setPendingPhoto] = useState(null); // { url, size }
  const [isUploadingPhoto, setIsUploadingPhoto] = useState(false);
  const fileInputRef = useRef(null);

  // Infinite-scroll pagination state. We fetch the newest 50 messages on
  // channel open, then load 50 more each time the user scrolls near the
  // top of the viewport. `hasMore` is set to false when the last page
  // returned fewer than PAGE_SIZE — no need to keep asking the server.
  const PAGE_SIZE = 50;
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const isLoadingMoreRef = useRef(false); // guards against re-entry from scroll spam
  // Only allow loadOlderMessages to fire AFTER the user has produced a real
  // scroll event (wheel / touchmove / pointerdown). The initial
  // scrollToBottom animation transiently reports scrollTop ≤ 80 while it
  // climbs from 0 to the bottom, which would otherwise spuriously trigger
  // "load older" and defeat the whole 50-message initial cap.
  const userHasScrolledRef = useRef(false);
  // Ref to skip the auto-scroll-to-bottom effect when we're prepending
  // older messages after scroll-up (we want to preserve the current
  // viewport position, not jump to the end).
  const suppressAutoScrollRef = useRef(false);
  // First scroll-to-bottom of each channel uses behavior:'auto' so the
  // instantaneous jump can't trip the userHasScroll guard. Subsequent
  // new-message autoscrolls use 'smooth'.
  const initialScrollDoneRef = useRef(false);
  
  const messagesEndRef = useRef(null);
  const scrollAreaRef = useRef(null);
  const viewportRef = useRef(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const token = localStorage.getItem('token');

  // Scroll to bottom
  const scrollToBottom = useCallback(() => {
    if (messagesEndRef.current) {
      // First jump per channel is instantaneous — a smooth animation
      // would fire scroll events with scrollTop ≤ 80 as it climbs, and
      // (before the userHasScrolledRef gate landed) that used to trigger
      // an unwanted "load older" fetch.
      const behavior = initialScrollDoneRef.current ? 'smooth' : 'auto';
      messagesEndRef.current.scrollIntoView({ behavior });
      initialScrollDoneRef.current = true;
    }
  }, []);

  useEffect(() => {
    // Prepending older messages during infinite-scroll must NOT yank the
    // viewport back to the bottom — the caller sets suppressAutoScrollRef
    // and manually restores scroll offset after the DOM updates.
    if (suppressAutoScrollRef.current) {
      suppressAutoScrollRef.current = false;
      return;
    }
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // WebSocket connection with reconnection logic
  const connectWebSocket = useCallback(() => {
    if (!token || wsRef.current?.readyState === WebSocket.OPEN) return;
    
    try {
      const ws = new WebSocket(`${WS_URL}/api/ws/chat`);
      
      ws.onopen = () => {
        setIsConnected(true);
        wsRef.retries = 0;

        // F8: authenticate via the first frame (token no longer in the URL).
        ws.send(JSON.stringify({ action: 'auth', token }));

        // Subscribe to current city if selected
        if (selectedCity) {
          ws.send(JSON.stringify({ action: 'subscribe_city', city_id: selectedCity }));
        }
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'new_message') {
            const msg = data.message;
            
            // Add message to state if it belongs to current chat
            setMessages(prev => {
              // Already have the real message (by id) → nothing to do.
              if (prev.some(m => m.id === msg.id)) return prev;

              // Own message echoed back over WS → replace the optimistic
              // "temp-…" placeholder instead of appending a duplicate.
              if (msg.sender_id === user?.id) {
                const idx = prev.findIndex(
                  m => m.is_sending && String(m.id).startsWith('temp-') && m.content === msg.content
                );
                if (idx !== -1) {
                  const copy = [...prev];
                  copy[idx] = msg;
                  return copy;
                }
              }

              // Check if message belongs to current chat
              const belongsToChat = 
                (activeTab === 'global' && msg.chat_type === 'global') ||
                (activeTab === 'alliance' && msg.chat_type === 'alliance') ||
                (activeTab === 'city' && msg.chat_type === 'city' && msg.city_id === selectedCity) ||
                (activeTab === 'private' && msg.chat_type === 'private' && 
                  (msg.sender_id === selectedConversation?.partner_id || 
                   msg.recipient_id === selectedConversation?.partner_id ||
                   msg.sender_id === user?.id));
              
              if (belongsToChat) {
                if (msg.sender_id !== user?.id) playSound();
                return [...prev, msg];
              }
              return prev;
            });
            
            // Update unread count for messages not from current user
            if (msg.recipient_id === user?.id && msg.sender_id !== user?.id) {
              setUnreadCount(prev => prev + 1);
            }
            // Keep the active PUBLIC channel marked read while the user is
            // looking at it — the WS already played the sound above, so this
            // stops the 15s poll from double-beeping and keeps the badge at 0.
            if (msg.sender_id !== user?.id) {
              if (activeTab === 'global' && msg.chat_type === 'global') markChannelRead('global');
              else if (activeTab === 'alliance' && msg.chat_type === 'alliance') markChannelRead('alliance');
              else if (activeTab === 'city' && msg.chat_type === 'city' && msg.city_id === selectedCity) markChannelRead('city', selectedCity);
            }
          }
        } catch (e) {
          console.error('Error parsing WebSocket message:', e);
        }
      };
      
      ws.onclose = () => {
        console.log('Chat WebSocket disconnected');
        setIsConnected(false);
        // reconnect with a growing pause (3 s → 6 → 12 … max 60 s), only while the tab is visible
        const n = (wsRef.retries = (wsRef.retries || 0) + 1);
        const delay = Math.min(60000, 3000 * 2 ** Math.min(5, n - 1));
        reconnectTimeoutRef.current = setTimeout(() => {
          if (document.visibilityState === 'visible') connectWebSocket();
          else document.addEventListener('visibilitychange', function once() { if (document.visibilityState === 'visible') { document.removeEventListener('visibilitychange', once); connectWebSocket(); } });
        }, delay);
      };
      
      ws.onerror = () => {
        // a failed connection is handled by onclose (quiet reconnect) — nothing to print
      };
      
      wsRef.current = ws;
    } catch (error) {
      /* the next attempt is scheduled by onclose */
    }
  }, [token, selectedCity, activeTab, selectedConversation, user?.id]);

  // Initialize WebSocket
  useEffect(() => {
    connectWebSocket();
    
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connectWebSocket]);

  // Load initial data
  useEffect(() => {
    if (!token) {
      navigate('/auth?mode=login');
      return;
    }
    loadCities();
    loadUnreadCount();
    // NOTE: initial `loadGlobalMessages()` is intentionally left to the
    // `[activeTab]` effect below (activeTab defaults to 'global'). Firing
    // it from both places caused a duplicate first-page fetch on mount
    // (× 2 more under React StrictMode).
  }, [token, navigate]);

  // Reload messages when tab changes.
  useEffect(() => {
    // A tab switch resets the per-channel scroll state: the next
    // load is a "fresh" bottom-jump, and we ignore synthetic scroll
    // events until the user actually gestures.
    userHasScrolledRef.current = false;
    initialScrollDoneRef.current = false;
    if (activeTab === 'global') {
      loadGlobalMessages();
    } else if (activeTab === 'alliance') {
      loadAllianceMessages();
    } else if (activeTab === 'private') {
      loadConversations();
    }
  }, [activeTab]);

  // The global chat updates with every message through the socket; if the socket is down (proxy, network),
  // new messages are fetched every 4 seconds instead, so the page still updates by itself.
  useEffect(() => {
    if ((activeTab !== 'global' && activeTab !== 'alliance') || isConnected) return undefined;
    const id = setInterval(async () => {
      try {
        const r = activeTab === 'alliance'
          ? await fetch(`${API}/chat/messages/alliance?limit=30`, { headers: { Authorization: `Bearer ${token}` } })
          : await fetch(`${API}/chat/messages/global?limit=30`);
        if (!r.ok) return;
        const d = await r.json();
        const fresh = d.messages || d || [];
        if (!Array.isArray(fresh) || !fresh.length) return;
        setMessages((prev) => {
          const have = new Set(prev.map((m) => m.id));
          const add = fresh.filter((m) => m && m.id && !have.has(m.id));
          if (!add.length) return prev;
          if (add.some((m) => m.sender_id !== user?.id)) playSound();
          return [...prev.filter((m) => !(m.is_sending && add.some((a) => a.sender_id === user?.id && a.content === m.content))), ...add]
            .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
        });
      } catch (_) { /* next time */ }
    }, 4000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, isConnected]);

  // P1.4: Poll the open P2P (private) conversation every 3 seconds so new
  // messages from the other user appear even if the WebSocket push is missed.
  // Uses the silent loader to avoid spinner flicker on each refresh.
  useEffect(() => {
    if (activeTab !== 'private' || !selectedConversation?.partner_id) return;
    const partnerId = selectedConversation.partner_id;
    const intervalId = setInterval(() => {
      loadPrivateMessages(partnerId, { silent: true });
      loadConversations();
    }, 3000);
    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, selectedConversation?.partner_id]);

  const markChannelRead = useCallback(async (chat_type, city_id = null) => {
    if (!token) return;
    try {
      await fetch(`${API}/chat/mark-read`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ chat_type, city_id })
      });
      window.dispatchEvent(new Event('chat:refresh-unread'));
    } catch (_) {}
  }, [token]);

  const loadGlobalMessages = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${API}/chat/messages/global?limit=${PAGE_SIZE}`);
      if (res.ok) {
        const data = await res.json();
        const msgs = data.messages || [];
        setMessages(msgs);
        setHasMore(msgs.length >= PAGE_SIZE);
        // Viewing the global chat clears its unread badge.
        markChannelRead('global');
      }
    } catch (error) {
      console.error('Failed to load global messages:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const loadAllianceMessages = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${API}/chat/messages/alliance?limit=${PAGE_SIZE}`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const data = await res.json();
        const msgs = data.messages || [];
        setAllianceMember(!!data.member);
        setMessages(msgs);
        setHasMore(msgs.length >= PAGE_SIZE);
        if (data.member) markChannelRead('alliance');
      }
    } catch (error) {
      console.error('Failed to load alliance messages:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const loadCityMessages = async (cityId) => {
    setIsLoading(true);
    try {
      const res = await fetch(`${API}/chat/messages/city/${cityId}?limit=${PAGE_SIZE}`);
      if (res.ok) {
        const data = await res.json();
        const msgs = data.messages || [];
        setMessages(msgs);
        setHasMore(msgs.length >= PAGE_SIZE);
        markChannelRead('city', cityId);
      }
      
      // Subscribe via WebSocket
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ action: 'subscribe_city', city_id: cityId }));
      }
    } catch (error) {
      console.error('Failed to load city messages:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const loadPrivateMessages = async (partnerId, { silent = false } = {}) => {
    if (!silent) setIsLoading(true);
    try {
      const res = await fetch(`${API}/chat/messages/private/${partnerId}?limit=${PAGE_SIZE}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        const msgs = data.messages || [];
        setMessages(msgs);
        setHasMore(msgs.length >= PAGE_SIZE);
        // Opening the conversation marks those messages read on the server —
        // tell the chat badge to refresh so the unread count drops immediately.
        try { window.dispatchEvent(new Event('chat:refresh-unread')); } catch (_) {}
      }
    } catch (error) {
      console.error('Failed to load private messages:', error);
    } finally {
      if (!silent) setIsLoading(false);
    }
  };

  // Fetch the next batch of OLDER messages (infinite scroll). Called when
  // the ScrollArea's viewport scrolls near the top. Uses `?before=<created_at>`
  // cursor so pagination is stable even if new messages arrive mid-scroll.
  const loadOlderMessages = useCallback(async () => {
    if (isLoadingMoreRef.current || !hasMore) return;
    if (!messages.length) return;
    const oldest = messages[0];
    const beforeTs = oldest?.created_at;
    if (!beforeTs) return;

    let url = null;
    if (activeTab === 'global') {
      url = `${API}/chat/messages/global?limit=${PAGE_SIZE}&before=${encodeURIComponent(beforeTs)}`;
    } else if (activeTab === 'alliance') {
      url = `${API}/chat/messages/alliance?limit=${PAGE_SIZE}&before=${encodeURIComponent(beforeTs)}`;
    } else if (activeTab === 'city' && selectedCity) {
      url = `${API}/chat/messages/city/${selectedCity}?limit=${PAGE_SIZE}&before=${encodeURIComponent(beforeTs)}`;
    } else if (activeTab === 'private' && selectedConversation?.partner_id) {
      url = `${API}/chat/messages/private/${selectedConversation.partner_id}?limit=${PAGE_SIZE}&before=${encodeURIComponent(beforeTs)}`;
    }
    if (!url) return;

    isLoadingMoreRef.current = true;
    setIsLoadingMore(true);
    // Capture the current scroll anchor so we can restore the same visual
    // position after we prepend older items (otherwise the browser jumps
    // to the very top of the newly-grown list).
    const vp = viewportRef.current;
    const anchorHeight = vp ? vp.scrollHeight : 0;
    const anchorTop = vp ? vp.scrollTop : 0;

    try {
      const headers = (activeTab === 'private' || activeTab === 'alliance') ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(url, { headers });
      if (res.ok) {
        const data = await res.json();
        const older = data.messages || [];
        if (older.length < PAGE_SIZE) setHasMore(false);
        if (older.length > 0) {
          // Filter duplicates by id (WebSocket could have echoed one already).
          setMessages(prev => {
            const seen = new Set(prev.map(m => m.id));
            const uniqueOlder = older.filter(m => !seen.has(m.id));
            if (uniqueOlder.length === 0) return prev;
            return [...uniqueOlder, ...prev];
          });
          // Preserve scroll position: after DOM updates, add the height
          // delta to scrollTop so the message the user was looking at
          // stays under the cursor instead of the list jumping to top.
          suppressAutoScrollRef.current = true;
          requestAnimationFrame(() => {
            if (vp) {
              const delta = vp.scrollHeight - anchorHeight;
              vp.scrollTop = anchorTop + delta;
            }
          });
        }
      }
    } catch (err) {
      console.error('Failed to load older messages:', err);
    } finally {
      setIsLoadingMore(false);
      // Small debounce so a bouncy trackpad doesn't fire us again the
      // same frame while the new content is still being laid out.
      setTimeout(() => { isLoadingMoreRef.current = false; }, 150);
    }
  }, [messages, hasMore, activeTab, selectedCity, selectedConversation, token]);

  const loadConversations = async () => {
    try {
      const res = await fetch(`${API}/chat/conversations`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setConversations(data.conversations || []);
      }
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadCities = async () => {
    try {
      const res = await fetch(`${API}/cities`);
      if (res.ok) {
        const data = await res.json();
        setCities(data.cities || []);
      }
    } catch (error) {
      console.error('Failed to load cities:', error);
    }
  };

  const loadUnreadCount = async () => {
    try {
      const res = await fetch(`${API}/chat/unread-count`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setUnreadCount(data.unread_count || 0);
      }
    } catch (error) {
      console.error('Failed to load unread count:', error);
    }
  };

  // Attach a photo: upload to the backend and stash the returned data URI
  // as `pendingPhoto` — the user still has to hit Send. Keeping the two
  // steps separate lets people combine an image + optional caption in one
  // message.
  const handlePickPhoto = () => {
    if (fileInputRef.current) fileInputRef.current.value = '';
    fileInputRef.current?.click();
  };

  // Client-side downscale + JPEG re-encode so every uploaded chat photo
  // arrives as a lightweight ≤~120 KB, ≤1024 px picture regardless of the
  // original camera-roll size. Keeps upload fast and MongoDB storage
  // small. If compression somehow fails we fall back to the original.
  const compressChatImage = (file) => new Promise((resolve, reject) => {
    const MAX_SIDE = 1024;
    const TARGET_BYTES = 120 * 1024; // ~120 KB
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('read-failed'));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error('invalid-image'));
      img.onload = () => {
        let { width, height } = img;
        if (width > MAX_SIDE || height > MAX_SIDE) {
          if (width >= height) {
            height = Math.round((height * MAX_SIDE) / width);
            width = MAX_SIDE;
          } else {
            width = Math.round((width * MAX_SIDE) / height);
            height = MAX_SIDE;
          }
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(img, 0, 0, width, height);

        const tryQuality = (q) => new Promise((res) => {
          canvas.toBlob((blob) => res(blob), 'image/jpeg', q);
        });

        (async () => {
          // Iteratively lower quality until we hit the ~120 KB target
          // (or bottom out at 0.35). Aggressive on huge DSLR files while
          // keeping smaller phone photos readable.
          const qualities = [0.75, 0.65, 0.55, 0.45, 0.4, 0.35];
          let out = null;
          for (const q of qualities) {
            const blob = await tryQuality(q);
            if (!blob) continue;
            out = blob;
            if (blob.size <= TARGET_BYTES) break;
          }
          if (!out) return reject(new Error('compress-failed'));
          const name = (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg';
          resolve(new File([out], name, { type: 'image/jpeg' }));
        })();
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });

  const handlePhotoFile = async (e) => {
    const file = e.target.files?.[0];
    // Reset the native input so re-selecting the same file re-fires onChange.
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      toast.error(t('chatOnlyImages') || 'Only images are allowed');
      return;
    }
    // Enforce "only 1 photo per message" at the source too: if there is
    // already a staged photo, silently ignore additional picks.
    if (pendingPhoto) return;
    setIsUploadingPhoto(true);
    try {
      let toUpload = file;
      try {
        toUpload = await compressChatImage(file);
      } catch (_err) {
        // fall back to original file if compression fails
        toUpload = file;
      }
      // Hard cap after compression — server also enforces 3MB.
      if (toUpload.size > 3 * 1024 * 1024) {
        toast.error(t('chatImageTooLarge') || 'Image must be ≤ 3 MB');
        setIsUploadingPhoto(false);
        return;
      }
      const fd = new FormData();
      fd.append('file', toUpload);
      const res = await fetch(`${API}/chat/upload-photo`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Upload failed');
      }
      const data = await res.json();
      setPendingPhoto({ url: data.url, size: data.size });
    } catch (err) {
      toast.error(err.message || 'Upload failed');
    } finally {
      setIsUploadingPhoto(false);
    }
  };

  const handleSendMessage = async () => {
    // Allow image-only messages: at least one of {text, pending image} required.
    const content = newMessage.trim();
    const imageUrl = pendingPhoto?.url || null;
    if (!content && !imageUrl) return;
    if (cooldownLeft > 0) { toast.error(fill(t('chat_cooldown'), { n: cooldownLeft })); return; }

    setNewMessage(''); // Clear input immediately
    setPendingPhoto(null); // Clear pending photo immediately (optimistic UI)
    
    let chatType = activeTab;
    let cityId = null;
    let recipientId = null;
    
    if (activeTab === 'city') {
      cityId = selectedCity;
      if (!cityId) {
        toast.error(t('selectCityChat'));
        return;
      }
    } else if (activeTab === 'private') {
      recipientId = selectedConversation?.partner_id;
      if (!recipientId) {
        toast.error(t('selectRecipientChat'));
        return;
      }
    }
    
    // Optimistically add message to UI
    const optimisticMessage = {
      id: `temp-${Date.now()}`,
      content,
      image_url: imageUrl,
      chat_type: chatType,
      city_id: cityId,
      sender_id: user?.id,
      sender_username: user?.username || t('youSender'),
      recipient_id: recipientId,
      created_at: new Date().toISOString(),
      is_sending: true
    };
    
    setMessages(prev => [...prev, optimisticMessage]);
    
    try {
      const res = await fetch(`${API}/chat/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          content,
          image_url: imageUrl,
          chat_type: chatType,
          city_id: cityId,
          recipient_id: recipientId
        })
      });
      
      if (!res.ok) {
        const err = await res.json();
        if (res.status === 429 && err?.detail?.code === 'chat_cooldown') {
          setCooldownUntil(Date.now() + (err.detail.wait || 15) * 1000);
          if (content) setNewMessage(content);                 // keep the text: send it when the wait is over
          throw new Error(fill(t('chat_cooldown'), { n: err.detail.wait || 15 }));
        }
        throw new Error(typeof err.detail === 'string' ? err.detail : 'Failed to send message');
      }
      setCooldownUntil(Date.now() + 15000);

      const data = await res.json();
      
      // Reconcile the optimistic message with the server's real one.
      // If the WebSocket echo already inserted the real message, just drop the
      // temp placeholder (prevents the "two messages" flash).
      setMessages(prev => {
        const withoutTemp = prev.filter(m => m.id !== optimisticMessage.id);
        if (withoutTemp.some(m => m.id === data.message.id)) return withoutTemp;
        return [...withoutTemp, { ...data.message, is_sending: false }];
      });
    } catch (error) {
      toast.error(error.message);
      // Remove failed optimistic message
      setMessages(prev => prev.filter(m => m.id !== optimisticMessage.id));
    }
  };

  const handleTabChange = (tab) => {
    // Unsubscribe from previous city
    if (selectedCity && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'unsubscribe_city', city_id: selectedCity }));
    }
    
    setActiveTab(tab);
    setMessages([]);
    setSelectedConversation(null);
    setSelectedCity(null);
  };

  const handleCitySelect = (cityId) => {
    // Unsubscribe from previous city
    if (selectedCity && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'unsubscribe_city', city_id: selectedCity }));
    }
    userHasScrolledRef.current = false;
    initialScrollDoneRef.current = false;
    setSelectedCity(cityId);
    loadCityMessages(cityId);
  };

  const handleConversationSelect = (conv) => {
    userHasScrolledRef.current = false;
    initialScrollDoneRef.current = false;
    setSelectedConversation(conv);
    loadPrivateMessages(conv.partner_id);
  };

  const formatTime = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  };

  // ── Sticky floating day header ──────────────────────────────────────────
  // Show the day of the topmost visible message; it updates as the user scrolls
  // until they reach the message where that day's separator is shown.
  const recomputeStickyDay = useCallback(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    const rows = vp.querySelectorAll('[data-msgrow]');
    if (!rows.length) { setStickyDay(''); return; }
    const topEdge = vp.getBoundingClientRect().top;

    // Day of the topmost message that is still (partly) visible.
    let currentDay = null;
    let currentLabel = '';
    for (const r of rows) {
      const rect = r.getBoundingClientRect();
      if (rect.bottom > topEdge + 1) {
        currentDay = r.getAttribute('data-day');
        currentLabel = r.getAttribute('data-daylabel');
        break;
      }
    }
    if (!currentDay) { setStickyDay(''); return; }

    // If that day's own separator is currently visible in the viewport, the
    // date is already shown inline → hide the floating header (per spec).
    const sep = vp.querySelector(`[data-daysep="${currentDay}"]`);
    if (sep) {
      const srect = sep.getBoundingClientRect();
      if (srect.top >= topEdge - 4) {
        setStickyDay('');
        return;
      }
    }
    setStickyDay(currentLabel);
  }, []);

  // Attach the scroll listener to the Radix ScrollArea viewport.
  useEffect(() => {
    const root = scrollAreaRef.current;
    const vp = root ? root.querySelector('[data-radix-scroll-area-viewport]') : null;
    viewportRef.current = vp;
    if (!vp) return;
    // Flip userHasScrolledRef true on any REAL user-driven gesture. The
    // programmatic scrollToBottom does not fire wheel/touchmove/pointerdown
    // — it only produces synthetic scroll events — so this gate blocks
    // the accidental "load older" fire during the initial jump-to-bottom.
    const markUserScroll = () => { userHasScrolledRef.current = true; };
    const onScroll = () => {
      recomputeStickyDay();
      if (!userHasScrolledRef.current) return; // ignore programmatic scrolls
      if (vp.scrollTop <= 80) loadOlderMessages();
    };
    vp.addEventListener('scroll', onScroll, { passive: true });
    vp.addEventListener('wheel', markUserScroll, { passive: true });
    vp.addEventListener('touchmove', markUserScroll, { passive: true });
    vp.addEventListener('pointerdown', markUserScroll, { passive: true });
    vp.addEventListener('keydown', markUserScroll);
    return () => {
      vp.removeEventListener('scroll', onScroll);
      vp.removeEventListener('wheel', markUserScroll);
      vp.removeEventListener('touchmove', markUserScroll);
      vp.removeEventListener('pointerdown', markUserScroll);
      vp.removeEventListener('keydown', markUserScroll);
    };
  }, [recomputeStickyDay, loadOlderMessages, isLoading, activeTab]);

  // Recompute sticky day whenever the message list changes.
  useEffect(() => {
    const id = setTimeout(recomputeStickyDay, 60);
    return () => clearTimeout(id);
  }, [messages, recomputeStickyDay]);

  // ── Per-message translation ─────────────────────────────────────────────
  const handleTranslate = async (msg) => {
    const existing = translations[msg.id];
    // Toggle back to the original if we've already translated it.
    if (existing && existing.text) {
      setTranslations(prev => ({ ...prev, [msg.id]: { ...existing, shown: !existing.shown } }));
      return;
    }
    setTranslations(prev => ({ ...prev, [msg.id]: { loading: true, shown: true } }));
    try {
      const res = await fetch(`${API}/chat/translate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message_id: msg.id, target_lang: language }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (err?.detail?.code === 'translation_unavailable') throw new Error(cui.unavailable);
        throw new Error(typeof err.detail === 'string' ? err.detail : cui.unavailable);
      }
      const data = await res.json();
      setTranslations(prev => ({ ...prev, [msg.id]: { text: data.translation, loading: false, shown: true } }));
    } catch (e) {
      setTranslations(prev => { const c = { ...prev }; delete c[msg.id]; return c; });
      toast.error(e.message || 'Translation failed');
    }
  };

  const canSendMessage = 
    activeTab === 'global' || 
    (activeTab === 'alliance' && allianceMember) || 
    (activeTab === 'city' && selectedCity) || 
    (activeTab === 'private' && selectedConversation);

  return (
    <div
      className="flex h-screen bg-void overflow-hidden"
      style={{ paddingTop: 'var(--tg-safe-top, 0px)' }}
    >
      <Sidebar user={user} />
      
      <div className="relative flex-1 flex flex-col lg:ml-16 h-screen overflow-hidden">
        {/* No page header any more: only the sound bell, in the top-right corner (below Telegram's own bar) */}
        <Button
          onClick={() => {
            const next = !soundOn;
            setSoundOn(next);
            setSoundEnabled(next);
            if (next) playSound();
          }}
          variant="outline"
          size="icon"
          data-testid="chat-sound-toggle"
          aria-pressed={soundOn}
          title={soundOn ? (t('chatSoundOn') || 'Звук включён') : (t('chatSoundOff') || 'Звук выключен')}
          className={`absolute z-20 right-3 top-[calc(var(--tg-safe-top,0px)+8px)] lg:top-3 h-9 w-9 rounded-full bg-black/60 backdrop-blur border-white/15 ${soundOn ? 'text-cyber-cyan' : 'text-white/50'}`}
        >
          {soundOn ? <Bell className="w-4 h-4" /> : <BellOff className="w-4 h-4" />}
        </Button>

        {/* Channel: general / alliance (top-left; the bell is top-right) */}
        <div className="absolute z-20 left-3 top-[calc(var(--tg-safe-top,0px)+8px)] lg:top-3 flex rounded-full bg-black/60 backdrop-blur border border-white/15 p-0.5" role="tablist" data-testid="chat-channels">
          {[['global', Globe, t('al_chat_global')], ['alliance', Shield, t('al_tab')]].map(([k, Icon, label]) => (
            <button key={k} type="button" role="tab" aria-selected={activeTab === k} onClick={() => activeTab !== k && handleTabChange(k)} data-testid={`chat-channel-${k}`}
              className={`h-8 px-3 rounded-full text-xs font-bold flex items-center gap-1.5 ${activeTab === k ? (k === 'alliance' ? 'bg-fuchsia-500/25 text-fuchsia-100' : 'bg-cyber-cyan/20 text-cyber-cyan') : 'text-white/60'}`}>
              <Icon className="w-3.5 h-3.5" />{label}
            </button>
          ))}
        </div>

        {/* Content Area - SCROLLABLE */}
        <div className="flex-1 flex overflow-hidden min-h-0">
          {/* City/Conversation Sidebar */}
          {(activeTab === 'city' || activeTab === 'private') && (
            <div className="w-64 border-r border-white/10 flex flex-col flex-shrink-0 overflow-hidden">
              <ScrollArea className="flex-1">
                <div className="p-2 space-y-1">
                  {activeTab === 'city' ? (
                    cities.length === 0 ? (
                      <div className="text-center py-8 text-text-muted">
                        <MapPin className="w-8 h-8 mx-auto mb-2 opacity-50" />
                        <p className="text-sm">{t('noCities')}</p>
                      </div>
                    ) : (
                      cities.map(city => (
                        <div
                          key={city.id}
                          onClick={() => handleCitySelect(city.id)}
                          className={`p-3 rounded-lg cursor-pointer transition-all ${
                            selectedCity === city.id
                              ? 'bg-amber-500/20 border border-amber-500/30'
                              : 'bg-white/5 border border-transparent hover:bg-white/10'
                          }`}
                        >
                          <div className="font-medium text-white">
                            {typeof city.name === 'object' ? city.name.ru || city.name.en : city.name}
                          </div>
                          <div className="text-xs text-text-muted">
                            {city.stats?.total_plots || 0} {t('plotsCount')}
                          </div>
                        </div>
                      ))
                    )
                  ) : (
                    conversations.length === 0 ? (
                      <div className="text-center py-8 text-text-muted">
                        <User className="w-8 h-8 mx-auto mb-2 opacity-50" />
                        <p className="text-sm">{t('noConversations')}</p>
                      </div>
                    ) : (
                      conversations.map(conv => (
                        <div
                          key={conv.partner_id}
                          onClick={() => handleConversationSelect(conv)}
                          className={`p-3 rounded-lg cursor-pointer transition-all ${
                            selectedConversation?.partner_id === conv.partner_id
                              ? 'bg-purple-500/20 border border-purple-500/30'
                              : 'bg-white/5 border border-transparent hover:bg-white/10'
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyber-cyan to-neon-purple flex items-center justify-center text-sm font-bold text-black flex-shrink-0">
                              {(conv.partner_username || 'U')[0].toUpperCase()}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="font-medium text-white truncate">
                                {conv.partner_username}
                              </div>
                              {conv.last_message && (
                                <div className="text-xs text-text-muted truncate">
                                  {conv.last_message.content}
                                </div>
                              )}
                            </div>
                            {conv.unread_count > 0 && (
                              <Badge className="bg-red-500 text-xs flex-shrink-0">{conv.unread_count}</Badge>
                            )}
                          </div>
                        </div>
                      ))
                    )
                  )}
                </div>
              </ScrollArea>
            </div>
          )}

          {/* Messages Area */}
          <div className="flex-1 flex flex-col overflow-hidden min-w-0 relative">
            {/* Sticky floating day header */}
            {!isLoading && messages.length > 0 && stickyDay && (
              <div className="absolute top-12 lg:top-14 left-0 right-0 z-20 flex justify-center pointer-events-none" data-testid="chat-sticky-day">
                <span className="px-3 py-1 rounded-full text-xs font-medium bg-void/80 backdrop-blur-md border border-white/10 text-white/80 shadow-lg">
                  {stickyDay}
                </span>
              </div>
            )}
            {/* Messages List */}
            <ScrollArea className="flex-1 p-4 pt-14" ref={scrollAreaRef}>
              <div className="space-y-1">
                {/* Top loader — visible only while a "load older" fetch is in
                    flight. When `hasMore` is false we hide it entirely so
                    the user knows they've reached the beginning. */}
                {isLoadingMore && (
                  <div
                    className="flex items-center justify-center py-2 text-xs text-text-muted gap-2"
                    data-testid="chat-loading-more"
                  >
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>{t('loadingMessages') || 'Loading…'}</span>
                  </div>
                )}
                {activeTab === 'alliance' && allianceMember === false && !isLoading ? (
                  <div className="text-center py-12 text-text-muted space-y-3" data-testid="chat-alliance-none">
                    <Shield className="w-12 h-12 mx-auto opacity-50 text-fuchsia-300" />
                    <p>{t('al_chat_no_alliance')}</p>
                    <Button onClick={() => navigate('/alliance')} className="bg-fuchsia-500/80 hover:bg-fuchsia-500 text-white">{t('al_tab')}</Button>
                  </div>
                ) : isLoading ? (
                  <div className="text-center py-12 text-text-muted">
                    <RefreshCw className="w-8 h-8 mx-auto mb-4 animate-spin opacity-50" />
                    <p>{t('loadingMessages')}</p>
                  </div>
                ) : messages.length === 0 ? (
                  <div className="text-center py-12 text-text-muted">
                    <MessageCircle className="w-12 h-12 mx-auto mb-4 opacity-50" />
                    <p>
                      {activeTab === 'global' && t('writeFirstMessage')}
                      {activeTab === 'city' && (selectedCity ? t('noMessagesInCity') : t('selectCityLeft'))}
                      {activeTab === 'private' && (selectedConversation ? t('startConversation') : t('selectRecipientLeft'))}
                    </p>
                  </div>
                ) : (
                  messages.map((msg, idx) => {
                    const isOwn = msg.sender_id === user?.id;
                    const curDay = dayKey(msg.created_at);
                    const prev = idx > 0 ? messages[idx - 1] : null;
                    const prevDay = prev ? dayKey(prev.created_at) : null;
                    const showDaySep = curDay && curDay !== prevDay;
                    const dayLabel = formatDayLabel(msg.created_at, language);

                    // Feature 4: consecutive messages from the SAME sender within
                    // 5 minutes are grouped — the avatar + name + time header is
                    // shown only on the first message of a group. A new day break,
                    // a different sender in between, or a > 5 min gap starts a new
                    // group and shows the header again.
                    const FIVE_MIN = 5 * 60 * 1000;
                    const sameSenderAsPrev = prev && prev.sender_id === msg.sender_id;
                    const withinGap = prev && (new Date(msg.created_at) - new Date(prev.created_at)) < FIVE_MIN;
                    const showMeta = showDaySep || !sameSenderAsPrev || !withinGap;

                    // Show a translate button when the message is in a different
                    // language than the current user's project language.
                    const canTranslate = !!msg.lang && msg.lang !== language;
                    const tr = translations[msg.id];
                    return (
                      <div key={msg.id || idx} data-msgrow data-day={curDay} data-daylabel={dayLabel}>
                        {showDaySep && (
                          <div className="flex justify-center my-3" data-testid="chat-day-separator" data-daysep={curDay}>
                            <span className="px-3 py-1 rounded-full text-xs font-medium bg-white/5 border border-white/10 text-text-muted">
                              {dayLabel}
                            </span>
                          </div>
                        )}
                        <motion.div
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: msg.is_sending ? 0.6 : 1, y: 0 }}
                          className={`flex gap-3 ${showMeta && !showDaySep ? 'mt-3' : ''} ${isOwn ? 'flex-row-reverse' : ''}`}
                        >
                          {showMeta ? (
                            <div data-testid={`chat-avatar-${msg.id}`} className="flex-shrink-0">
                              <SmartAvatar
                                avatar={typeof msg.sender_avatar === 'string' && msg.sender_avatar && !/^(https?:|data:)/.test(msg.sender_avatar) ? `${BACKEND_URL}${msg.sender_avatar}` : msg.sender_avatar}
                                name={msg.sender_username || 'U'}
                                className="w-8 h-8 rounded-full border border-white/10"
                                textClassName="text-sm"
                              />
                            </div>
                          ) : (
                            <div className="w-8 flex-shrink-0" aria-hidden="true" />
                          )}
                          <div className={`max-w-[70%] ${isOwn ? 'items-end' : 'items-start'}`}>
                            {showMeta && (
                              <div className={`text-xs mb-1 flex items-center gap-2 ${isOwn ? 'flex-row-reverse' : ''}`}>
                                <span className={isOwn ? 'text-cyber-cyan' : 'text-white/70'}>
                                  {!isOwn && msg.sender_alliance_tag && <span className="text-fuchsia-300 font-semibold mr-1" data-testid="chat-msg-tag">[{msg.sender_alliance_tag}]</span>}
                                  {isOwn ? t('youSender') : msg.sender_username}
                                </span>
                                <span className="text-text-muted">{formatTime(msg.created_at)}</span>
                                {msg.is_sending && <span className="text-yellow-500 text-xs">{t('sendingMsg')}</span>}
                              </div>
                            )}
                            <div className={`flex items-end gap-1.5 ${isOwn ? 'flex-row-reverse' : ''}`}>
                              {msg.image_url ? (
                                // Image-only / image+caption message.
                                // Per product spec the image is shown WITHOUT a bubble
                                // background/border — just the picture (rounded corners
                                // for aesthetics), with the optional caption underneath.
                                <div className="flex flex-col gap-1 items-start">
                                  <img
                                    src={msg.image_url}
                                    alt=""
                                    data-testid={`chat-image-${msg.id}`}
                                    className="w-full max-w-[220px] sm:max-w-[280px] max-h-[300px] h-auto rounded-lg select-none object-cover"
                                    draggable={false}
                                  />
                                  {msg.content ? (
                                    <p className="text-white text-sm break-words whitespace-pre-wrap max-w-[320px]">
                                      {msg.content}
                                    </p>
                                  ) : null}
                                  {tr && tr.shown && (tr.loading || tr.text) && (
                                    <div className="max-w-[320px]">
                                      {tr.loading ? (
                                        <span className="flex items-center gap-1.5 text-xs text-text-muted">
                                          <RefreshCw className="w-3 h-3 animate-spin" /> {cui.translating}
                                        </span>
                                      ) : (
                                        <p className="text-white/90 text-sm break-words whitespace-pre-wrap italic">{tr.text}</p>
                                      )}
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <div className={`p-3 rounded-xl ${
                                  isOwn
                                    ? 'bg-cyber-cyan/20 border border-cyber-cyan/30'
                                    : 'bg-white/10 border border-white/10'
                                }`}>
                                  <p className="text-white text-sm break-words whitespace-pre-wrap">{msg.content}</p>
                                  {tr && tr.shown && (tr.loading || tr.text) && (
                                    <div className="mt-2 pt-2 border-t border-white/10">
                                      {tr.loading ? (
                                        <span className="flex items-center gap-1.5 text-xs text-text-muted">
                                          <RefreshCw className="w-3 h-3 animate-spin" /> {cui.translating}
                                        </span>
                                      ) : (
                                        <p className="text-white/90 text-sm break-words whitespace-pre-wrap italic">{tr.text}</p>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )}
                              {canTranslate && !msg.is_sending && (
                                <button
                                  type="button"
                                  onClick={() => handleTranslate(msg)}
                                  data-testid={`chat-translate-btn-${msg.id}`}
                                  title={tr && tr.shown ? cui.showOriginal : cui.translate}
                                  aria-label={cui.translate}
                                  className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 backdrop-blur-sm transition-colors ${
                                    tr && tr.shown
                                      ? 'bg-cyber-cyan/25 text-cyber-cyan'
                                      : 'bg-white/10 text-white/70 hover:bg-white/20 hover:text-white'
                                  }`}
                                >
                                  <Languages className="w-4 h-4" />
                                </button>
                              )}
                            </div>
                          </div>
                        </motion.div>
                      </div>
                    );
                  })
                )}
                <div ref={messagesEndRef} />
              </div>
            </ScrollArea>

            {/* Message Input - FIXED AT BOTTOM */}
            {canSendMessage && (
              <div className="flex-shrink-0 p-4 pb-[calc(var(--bottom-nav-h,46px)+24px)] lg:pb-4 border-t border-white/10 bg-void">
                {/* Pending photo preview (borderless — matches how it will
                    appear in the message list once sent). The 'X' unstages
                    the photo without sending. */}
                {pendingPhoto && (
                  <div className="mb-2 relative inline-block" data-testid="chat-pending-photo">
                    <img
                      src={pendingPhoto.url}
                      alt=""
                      className="max-w-[120px] max-h-[120px] rounded-lg"
                    />
                    <button
                      type="button"
                      onClick={() => setPendingPhoto(null)}
                      data-testid="chat-remove-photo-btn"
                      className="absolute -top-1.5 -right-1.5 w-6 h-6 rounded-full bg-black/70 border border-white/20 flex items-center justify-center hover:bg-black"
                      aria-label={t('chatRemovePhoto') || 'Remove photo'}
                    >
                      <X className="w-3.5 h-3.5 text-white" />
                    </button>
                  </div>
                )}
                <div className="flex gap-2 items-end">
                  {/* Hidden file input — triggered by paperclip. */}
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={handlePhotoFile}
                    data-testid="chat-file-input"
                  />
                  {/* Attach button is hidden while a photo is staged. It
                      reappears the moment the user removes the pending
                      photo. Enforces "max 1 photo per message". */}
                  {!pendingPhoto && (
                    <Button
                      type="button"
                      onClick={handlePickPhoto}
                      variant="outline"
                      size="icon"
                      disabled={isUploadingPhoto}
                      data-testid="chat-attach-photo-btn"
                      title={t('chatAttachPhoto') || 'Attach photo'}
                      className="border-white/10 h-10 w-10 shrink-0"
                    >
                      {isUploadingPhoto ? (
                        <RefreshCw className="w-4 h-4 animate-spin" />
                      ) : (
                        <Paperclip className="w-4 h-4" />
                      )}
                    </Button>
                  )}
                  <Input
                    value={newMessage}
                    onChange={(e) => setNewMessage(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSendMessage();
                      }
                    }}
                    placeholder={t('enterMessagePlaceholder')}
                    className="flex-1 bg-white/5 border-white/10 focus:border-cyber-cyan"
                    maxLength={1000}
                  />
                  <Button 
                    onClick={handleSendMessage}
                    className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80"
                    disabled={(!newMessage.trim() && !pendingPhoto) || cooldownLeft > 0}
                    data-testid="chat-send-btn"
                  >
                    {cooldownLeft > 0 ? <span className="text-xs font-bold w-4 text-center" data-testid="chat-cooldown">{cooldownLeft}</span> : <Send className="w-4 h-4" />}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
