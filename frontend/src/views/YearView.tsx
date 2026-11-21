import { Fragment, useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Ctx } from '../App'
import { api, money, monthLabel, shortDate, useDark } from '../lib'
import { Delta, DeltaCell } from './MonthView'
import CashFlow from './CashFlow'

/** Whole-year (to date) version of the Monthly view: same category drill-down, summed over the year. */
export default function YearView({ ctx, initialYear }: { ctx: Ctx; initialYear?: string }) {
  const [year, setYear] = useState<string | undefined>(initialYear)
  const [oneOff, setOneOff] = useState(true)
  const [data, setData] = useState<any>(null)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const dark = useDark()

  useEffect(() => { api(`/year?${year ? `year=${year}&` : ''}one_off=${oneOff}`).then(setData) }, [year, oneOff, ctx.version])
  useEffect(() => {
    if (data?.year && location.hash.startsWith('#year') && location.hash !== `#year/${data.year}`)
      history.replaceState(null, '', `#year/${data.year}`)
  }, [data?.year])

  if (!data) return null
  if (!data.year) return <div className="card empty">No statements yet.</div>

  const i = data.years.indexOf(data.year)
  const full = (m: string) => monthLabel(m, true).split(' ')[0]
  const span = `${full(data.months[0])} – ${full(data.months[data.months.length - 1])} ${data.year}`
  const parents = data.parents.filter((p: any) => p.total || p.prev)
  const max = Math.max(1, ...parents.map((p: any) => p.total))
  const cmp = data.prev_has_data
  const toggle = (p: string) => setOpen(s => { const n = new Set(s); n.has(p) ? n.delete(p) : n.add(p); return n })
  const share = (v: number) => {
    if (data.total <= 0 || v <= 0) return '–'
    const p = (v / data.total) * 100
    return p < 1 ? '<1%' : `${Math.round(p)}%`
  }

  return (
    <>
      <div className="toolbar">
        <button className="btn" disabled={i <= 0} onClick={() => setYear(data.years[i - 1])}>‹</button>
        <select value={data.year} onChange={e => setYear(e.target.value)}>
          {[...data.years].reverse().map((y: string) => <option key={y} value={y}>{y}</option>)}
        </select>
        <button className="btn" disabled={i >= data.years.length - 1} onClick={() => setYear(data.years[i + 1])}>›</button>
        <span className="muted small">{span}</span>
        <label className="check" style={{ marginLeft: 'auto' }}>
          <input type="checkbox" checked={!oneOff} onChange={e => setOneOff(!e.target.checked)} /> Exclude one-off purchases
        </label>
      </div>

      {data.incomplete_months.length > 0 && (
        <div className="notice">
          <b>⚠ Not every month is complete.</b>
          {data.incomplete_months.map((m: string) => monthLabel(m, true).split(' ')[0]).join(', ')} {data.incomplete_months.length === 1 ? 'is' : 'are'} missing
          some card statements, so the year total undercounts slightly. See Accounts & Upload → Coverage.
        </div>
      )}

      <div className="grid3">
        <div className="card stat">
          <div className="label">Spent in {data.year}{data.months.length < 12 ? ' so far' : ''}</div>
          <div className="value">{money(data.total)}</div>
          <div className="sub muted">
            {data.manual_total ? `${money(data.total - data.manual_total)} on cards + ${money(data.manual_total)} fixed expenses` : 'across all cards'}
            {data.reimbursed_total > 0 && ` · ${money(data.reimbursed_total)} reimbursed not counted`}
          </div>
        </div>
        <div className="card stat">
          <div className="label">Average per month</div>
          <div className="value">{money(data.avg_per_month)}</div>
          <div className="sub muted">over {data.months.length} month{data.months.length === 1 ? '' : 's'}
            {data.one_off_total > 0 && ` · includes ${money(data.one_off_total)} one-off`}</div>
        </div>
        <div className="card stat">
          <div className="label">vs same months of {data.prior}</div>
          <div className="value">{cmp ? money(data.prev_total) : '–'}</div>
          <div className="sub">{cmp ? <Delta cur={data.total} base={data.prev_total} label={data.prior} /> : <span className="muted">Upload {data.prior} statements to compare</span>}</div>
        </div>
      </div>

      <CashFlow income={data.income} spent={data.actual_spent} saved={data.saved}
        note={data.income ? `≈ ${money(data.saved / data.months.length)} saved per month` : undefined} />

      <div className="card">
        <div className="row spread"><h2>Month by month</h2><span className="muted small">Click a month to open it · faded = incomplete</span></div>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data.monthly.map((m: any) => ({ ...m, label: monthLabel(m.month).split(' ')[0], v: m.total / 100 }))}
            margin={{ top: 8, right: 8, left: 8, bottom: 0 }} style={{ cursor: 'pointer' }}
            onClick={(e: any) => { const m = e?.activePayload?.[0]?.payload?.month; if (m) ctx.goMonth(m) }}>
            <CartesianGrid vertical={false} stroke={dark ? '#2a2a27' : '#e8e7e2'} />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: dark ? '#c3c2b7' : '#52514e' }} />
            <YAxis tickLine={false} axisLine={false} width={56} tick={{ fontSize: 11, fill: dark ? '#c3c2b7' : '#52514e' }}
              tickFormatter={v => (v >= 1000 ? `$${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : `$${v}`)} />
            <Tooltip cursor={{ fill: dark ? 'rgba(255,255,255,.05)' : 'rgba(0,0,0,.04)' }} content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const r: any = payload[0].payload
              const cf = data.monthly_cashflow?.find((x: any) => x.month === r.month)
              return <div className="tip"><b>{monthLabel(r.month, true)}</b><div className="r"><span>Spent</span><b className="num">{money(r.total)}</b></div>
                {cf && <><div className="r"><span>Income</span><span className="num">{money(cf.income)}</span></div>
                  <div className="r"><span>Saved</span><span className={`num ${cf.saved >= 0 ? 'down' : 'up'}`}>{money(cf.saved)}</span></div></>}
                {!r.complete && <div className="muted">Incomplete month</div>}<div className="muted" style={{ marginTop: 4 }}>Click to open →</div></div>
            }} />
            <Bar dataKey="v" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={false}>
              {data.monthly.map((m: any) => <Cell key={m.month} fill={dark ? '#3987e5' : '#2a78d6'} fillOpacity={m.complete ? 1 : 0.4} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <div className="row spread"><h2>Spending by category</h2><span className="muted small">Click a category to expand · click a subcategory to see its transactions</span></div>
        <div className="scroll">
          <table>
            <thead>
              <tr><th>Category</th><th style={{ width: '28%' }}></th><th className="num">Total</th><th className="num">Share</th>
                <th className="num">Avg / month</th>{cmp && <th className="num">vs {data.prior}</th>}</tr>
            </thead>
            <tbody>
              {parents.map((p: any) => (
                <Fragment key={p.parent}>
                  <tr className="cat-row" onClick={() => toggle(p.parent)}>
                    <td><span className="muted small">{open.has(p.parent) ? '▾' : '▸'}</span> <span className="swatch" style={{ background: ctx.colorOf(p.parent) }} /><b>{p.parent}</b></td>
                    <td className="bar-track"><div className="bar" style={{ width: `${Math.max(0, (p.total / max) * 100)}%`, background: ctx.colorOf(p.parent) }} /></td>
                    <td className="num"><b>{money(p.total)}</b></td>
                    <td className="num muted">{share(p.total)}</td>
                    <td className="num">{money(p.avg)}</td>
                    {cmp && <DeltaCell cur={p.total} base={p.prev} />}
                  </tr>
                  {open.has(p.parent) && p.children.filter((c: any) => c.total || c.prev).map((c: any) => (
                    <tr key={c.name} className="child">
                      <td><button className="linkish" onClick={() => ctx.goTxns({ year: data.year, category: c.name })}>{c.name}</button></td>
                      <td className="bar-track"><div className="bar" style={{ width: `${Math.max(0, (c.total / max) * 100)}%`, background: ctx.colorOf(p.parent), opacity: 0.55 }} /></td>
                      <td className="num">{money(c.total)}</td>
                      <td className="num muted">{share(c.total)}</td>
                      <td className="num">{money(c.avg)}</td>
                      {cmp && <DeltaCell cur={c.total} base={c.prev} />}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Top merchants in {data.year}</h2>
          <table><tbody>
            {data.top_merchants.map((m: any) => (
              <tr key={m.merchant}>
                <td><button className="linkish" onClick={() => ctx.goTxns({ merchant: m.merchant, year: data.year })}>{m.merchant}</button><div className="muted small">{m.cat} · {m.n}×</div></td>
                <td className="num">{money(m.total)}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
        <div className="card">
          <h2>Largest purchases in {data.year}</h2>
          <table><tbody>
            {data.top_transactions.map((t: any) => (
              <tr key={t.id}>
                <td>{t.merchant}<div className="muted small">{shortDate(t.trans_date)} · {t.cat} · {t.account_name}</div></td>
                <td className="num">{money(t.amount, true)}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
      </div>
    </>
  )
}
