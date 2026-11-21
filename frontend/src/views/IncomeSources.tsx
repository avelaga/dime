import { useEffect, useState } from 'react'
import { api, money, monthLabel, send } from '../lib'

const FREQ: Record<string, [string, number]> = {
  monthly: ['Monthly', 1], semimonthly: ['Twice a month', 2], biweekly: ['Every 2 weeks', 26 / 12], once: ['One-time (bonus etc.)', 0],
}
const empty = () => ({ id: 0, name: '', amount: '', frequency: 'biweekly', start_month: `${new Date().getFullYear()}-01`, end_month: '' })

/** Take-home pay (after tax and deductions), so Monthly / Yearly can show what you saved. */
export default function IncomeSources({ onChanged, version }: { onChanged: () => void; version: number }) {
  const [items, setItems] = useState<any[]>([])
  const [f, setF] = useState<any>(empty())
  const [err, setErr] = useState('')
  const load = () => api('/income').then(setItems)
  useEffect(() => { load() }, [version])

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr('')
    const cents = Math.round(parseFloat(String(f.amount).replace(/[$,]/g, '')) * 100)
    if (!f.name.trim() || !(cents > 0)) return setErr('Enter a name and an amount.')
    const body = { ...f, amount: cents, end_month: f.frequency === 'once' ? null : f.end_month || null }
    try {
      await (f.id ? send(`/income/${f.id}`, 'PUT', body) : send('/income', 'POST', body))
      setF(empty()); load(); onChanged()
    } catch (e: any) { setErr(String(e.message ?? e)) }
  }
  const del = async (r: any) => {
    if (confirm(`Remove "${r.name}"?`)) { await send(`/income/${r.id}`, 'DELETE'); load(); onChanged() }
  }
  const now = new Date().toISOString().slice(0, 7)
  const monthly = items.filter(r => r.frequency !== 'once' && r.start_month <= now && (!r.end_month || r.end_month >= now))
    .reduce((s, r) => s + r.amount * FREQ[r.frequency][1], 0)

  return (
    <div className="card">
      <div className="row spread">
        <h2>Income (take-home pay)</h2>
        {monthly > 0 && <span>≈ <b>{money(monthly)}/mo</b> <span className="muted">current</span></span>}
      </div>
      <p className="muted" style={{ marginTop: -4 }}>
        What lands in your bank after taxes and deductions. Used to show how much you saved each month. When pay changes
        (new job, raise), set an end month on the old entry and add a new one. Reimbursements aren't income here: they're
        already subtracted from the purchases they paid back.
      </p>
      {items.length > 0 && (
        <div className="scroll"><table style={{ marginBottom: 12 }}>
          <thead><tr><th>Source</th><th>Every</th><th>From</th><th>Until</th><th className="num">Per payment</th><th className="num">≈ Per month</th><th></th></tr></thead>
          <tbody>{items.map(r => (
            <tr key={r.id}>
              <td><b>{r.name}</b></td>
              <td>{FREQ[r.frequency][0]}</td>
              <td className="muted small">{monthLabel(r.start_month)}</td>
              <td className="muted small">{r.frequency === 'once' ? '–' : r.end_month ? monthLabel(r.end_month) : 'ongoing'}</td>
              <td className="num">{money(r.amount, true)}</td>
              <td className="num">{r.frequency === 'once' ? '–' : money(r.amount * FREQ[r.frequency][1])}</td>
              <td className="row"><button className="btn sm" onClick={() => setF({ ...r, amount: (r.amount / 100).toFixed(2), end_month: r.end_month ?? '' })}>Edit</button>
                <button className="btn sm danger" onClick={() => del(r)}>Delete</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      <form className="row" onSubmit={save}>
        <input type="text" placeholder="e.g. Paycheck" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} style={{ width: 160 }} />
        <input type="text" inputMode="decimal" placeholder="$ per payment" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} style={{ width: 120 }} />
        <select value={f.frequency} onChange={e => setF({ ...f, frequency: e.target.value })}>
          {Object.entries(FREQ).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <label className="muted small">{f.frequency === 'once' ? 'in' : 'from'} <input type="month" value={f.start_month} onChange={e => setF({ ...f, start_month: e.target.value })} /></label>
        {f.frequency !== 'once' && <label className="muted small">until <input type="month" value={f.end_month} onChange={e => setF({ ...f, end_month: e.target.value })} /></label>}
        <button className="btn primary">{f.id ? 'Save' : 'Add income'}</button>
        {f.id ? <button type="button" className="btn" onClick={() => setF(empty())}>Cancel</button> : null}
        {err && <span className="status error">{err}</span>}
      </form>
    </div>
  )
}
