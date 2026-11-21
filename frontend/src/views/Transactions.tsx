import { useEffect, useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { api, money, send, shortDate, TxnFilter } from '../lib'

type SortKey = 'trans_date' | 'merchant' | 'cat' | 'account_name' | 'amount'

export default function Transactions({ ctx, initial }: { ctx: Ctx; initial: TxnFilter }) {
  const [f, setF] = useState<TxnFilter>(initial)
  const [list, setList] = useState<any[] | null>(null)
  const [cats, setCats] = useState<any[]>([])
  const [accounts, setAccounts] = useState<any[]>([])
  const [tags, setTags] = useState<any[]>([])
  const [applyAll, setApplyAll] = useState(true)
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'trans_date', dir: -1 })

  useEffect(() => { api('/categories').then(setCats); api('/accounts').then(setAccounts) }, [])
  useEffect(() => { api('/tags').then(setTags) }, [ctx.version])
  useEffect(() => {
    const p = new URLSearchParams()
    Object.entries(f).forEach(([k, v]) => v !== undefined && v !== '' && p.set(k, String(v)))
    const t = setTimeout(() => api(`/transactions?${p}`).then(setList), f.q ? 250 : 0)
    return () => clearTimeout(t)
  }, [f, ctx.version])
  useEffect(() => setSel(new Set()), [f])

  const set = (k: keyof TxnFilter, v: any) => setF(prev => ({ ...prev, [k]: v || undefined }))
  const changeCat = async (t: any, category: string) => {
    await send(`/transactions/${t.id}`, 'PATCH', { category, apply_to_merchant: applyAll })
    ctx.refresh()
  }
  const toggleOneOff = async (t: any) => { await send(`/transactions/${t.id}`, 'PATCH', { one_off: !t.one_off }); ctx.refresh() }
  const rename = async (t: any) => {
    const name = prompt(`Rename "${t.merchant}" everywhere it appears:`, t.merchant)
    if (name && name !== t.merchant) { await send(`/merchants/${encodeURIComponent(t.merchant_key)}`, 'PATCH', { display_name: name }); ctx.refresh() }
  }

  const reimburse = async (t: any) => {
    const ans = prompt(
      `How much of ${t.merchant} (${money(t.gross_amount, true)} on ${t.trans_date}) was reimbursed?\n` +
      `Leave blank for the full amount · enter 0 to clear.`,
      t.reimbursed ? (t.reimbursed / 100).toFixed(2) : '')
    if (ans === null) return
    const cents = ans.trim() === '' ? t.gross_amount : Math.round(parseFloat(ans.replace(/[$,]/g, '')) * 100)
    if (Number.isNaN(cents)) return
    await send(`/transactions/${t.id}`, 'PATCH', { reimbursed: cents })
    ctx.refresh()
  }
  const reimbursable = (t: any) => (t.kind === 'purchase' || t.kind === 'cash_advance') && t.gross_amount > 0

  // Bulk actions apply to the checked rows, or to everything shown when nothing is checked.
  const targets = () => (list ?? []).filter(t => !sel.size || sel.has(t.id))
  const scope = () => (sel.size ? `${sel.size} selected` : `${(list ?? []).length} shown`)
  const bulkReimburse = async (full: boolean) => {
    const rows = targets().filter(t => reimbursable(t) && (full ? t.reimbursed < t.gross_amount : t.reimbursed > 0))
    if (!rows.length) return
    const total = rows.reduce((s, t) => s + (full ? t.gross_amount - t.reimbursed : t.reimbursed), 0)
    if (!confirm(full ? `Mark ${rows.length} purchase(s) as fully reimbursed (${money(total, true)})?`
                      : `Clear reimbursements on ${rows.length} purchase(s) (${money(total, true)})?`)) return
    await send('/transactions/reimburse', 'POST', { ids: rows.map(t => t.id), full })
    ctx.refresh()
  }
  const bulkTag = async (remove = false) => {
    const rows = targets().filter(t => t.kind !== 'payment' && t.kind !== 'manual')
    if (!rows.length) return
    let tag: string | null = null
    if (!remove) {
      const existing = tags.map(t => t.tag).join(', ')
      tag = prompt(`Add ${rows.length} charge(s) to a trip or event (they become one-off).\n` +
        (existing ? `Existing: ${existing}\n` : '') + 'Name:', f.tag ?? tags[0]?.tag ?? '')
      if (!tag?.trim()) return
    } else if (!confirm(`Remove ${rows.length} charge(s) from their trip and un-mark them as one-off?`)) return
    await send('/transactions/tag', 'POST', { ids: rows.map(t => t.id), tag })
    setSel(new Set())
    ctx.refresh()
  }
  const toggleSel = (id: number) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const allSel = !!list?.length && list.every(t => sel.has(t.id))

  const rows = useMemo(() => {
    const { key, dir } = sort
    return [...(list ?? [])].sort((a, b) => {
      const x = a[key], y = b[key]
      const c = typeof x === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { sensitivity: 'base' })
      return c * dir || (b.trans_date.localeCompare(a.trans_date)) || b.id - a.id
    })
  }, [list, sort])
  const Th = ({ k, label, num }: { k: SortKey; label: string; num?: boolean }) => (
    <th className={`sortable${num ? ' num' : ''}`} aria-sort={sort.key === k ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none'}
      onClick={() => setSort(s => s.key === k ? { key: k, dir: (s.dir * -1) as 1 | -1 } : { key: k, dir: k === 'trans_date' || k === 'amount' ? -1 : 1 })}>
      {label}<span className="sort-ind">{sort.key === k ? (sort.dir > 0 ? ' ▲' : ' ▼') : ''}</span>
    </th>
  )

  const spend = (list ?? []).filter(t => t.parent !== 'Transfers').reduce((s, t) => s + t.amount, 0)
  const selSpend = (list ?? []).filter(t => sel.has(t.id) && t.parent !== 'Transfers').reduce((s, t) => s + t.amount, 0)
  const reimbTotal = (list ?? []).reduce((s, t) => s + (t.reimbursed || 0), 0)
  const filtered = Object.values(f).some(v => v !== undefined && v !== '')
  const canBulk = filtered || sel.size > 0

  return (
    <>
      <div className="toolbar">
        <input type="search" placeholder="Search merchant or description" value={f.q ?? ''} onChange={e => set('q', e.target.value)} style={{ minWidth: 220 }} />
        <input type="month" value={f.month ?? ''} onChange={e => set('month', e.target.value)} />
        <select value={f.parent ?? ''} onChange={e => setF(p => ({ ...p, parent: e.target.value || undefined, category: undefined }))}>
          <option value="">All categories</option>
          {cats.map(c => <option key={c.parent} value={c.parent}>{c.parent}</option>)}
        </select>
        <select value={f.category ?? ''} onChange={e => set('category', e.target.value)}>
          <option value="">All subcategories</option>
          {cats.filter(c => !f.parent || c.parent === f.parent).flatMap(c => c.children).map((c: string) => <option key={c}>{c}</option>)}
        </select>
        <select value={f.account_id ?? ''} onChange={e => set('account_id', e.target.value ? Number(e.target.value) : undefined)}>
          <option value="">All cards</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        {tags.length > 0 && (
          <select value={f.tag ?? ''} onChange={e => set('tag', e.target.value)}>
            <option value="">All trips/events</option>
            {tags.map(t => <option key={t.tag} value={t.tag}>{t.tag}</option>)}
          </select>
        )}
        <label className="muted small">from <input type="date" value={f.date_from ?? ''} onChange={e => set('date_from', e.target.value)} /></label>
        <label className="muted small">to <input type="date" value={f.date_to ?? ''} onChange={e => set('date_to', e.target.value)} /></label>
        <label className="check small"><input type="checkbox" checked={!!f.reimbursed} onChange={e => set('reimbursed', e.target.checked || undefined)} /> Reimbursed only</label>
        {f.merchant && <span className="pill" style={{ marginLeft: 0 }}>Merchant: {f.merchant} <button className="linkish" onClick={() => set('merchant', undefined)}>✕</button></span>}
        {filtered && <button className="btn sm" onClick={() => setF({})}>Clear</button>}
      </div>

      <div className="card">
        <div className="row spread" style={{ marginBottom: 8 }}>
          <span>
            <b>{list?.length ?? 0}</b> transactions · <b>{money(spend, true)}</b> spending (excl. payments)
            {sel.size > 0 && <> · <b>{sel.size} selected</b> ({money(selSpend, true)})</>}
            {reimbTotal > 0 && <span className="muted"> · {money(reimbTotal, true)} reimbursed (not counted)</span>}
            {list?.length === 3000 ? ' · showing first 3000' : ''}
          </span>
          <label className="check"><input type="checkbox" checked={applyAll} onChange={e => setApplyAll(e.target.checked)} /> Category changes apply to every transaction from that merchant</label>
        </div>
        {canBulk && (
          <div className="row" style={{ marginBottom: 10 }}>
            <span className="muted small">Apply to {scope()}:</span>
            <button className="btn sm" onClick={() => bulkTag()}>Add to trip / event…</button>
            <button className="btn sm" onClick={() => bulkTag(true)}>Remove from trip</button>
            <button className="btn sm" onClick={() => bulkReimburse(true)}>Mark reimbursed</button>
            <button className="btn sm" onClick={() => bulkReimburse(false)}>Clear reimbursed</button>
            {sel.size > 0 && <button className="btn sm" onClick={() => setSel(new Set())}>Deselect</button>}
          </div>
        )}
        <div className="scroll">
          <table>
            <thead><tr>
              <th><input type="checkbox" checked={allSel} onChange={() => setSel(allSel ? new Set() : new Set((list ?? []).map(t => t.id)))} title="Select all shown" /></th>
              <Th k="trans_date" label="Date" /><Th k="merchant" label="Merchant" /><Th k="cat" label="Category" />
              <Th k="account_name" label="Card" /><Th k="amount" label="Amount" num /><th>Reimbursed</th>
              <th title="Exclude from trends when 'Exclude one-off purchases' is on">One-off</th>
            </tr></thead>
            <tbody>
              {rows.map(t => (
                <tr key={t.id} style={sel.has(t.id) ? { background: 'var(--surface-2)' } : undefined}>
                  <td><input type="checkbox" checked={sel.has(t.id)} onChange={() => toggleSel(t.id)} /></td>
                  <td className="muted" style={{ whiteSpace: 'nowrap' }}>{shortDate(t.trans_date)} '{t.trans_date.slice(2, 4)}</td>
                  <td>
                    <button className="linkish" title="Rename merchant" onClick={() => rename(t)}>{t.merchant}</button>
                    {t.tag && <button className="tag" onClick={() => set('tag', t.tag)} title="Show this trip">{t.tag}</button>}
                    <div className="muted small">{t.description}</div>
                  </td>
                  <td>
                    {['payment', 'reward', 'fee', 'interest', 'manual'].includes(t.kind) ? <span className="muted">{t.cat}{t.kind === 'manual' ? ' (fixed expense)' : ''}</span> : (
                      <select value={t.cat} onChange={e => changeCat(t, e.target.value)} style={{ maxWidth: 210 }}>
                        {cats.map(c => <optgroup key={c.parent} label={c.parent}>{c.children.map((ch: string) => <option key={ch}>{ch}</option>)}</optgroup>)}
                      </select>
                    )}
                    {t.category_source === 'pending' && <span className="muted small"> (categorizing…)</span>}
                  </td>
                  <td className="muted small">{t.account_name}</td>
                  <td className={`num ${t.amount < 0 ? 'down' : ''}`}>
                    {t.reimbursed > 0 ? <><s className="muted">{money(t.gross_amount, true)}</s><div>{money(t.amount, true)}</div></> : money(t.amount, true)}
                  </td>
                  <td>
                    {reimbursable(t) && (t.reimbursed > 0
                      ? <button className="linkish down small" onClick={() => reimburse(t)} title="Edit reimbursement">−{money(t.reimbursed, true)}</button>
                      : <button className="btn sm" onClick={() => reimburse(t)}>Reimburse…</button>)}
                  </td>
                  <td style={{ textAlign: 'center' }}>{t.kind !== 'payment' && t.kind !== 'manual' && <input type="checkbox" checked={!!t.one_off} onChange={() => toggleOneOff(t)} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list && !list.length && <div className="empty">No transactions match.</div>}
        </div>
      </div>
    </>
  )
}
