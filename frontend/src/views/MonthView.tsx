import { Fragment, useEffect, useState } from 'react'
import type { Ctx } from '../App'
import { api, money, monthLabel, pct, shortDate } from '../lib'
import CashFlow from './CashFlow'

export function Delta({ cur, base, label }: { cur: number; base: number; label: string }) {
  if (!base) return <span className="muted">no {label} data</span>
  const d = cur - base
  const p = pct(cur, base)
  if (Math.abs(d) < 100) return <span className="muted">≈ same as {label}</span>
  return (
    <span className={d > 0 ? 'up' : 'down'}>
      {d > 0 ? '▲' : '▼'} {money(Math.abs(d))} ({Math.abs(p ?? 0)}%) {d > 0 ? 'more' : 'less'} than {label}
    </span>
  )
}

export function DeltaCell({ cur, base }: { cur: number; base: number }) {
  const d = cur - base
  if (!base && !cur) return <td className="num muted">–</td>
  if (Math.abs(d) < 100) return <td className="num muted">≈</td>
  return <td className={`num ${d > 0 ? 'up' : 'down'}`}>{d > 0 ? '▲' : '▼'} {money(Math.abs(d))}</td>
}

export default function MonthView({ ctx, initialMonth, initialOpen }: { ctx: Ctx; initialMonth?: string; initialOpen?: string }) {
  const [month, setMonth] = useState<string | undefined>(initialMonth)
  const [oneOff, setOneOff] = useState(true)
  const [data, setData] = useState<any>(null)
  const [cov, setCov] = useState<any>(null)
  const [open, setOpen] = useState<Set<string>>(new Set(initialOpen ? [initialOpen] : []))

  useEffect(() => {
    api(`/month?${month ? `month=${month}&` : ''}one_off=${oneOff}`).then(setData)
    api('/coverage').then(setCov)
  }, [month, oneOff, ctx.version])

  useEffect(() => {
    if (data?.month && location.hash.startsWith('#month') && !location.hash.startsWith(`#month/${data.month}`))
      history.replaceState(null, '', `#month/${data.month}`)
  }, [data?.month])

  if (!data) return null
  if (!data.month) return <div className="card empty">No statements yet. Go to <b>Accounts & Upload</b> to add your cards and drop in statements.</div>

  const months: string[] = data.months.map((m: any) => m.month)
  const i = months.indexOf(data.month)
  const missing = (cov?.accounts ?? []).filter((a: any) => a.cells[data.month] && !['full', 'inactive'].includes(a.cells[data.month]))
  const parents = data.parents.filter((p: any) => p.total || p.prev || p.avg)
  const max = Math.max(1, ...parents.map((p: any) => p.total))
  const avgLabel = `${data.avg_months.length}-mo avg`

  // Plain-language callouts: biggest moves vs your own average.
  const callouts = data.avg_months.length >= 2 ? parents
    .filter((p: any) => p.avg > 0 && Math.abs(p.total - p.avg) >= 5000 && Math.abs(pct(p.total, p.avg) ?? 0) >= 25)
    .sort((a: any, b: any) => Math.abs(b.total - b.avg) - Math.abs(a.total - a.avg))
    .slice(0, 4) : []

  const toggle = (p: string) => setOpen(s => { const n = new Set(s); n.has(p) ? n.delete(p) : n.add(p); return n })

  return (
    <>
      <div className="toolbar">
        <button className="btn" disabled={i <= 0} onClick={() => setMonth(months[i - 1])}>‹</button>
        <select value={data.month} onChange={e => setMonth(e.target.value)}>
          {[...data.months].reverse().map((m: any) => (
            <option key={m.month} value={m.month}>{monthLabel(m.month, true)}{m.complete ? '' : ' (incomplete)'}</option>
          ))}
        </select>
        <button className="btn" disabled={i >= months.length - 1} onClick={() => setMonth(months[i + 1])}>›</button>
        <label className="check" style={{ marginLeft: 'auto' }}>
          <input type="checkbox" checked={!oneOff} onChange={e => setOneOff(!e.target.checked)} /> Exclude one-off purchases
        </label>
      </div>

      {!data.complete && (
        <div className="notice">
          <b>⚠ Incomplete month.</b>
          {missing.length
            ? <>Missing statement coverage for: {missing.map((a: any) => `${a.name} (${a.cells[data.month]})`).join(', ')}. </>
            : null}
          Totals undercount until every card's statements covering {monthLabel(data.month, true)} are uploaded.
        </div>
      )}

      <div className="grid3">
        <div className="card stat">
          <div className="label">Spent in {monthLabel(data.month, true)}</div>
          <div className="value">{money(data.total)}</div>
          <div className="sub muted">
            {data.manual_total ? `${money(data.total - data.manual_total)} on cards + ${money(data.manual_total)} fixed expenses` : 'across all cards · payments excluded'}
            {data.reimbursed_total > 0 && ` · ${money(data.reimbursed_total)} reimbursed not counted`}
          </div>
        </div>
        <div className="card stat">
          <div className="label">vs {monthLabel(data.prev_month, true)}{data.prev_complete ? '' : data.prev_has_data ? ' (incomplete)' : ''}</div>
          <div className="value">{data.prev_has_data ? money(data.prev_total) : '–'}</div>
          <div className="sub">{data.prev_has_data ? <Delta cur={data.total} base={data.prev_total} label="last month" /> : <span className="muted">no data</span>}</div>
        </div>
        <div className="card stat">
          <div className="label">Your {data.avg_months.length}-month average</div>
          <div className="value">{data.avg_months.length ? money(data.avg_total) : '–'}</div>
          <div className="sub">{data.avg_months.length ? <Delta cur={data.total} base={data.avg_total} label="average" /> : <span className="muted">needs earlier months</span>}</div>
        </div>
      </div>

      <CashFlow income={data.income} spent={data.actual_spent} saved={data.saved}
        note={data.prev_income ? `${monthLabel(data.prev_month, true)}: saved ${money(data.prev_saved)} (${Math.round((data.prev_saved / data.prev_income) * 100)}%)` : undefined} />

      {callouts.length > 0 && (
        <div className="card">
          <h2>What stood out</h2>
          <ul className="callouts">
            {callouts.map((p: any) => {
              const up = p.total > p.avg
              return (
                <li key={p.parent}>
                  <span className="swatch" style={{ background: ctx.colorOf(p.parent) }} />
                  <b>{p.parent}</b> was <span className={up ? 'up' : 'down'}>{up ? '▲' : '▼'} {Math.abs(pct(p.total, p.avg) ?? 0)}% {up ? 'above' : 'below'}</span> your average ({money(p.total)} vs {money(p.avg)})
                </li>
              )
            })}
          </ul>
        </div>
      )}

      <div className="card">
        <div className="row spread"><h2>Spending by category</h2><span className="muted small">Click a category to expand · click a subcategory to see transactions</span></div>
        <div className="scroll">
          <table>
            <thead>
              <tr><th>Category</th><th style={{ width: '32%' }}></th><th className="num">Amount</th><th className="num">vs last month</th><th className="num">vs {avgLabel}</th></tr>
            </thead>
            <tbody>
              {parents.map((p: any) => (
                <Fragment key={p.parent}>
                  <tr className="cat-row" onClick={() => toggle(p.parent)}>
                    <td><span className="muted small">{open.has(p.parent) ? '▾' : '▸'}</span> <span className="swatch" style={{ background: ctx.colorOf(p.parent) }} /><b>{p.parent}</b></td>
                    <td className="bar-track"><div className="bar" style={{ width: `${Math.max(0, (p.total / max) * 100)}%`, background: ctx.colorOf(p.parent) }} /></td>
                    <td className="num"><b>{money(p.total)}</b></td>
                    <DeltaCell cur={p.total} base={p.prev} />
                    <DeltaCell cur={p.total} base={p.avg} />
                  </tr>
                  {open.has(p.parent) && p.children.filter((c: any) => c.total || c.prev || c.avg).map((c: any) => (
                    <tr key={c.name} className="child">
                      <td><button className="linkish" onClick={() => ctx.goTxns({ month: data.month, category: c.name })}>{c.name}</button></td>
                      <td className="bar-track"><div className="bar" style={{ width: `${Math.max(0, (c.total / max) * 100)}%`, background: ctx.colorOf(p.parent), opacity: 0.55 }} /></td>
                      <td className="num">{money(c.total)}</td>
                      <DeltaCell cur={c.total} base={c.prev} />
                      <DeltaCell cur={c.total} base={c.avg} />
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
          <h2>Top merchants</h2>
          <table><tbody>
            {data.top_merchants.map((m: any) => (
              <tr key={m.merchant}>
                <td><button className="linkish" onClick={() => ctx.goTxns({ merchant: m.merchant })}>{m.merchant}</button><div className="muted small">{m.cat} · {m.n}×</div></td>
                <td className="num">{money(m.total)}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
        <div className="card">
          <h2>Largest purchases</h2>
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
