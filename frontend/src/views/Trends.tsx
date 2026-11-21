import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Ctx } from '../App'
import { api, makeColorOf, money, monthLabel, OTHER, pct, useDark } from '../lib'

const RANGES: [string, number][] = [['12 mo', 12], ['24 mo', 24], ['3 yr', 36], ['All', 0]]

function ChangeCell({ cur, base }: { cur: number; base: number }) {
  const p = pct(cur, base)
  if (!base || p === null) return <td className="num muted">–</td>
  if (Math.abs(p) < 3) return <td className="num muted">≈ 0%</td>
  return <td className={`num ${p > 0 ? 'up' : 'down'}`}>{p > 0 ? '▲' : '▼'} {Math.abs(p)}%</td>
}

export default function Trends({ ctx }: { ctx: Ctx }) {
  const [range, setRange] = useState(12)
  const [parent, setParent] = useState('')
  const [oneOff, setOneOff] = useState(true)
  const [t, setT] = useState<any>(null)
  const [y, setY] = useState<any>(null)
  const dark = useDark()

  useEffect(() => {
    api(`/trends?one_off=${oneOff}${parent ? `&parent=${encodeURIComponent(parent)}` : ''}`).then(setT)
  }, [parent, oneOff, ctx.version])
  useEffect(() => { api(`/yearly?one_off=${oneOff}`).then(setY) }, [oneOff, ctx.version])

  // Drill-down colors are ranked within the parent; top level uses the app-wide mapping.
  const colorOf = useMemo(() => (parent && t ? makeColorOf(t.series, dark) : ctx.colorOf), [parent, t, dark, ctx.colorOf])
  const ranked: string[] = parent ? (t?.series ?? []) : ctx.rankedParents
  const shown = ranked.slice(0, 7).filter(s => t?.series.includes(s))
  const hasOther = (t?.series ?? []).some((s: string) => !shown.includes(s))
  const keys = hasOther ? [...shown, OTHER] : shown

  const rows = useMemo(() => {
    if (!t) return []
    const ms = range ? t.months.slice(-range) : t.months
    return ms.map((m: any) => {
      const r: any = { month: m.month, label: monthLabel(m.month) + (m.complete ? '' : '*'), complete: m.complete, total: m.total }
      let other = 0
      for (const [k, v] of Object.entries<number>(m.values)) shown.includes(k) ? (r[k] = v / 100) : (other += v)
      if (hasOther) r[OTHER] = other / 100
      return r
    })
  }, [t, range, shown.join('|'), hasOther])

  const completeRows = rows.filter((r: any) => r.complete)
  const avg = completeRows.length ? completeRows.reduce((s: number, r: any) => s + r.total, 0) / completeRows.length : 0

  if (!t || !y) return null
  if (!t.months.length) return <div className="card empty">No data yet.</div>

  const years: any[] = y.years
  const ytdYears = y.ytd ? Object.keys(y.ytd.years).filter(yr => y.ytd.years[yr].total > 0).sort() : []
  const lastY = ytdYears[ytdYears.length - 1], prevY = ytdYears[ytdYears.length - 2]
  const thru = y.ytd ? monthLabel(`2000-${String(y.ytd.through_month).padStart(2, '0')}`).split(' ')[0] : ''
  const parentRows = ctx.rankedParents.filter(p => ytdYears.some(yr => y.ytd.years[yr].by_parent[p]))

  return (
    <>
      <div className="toolbar">
        <div className="seg">{RANGES.map(([l, n]) => <button key={l} className={range === n ? 'on' : ''} onClick={() => setRange(n)}>{l}</button>)}</div>
        <select value={parent} onChange={e => setParent(e.target.value)}>
          <option value="">All categories</option>
          {ctx.rankedParents.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <label className="check" style={{ marginLeft: 'auto' }}>
          <input type="checkbox" checked={!oneOff} onChange={e => setOneOff(!e.target.checked)} /> Exclude one-off purchases
        </label>
      </div>

      <div className="card">
        <div className="row spread">
          <h2>{parent ? `${parent}: monthly spending` : 'Monthly spending by category'}</h2>
          <span className="muted small">Click a month to open it · * incomplete month (not every card uploaded): shown faded{avg ? ` · dashed line = average of complete months (${money(avg)})` : ''}</span>
        </div>
        <div className="legend">
          {keys.map(k => <span key={k}><span className="swatch" style={{ background: k === OTHER ? colorOf('__other__') : colorOf(k) }} />{k}</span>)}
        </div>
        <ResponsiveContainer width="100%" height={340}>
          <BarChart data={rows} margin={{ top: 8, right: 8, left: 8, bottom: 0 }} barCategoryGap="22%" style={{ cursor: 'pointer' }}
            onClick={(e: any) => { const m = e?.activePayload?.[0]?.payload?.month; if (m) ctx.goMonth(m, parent || undefined) }}>
            <CartesianGrid vertical={false} stroke={dark ? '#2a2a27' : '#e8e7e2'} />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: dark ? '#c3c2b7' : '#52514e' }} interval="preserveStartEnd" />
            <YAxis tickLine={false} axisLine={false} width={56} tick={{ fontSize: 11, fill: dark ? '#c3c2b7' : '#52514e' }}
              tickFormatter={v => (v >= 1000 ? `$${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : `$${v}`)} />
            <Tooltip cursor={{ fill: dark ? 'rgba(255,255,255,.05)' : 'rgba(0,0,0,.04)' }} content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const r: any = payload[0].payload
              return (
                <div className="tip">
                  <b>{monthLabel(r.month, true)}</b>{!r.complete && <div className="muted">Incomplete: not all cards uploaded</div>}
                  {[...keys].reverse().filter(k => r[k]).map(k => (
                    <div className="r" key={k}><span><span className="swatch" style={{ background: k === OTHER ? colorOf('__other__') : colorOf(k) }} />{k}</span><span className="num">{money(r[k] * 100)}</span></div>
                  ))}
                  <div className="r" style={{ borderTop: '1px solid var(--border)', marginTop: 4, paddingTop: 4 }}><b>Total</b><b className="num">{money(r.total)}</b></div>
                  <div className="muted" style={{ marginTop: 4 }}>Click to open this month →</div>
                </div>
              )
            }} />
            {avg > 0 && <ReferenceLine y={avg / 100} stroke={dark ? '#8e8d86' : '#7c7b76'} strokeDasharray="4 4" />}
            {keys.map((k, idx) => (
              <Bar key={k} dataKey={k} stackId="a" fill={k === OTHER ? colorOf('__other__') : colorOf(k)}
                stroke={dark ? '#1a1a19' : '#fcfcfb'} strokeWidth={1}
                radius={idx === keys.length - 1 ? [4, 4, 0, 0] : 0} isAnimationActive={false}>
                {rows.map((r: any) => <Cell key={r.month} fillOpacity={r.complete ? 1 : 0.4} />)}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>By year</h2>
          <table>
            <thead><tr><th>Year</th><th className="num">Total</th><th className="num">Months</th><th className="num">Avg / month</th><th className="num">vs prior yr</th></tr></thead>
            <tbody>
              {years.map((yr, i) => (
                <tr key={yr.year}>
                  <td><b>{yr.year}</b></td>
                  <td className="num">{money(yr.total)}</td>
                  <td className="num" title="complete months / months with any data">{yr.complete_months}/{yr.months_with_data}{yr.complete_months < yr.months_with_data ? ' ⚠' : ''}</td>
                  <td className="num">{money(yr.avg_per_month)}</td>
                  {/* Only compare against a prior year with enough months to mean something. */}
                  <ChangeCell cur={yr.avg_per_month} base={years[i - 1]?.months_with_data >= 3 ? years[i - 1].avg_per_month : 0} />
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Average per month makes partial years comparable. ⚠ = some months are missing a card's statement.</p>
        </div>
        <div className="card">
          <h2>Year-to-date (Jan–{thru})</h2>
          {ytdYears.length < 2 ? <p className="muted">Upload statements from more than one year to compare the same months year over year.</p> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={ytdYears.map(yr => ({ year: yr, total: y.ytd.years[yr].total / 100 }))} margin={{ top: 16, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke={dark ? '#2a2a27' : '#e8e7e2'} />
                <XAxis dataKey="year" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: dark ? '#c3c2b7' : '#52514e' }} />
                <YAxis tickLine={false} axisLine={false} width={56} tick={{ fontSize: 11, fill: dark ? '#c3c2b7' : '#52514e' }} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip formatter={(v: number) => money(v * 100)} cursor={{ fill: 'transparent' }} contentStyle={{ background: dark ? '#1a1a19' : '#fff', border: '1px solid var(--border)', borderRadius: 8 }} />
                <Bar dataKey="total" name="Spent" fill={dark ? '#3987e5' : '#2a78d6'} radius={[4, 4, 0, 0]} maxBarSize={56} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {ytdYears.length >= 2 && (
        <div className="card">
          <h2>Category direction, year-to-date (Jan–{thru})</h2>
          <div className="scroll">
            <table>
              <thead><tr><th>Category</th>{ytdYears.map(yr => <th key={yr} className="num">{yr}</th>)}<th className="num">{lastY} vs {prevY}</th></tr></thead>
              <tbody>
                {parentRows.map(p => (
                  <tr key={p}>
                    <td><span className="swatch" style={{ background: ctx.colorOf(p) }} />{p}</td>
                    {ytdYears.map(yr => <td key={yr} className="num">{money(y.ytd.years[yr].by_parent[p] ?? 0)}</td>)}
                    <ChangeCell cur={y.ytd.years[lastY].by_parent[p] ?? 0} base={y.ytd.years[prevY].by_parent[p] ?? 0} />
                  </tr>
                ))}
                <tr>
                  <td><b>Total</b></td>
                  {ytdYears.map(yr => <td key={yr} className="num"><b>{money(y.ytd.years[yr].total)}</b></td>)}
                  <ChangeCell cur={y.ytd.years[lastY].total} base={y.ytd.years[prevY].total} />
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}
