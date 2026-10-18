import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { toast } from 'sonner';
import {
  MapPin, Search, Filter, ArrowRight, Sparkles,
  Lock, Construction, Activity, Users, Coins
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useTranslation } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';
import Sidebar from '@/components/Sidebar';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

// Active city ids (rest are "В разработке")
const ACTIVE_CITY_IDS = new Set(['ton-island']);

// Display-only plot counts for in-development cities (грид не трогаем, только цифры на карточке)
const PLOT_COUNT_OVERRIDES = {
  'nebula-bay': 1006,
  'nova-archipelago': 1962,
  'genesis-plains': 3874,
  'crystal-reef': 4327,
};

// Per-city price chip override — value-only; localized prefix added at render time
const PRICE_CHIP_OVERRIDES = {
  'ton-island': { value: '5000', currency: '$CITY' },
};

// Full per-city i18n (overrides backend's en/ru-only data so all 8 languages work)
const CITY_I18N = {
  'ton-island': {
    name: { en: 'GRAM Island', ru: 'Остров GRAM', es: 'Isla GRAM', zh: 'GRAM 岛', fr: 'Île GRAM', de: 'GRAM-Insel', ja: 'GRAM アイランド', ko: 'GRAM 아일랜드' },
    description: {
      en: 'The heart of the TON ecosystem. Premium location with high traffic.',
      ru: 'Сердце экосистемы TON. Премиальное расположение с высоким трафиком.',
      es: 'El corazón del ecosistema TON. Ubicación premium con alto tráfico.',
      zh: 'TON 生态系统的核心。高人流量的优质地段。',
      fr: 'Le cœur de l’écosystème TON. Emplacement premium à fort trafic.',
      de: 'Das Herz des TON-Ökosystems. Premium-Lage mit hohem Traffic.',
      ja: 'TON エコシステムの中心。トラフィックの多いプレミアムロケーション。',
      ko: 'TON 생태계의 중심. 높은 유동인구의 프리미엄 입지.',
    },
  },
  'nebula-bay': {
    name: { en: 'Nebula Bay', ru: 'Залив Небула', es: 'Bahía Nébula', zh: '星云湾', fr: 'Baie Nébuleuse', de: 'Nebelbucht', ja: 'ネビュラ湾', ko: '네뷸라 베이' },
    description: {
      en: 'A natural harbor perfect for trading businesses.',
      ru: 'Природная гавань, идеальная для торговых предприятий.',
      es: 'Un puerto natural perfecto para negocios comerciales.',
      zh: '天然港湾,非常适合贸易类企业。',
      fr: 'Un port naturel idéal pour les commerces.',
      de: 'Ein natürlicher Hafen, perfekt für Handelsbetriebe.',
      ja: '貿易ビジネスに最適な天然の港。',
      ko: '무역 사업에 최적화된 천연 항구.',
    },
  },
  'nova-archipelago': {
    name: { en: 'Nova Archipelago', ru: 'Архипелаг Нова', es: 'Archipiélago Nova', zh: '诺瓦群岛', fr: 'Archipel Nova', de: 'Nova-Archipel', ja: 'ノヴァ群島', ko: '노바 군도' },
    description: {
      en: 'A chain of islands connected by bridges. Strategic diversity.',
      ru: 'Цепь островов, соединённых мостами. Стратегическое разнообразие.',
      es: 'Una cadena de islas conectadas por puentes. Diversidad estratégica.',
      zh: '由桥梁连接的岛链。战略多样性。',
      fr: 'Une chaîne d’îles reliées par des ponts. Diversité stratégique.',
      de: 'Eine Inselkette, verbunden durch Brücken. Strategische Vielfalt.',
      ja: '橋で繋がれた島々のチェーン。戦略的多様性。',
      ko: '다리로 연결된 섬 체인. 전략적 다양성.',
    },
  },
  'genesis-plains': {
    name: { en: 'Genesis Plains', ru: 'Равнины Генезис', es: 'Llanuras Génesis', zh: '创世平原', fr: 'Plaines Genèse', de: 'Genesis-Ebenen', ja: 'ジェネシス平原', ko: '제네시스 평원' },
    description: {
      en: 'The original settlement. Affordable plots for newcomers.',
      ru: 'Изначальное поселение. Доступные участки для новичков.',
      es: 'El asentamiento original. Parcelas asequibles para recién llegados.',
      zh: '最初的定居地。新人可负担的地块。',
      fr: 'La colonie d’origine. Parcelles abordables pour les nouveaux.',
      de: 'Die Ur-Siedlung. Erschwingliche Grundstücke für Neulinge.',
      ja: '最初の入植地。新規プレイヤー向けの手頃な区画。',
      ko: '최초의 정착지. 신규 유저를 위한 합리적인 필지.',
    },
  },
  'crystal-reef': {
    name: { en: 'Crystal Reef', ru: 'Кристальный Риф', es: 'Arrecife de Cristal', zh: '水晶礁', fr: 'Récif de Cristal', de: 'Kristallriff', ja: 'クリスタル・リーフ', ko: '크리스탈 리프' },
    description: {
      en: 'Rich in resources. Perfect for production chains.',
      ru: 'Богат ресурсами. Идеален для производственных цепочек.',
      es: 'Rico en recursos. Perfecto para cadenas de producción.',
      zh: '资源丰富。适合生产链。',
      fr: 'Riche en ressources. Parfait pour les chaînes de production.',
      de: 'Reich an Ressourcen. Perfekt für Produktionsketten.',
      ja: '資源が豊富。生産チェーンに最適。',
      ko: '자원이 풍부. 생산 체인에 완벽.',
    },
  },
};

// Local i18n strings — covers all 8 project languages (en, ru, es, zh, fr, de, ja, ko)
const STR = {
  en: { title: 'Maps', subtitle: 'Pick a city to enter and start building your empire', search: 'Search cities…', sortDefault: 'Default', sortName: 'By name', sortPrice: 'By price', sortPlayers: 'By players', total: 'Total plots', available: 'Available', filled: 'Filled', enter: 'Enter city', soon: 'Soon', active: 'Active', dev: 'In development', comingSoon: 'Coming soon', toastTitle: 'is in development', toastDesc: 'This city will be available soon', empty: 'No cities found', loading: 'Loading maps…', priceFrom: 'from', backendPrice: 'TON' },
  ru: { title: 'Список карт', subtitle: 'Выберите город, чтобы отправиться на его карту и начать строительство своей империи', search: 'Поиск городов…', sortDefault: 'По умолчанию', sortName: 'По названию', sortPrice: 'По цене', sortPlayers: 'По игрокам', total: 'Всего', available: 'Доступно', filled: 'Заполненность', enter: 'Войти в город', soon: 'Скоро', active: 'Активен', dev: 'В разработке', comingSoon: 'Скоро доступно', toastTitle: 'находится на стадии разработки', toastDesc: 'Этот город скоро станет доступен для игры', empty: 'Города не найдены', loading: 'Загрузка карт…', priceFrom: 'от', backendPrice: 'TON' },
  es: { title: 'Mapas', subtitle: 'Elige una ciudad para entrar y empezar a construir tu imperio', search: 'Buscar ciudades…', sortDefault: 'Por defecto', sortName: 'Por nombre', sortPrice: 'Por precio', sortPlayers: 'Por jugadores', total: 'Parcelas totales', available: 'Disponibles', filled: 'Ocupación', enter: 'Entrar', soon: 'Pronto', active: 'Activo', dev: 'En desarrollo', comingSoon: 'Próximamente', toastTitle: 'está en desarrollo', toastDesc: 'Esta ciudad estará disponible pronto', empty: 'No hay ciudades', loading: 'Cargando mapas…', priceFrom: 'desde', backendPrice: 'TON' },
  zh: { title: '地图列表', subtitle: '选择一座城市进入,开始打造你的帝国', search: '搜索城市…', sortDefault: '默认', sortName: '按名称', sortPrice: '按价格', sortPlayers: '按玩家', total: '总地块', available: '可用', filled: '占用率', enter: '进入城市', soon: '即将', active: '已开放', dev: '开发中', comingSoon: '即将开放', toastTitle: '正在开发中', toastDesc: '该城市即将开放', empty: '未找到城市', loading: '加载地图中…', priceFrom: '起', backendPrice: 'TON' },
  fr: { title: 'Cartes', subtitle: 'Choisissez une ville pour entrer et bâtir votre empire', search: 'Rechercher des villes…', sortDefault: 'Par défaut', sortName: 'Par nom', sortPrice: 'Par prix', sortPlayers: 'Par joueurs', total: 'Parcelles totales', available: 'Disponibles', filled: 'Remplissage', enter: 'Entrer', soon: 'Bientôt', active: 'Actif', dev: 'En développement', comingSoon: 'Bientôt disponible', toastTitle: 'est en développement', toastDesc: 'Cette ville sera bientôt disponible', empty: 'Aucune ville trouvée', loading: 'Chargement des cartes…', priceFrom: 'à partir de', backendPrice: 'TON' },
  de: { title: 'Karten', subtitle: 'Wähle eine Stadt, um dein Imperium aufzubauen', search: 'Städte suchen…', sortDefault: 'Standard', sortName: 'Nach Name', sortPrice: 'Nach Preis', sortPlayers: 'Nach Spielern', total: 'Felder gesamt', available: 'Verfügbar', filled: 'Belegung', enter: 'Stadt betreten', soon: 'Bald', active: 'Aktiv', dev: 'In Entwicklung', comingSoon: 'Bald verfügbar', toastTitle: 'befindet sich in Entwicklung', toastDesc: 'Diese Stadt wird bald verfügbar sein', empty: 'Keine Städte gefunden', loading: 'Karten werden geladen…', priceFrom: 'ab', backendPrice: 'TON' },
  ja: { title: 'マップ一覧', subtitle: '街を選んで帝国を築こう', search: '都市を検索…', sortDefault: 'デフォルト', sortName: '名前順', sortPrice: '価格順', sortPlayers: 'プレイヤー数順', total: '総区画', available: '利用可能', filled: '占有率', enter: '街に入る', soon: '近日公開', active: '稼働中', dev: '開発中', comingSoon: '近日公開', toastTitle: 'は開発中です', toastDesc: 'まもなく利用可能になります', empty: '都市が見つかりません', loading: 'マップを読み込み中…', priceFrom: 'から', backendPrice: 'TON' },
  ko: { title: '지도 목록', subtitle: '도시를 선택해 제국을 건설하세요', search: '도시 검색…', sortDefault: '기본', sortName: '이름순', sortPrice: '가격순', sortPlayers: '플레이어순', total: '총 구역', available: '사용 가능', filled: '점유율', enter: '도시 입장', soon: '곧 출시', active: '활성', dev: '개발 중', comingSoon: '곧 공개', toastTitle: '은(는) 개발 중입니다', toastDesc: '곧 이용 가능합니다', empty: '도시를 찾을 수 없습니다', loading: '맵 로딩 중…', priceFrom: '부터', backendPrice: 'TON' },
};
const getStr = (lang) => STR[lang] || STR.en;

const STYLE_PALETTES = {
  cyber:      { water1: '#031018', water2: '#06222e', land: '#1de3ff', shadow: '#0a98b8', accent: '#7df9ff', glow: 'rgba(29,227,255,0.45)' },
  tropical:   { water1: '#04201f', water2: '#0a3a36', land: '#5be39a', shadow: '#1f8a4f', accent: '#a7f3d0', glow: 'rgba(91,227,154,0.45)' },
  industrial: { water1: '#1a0e02', water2: '#2b1605', land: '#fbbf24', shadow: '#b06a05', accent: '#fde68a', glow: 'rgba(251,191,36,0.45)' },
  neon:       { water1: '#0c0420', water2: '#1a0a3d', land: '#c084fc', shadow: '#7c3aed', accent: '#f3e8ff', glow: 'rgba(192,132,252,0.45)' },
};

// Live, animated top-down canvas preview
function CityTopDownPreview({ grid, style, cityId, isActive, height = 200 }) {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || !grid || grid.length === 0) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const gridH = grid.length;
    const gridW = grid[0]?.length || 0;

    // Compute cell size to fully fill the available canvas area
    const dpr = window.devicePixelRatio || 1;
    const wrapper = canvas.parentElement;
    const wrapperW = wrapper?.clientWidth || 320;
    const wrapperH = height;
    const cellSize = Math.max(2, Math.min(wrapperW / gridW, wrapperH / gridH));
    const cssW = Math.round(cellSize * gridW);
    const cssH = Math.round(cellSize * gridH);
    canvas.style.width = cssW + 'px';
    canvas.style.height = cssH + 'px';
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const palette = STYLE_PALETTES[style] || STYLE_PALETTES.cyber;

    // Pre-compute land neighbors to render subtle inner highlight on edges
    const isLand = (x, y) => x >= 0 && y >= 0 && x < gridW && y < gridH && grid[y][x] === 1;

    let centerCell = null;
    for (let y = 0; y < gridH; y++) {
      for (let x = 0; x < gridW; x++) {
        if (grid[y][x] === 1) {
          if (!centerCell || (Math.hypot(x - gridW / 2, y - gridH / 2) < Math.hypot(centerCell.x - gridW / 2, centerCell.y - gridH / 2))) {
            centerCell = { x, y };
          }
        }
      }
    }

    const drawFrame = (t) => {
      // Background gradient water
      const grd = ctx.createLinearGradient(0, 0, 0, cssH);
      grd.addColorStop(0, palette.water1);
      grd.addColorStop(1, palette.water2);
      ctx.fillStyle = grd;
      ctx.fillRect(0, 0, cssW, cssH);

      // Subtle moving wave bands
      ctx.save();
      ctx.globalAlpha = 0.07;
      const offset = isActive ? (t / 60) % cssW : 0;
      for (let i = -1; i < 6; i++) {
        ctx.beginPath();
        ctx.strokeStyle = palette.accent;
        ctx.lineWidth = 1;
        const yBase = (cssH / 5) * i + (offset % (cssH / 5));
        ctx.moveTo(0, yBase);
        for (let x = 0; x <= cssW; x += 8) {
          ctx.lineTo(x, yBase + Math.sin((x + offset) * 0.04) * 2);
        }
        ctx.stroke();
      }
      ctx.restore();

      // Faint grid overlay
      ctx.strokeStyle = 'rgba(255,255,255,0.04)';
      ctx.lineWidth = 1;
      for (let i = 0; i <= gridW; i += 2) {
        ctx.beginPath();
        ctx.moveTo(i * cellSize, 0);
        ctx.lineTo(i * cellSize, cssH);
        ctx.stroke();
      }
      for (let i = 0; i <= gridH; i += 2) {
        ctx.beginPath();
        ctx.moveTo(0, i * cellSize);
        ctx.lineTo(cssW, i * cellSize);
        ctx.stroke();
      }

      // Pulsing glow factor (0..1)
      const pulse = isActive ? 0.55 + 0.45 * Math.sin(t / 600) : 0.45;

      // Draw land cells with depth
      for (let y = 0; y < gridH; y++) {
        for (let x = 0; x < gridW; x++) {
          if (grid[y][x] !== 1) continue;
          const px = x * cellSize;
          const py = y * cellSize;

          // Shadow / depth
          ctx.fillStyle = palette.shadow;
          ctx.fillRect(px + 1, py + 1, cellSize - 0.5, cellSize - 0.5);

          // Top surface
          ctx.fillStyle = palette.land;
          ctx.fillRect(px, py, cellSize - 1, cellSize - 1);

          // Edge highlight if neighbor is water
          const edgeUp = !isLand(x, y - 1);
          const edgeLeft = !isLand(x - 1, y);
          if (edgeUp || edgeLeft) {
            ctx.fillStyle = palette.accent;
            ctx.globalAlpha = 0.35;
            if (edgeUp) ctx.fillRect(px, py, cellSize - 1, Math.max(1, cellSize * 0.2));
            if (edgeLeft) ctx.fillRect(px, py, Math.max(1, cellSize * 0.2), cellSize - 1);
            ctx.globalAlpha = 1;
          }
        }
      }

      // Center beacon for active city
      if (centerCell && isActive) {
        const cx = (centerCell.x + 0.5) * cellSize;
        const cy = (centerCell.y + 0.5) * cellSize;
        const radius = Math.max(3, cellSize * 1.6) * (0.85 + 0.3 * pulse);

        const beacon = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
        beacon.addColorStop(0, palette.accent);
        beacon.addColorStop(0.4, palette.land);
        beacon.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = beacon;
        ctx.globalCompositeOperation = 'lighter';
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalCompositeOperation = 'source-over';
      }

      if (isActive) {
        rafRef.current = requestAnimationFrame(drawFrame);
      }
    };

    drawFrame(performance.now());

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [grid, style, cityId, isActive, height]);

  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <canvas
        ref={canvasRef}
        data-testid={`city-top-down-${cityId}`}
        style={{ imageRendering: 'pixelated' }}
      />
    </div>
  );
}

export default function MapPage({ user }) {
  const navigate = useNavigate();
  const [cities, setCities] = useState([]);
  const [tonIslandData, setTonIslandData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('default');
  const { language: lang, setLanguage } = useLanguage();
  const { t } = useTranslation(lang);

  useEffect(() => {
    loadAll();
  }, []);

  const loadAll = async () => {
    try {
      const [citiesRes, islandRes] = await Promise.all([
        fetch(`${BACKEND_URL}/api/cities`).then(r => r.json()).catch(() => ({ cities: [] })),
        fetch(`${BACKEND_URL}/api/island`).then(r => r.json()).catch(() => null),
      ]);
      setCities(citiesRes.cities || []);
      setTonIslandData(islandRes);
    } catch (error) {
      console.error('Failed to load cities:', error);
    } finally {
      setLoading(false);
    }
  };

  const getName = (city) => {
    const override = CITY_I18N[city.id]?.name?.[lang];
    if (override) return override;
    if (typeof city.name === 'string') return city.name;
    return city.name?.[lang] || city.name?.en || city.name?.ru || 'Unknown';
  };
  const getDesc = (city) => {
    const override = CITY_I18N[city.id]?.description?.[lang];
    if (override) return override;
    if (typeof city.description === 'string') return city.description;
    return city.description?.[lang] || city.description?.en || city.description?.ru || '';
  };

  const isCityActive = (city) => ACTIVE_CITY_IDS.has(city.id);

  // Merge real GRAM Island data (correct grid + 478 plots) over the demo entry
  const enrichCity = (city) => {
    if (city.id !== 'ton-island' || !tonIslandData) return city;
    const cells = tonIslandData.cells || [];
    const sellable = cells.filter(c => !c.is_empty).length;
    const owned = cells.filter(c => !!c.owner).length;
    return {
      ...city,
      grid_preview: tonIslandData.grid || city.grid_preview,
      stats: {
        ...(city.stats || {}),
        total_plots: sellable,
        owned_plots: owned,
        total_businesses: tonIslandData.stats?.businesses ?? city.stats?.total_businesses ?? 0,
      },
    };
  };

  const enrichedCities = cities.map(enrichCity);

  const filteredCities = enrichedCities
    .filter((city) => getName(city).toLowerCase().includes(searchQuery.toLowerCase()))
    .sort((a, b) => {
      if (a.id === 'ton-island') return -1;
      if (b.id === 'ton-island') return 1;
      const aActive = isCityActive(a) ? 0 : 1;
      const bActive = isCityActive(b) ? 0 : 1;
      if (aActive !== bActive) return aActive - bActive;
      if (sortBy === 'name') return getName(a).localeCompare(getName(b));
      if (sortBy === 'price') return (a.base_price || 0) - (b.base_price || 0);
      if (sortBy === 'players') return (b.stats?.active_players || 0) - (a.stats?.active_players || 0);
      return 0;
    });

  const handleCardClick = (city) => {
    if (isCityActive(city)) {
      // Only `ton-island` is active. Other "active" cities don't exist
      // anymore — old `/game/:cityId` route was removed because that map
      // implementation had no business icons. If a new active city is ever
      // added, route it here.
      navigate('/ton-island');
    } else {
      toast.info(`${getName(city)} ${str.toastTitle}`, {
        description: str.toastDesc,
        duration: 3500,
      });
    }
  };

  const changeLang = (newLang) => {
    setLanguage?.(newLang);
    try { localStorage.setItem('ton_city_lang', newLang); } catch { /* ignore */ }
  };

  const str = getStr(lang);

  // No full-screen loader: render the page directly. Cities load quickly,
  // and any short delay is visually masked by the existing skeleton/empty state.

  return (
    <div className="flex min-h-screen bg-void font-rajdhani" data-testid="maps-page">
      {/* Sidebar (desktop) */}
      <Sidebar user={user} />

      {/* Main scroll container, leaves space for collapsed sidebar on lg+ */}
      <div className="flex-1 relative overflow-x-hidden lg:ml-16 pb-24 lg:pb-8">
      {/* Background grid */}
      <div className="absolute inset-0 opacity-5 pointer-events-none">
        <div
          className="absolute inset-0"
          style={{
            backgroundImage:
              'linear-gradient(rgba(0, 240, 255, 0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 240, 255, 0.1) 1px, transparent 1px)',
            backgroundSize: '40px 40px',
          }}
        />
      </div>

      <div className="relative z-10">
        {/* Page Title — content row aligned with the burger button on mobile. */}
        <div className="container mx-auto px-3 sm:px-6 tg-header-pad sm:pt-10">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-4 sm:mb-8"
          >
            <h1 className="font-unbounded text-base sm:text-3xl lg:text-4xl font-bold text-white uppercase flex items-center gap-2 sm:gap-3 sm:justify-center min-h-[2.5rem] mb-2 sm:mb-3" data-testid="maps-title">
              <MapPin className="w-5 h-5 sm:w-8 sm:h-8 text-cyber-cyan shrink-0" />
              <span className="leading-none">{str.title}</span>
            </h1>
            <p className="text-text-muted w-full sm:max-w-xl sm:mx-auto text-xs sm:text-base sm:text-center sm:px-2 leading-snug">
              {str.subtitle}
            </p>
          </motion.div>

          {/* Filters */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="flex flex-col sm:flex-row gap-2 sm:gap-4 mb-4 sm:mb-8 w-full sm:max-w-2xl sm:mx-auto"
          >
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={str.search}
                className="pl-10 bg-white/5 border-white/10 text-white placeholder:text-text-muted"
                data-testid="maps-search-input"
              />
            </div>

            <Select value={sortBy} onValueChange={setSortBy}>
              <SelectTrigger className="w-full sm:w-44 bg-white/5 border-white/10 text-white" data-testid="maps-sort-select">
                <Filter className="w-4 h-4 mr-2" />
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-panel border-grid-border">
                <SelectItem value="default">{str.sortDefault}</SelectItem>
                <SelectItem value="name">{str.sortName}</SelectItem>
                <SelectItem value="price">{str.sortPrice}</SelectItem>
                <SelectItem value="players">{str.sortPlayers}</SelectItem>
              </SelectContent>
            </Select>
          </motion.div>

          {/* Cities Grid */}
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-6 max-w-6xl mx-auto" data-testid="maps-grid">
            {filteredCities.map((city, index) => {
              const active = isCityActive(city);
              const rawTotal = city.stats?.total_plots || 0;
              const total = PLOT_COUNT_OVERRIDES[city.id] ?? rawTotal;
              const owned = city.stats?.owned_plots || 0;
              const available = Math.max(0, total - owned);
              const cityName = getName(city);
              const palette = STYLE_PALETTES[city.style] || STYLE_PALETTES.cyber;
              const rawPriceChip = PRICE_CHIP_OVERRIDES[city.id];
              const priceChip = rawPriceChip
                ? { label: `${str.priceFrom} ${rawPriceChip.value}`, currency: rawPriceChip.currency }
                : { label: String(city.base_price || 0), currency: str.backendPrice };

              return (
                <motion.div
                  key={city.id}
                  initial={{ opacity: 0, y: 24 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.05 + index * 0.05, type: 'spring', stiffness: 110, damping: 18 }}
                  whileHover={{ y: -6, scale: 1.01 }}
                  className={`group relative rounded-2xl overflow-hidden cursor-pointer border backdrop-blur-md transition-colors duration-300 ${
                    active
                      ? 'border-cyber-cyan/30 hover:border-cyber-cyan/70'
                      : 'border-white/5 hover:border-amber-500/40'
                  }`}
                  style={{
                    background: 'linear-gradient(160deg, rgba(15,18,28,0.85) 0%, rgba(8,10,16,0.92) 100%)',
                    boxShadow: active
                      ? `0 0 0 1px rgba(255,255,255,0.02), 0 24px 48px -28px ${palette.glow}`
                      : '0 18px 36px -28px rgba(0,0,0,0.6)',
                  }}
                  onClick={() => handleCardClick(city)}
                  data-testid={`city-card-${city.id}`}
                >
                  {/* Animated radial accent */}
                  {active && (
                    <div
                      className="pointer-events-none absolute -top-24 -right-24 w-64 h-64 rounded-full blur-3xl opacity-30 group-hover:opacity-50 transition-opacity"
                      style={{ background: palette.glow }}
                    />
                  )}

                  {/* Status Badge */}
                  <div className="absolute top-2 right-2 sm:top-3 sm:right-3 z-20">
                    {active ? (
                      <span
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 sm:px-2.5 sm:py-1 rounded-full text-[8px] sm:text-[10px] font-bold uppercase tracking-wider bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 backdrop-blur-md"
                        data-testid={`status-${city.id}`}
                      >
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400" />
                        </span>
                        {str.active}
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 sm:px-2.5 sm:py-1 rounded-full text-[8px] sm:text-[10px] font-bold uppercase tracking-wider bg-amber-500/15 border border-amber-500/40 text-amber-300 backdrop-blur-md"
                        data-testid={`status-${city.id}`}
                      >
                        <Construction className="w-2.5 h-2.5 sm:w-3 sm:h-3" />
                        {str.dev}
                      </span>
                    )}
                  </div>

                  {/* Top-down Preview area */}
                  <div
                    className="relative h-28 sm:h-52 overflow-hidden border-b border-white/5"
                    style={{
                      background:
                        `radial-gradient(ellipse at top, ${palette.water1} 0%, ${palette.water2} 70%, #02060a 100%)`,
                    }}
                  >
                    <CityTopDownPreview
                      grid={city.grid_preview}
                      style={city.style}
                      cityId={city.id}
                      isActive={active}
                      height={208}
                    />

                    {/* Lock overlay for in-development cities */}
                    {!active && (
                      <div className="absolute inset-0 flex items-center justify-center bg-black/55 backdrop-blur-[2px] z-[2]">
                        <div className="flex flex-col items-center gap-1 sm:gap-2 px-2 sm:px-4 py-1 sm:py-2 rounded-xl">
                          <div className="w-8 h-8 sm:w-12 sm:h-12 rounded-full bg-amber-500/15 border border-amber-500/40 flex items-center justify-center">
                            <Lock className="w-4 h-4 sm:w-6 sm:h-6 text-amber-400" />
                          </div>
                          <span className="text-amber-200 text-[9px] sm:text-xs font-bold uppercase tracking-wider">{str.comingSoon}</span>
                        </div>
                      </div>
                    )}

                    {/* Style chip */}
                    <div className="absolute top-2 left-2 sm:top-3 sm:left-3 z-[3]">
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 sm:px-2 rounded-md text-[8px] sm:text-[10px] font-bold uppercase tracking-wider bg-black/40 border border-white/10 text-white/80">
                        <Activity className="w-2.5 h-2.5 sm:w-3 sm:h-3" style={{ color: palette.land }} />
                        {city.style}
                      </span>
                    </div>

                    {/* Bottom shine bar */}
                    <div
                      className="absolute bottom-0 left-0 right-0 h-8 sm:h-12 pointer-events-none"
                      style={{
                        background: `linear-gradient(to top, rgba(8,10,16,0.92), transparent)`,
                      }}
                    />
                  </div>

                  {/* Card Body */}
                  <div className="p-2.5 sm:p-5 relative z-[3]">
                    <div className="flex items-start justify-between gap-1.5 sm:gap-3 mb-1">
                      <h3
                        className={`font-unbounded text-xs sm:text-lg font-bold uppercase tracking-tight transition-colors leading-tight ${
                          active ? 'text-white group-hover:text-cyber-cyan' : 'text-white/85'
                        }`}
                        data-testid={`city-name-${city.id}`}
                      >
                        {cityName}
                      </h3>
                      {active && (
                        <span className="shrink-0 hidden sm:inline-flex items-center gap-1 text-[11px] font-mono font-bold text-emerald-300 bg-emerald-500/10 border border-emerald-500/25 rounded-md px-2 py-0.5">
                          <Coins className="w-3 h-3" />
                          {priceChip.label} {priceChip.currency}
                        </span>
                      )}
                    </div>
                    {active && (
                      <span className="sm:hidden inline-flex items-center gap-1 text-[9px] font-mono font-bold text-emerald-300 bg-emerald-500/10 border border-emerald-500/25 rounded-md px-1.5 py-0.5 mb-2">
                        <Coins className="w-2.5 h-2.5" />
                        {priceChip.label} {priceChip.currency}
                      </span>
                    )}
                    <p className="text-text-muted text-[10px] sm:text-xs mb-2 sm:mb-4 line-clamp-2 sm:min-h-[2rem] leading-snug">
                      {getDesc(city)}
                    </p>

                    {/* Plots stats */}
                    <div className="grid grid-cols-2 gap-1.5 sm:gap-2.5 mb-2 sm:mb-4">
                      <div
                        className="rounded-md sm:rounded-lg p-1.5 sm:p-2.5 border border-white/5"
                        style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01))' }}
                      >
                        <div className="text-[8px] sm:text-[10px] text-text-muted uppercase tracking-wider mb-0.5 flex items-center gap-0.5 sm:gap-1">
                          <MapPin className="w-2.5 h-2.5 sm:w-3 sm:h-3" /> {str.total}
                        </div>
                        <div className="text-cyber-cyan font-mono text-xs sm:text-base font-bold" data-testid={`total-plots-${city.id}`}>
                          {total || '—'}
                        </div>
                      </div>
                      <div
                        className="rounded-md sm:rounded-lg p-1.5 sm:p-2.5 border border-white/5"
                        style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01))' }}
                      >
                        <div className="text-[8px] sm:text-[10px] text-text-muted uppercase tracking-wider mb-0.5 flex items-center gap-0.5 sm:gap-1">
                          <Users className="w-2.5 h-2.5 sm:w-3 sm:h-3" /> {str.available}
                        </div>
                        <div
                          className={`font-mono text-xs sm:text-base font-bold ${active ? 'text-emerald-400' : 'text-amber-300'}`}
                          data-testid={`available-plots-${city.id}`}
                        >
                          {active ? available : '—'}
                        </div>
                      </div>
                    </div>

                    {/* Availability bar (only active) */}
                    {active && total > 0 && (
                      <div className="mb-2 sm:mb-4">
                        <div className="flex items-center justify-between text-[8px] sm:text-[10px] text-text-muted uppercase tracking-wider mb-1">
                          <span>{str.filled}</span>
                          <span>{((owned / total) * 100).toFixed(1)}%</span>
                        </div>
                        <div className="h-1 sm:h-1.5 bg-white/5 rounded-full overflow-hidden">
                          <div
                            className="h-full transition-all"
                            style={{
                              width: `${Math.min(100, (owned / total) * 100)}%`,
                              background: `linear-gradient(90deg, ${palette.land}, ${palette.accent})`,
                            }}
                          />
                        </div>
                      </div>
                    )}

                    {/* Action button */}
                    <Button
                      className={`w-full h-8 sm:h-10 text-[11px] sm:text-sm px-2 transition-all ${
                        active
                          ? 'bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan hover:text-black hover:shadow-[0_0_18px_rgba(29,227,255,0.45)]'
                          : 'bg-amber-500/10 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 cursor-not-allowed'
                      }`}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCardClick(city);
                      }}
                      data-testid={`enter-city-${city.id}`}
                    >
                      {active ? (
                        <>
                          <Sparkles className="w-3 h-3 sm:w-4 sm:h-4 mr-1 sm:mr-2" />
                          {str.enter}
                          <ArrowRight className="w-3 h-3 sm:w-4 sm:h-4 ml-1 sm:ml-2 group-hover:translate-x-1 transition-transform" />
                        </>
                      ) : (
                        <>
                          <Construction className="w-3 h-3 sm:w-4 sm:h-4 mr-1 sm:mr-2" />
                          {str.soon}
                        </>
                      )}
                    </Button>
                  </div>
                </motion.div>
              );
            })}
          </div>

          {!loading && filteredCities.length === 0 && (
            <div className="text-center py-12" data-testid="maps-empty">
              <MapPin className="w-12 h-12 text-text-muted mx-auto mb-4 opacity-50" />
              <p className="text-text-muted">{str.empty}</p>
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
