import { useEffect, useState } from 'react'
import type { Ctx } from '../App'
import { api, money, monthLabel, send, shortDate } from '../lib'

export default function Insights({ ctx }: { ctx: Ctx }) {
  const [d, setD] = useState<any>(null)
  const [tags, setTags] = useState<any[]>([])
  useEffect(() => { api('/insights').then(setD); api('/tags').then(setTags) }, [ctx.version])
  if (!d) return null
  if (!d.latest_date) return <div className="card empty">No data yet.</div>

  const active = d.recurring.filter((r: any) => r.active)
  const recurringMonthly = active.reduce((s: number, r: any) => s + r.monthly_cost, 0)
  const recurringYearly = active.reduce((s: number, r: any) => s + r.annual_cost, 0)
  const setYearly = async (r: any, yes: boolean) => {
    await send(`/merchants/${encodeURIComponent(r.merchant_key)}`, 'PATCH', { yearly: yes })
    ctx.refresh()
  }
  const feeTotal = d.fees.reduce((s: number, f: any) => s + f.fees + f.interest, 0)
  const maxTop = Math.max(1, ...d.top_merchants.map((m: any) => m.total))

  return (
    <>
      {tags.length > 0 && (
        <div className="card">
          <h2>Trips & one-off events</h2>
          <p className="muted small" style={{ marginTop: -6 }}>
            Group charges (including things booked months ahead) in Transactions → select → "Add to trip / event". They're one-off, so
            "Exclude one-off purchases" in Monthly and Trends shows your spending without them.
          </p>
          <div className={tags.length > 1 ? 'grid2' : ''}>
            {tags.map(t => {
              const max = Math.max(1, ...t.by_category.map((c: any) => c.total))
              return (
                <div key={t.tag}>
                  <div className="row spread">
                    <button className="linkish" onClick={() => ctx.goTxns({ tag: t.tag })}><b>{t.tag}</b></button>
                    <span className="num"><b>{money(t.total)}</b>{t.reimbursed > 0 && <span className="muted small"> after reimbursement</span>}</span>
                  </div>
                  <div className="muted small" style={{ marginBottom: 6 }}>
                    {shortDate(t.first)} '{t.first.slice(2, 4)} – {shortDate(t.last)} '{t.last.slice(2, 4)} · {t.n} charges
                  </div>
                  <table style={{ tableLayout: 'fixed' }}>
                    <colgroup><col style={{ width: '34%' }} /><col /><col style={{ width: 90 }} /></colgroup>
                    <tbody>{t.by_category.slice(0, 8).map((c: any) => (
                      <tr key={c.cat}>
                        <td className="small" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={c.cat}>
                          <span className="swatch" style={{ background: ctx.colorOf(c.parent) }} />{c.cat}
                        </td>
                        <td><div className="bar" style={{ width: `${Math.max(0, c.total / max) * 100}%`, background: ctx.colorOf(c.parent) }} /></td>
                        <td className="num small">{money(c.total)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="card">
        <div className="row spread">
          <h2>Subscriptions & recurring charges</h2>
          <span><b>{money(recurringMonthly)}/mo</b> <span className="muted">· {money(recurringYearly)}/yr active</span></span>
        </div>
        <p className="muted small" style={{ marginTop: -6 }}>
          Everything that charges you on a schedule, at today's price. <b>New</b> = started in the last ~4 months or only two charges so far:
          check you meant to sign up. Faded = no recent charge (cancelled?).
        </p>
        {d.recurring.length === 0 ? <p className="muted">Needs a couple of months of history to detect repeating charges.</p> : (
          <div className="scroll"><table>
            <thead><tr><th>Merchant</th><th>Every</th><th>Since</th><th className="num">Last charge</th><th>Price change</th>
              <th className="num">Per month</th><th className="num">Per year</th></tr></thead>
            <tbody>
              {[...d.recurring].sort((a: any, b: any) => (Number(b.active) - Number(a.active)) || b.annual_cost - a.annual_cost).map((r: any) => (
                <tr key={r.merchant} style={{ opacity: r.active ? 1 : 0.5 }}>
                  <td>
                    <button className="linkish" onClick={() => ctx.goTxns({ merchant: r.merchant })}>{r.merchant}</button>
                    {r.is_new && r.active && <span className="badge new" title="Recently started: did you mean to sign up?">New</span>}
                    <div className="muted small">{r.category} · {r.account}{r.active ? '' : ' · no recent charge (cancelled?)'}</div>
                  </td>
                  <td>{{ monthly: 'month', yearly: 'year', weekly: 'week' }[r.period as string] ?? r.period}</td>
                  <td className="muted small">{shortDate(r.first_date)} '{r.first_date.slice(2, 4)}</td>
                  <td className="num">{money(r.last_amount, true)}<div className="muted small">{shortDate(r.last_date)}</div></td>
                  <td>{r.price_change ? <><span className={r.price_change > 0 ? 'up' : 'down'}>{r.price_change > 0 ? '▲' : '▼'} {money(Math.abs(r.price_change), true)}</span><div className="muted small">{shortDate(r.price_change_date)} '{r.price_change_date.slice(2, 4)}</div></> : <span className="muted">–</span>}</td>
                  <td className="num">{money(r.monthly_cost, true)}</td>
                  <td className="num"><b>{money(r.annual_cost)}</b></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>

      {d.annual_renewals?.length > 0 && (
        <div className="card">
          <div className="row spread">
            <h2>Annual renewals</h2>
            <span className="muted">≈ {money(d.annual_renewals.reduce((s: number, r: any) => s + r.amount, 0))}/yr</span>
          </div>
          <p className="muted small" style={{ marginTop: -6 }}>
            Charges that come once a year and are easy to forget. ✓ confirms it's yearly, ✕ hides it.
          </p>
          <div className="scroll"><table>
            <thead><tr><th>Merchant</th><th>Last charged</th><th>Next (est.)</th><th className="num">Amount</th><th></th></tr></thead>
            <tbody>{d.annual_renewals.map((r: any) => (
              <tr key={r.merchant}>
                <td>
                  <button className="linkish" onClick={() => ctx.goTxns({ merchant: r.merchant })}>{r.merchant}</button>
                  {r.status === 'likely' && <span className="badge">likely</span>}
                  <div className="muted small">{r.category} · {r.account} · {r.reason}</div>
                </td>
                <td className="muted small">{shortDate(r.last_date)} '{r.last_date.slice(2, 4)}</td>
                <td className="small">
                  {shortDate(r.next_date)} '{r.next_date.slice(2, 4)}
                  {r.renewal === 'soon' && <span className="badge new">in {r.days_until} days</span>}
                  {r.renewal === 'overdue' && <span className="badge">didn't renew?</span>}
                </td>
                <td className="num">{money(r.amount, true)}</td>
                <td className="row" style={{ flexWrap: 'nowrap' }}>
                  {r.status === 'likely' && <button className="btn sm" title="Yes, this renews yearly" onClick={() => setYearly(r, true)}>✓</button>}
                  <button className="btn sm" title="Not a yearly subscription: hide" onClick={() => setYearly(r, false)}>✕</button>
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        </div>
      )}

      <div className="grid2">
        <div className="card">
          <h2>Unusual charges</h2>
          {d.anomalies.length === 0 ? <p className="muted">Nothing unusual found.</p> : (
            <table><tbody>{d.anomalies.map((a: any) => (
              <tr key={a.id}><td>{a.merchant}<div className="muted small">{shortDate(a.trans_date)} '{a.trans_date.slice(2, 4)} · {a.reason}{a.typical ? ` (usually ${money(a.typical, true)})` : ''}</div></td><td className="num">{money(a.amount, true)}</td></tr>
            ))}</tbody></table>
          )}
        </div>
        <div className="card">
          <h2>Possible duplicate charges</h2>
          <p className="muted small" style={{ marginTop: -6 }}>Same card, merchant and amount ($5+) on the same day. Often legitimate, but worth a glance.</p>
          {d.duplicates.length === 0 ? <p className="muted">None found.</p> : (
            <table><tbody>{d.duplicates.map((x: any) => (
              <tr key={x.ids.join('-')}><td>{x.merchant}<div className="muted small">{x.dates.map(shortDate).join(' & ')} · {x.account}</div></td><td className="num">{money(x.amount, true)} ×2</td></tr>
            ))}</tbody></table>
          )}
        </div>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Top merchants (last 12 months)</h2>
          <table><tbody>{d.top_merchants.map((m: any) => (
            <tr key={m.merchant}>
              <td style={{ width: '45%' }}><button className="linkish" onClick={() => ctx.goTxns({ merchant: m.merchant })}>{m.merchant}</button><div className="muted small">{m.cat} · {m.n}×</div></td>
              <td className="bar-track"><div className="bar" style={{ width: `${(m.total / maxTop) * 100}%` }} /></td>
              <td className="num">{money(m.total)}</td>
            </tr>
          ))}</tbody></table>
        </div>
        <div className="card">
          <h2>Fees & interest</h2>
          {d.fees.length === 0 ? <p className="muted">No fees or interest charged. 🎉</p> : (
            <>
              <p>Total paid: <b className="up">{money(feeTotal, true)}</b></p>
              <table>
                <thead><tr><th>Month</th><th className="num">Fees</th><th className="num">Interest</th></tr></thead>
                <tbody>{d.fees.map((f: any) => <tr key={f.month}><td>{monthLabel(f.month)}</td><td className="num">{money(f.fees, true)}</td><td className="num">{money(f.interest, true)}</td></tr>)}</tbody>
              </table>
            </>
          )}
          <h2 style={{ marginTop: 20 }}>New merchants (last 30 days)</h2>
          {d.new_merchants.length === 0 ? <p className="muted">Shown once you have a few months of history.</p> : (
            <table><tbody>{d.new_merchants.map((n: any) => (
              <tr key={n.merchant}><td>{n.merchant}<div className="muted small">{shortDate(n.first_date)} · {n.category}</div></td><td className="num">{money(n.amount, true)}</td></tr>
            ))}</tbody></table>
          )}
        </div>
      </div>
    </>
  )
}
