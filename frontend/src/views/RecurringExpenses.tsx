import { useEffect, useState } from 'react'
import { api, money, monthLabel, send } from '../lib'

const FREQ: Record<string, [string, number]> = { monthly: ['Monthly', 1], quarterly: ['Every 3 months', 1 / 3], yearly: ['Yearly', 1 / 12] }
const empty = () => ({ id: 0, name: '', amount: '', category: 'Rent & Mortgage', frequency: 'monthly', day_of_month: 1, start_month: `${new Date().getFullYear()}-01`, end_month: '' })

/** Fixed expenses paid from the bank (mortgage, insurance, utilities): entered once, added every period. */
export default function RecurringExpenses({ onChanged, version }: { onChanged: () => void; version: number }) {
  const [items, setItems] = useState<any[]>([])
  const [cats, setCats] = useState<any[]>([])
  const [f, setF] = useState<any>(empty())
  const [err, setErr] = useState('')

  const load = () => api('/recurring').then(setItems)
  useEffect(() => { load(); api('/categories').then(setCats) }, [version])

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr('')
    const cents = Math.round(parseFloat(String(f.amount).replace(/[$,]/g, '')) * 100)
    if (!f.name.trim() || !(cents > 0)) return setErr('Enter a name and an amount.')
    const body = { ...f, amount: cents, day_of_month: Number(f.day_of_month), end_month: f.end_month || null }
    try {
      await (f.id ? send(`/recurring/${f.id}`, 'PUT', body) : send('/recurring', 'POST', body))
      setF(empty()); load(); onChanged()
    } catch (e: any) { setErr(String(e.message ?? e)) }
  }
  const edit = (r: any) => setF({ ...r, amount: (r.amount / 100).toFixed(2), end_month: r.end_month ?? '' })
  const del = async (r: any) => {
    if (confirm(`Remove "${r.name}" and all of its entries?`)) { await send(`/recurring/${r.id}`, 'DELETE'); load(); onChanged() }
  }
  const monthly = items.filter(r => !r.end_month || r.end_month >= new Date().toISOString().slice(0, 7))
    .reduce((s, r) => s + r.amount * FREQ[r.frequency][1], 0)
  const spendCats = cats.filter(c => c.parent !== 'Transfers')

  return (
    <div className="card">
      <div className="row spread">
        <h2>Fixed expenses paid from your bank</h2>
        {items.length > 0 && <span>≈ <b>{money(monthly)}/mo</b> <span className="muted">active</span></span>}
      </div>
      <p className="muted" style={{ marginTop: -4 }}>
        Mortgage, insurance, utilities and other set amounts that never hit a card. Each one is added automatically every period,
        so trends and monthly totals show your whole picture. If an amount changes, set an end month on the old one and add a new one.
      </p>
      {items.length > 0 && (
        <div className="scroll"><table style={{ marginBottom: 12 }}>
          <thead><tr><th>Expense</th><th>Category</th><th>Every</th><th>From</th><th>Until</th><th className="num">Amount</th><th></th></tr></thead>
          <tbody>{items.map(r => (
            <tr key={r.id}>
              <td><b>{r.name}</b><div className="muted small">on day {r.day_of_month}</div></td>
              <td className="muted">{r.category}</td>
              <td>{FREQ[r.frequency][0]}</td>
              <td className="muted small">{monthLabel(r.start_month)}</td>
              <td className="muted small">{r.end_month ? monthLabel(r.end_month) : 'ongoing'}</td>
              <td className="num">{money(r.amount, true)}</td>
              <td className="row"><button className="btn sm" onClick={() => edit(r)}>Edit</button><button className="btn sm danger" onClick={() => del(r)}>Delete</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      <form className="row" onSubmit={save}>
        <input type="text" placeholder="e.g. Mortgage" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} style={{ width: 170 }} />
        <input type="text" inputMode="decimal" placeholder="$ amount" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} style={{ width: 100 }} />
        <select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>
          {spendCats.map(c => <optgroup key={c.parent} label={c.parent}>{c.children.map((ch: string) => <option key={ch}>{ch}</option>)}</optgroup>)}
        </select>
        <select value={f.frequency} onChange={e => setF({ ...f, frequency: e.target.value })}>
          {Object.entries(FREQ).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <label className="muted small">day <input type="text" inputMode="numeric" value={f.day_of_month} onChange={e => setF({ ...f, day_of_month: e.target.value.replace(/\D/g, '').slice(0, 2) })} style={{ width: 44 }} /></label>
        <label className="muted small">from <input type="month" value={f.start_month} onChange={e => setF({ ...f, start_month: e.target.value })} /></label>
        <label className="muted small">until <input type="month" value={f.end_month} onChange={e => setF({ ...f, end_month: e.target.value })} /></label>
        <button className="btn primary">{f.id ? 'Save' : 'Add expense'}</button>
        {f.id ? <button type="button" className="btn" onClick={() => setF(empty())}>Cancel</button> : null}
        {err && <span className="status error">{err}</span>}
      </form>
    </div>
  )
}
