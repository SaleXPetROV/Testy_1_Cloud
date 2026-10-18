import { useState, useEffect, useRef, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Download, Search, RefreshCw } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api/admin`;

export default function AdminReferralsList() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [sort, setSort] = useState('active'); // active | total
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const sentinelRef = useRef(null);
  const offsetRef = useRef(0);
  const doneRef = useRef(false);

  const token = () => localStorage.getItem('token');

  const fetchPage = useCallback(async (offset = 0, replace = false) => {
    const t = token();
    if (!t) return;
    if (replace) setLoading(true); else setLoadingMore(true);
    try {
      const params = new URLSearchParams({
        sort,
        offset: String(offset),
        limit: '100',
      });
      if (search.trim()) params.set('search', search.trim());
      const res = await fetch(`${API}/referrals?${params.toString()}`, {
        headers: { Authorization: `Bearer ${t}` },
      });
      const data = await res.json();
      const newRows = data.rows || [];
      setTotal(data.total_count || 0);
      if (replace) {
        setRows(newRows);
        offsetRef.current = newRows.length;
      } else {
        setRows(prev => [...prev, ...newRows]);
        offsetRef.current = offset + newRows.length;
      }
      doneRef.current = offsetRef.current >= (data.total_count || 0);
    } catch (e) { /* silent */ }
    finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [sort, search]);

  useEffect(() => {
    doneRef.current = false;
    offsetRef.current = 0;
    fetchPage(0, true);
  }, [sort, fetchPage]);

  useEffect(() => {
    if (!sentinelRef.current) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && !loadingMore && !doneRef.current) {
        fetchPage(offsetRef.current, false);
      }
    }, { rootMargin: '200px' });
    io.observe(sentinelRef.current);
    return () => io.disconnect();
  }, [fetchPage, loadingMore]);

  const doSearch = (e) => {
    e.preventDefault();
    doneRef.current = false;
    offsetRef.current = 0;
    fetchPage(0, true);
  };

  const handleExport = async () => {
    const t = token();
    if (!t) return;
    try {
      const res = await fetch(`${API}/referrals/export.csv?sort=${sort}`, {
        headers: { Authorization: `Bearer ${t}` },
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `referrals_${sort}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { /* silent */ }
  };

  return (
    <div className="glass-panel rounded-xl border border-white/10 p-4" data-testid="admin-referrals-panel">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="font-unbounded text-sm font-bold text-white">Рефералы ({total})</h3>
        <div className="flex items-center gap-2 flex-wrap">
          <Tabs value={sort} onValueChange={setSort}>
            <TabsList className="bg-white/5 border border-white/10">
              <TabsTrigger value="active" data-testid="referrals-sort-active">Активные</TabsTrigger>
              <TabsTrigger value="total" data-testid="referrals-sort-total">По количеству</TabsTrigger>
            </TabsList>
          </Tabs>
          <Button size="sm" variant="outline" onClick={handleExport} className="border-white/20 text-white" data-testid="referrals-export-btn">
            <Download className="w-4 h-4 mr-1" /> CSV
          </Button>
        </div>
      </div>

      <form onSubmit={doSearch} className="mb-3 flex gap-2">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
          <Input
            placeholder="Поиск по username..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-white/5 border-white/10 text-white pl-8"
            data-testid="referrals-search-input"
          />
        </div>
        <Button type="submit" variant="outline" className="border-white/20 text-white">Найти</Button>
      </form>

      <div className="overflow-x-auto">
        <div className="min-w-[600px]">
          <div className="grid grid-cols-[60px_1fr_120px_120px_140px] gap-2 px-3 py-2 text-[11px] uppercase tracking-wider text-text-muted sticky top-0 bg-black/40 backdrop-blur border-b border-white/10">
            <div>#</div>
            <div>Пользователь</div>
            <div className="text-right">Всего рефералов</div>
            <div className="text-right">Активные</div>
            <div className="text-right">Кошелёк</div>
          </div>
          <div className="divide-y divide-white/5">
            {loading && rows.length === 0 && (
              <div className="flex items-center justify-center py-10 text-text-muted">
                <RefreshCw className="w-4 h-4 animate-spin mr-2" /> Загрузка...
              </div>
            )}
            {!loading && rows.length === 0 && (
              <div className="text-center py-10 text-text-muted text-sm">Нет данных</div>
            )}
            {rows.map((r, idx) => (
              <div key={r.user_id || idx}
                className="grid grid-cols-[60px_1fr_120px_120px_140px] gap-2 items-center px-3 py-2.5 hover:bg-white/5"
                data-testid={`admin-referral-row-${idx}`}
              >
                <div className="font-mono text-text-muted text-sm">#{r.rank || idx + 1}</div>
                <div className="text-white font-medium text-sm truncate">@{r.username || '—'}</div>
                <div className="text-right text-white font-mono">{r.total || 0}</div>
                <div className="text-right text-green-300 font-mono font-bold">{r.active || 0}</div>
                <div className="text-right text-text-muted font-mono text-xs truncate">
                  {r.wallet_address ? `${r.wallet_address.slice(0, 4)}…${r.wallet_address.slice(-4)}` : '—'}
                </div>
              </div>
            ))}
          </div>
          {!doneRef.current && rows.length > 0 && (
            <div ref={sentinelRef} className="flex items-center justify-center py-4">
              {loadingMore ? (
                <RefreshCw className="w-5 h-5 animate-spin text-cyan-400" />
              ) : (
                <span className="text-text-muted text-xs">Прокрутите для загрузки</span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
