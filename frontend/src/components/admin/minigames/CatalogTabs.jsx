/** Admin «Мини-игры»: награды, сундуки, усилители, NFT (тираж + склад), пазлы, игроки. Russian only. */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, Field, ImagePick, NamesI18n, Row, Modal, Stat, inp, inpS, err, img, fmt, dt, EFFECTS, REWARD_TYPES, GRANT_ST, ANOMALY } from './mgAdminKit';

function useList(api, path) {
  const [data, setData] = useState(null);
  const load = useCallback(() => api.get(path).then(setData).catch(err), [path]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  return [data, load];
}

// ───────────────────────── Награды ─────────────────────────
export function RewardsTab({ api }) {
  const [rows, load] = useList(api, '/admin/minigames/rewards');
  const [refs, setRefs] = useState({ containers: [], boosters: [], nfts: [] });
  const [edit, setEdit] = useState(null);
  useEffect(() => {
    Promise.all([api.get('/admin/minigames/containers'), api.get('/admin/minigames/boosters'), api.get('/admin/minigames/nfts')])
      .then(([c, b, n]) => setRefs({ containers: c.containers, boosters: b, nfts: n.nfts })).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async () => {
    try {
      if (edit.id) await api.put(`/admin/minigames/rewards/${edit.id}`, edit); else await api.post('/admin/minigames/rewards', edit);
      toast.success('Сохранено'); setEdit(null); load();
    } catch (e) { err(e); }
  };
  const checkAll = async () => { try { const r = await api.post('/admin/minigames/rewards/check-all', {}); toast.success(`Проверено игроков: ${r.players}, выдано наград: ${r.given}`); load(); } catch (e) { err(e); } };
  const set = (k, v) => setEdit((x) => ({ ...x, [k]: v }));
  return (
    <Card title="Награды за пороги" right={<div className="flex gap-2"><Button size="sm" variant="outline" onClick={checkAll} data-testid="mg-check-all">Проверить пороги для всех</Button>
      <Button size="sm" onClick={() => setEdit({ category: 'points', type: 'container', threshold: 1000, is_active: true, name: '' })}>+ Награда</Button></div>}>
      <div className="text-xs text-text-muted">«За очки» — по сумме очков акции, выдаются заново в каждой акции. «За рекорд» — по лучшей партии, один раз за всё время.</div>
      {['points', 'best'].map((cat) => (
        <div key={cat}>
          <div className="text-xs font-bold text-cyan-300 mt-2">{cat === 'points' ? 'За очки акции' : 'За рекорд партии'}</div>
          {(rows || []).filter((r) => r.category === cat).map((r) => (
            <Row key={r.id} off={!r.is_active} onEdit={() => setEdit({ ...r })}>
              <div className="w-10 h-10 rounded bg-black/40 overflow-hidden flex items-center justify-center shrink-0">{r.image_url ? <img src={img(r.image_url)} alt="" className="w-full h-full object-cover" /> : '🏅'}</div>
              <div className="min-w-0"><div className="text-white truncate">{r.name}</div><div className="text-[11px] text-text-muted">{REWARD_TYPES[r.type]} · порог {fmt(r.threshold)} · выдано {r.given}{r.is_active ? '' : ' · выключена'}</div></div>
            </Row>
          ))}
        </div>
      ))}
      {edit && (
        <Modal title={edit.id ? 'Награда' : 'Новая награда'} onClose={() => setEdit(null)} onSave={save}>
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Название (рус.)"><input className={inp} value={edit.name || ''} onChange={(e) => set('name', e.target.value)} /></Field>
            <Field label="Код (латиница, уникальный)"><input className={inp} value={edit.code || ''} onChange={(e) => set('code', e.target.value.replace(/[^a-z0-9_]/gi, ''))} /></Field>
            <NamesI18n value={edit.name_i18n} onChange={(v) => set('name_i18n', v)} />
            <Field label="Категория"><select className={inp} value={edit.category} onChange={(e) => set('category', e.target.value)}><option value="points">За очки акции</option><option value="best">За рекорд партии</option></select></Field>
            <Field label="Порог, очков"><input type="number" className={inp} value={edit.threshold} onChange={(e) => set('threshold', e.target.value)} /></Field>
            <Field label="Тип"><select className={inp} value={edit.type} onChange={(e) => set('type', e.target.value)}>{Object.entries(REWARD_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
            {edit.type === 'container' && <Field label="Сундук"><select className={inp} value={edit.container_id || ''} onChange={(e) => set('container_id', e.target.value)}><option value="">—</option>{refs.containers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>}
            {edit.type === 'booster' && <Field label="Усилитель"><select className={inp} value={edit.booster_id || ''} onChange={(e) => set('booster_id', e.target.value)}><option value="">—</option>{refs.boosters.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field>}
            {edit.type === 'nft' && <Field label="NFT (со склада, со своим тиражом)"><select className={inp} value={edit.nft_id || ''} onChange={(e) => set('nft_id', e.target.value)}><option value="">—</option>{refs.nfts.map((n) => <option key={n.id} value={n.id}>{n.name} · тираж {n.supply_total}</option>)}</select></Field>}
            <Field label="Описание" wide><input className={inp} value={edit.description || ''} onChange={(e) => set('description', e.target.value)} /></Field>
            <Field label="Картинка"><ImagePick api={api} value={edit.image_url} onChange={(v) => set('image_url', v)} /></Field>
            <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!edit.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Включена</label>
          </div>
        </Modal>
      )}
    </Card>
  );
}

// ───────────────────────── Сундуки ─────────────────────────
export function ContainersTab({ api }) {
  const [data, load] = useList(api, '/admin/minigames/containers');
  const [puzzles, setPuzzles] = useState([]);
  const [edit, setEdit] = useState(null);
  useEffect(() => { api.get('/admin/minigames/puzzles').then(setPuzzles).catch(() => {}); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k, v) => setEdit((x) => ({ ...x, [k]: v }));
  const setRow = (i, k, v) => setEdit((x) => ({ ...x, rows: x.rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)) }));
  const total = (edit?.rows || []).reduce((a, r) => a + (Number(r.weight) || 0), 0) || 1;
  const save = async () => {
    try {
      if (edit.id) await api.put(`/admin/minigames/containers/${edit.id}`, edit); else await api.post('/admin/minigames/containers', edit);
      toast.success('Сохранено'); setEdit(null); load();
    } catch (e) { err(e); }
  };
  return (
    <Card title="Сундуки (контейнеры)" right={<Button size="sm" onClick={() => setEdit({ name: '', rolls: 1, is_active: true, rows: [{ kind: 'resource', resource: 'energy', min: 10, max: 30, weight: 10 }] })}>+ Сундук</Button>}>
      <div className="text-xs text-text-muted">При открытии делается N бросков по весам среди строк: ресурс (из производимых бизнесами, количество от min до max) или кусочек пазла. Вес 0 — строка не выпадает.</div>
      {(data?.containers || []).map((c) => (
        <Row key={c.id} off={!c.is_active} onEdit={() => setEdit({ ...c, rows: c.rows.map(({ chance, ...r }) => r) })}>
          <div className="w-10 h-10 rounded bg-black/40 overflow-hidden flex items-center justify-center shrink-0">{c.image_url ? <img src={img(c.image_url)} alt="" className="w-full h-full object-cover" /> : '🎁'}</div>
          <div className="min-w-0 flex-1">
            <div className="text-white">{c.name} <span className="text-[11px] text-text-muted">· бросков {c.rolls} · выдано {c.given} · открыто {c.opened}</span></div>
            <div className="text-[11px] text-text-muted truncate">{c.rows.map((r) => (r.kind === 'puzzle' ? `🧩 ${(puzzles.find((p) => p.id === r.puzzle_id) || {}).name || r.puzzle_id} ${r.chance}%` : `${r.resource} ${r.min}–${r.max} ${r.chance}%`)).join(' · ')}</div>
          </div>
        </Row>
      ))}
      {edit && (
        <Modal title={edit.id ? 'Сундук' : 'Новый сундук'} onClose={() => setEdit(null)} onSave={save}>
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Название (рус.)"><input className={inp} value={edit.name} onChange={(e) => set('name', e.target.value)} /></Field>
            <Field label="Бросков за открытие (1–5)"><input type="number" min={1} max={5} className={inp} value={edit.rolls} onChange={(e) => set('rolls', e.target.value)} /></Field>
            <NamesI18n value={edit.name_i18n} onChange={(v) => set('name_i18n', v)} />
            <Field label="Картинка"><ImagePick api={api} value={edit.image_url} onChange={(v) => set('image_url', v)} /></Field>
            <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!edit.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Включён</label>
          </div>
          <div className="space-y-2">
            {edit.rows.map((r, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 text-xs">
                <select className={`${inpS} w-32`} value={r.kind} onChange={(e) => setRow(i, 'kind', e.target.value)}><option value="resource">Ресурс</option><option value="puzzle">Кусочек пазла</option></select>
                {r.kind === 'resource' ? (<>
                  <select className={`${inpS} w-36`} value={r.resource} onChange={(e) => setRow(i, 'resource', e.target.value)}>{(data?.resources || []).map((x) => <option key={x} value={x}>{x}</option>)}</select>
                  <span className="text-text-muted">от</span><input type="number" className={`${inpS} w-20`} value={r.min} onChange={(e) => setRow(i, 'min', e.target.value)} />
                  <span className="text-text-muted">до</span><input type="number" className={`${inpS} w-20`} value={r.max} onChange={(e) => setRow(i, 'max', e.target.value)} />
                </>) : (
                  <select className={`${inpS} w-56`} value={r.puzzle_id || ''} onChange={(e) => setRow(i, 'puzzle_id', e.target.value)}><option value="">— пазл —</option>{puzzles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
                )}
                <span className="text-text-muted">вес</span><input type="number" className={`${inpS} w-20`} value={r.weight} onChange={(e) => setRow(i, 'weight', e.target.value)} />
                <span className="text-cyan-300 w-14">{((Number(r.weight) || 0) * 100 / total).toFixed(1)}%</span>
                <Button size="sm" variant="outline" className="h-7 px-2" onClick={() => set('rows', edit.rows.filter((_, j) => j !== i))}>✕</Button>
              </div>
            ))}
            <Button size="sm" variant="outline" onClick={() => set('rows', [...edit.rows, { kind: 'resource', resource: (data?.resources || ['energy'])[0], min: 1, max: 5, weight: 10 }])}>+ Строка</Button>
          </div>
        </Modal>
      )}
    </Card>
  );
}

// ───────────────────────── Усилители ─────────────────────────
export function BoostersTab({ api }) {
  const [rows, load] = useList(api, '/admin/minigames/boosters');
  const [edit, setEdit] = useState(null);
  const set = (k, v) => setEdit((x) => ({ ...x, [k]: v }));
  const save = async () => {
    try {
      if (edit.id) await api.put(`/admin/minigames/boosters/${edit.id}`, edit); else await api.post('/admin/minigames/boosters', edit);
      toast.success('Сохранено'); setEdit(null); load();
    } catch (e) { err(e); }
  };
  return (
    <Card title="Усилители" right={<Button size="sm" onClick={() => setEdit({ name: '', effect: 'auto_shift', duration_hours: 24, is_active: true })}>+ Усилитель</Button>}>
      <div className="text-xs text-text-muted">Игрок получает усилитель в инвентарь и активирует сам. Повторная активация продлевает действующий эффект.</div>
      {(rows || []).map((b) => (
        <Row key={b.id} off={!b.is_active} onEdit={() => setEdit({ ...b })}>
          <div className="text-xl">⚡</div>
          <div className="min-w-0"><div className="text-white">{b.name}</div><div className="text-[11px] text-text-muted">{EFFECTS[b.effect]} · {b.duration_hours} ч · код {b.code} · активны сейчас {b.active_now} · ждут активации {b.available}</div></div>
        </Row>
      ))}
      {edit && (
        <Modal title={edit.id ? 'Усилитель' : 'Новый усилитель'} onClose={() => setEdit(null)} onSave={save}>
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Название (рус.)"><input className={inp} value={edit.name} onChange={(e) => set('name', e.target.value)} /></Field>
            <Field label="Код"><input className={inp} value={edit.code || ''} onChange={(e) => set('code', e.target.value.replace(/[^a-z0-9_]/gi, ''))} /></Field>
            <NamesI18n value={edit.name_i18n} onChange={(v) => set('name_i18n', v)} />
            <Field label="Эффект"><select className={inp} value={edit.effect} onChange={(e) => set('effect', e.target.value)}>{Object.entries(EFFECTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
            <Field label="Длительность, часов"><input type="number" min={1} max={720} className={inp} value={edit.duration_hours} onChange={(e) => set('duration_hours', e.target.value)} /></Field>
            <Field label="Описание" wide><input className={inp} value={edit.description || ''} onChange={(e) => set('description', e.target.value)} /></Field>
            <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!edit.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Включён</label>
          </div>
        </Modal>
      )}
    </Card>
  );
}

// ───────────────────────── NFT: тираж и склад ─────────────────────────
export function NftTab({ api }) {
  const [data, load] = useList(api, '/admin/minigames/nfts');
  const [edit, setEdit] = useState(null);
  const [imp, setImp] = useState(null);           // {nft, collection_address, nft_address}
  const [items, setItems] = useState(null);
  const [grants, setGrants] = useState(null);
  const set = (k, v) => setEdit((x) => ({ ...x, [k]: v }));
  const save = async () => {
    try {
      if (edit.id) await api.put(`/admin/minigames/nfts/${edit.id}`, edit); else await api.post('/admin/minigames/nfts', edit);
      toast.success('Сохранено'); setEdit(null); load();
    } catch (e) { err(e); }
  };
  const doImport = async () => {
    try {
      const body = imp.mode === 'one' ? { nft_address: imp.addr } : { collection_address: imp.addr };
      const r = await api.post(`/admin/minigames/nfts/${imp.nft.id}/import`, body);
      toast.success(`Добавлено ${r.added}, пропущено ${r.skipped}. ${r.note}`); setImp(null); load();
    } catch (e) { err(e); }
  };
  const settings = async (patch) => { try { await api.put('/admin/minigames/nft-settings', patch); load(); } catch (e) { err(e); } };
  const retry = async (g) => { try { await api.post(`/admin/minigames/nft-grants/${g.id}/retry`, {}); toast.success('Поставлено в очередь'); setGrants(await api.get('/admin/minigames/nft-grants')); } catch (e) { err(e); } };
  if (!data) return <div className="text-sm text-text-muted">Загрузка…</div>;
  const st = data.settings || {};
  return (
    <div className="space-y-4">
      <Card title="Сеть и кошелёк проекта">
        <div className="grid md:grid-cols-4 gap-3 text-sm">
          <Field label="Сеть">
            <select className={inp} value={st.network} onChange={(e) => settings({ network: e.target.value })} data-testid="mg-nft-network">
              <option value="testnet">Тестовая (testnet)</option><option value="mainnet">Основная (mainnet)</option>
            </select>
          </Field>
          <label className="flex items-center gap-2 text-white mt-5"><input type="checkbox" checked={!!st.sending_enabled} onChange={(e) => settings({ sending_enabled: e.target.checked })} /> Отправка NFT включена</label>
          <div className="md:col-span-2 text-xs text-text-muted">
            {data.wallet?.error ? <span className="text-red-300">Кошелёк: {data.wallet.error}</span>
              : <>Кошелёк проекта: <span className="text-white break-all">{data.wallet?.address}</span><br />Баланс: <b className={data.wallet?.balance_ton < 0.5 ? 'text-red-300' : 'text-white'}>{data.wallet?.balance_ton?.toFixed(3)} TON</b>{data.wallet?.balance_ton < 0.5 ? ' — мало для комиссий, пополните' : ''}</>}
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {Object.entries(GRANT_ST).map(([k, v]) => <Stat key={k} label={v} value={data.queue?.[k] ?? 0} />)}
        </div>
        <Button size="sm" variant="outline" onClick={async () => setGrants(await api.get('/admin/minigames/nft-grants'))}>Очередь отправки</Button>
        <div className="text-[11px] text-text-muted">Кошелёк проекта — тот же, что для выплат (админка → «Контракт»); на нём нужен TON на комиссии (≈0,05–0,06 TON за отправку). Сначала проверьте всё в тестовой сети. Метаданные SBT отдаёт сервер: базовый адрес SBT-коллекции должен быть <b className="text-white select-all">{(process.env.REACT_APP_BACKEND_URL || window.location.origin).replace(/\/$/, '')}/api/nft-meta/</b> (копия получает адрес …/api/nft-meta/&lt;id NFT&gt;/&lt;номер&gt;.json, картинка берётся из поля «Картинка»).</div>
      </Card>
      <Card title="NFT и тираж" right={<Button size="sm" onClick={() => setEdit({ name: '', kind: 'sbt', supply_total: 100, is_active: true, low_stock_alert: 10, content_template: '{nft_id}/{index}.json' })}>+ NFT</Button>}>
        <div className="text-xs text-text-muted">Тираж — жёсткий предел: сверх него не выдаётся ни одной штуки (ни за пороги, ни за пазлы, ни вручную). Передаваемые NFT выпускаются заранее на кошелёк проекта (например, на GetGems) и импортируются; SBT выпускаются прямо на кошелёк игрока при отправке.</div>
        {(data.nfts || []).map((n) => (
          <div key={n.id} className={`py-2 border-t border-white/5 ${n.is_active ? '' : 'opacity-50'}`} data-testid="mg-nft-row">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded bg-black/40 overflow-hidden flex items-center justify-center shrink-0">{n.image_url ? <img src={img(n.image_url)} alt="" className="w-full h-full object-cover" /> : '💎'}</div>
              <div className="min-w-0 flex-1"><div className="text-white">{n.name} <span className="text-[11px] text-text-muted">· {n.kind === 'sbt' ? 'SBT (непередаваемый)' : 'передаваемый'}</span></div>
                <div className="text-[11px] text-text-muted">тираж {fmt(n.stats.supply_total)} · на складе {fmt(n.stats.free)} · закреплено {fmt(n.stats.reserved)} · отправляется {fmt(n.stats.sending)} · отправлено {fmt(n.stats.delivered)} · осталось выдать {fmt(n.stats.left_to_grant)}{n.stats.waiting_stock ? ` · ждут склада ${n.stats.waiting_stock}` : ''}{n.kind === 'tradable' ? ` · загружено ${n.stats.loaded} из ${n.stats.supply_total}` : ''}</div>
              </div>
              {n.kind === 'tradable' && <Button size="sm" variant="outline" className="h-7 px-2" onClick={() => setImp({ nft: n, mode: 'collection', addr: '' })}>Импорт</Button>}
              <Button size="sm" variant="outline" className="h-7 px-2" onClick={async () => setItems({ nft: n, rows: await api.get(`/admin/minigames/nfts/${n.id}/items`) })}>Склад</Button>
              <Button size="sm" variant="outline" className="h-7 px-2" onClick={() => setEdit({ ...n })}>Изменить</Button>
            </div>
          </div>
        ))}
      </Card>
      {edit && (
        <Modal title={edit.id ? 'NFT' : 'Новый NFT'} onClose={() => setEdit(null)} onSave={save}>
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Название"><input className={inp} value={edit.name} onChange={(e) => set('name', e.target.value)} /></Field>
            <Field label="Тип"><select className={inp} value={edit.kind} onChange={(e) => set('kind', e.target.value)}><option value="sbt">SBT — непередаваемый (выпуск на кошелёк игрока)</option><option value="tradable">Передаваемый (выпущен заранее, импорт)</option></select></Field>
            <Field label="Тираж — сколько штук будет выпущено"><input type="number" min={1} className={inp} value={edit.supply_total} onChange={(e) => set('supply_total', e.target.value)} data-testid="mg-nft-supply" /></Field>
            <Field label="Предупредить, когда на складе осталось"><input type="number" min={0} className={inp} value={edit.low_stock_alert} onChange={(e) => set('low_stock_alert', e.target.value)} /></Field>
            <Field label={edit.kind === 'sbt' ? 'Адрес SBT-коллекции (TEP-85)' : 'Адрес коллекции (для справки)'} wide><input className={inp} value={edit.collection_address || ''} onChange={(e) => set('collection_address', e.target.value)} /></Field>
            {edit.kind === 'sbt' && <Field label="Контент копии (суффикс к базе коллекции)" wide><input className={inp} value={edit.content_template || ''} onChange={(e) => set('content_template', e.target.value)} /></Field>}
            <Field label="Описание" wide><input className={inp} value={edit.description || ''} onChange={(e) => set('description', e.target.value)} /></Field>
            <Field label="Картинка"><ImagePick api={api} value={edit.image_url} onChange={(v) => set('image_url', v)} /></Field>
            <Field label="Свойства (каждое с новой строки: свойство=значение)" wide>
              <textarea className={`${inp} h-20`} value={(edit.attributes || []).map((a) => `${a.trait_type}=${a.value}`).join('\n')}
                onChange={(e) => set('attributes', e.target.value.split('\n').map((l) => l.split('=')).filter((p) => p[0]?.trim()).map(([k, ...v]) => ({ trait_type: k.trim(), value: v.join('=').trim() })))} />
            </Field>
            <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!edit.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Включён</label>
          </div>
        </Modal>
      )}
      {imp && (
        <Modal title={`Импорт на склад: ${imp.nft.name}`} onClose={() => setImp(null)} onSave={doImport}>
          <div className="flex gap-3 text-sm text-white">
            <label className="flex items-center gap-1"><input type="radio" checked={imp.mode === 'collection'} onChange={() => setImp({ ...imp, mode: 'collection' })} /> Вся коллекция на кошельке проекта</label>
            <label className="flex items-center gap-1"><input type="radio" checked={imp.mode === 'one'} onChange={() => setImp({ ...imp, mode: 'one' })} /> Один NFT</label>
          </div>
          <input className={inp} placeholder={imp.mode === 'one' ? 'Адрес NFT' : 'Адрес коллекции'} value={imp.addr} onChange={(e) => setImp({ ...imp, addr: e.target.value })} />
          <div className="text-[11px] text-text-muted">Больше тиража не загрузится. Название и картинка берутся из метаданных.</div>
        </Modal>
      )}
      {items && (
        <Modal title={`Склад: ${items.nft.name}`} onClose={() => setItems(null)}>
          {items.rows.length === 0 && <div className="text-xs text-text-muted">Пусто</div>}
          {items.rows.map((i) => (
            <div key={i.id} className="flex gap-2 text-[11px] py-1 border-t border-white/5 text-white/80">
              <span className="w-24 shrink-0">{i.kind === 'sbt' ? `№ ${(i.index ?? 0) + 1}` : (i.nft_address || '').slice(0, 10) + '…'}</span>
              <span className="w-28 shrink-0">{GRANT_ST[i.status] || (i.status === 'free' ? 'свободен' : i.status)}</span>
              <span className="truncate">{i.username ? `@${i.username}` : ''} {i.tx_hash ? `· ${i.tx_hash.slice(0, 10)}…` : ''}</span>
            </div>
          ))}
        </Modal>
      )}
      {grants && (
        <Modal title="Очередь отправки NFT" onClose={() => setGrants(null)}>
          {grants.length === 0 && <div className="text-xs text-text-muted">Пусто</div>}
          {grants.map((g) => (
            <div key={g.id} className="flex items-center gap-2 text-[11px] py-1.5 border-t border-white/5 text-white/80">
              <span className="w-28 shrink-0">{dt(g.created_at)}</span>
              <span className="w-28 truncate">@{g.username}</span>
              <span className="w-32 truncate">{g.nft_name}</span>
              <span className="flex-1 truncate">{GRANT_ST[g.status] || g.status}{g.attempts ? ` · попыток ${g.attempts}` : ''}{g.error ? ` · ${g.error}` : ''}</span>
              {g.status === 'failed' && <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]" onClick={() => retry(g)}>Повторить</Button>}
            </div>
          ))}
        </Modal>
      )}
    </div>
  );
}

// ───────────────────────── Пазлы ─────────────────────────
export function PuzzlesTab({ api }) {
  const [rows, load] = useList(api, '/admin/minigames/puzzles');
  const [nfts, setNfts] = useState([]);
  const [edit, setEdit] = useState(null);
  useEffect(() => { api.get('/admin/minigames/nfts').then((d) => setNfts(d.nfts)).catch(() => {}); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k, v) => setEdit((x) => ({ ...x, [k]: v }));
  const save = async () => {
    try {
      if (edit.id) await api.put(`/admin/minigames/puzzles/${edit.id}`, edit); else await api.post('/admin/minigames/puzzles', edit);
      toast.success('Сохранено'); setEdit(null); load();
    } catch (e) { err(e); }
  };
  return (
    <Card title="Пазлы NFT" right={<Button size="sm" onClick={() => setEdit({ name: '', is_active: true, repeatable: false })}>+ Пазл</Button>}>
      <div className="text-xs text-text-muted">Картинка режется на 9 частей (3×3). Кусочки выпадают из сундуков (добавьте строку «Кусочек пазла» в сундук), без повторов. «Собрать» отправляет NFT только при привязанном кошельке. Кусочки перестают выпадать новым игрокам, когда NFT осталось не больше, чем игроков, уже собирающих пазл.</div>
      {(rows || []).map((p) => (
        <Row key={p.id} off={!p.is_active} onEdit={() => setEdit({ ...p })}>
          <div className="w-10 h-10 rounded bg-black/40 overflow-hidden flex items-center justify-center shrink-0">{p.image_url ? <img src={img(p.image_url)} alt="" className="w-full h-full object-cover" /> : '🧩'}</div>
          <div className="min-w-0"><div className="text-white">{p.name}</div><div className="text-[11px] text-text-muted">NFT: {(nfts.find((n) => n.id === p.nft_id) || {}).name || p.nft_id} · собирают сейчас {p.collecting} · собрали {p.assembled}{p.has_pieces ? '' : ' · нет картинки'}</div></div>
        </Row>
      ))}
      {edit && (
        <Modal title={edit.id ? 'Пазл' : 'Новый пазл'} onClose={() => setEdit(null)} onSave={save}>
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Название (рус.)"><input className={inp} value={edit.name} onChange={(e) => set('name', e.target.value)} /></Field>
            <Field label="NFT для собравшего"><select className={inp} value={edit.nft_id || ''} onChange={(e) => set('nft_id', e.target.value)}><option value="">—</option>{nfts.map((n) => <option key={n.id} value={n.id}>{n.name} · тираж {n.supply_total}</option>)}</select></Field>
            <NamesI18n value={edit.name_i18n} onChange={(v) => set('name_i18n', v)} />
            <Field label="Картинка (квадратная)"><ImagePick api={api} value={edit.image_url} onChange={(v) => set('image_url', v)} /></Field>
            <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!edit.repeatable} onChange={(e) => set('repeatable', e.target.checked)} /> Можно собирать повторно</label>
            <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!edit.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Включён</label>
          </div>
        </Modal>
      )}
    </Card>
  );
}

// ───────────────────────── Игроки ─────────────────────────
export function PlayersTab({ api }) {
  const [q, setQ] = useState('');
  const [rows, setRows] = useState(null);
  const [cur, setCur] = useState(null);
  const [refs, setRefs] = useState(null);
  const [grant, setGrant] = useState({ kind: 'container', ref_id: '' });
  const search = useCallback(() => api.get(`/admin/minigames/players?q=${encodeURIComponent(q)}`).then(setRows).catch(err), [q]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { search(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    Promise.all([api.get('/admin/minigames/rewards'), api.get('/admin/minigames/containers'), api.get('/admin/minigames/boosters'), api.get('/admin/minigames/nfts')])
      .then(([r, c, b, n]) => setRefs({ reward: r, container: c.containers, booster: b, nft: n.nfts })).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const open = async (u) => { try { setCur(await api.get(`/admin/minigames/players/${u.id}`)); } catch (e) { err(e); } };
  const doGrant = async () => { try { await api.post(`/admin/minigames/players/${cur.user.id}/grant`, grant); toast.success('Выдано'); open(cur.user); } catch (e) { err(e); } };
  const reset = async (what) => {
    if (!window.confirm(what === 'points' ? 'Обнулить очки акции игрока?' : 'Обнулить рекорд игрока?')) return;
    try { await api.post(`/admin/minigames/players/${cur.user.id}/reset`, { what, confirm: true }); toast.success('Сброшено'); open(cur.user); search(); } catch (e) { err(e); }
  };
  return (
    <Card title="Игроки">
      <div className="flex gap-2"><input className={inp} placeholder="Ник или ID" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} /><Button size="sm" onClick={search}>Найти</Button></div>
      {(rows || []).map((u) => (
        <Row key={u.id} onEdit={() => open(u)}><div className="text-white">@{u.username}</div><div className="text-[11px] text-text-muted">очки акции {fmt(u.campaign_points)} · рекорд {fmt(u.mg_best_score)}</div></Row>
      ))}
      {cur && (
        <Modal title={`@${cur.user.username}`} onClose={() => setCur(null)}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <Stat label="Очки акции" value={fmt(cur.rewards.campaign_points)} /><Stat label="Рекорд" value={fmt(cur.rewards.best_score)} />
            <Stat label="Сундуков сегодня" value={`${cur.rewards.chests_today}/${cur.rewards.chests_per_day}`} /><Stat label="Кошелёк" value={cur.user.wallet_address ? 'привязан' : 'нет'} />
          </div>
          <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => reset('points')}>Сбросить очки акции</Button><Button size="sm" variant="outline" onClick={() => reset('best')}>Сбросить рекорд</Button></div>
          <div className="rounded-lg border border-white/10 p-3 space-y-2">
            <div className="text-sm text-white">Выдать вручную</div>
            <div className="flex flex-wrap gap-2">
              <select className={`${inpS} w-36`} value={grant.kind} onChange={(e) => setGrant({ kind: e.target.value, ref_id: '' })}>
                <option value="container">Сундук</option><option value="booster">Усилитель</option><option value="reward">Награду</option><option value="nft">NFT</option>
              </select>
              <select className={`${inpS} flex-1`} value={grant.ref_id} onChange={(e) => setGrant({ ...grant, ref_id: e.target.value })}>
                <option value="">—</option>{(refs?.[grant.kind] || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </select>
              <Button size="sm" onClick={doGrant} disabled={!grant.ref_id}>Выдать</Button>
            </div>
          </div>
          <div className="text-sm text-white">Награды</div>
          {cur.rewards.rewards.filter((r) => r.given).map((r) => <div key={r.id} className="text-[11px] text-white/80">✓ {r.name}{r.grant ? ` · NFT: ${GRANT_ST[r.grant.status] || r.grant.status}` : ''}</div>)}
          <div className="text-[11px] text-text-muted">Сундуков: {cur.rewards.containers.length} (не открыто {cur.rewards.unopened}) · усилителей: {cur.rewards.boosters.length} · пазлов: {cur.rewards.puzzles.filter((p) => p.status !== 'none').length}</div>
          <div className="text-sm text-white">Последние партии</div>
          {cur.games.map((g) => <div key={g.id} className="text-[11px] text-white/80">{dt(g.finished_at)} · {fmt(g.points)} очков · {'★'.repeat(g.stars || 0) || '—'}{g.rejected ? ` · отклонена: ${ANOMALY[g.reject_reason] || g.reject_reason}` : ''}</div>)}
          {cur.anomalies.length > 0 && <div className="text-sm text-red-300">Аномалии: {cur.anomalies.map((a) => ANOMALY[a.reason] || a.reason).join(', ')}</div>}
        </Modal>
      )}
    </Card>
  );
}
