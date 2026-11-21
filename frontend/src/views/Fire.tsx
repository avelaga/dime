import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Ctx } from '../App'
import { api, money, monthLabel, send, useDark } from '../lib'

const kfmt = (v: number) => (v >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M` : v >= 1000 ? `$${Math.round(v / 1000)}k` : `$${v}`)
/** Yearly as the headline figure, monthly underneath for reference. `sign` prefixes both (e.g. "−"). */
function Yearly({ cents, sign = '', bold = false }: { cents: number; sign?: string; bold?: boolean }) {
  const y = `${sign}${money(cents * 12)}/yr`
  return <>{bold ? <b>{y}</b> : y}<div className="muted small">{sign}{money(cents)}/mo</div></>
}
const dollars = (s: string) => Math.round(parseFloat(String(s).replace(/[$,]/g, '')) * 100)

const span = (n: number) => [Math.floor(n / 12) && `${Math.floor(n / 12)} yr`, n % 12 && `${n % 12} mo`].filter(Boolean).join(' ')
function untilLabel(from: string, to: string) {
  const n = (+to.slice(0, 4) - +from.slice(0, 4)) * 12 + (+to.slice(5, 7) - +from.slice(5, 7))
  return n <= 0 ? 'now' : span(n)
}

/** Financial independence: FI number, progress, projected FI date, and what moves it. */
export default function Fire({ ctx }: { ctx: Ctx }) {
  const [d, setD] = useState<any>(null)
  const [s, setS] = useState<any>(null)  // settings form
  const [bal, setBal] = useState({ month: new Date().toISOString().slice(0, 7), amount: '' })
  const [err, setErr] = useState('')
  const dark = useDark()

  const load = () => api('/fire').then(r => {
    setD(r)
    const st = r.settings
    const toDollars = (c: number | null) => (c ? (c / 100).toFixed(0) : '')
    setS({ ...st, birth_year: st.birth_year ?? '', retire_spend: toDollars(st.retire_spend), current_spend: toDollars(st.current_spend) })
  })
  useEffect(() => { load() }, [ctx.version])

  const saveSettings = async (patch: any) => {
    const next = { ...s, ...patch }
    setS(next)
    setErr('')
    try {
      await send('/fire/settings', 'PUT', {
        return_pct: +next.return_pct, swr_pct: +next.swr_pct, basis: next.basis,
        birth_year: next.birth_year ? +next.birth_year : null,
        retire_spend: next.retire_spend ? dollars(next.retire_spend) : null,
        current_spend: next.current_spend ? dollars(next.current_spend) : null,
      })
      load()
    } catch (e: any) { setErr(String(e.message ?? e)) }
  }
  const addBalance = async (e: React.FormEvent) => {
    e.preventDefault()
    const cents = dollars(bal.amount)
    if (!(cents >= 0) || !bal.month) return setErr('Enter a month and an amount.')
    setErr('')
    await send('/fire/balances', 'POST', { month: bal.month, amount: cents })
    setBal({ ...bal, amount: '' }); load()
  }
  const delBalance = async (m: string) => { if (confirm(`Remove the ${monthLabel(m, true)} balance?`)) { await send(`/fire/balances/${m}`, 'DELETE'); load() } }

  const chart = useMemo(() => {
    if (!d) return []
    const byMonth = new Map<string, any>()
    for (const b of d.balances) byMonth.set(b.month, { month: b.month, actual: b.amount / 100 })
    for (const p of d.path) byMonth.set(p.month, { ...(byMonth.get(p.month) ?? { month: p.month }), projected: p.balance / 100 })
    return [...byMonth.values()].sort((a, b) => a.month.localeCompare(b.month))
  }, [d])

  if (!d || !s) return null
  // One tick per January, thinned to at most ~8 labels so long horizons stay legible.
  const jans = chart.map(r => r.month).filter(m => m.endsWith('-01'))
  const every = Math.max(1, Math.ceil(jans.length / 8))
  const yearTicks = jans.filter((_, i) => i % every === 0)
  const noBalance = d.balances.length === 0
  const ink = dark ? '#c3c2b7' : '#52514e'
  const blue = dark ? '#3987e5' : '#2a78d6', orange = dark ? '#d95926' : '#eb6834'
  const pctDone = d.progress !== null ? Math.min(d.progress * 100, 100) : 0
  const ending = d.fixed.filter((f: any) => f.end_month)
  const ongoing = d.fixed.filter((f: any) => !f.end_month)

  return (
    <>
      {noBalance && (
        <div className="notice"><b>Start here:</b> log your current invested balance below (401(k), IRA, brokerage, HSA: money
          you'd live off, not home equity or your emergency fund). Until then the projection starts from $0.</div>
      )}

      <div className="grid3">
        <div className="card stat">
          <div className="label">FI number</div>
          <div className="value">{money(d.target)}</div>
          <div className="sub muted">{money(d.retire_monthly * 12)}/yr spending ÷ {s.swr_pct}% withdrawal rate</div>
        </div>
        <div className="card stat">
          <div className="label">Invested{d.balances.length ? ` (${monthLabel(d.start)})` : ''}</div>
          <div className="value">{money(d.balance)}</div>
          <div className="fire-track" role="img" aria-label={`${pctDone.toFixed(1)}% of FI number`}><div style={{ width: `${pctDone}%` }} /></div>
          <div className="sub muted">{pctDone.toFixed(1)}% of the way there</div>
        </div>
        <div className="card stat">
          <div className="label">Projected FI date</div>
          <div className="value">{d.fi_month ? monthLabel(d.fi_month, true) : 'Not within 60 years'}</div>
          <div className="sub muted">
            {d.fi_month ? <>in {untilLabel(d.today, d.fi_month)}{d.fi_age ? ` · age ${d.fi_age}` : ''}</> : 'Savings are too low for the target'}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="row spread">
          <h2>Invested balance: projected vs. FI number</h2>
          <span className="muted small">Today's dollars · {s.return_pct}% real return · savings grow when fixed expenses end</span>
        </div>
        <div className="legend">
          <span><span className="swatch" style={{ background: blue }} />Projected</span>
          {d.balances.length > 0 && <span><span className="swatch" style={{ background: orange, borderRadius: 99 }} />Logged balance</span>}
          <span><span className="swatch" style={{ background: 'none', borderTop: `2px dashed ${ink}`, borderRadius: 0, height: 0 }} />FI number</span>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={chart} margin={{ top: 16, right: 12, left: 8, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke={dark ? '#2a2a27' : '#e8e7e2'} />
            <XAxis dataKey="month" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: ink }} interval={0}
              ticks={yearTicks} tickFormatter={m => m.slice(0, 4)} />
            <YAxis tickLine={false} axisLine={false} width={56} tick={{ fontSize: 11, fill: ink }} tickFormatter={kfmt} />
            <Tooltip cursor={{ stroke: ink, strokeOpacity: 0.3 }} content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const r: any = payload[0].payload
              return (
                <div className="tip">
                  <b>{monthLabel(r.month, true)}</b>
                  {r.actual !== undefined && <div className="r"><span><span className="swatch" style={{ background: orange }} />Logged</span><span className="num">{money(r.actual * 100)}</span></div>}
                  {r.projected !== undefined && <div className="r"><span><span className="swatch" style={{ background: blue }} />Projected</span><span className="num">{money(r.projected * 100)}</span></div>}
                  <div className="r muted"><span>FI number</span><span className="num">{money(d.target)}</span></div>
                </div>
              )
            }} />
            {d.target > 0 && <ReferenceLine y={d.target / 100} stroke={ink} strokeDasharray="5 4"
              label={{ value: `FI ${kfmt(d.target / 100)}`, position: 'insideTopLeft', fill: ink, fontSize: 11 }} />}
            {d.fi_month && <ReferenceLine x={d.fi_month} stroke={ink} strokeOpacity={0.5} strokeDasharray="2 4" />}
            <Line dataKey="projected" stroke={blue} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            <Line dataKey="actual" stroke={orange} strokeWidth={2} isAnimationActive={false} connectNulls
              dot={{ r: 4, fill: orange, stroke: dark ? '#1a1a19' : '#fcfcfb', strokeWidth: 2 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>How the numbers are built</h2>
          <table>
            <tbody>
              <tr><td>Spending now <span className="muted small">{d.settings.current_spend ? '(your override)'
                : `avg of ${d.basis_months.length} complete months${d.basis_months.length ? ` (${monthLabel(d.basis_months[0])}–${monthLabel(d.basis_months[d.basis_months.length - 1])})` : ''}`}</span></td>
                <td className="num"><Yearly cents={d.monthly_spend} /></td></tr>
              {ending.map((f: any) => (
                <tr key={f.name}><td className="muted">− {f.name} <span className="small">(ends {monthLabel(f.end_month)})</span></td><td className="num muted"><Yearly cents={f.monthly} sign="−" /></td></tr>
              ))}
              <tr><td><b>Spending in retirement</b>{d.settings.retire_spend ? <span className="muted small"> (your override)</span> : null}</td>
                <td className="num"><Yearly cents={d.retire_monthly} bold /></td></tr>
              <tr><td>Income now <span className="muted small">take-home + 401(k)</span></td><td className="num"><Yearly cents={d.income} /></td></tr>
              <tr><td><b>Saving now</b> <span className="muted small">{d.income ? `${Math.round((d.savings / d.income) * 100)}% savings rate` : ''}</span></td>
                <td className={`num ${d.savings < 0 ? 'up' : ''}`}><Yearly cents={d.savings} bold /></td></tr>
              {ending.length > 0 && <tr><td>Saving once those end</td><td className="num"><Yearly cents={d.savings_after_debts} /></td></tr>}
            </tbody>
          </table>
          {ongoing.length > 0 && (
            <p className="muted small">
              Fixed expenses with no end month are assumed to continue in retirement: {ongoing.map((f: any) => f.name).join(', ')}.
              If one will be paid off (car loan, mortgage), set its end month under <a href="#accounts">Accounts &amp; Upload</a> and it
              drops out of retirement spending and adds to your savings from then on.
            </p>
          )}
        </div>

        <div className="card">
          <h2>Assumptions</h2>
          <div className="fire-form">
            <label>Spending basis
              <div className="seg">
                <button className={s.basis === 'actual' ? 'on' : ''} onClick={() => saveSettings({ basis: 'actual' })}>With one-offs ({money(d.spend.actual * 12)}/yr)</button>
                <button className={s.basis === 'typical' ? 'on' : ''} onClick={() => saveSettings({ basis: 'typical' })}>Without ({money(d.spend.typical * 12)}/yr)</button>
              </div>
            </label>
            <label>Real return (after inflation)
              <span><input type="number" step="0.5" value={s.return_pct} onChange={e => setS({ ...s, return_pct: e.target.value })}
                onBlur={() => saveSettings({})} style={{ width: 70 }} /> %</span></label>
            <label>Safe withdrawal rate
              <span><input type="number" step="0.25" value={s.swr_pct} onChange={e => setS({ ...s, swr_pct: e.target.value })}
                onBlur={() => saveSettings({})} style={{ width: 70 }} /> %</span></label>
            <label>Birth year <span className="muted small">(optional, for age at FI)</span>
              <input type="number" placeholder="e.g. 1994" value={s.birth_year} onChange={e => setS({ ...s, birth_year: e.target.value })}
                onBlur={() => saveSettings({})} style={{ width: 100 }} /></label>
            <label>Current spending override <span className="muted small">($/yr, blank = from statements)</span>
              <input type="text" inputMode="decimal" placeholder={money(d.monthly_spend_auto * 12)} value={s.current_spend}
                onChange={e => setS({ ...s, current_spend: e.target.value })} onBlur={() => saveSettings({})} style={{ width: 120 }} /></label>
            <label>Retirement spending override <span className="muted small">($/yr, blank = derived)</span>
              <input type="text" inputMode="decimal" placeholder={money(d.retire_monthly_auto * 12)} value={s.retire_spend}
                onChange={e => setS({ ...s, retire_spend: e.target.value })} onBlur={() => saveSettings({})} style={{ width: 120 }} /></label>
          </div>
          <p className="muted small">With one-offs is the safer default: trips, electronics and car repairs keep happening in retirement too.
            4% is the classic withdrawal rate; 3.5% is more conservative for retirements longer than 30 years.</p>
          {err && <span className="status error">{err}</span>}
        </div>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>What moves the date</h2>
          {d.scenarios.length === 0 ? <p className="muted">Needs spending data first.</p> : (
            <table>
              <thead><tr><th>If you…</th><th className="num">FI date</th><th className="num">Change</th></tr></thead>
              <tbody>{d.scenarios.map((x: any) => (
                <tr key={x.label}>
                  <td>{x.label}</td>
                  <td className="num">{x.fi_month ? monthLabel(x.fi_month) : '–'}</td>
                  <td className={`num ${x.delta_months < 0 ? 'down' : x.delta_months > 0 ? 'up' : 'muted'}`}>
                    {x.delta_months === null ? '–' : x.delta_months === 0 ? 'same' : `${x.delta_months < 0 ? '▼' : '▲'} ${span(Math.abs(x.delta_months))} ${x.delta_months < 0 ? 'sooner' : 'later'}`}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h2>Invested balance log</h2>
          <p className="muted small" style={{ marginTop: -4 }}>Log the total once a month or quarter; the latest entry is where the projection starts, and
            earlier ones show whether you're ahead of or behind the line.</p>
          {d.balances.length > 0 && (
            <table style={{ marginBottom: 12 }}>
              <thead><tr><th>Month</th><th className="num">Invested</th><th></th></tr></thead>
              <tbody>{[...d.balances].reverse().map((b: any) => (
                <tr key={b.month}><td>{monthLabel(b.month, true)}</td><td className="num">{money(b.amount)}</td>
                  <td className="num"><button className="btn sm danger" onClick={() => delBalance(b.month)}>Delete</button></td></tr>
              ))}</tbody>
            </table>
          )}
          <form className="row" onSubmit={addBalance}>
            <input type="month" value={bal.month} onChange={e => setBal({ ...bal, month: e.target.value })} />
            <input type="text" inputMode="decimal" placeholder="$ total invested" value={bal.amount}
              onChange={e => setBal({ ...bal, amount: e.target.value })} style={{ width: 140 }} />
            <button className="btn primary">Log balance</button>
          </form>
        </div>
      </div>
    </>
  )
}
