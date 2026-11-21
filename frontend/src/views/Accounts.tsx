import { useEffect, useRef, useState } from 'react'
import type { Ctx } from '../App'
import { api, ISSUERS, money, monthLabel, send } from '../lib'
import RecurringExpenses from './RecurringExpenses'
import IncomeSources from './IncomeSources'

const CELL: Record<string, [string, string]> = {
  full: ['✓', 'Statements cover the whole month'],
  zero: ['0', 'No statement issued: no activity ($0)'],
  partial: ['◐', 'Only part of the month is covered'],
  missing: ['✕', 'No statement covers this month'],
  inactive: ['·', 'Card not open'],
}

function AccountForm({ onSaved }: { onSaved: () => void }) {
  const [name, setName] = useState('')
  const [issuer, setIssuer] = useState('chase')
  const [last4, setLast4] = useState('')
  const [opened, setOpened] = useState('')
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    await send('/accounts', 'POST', { name, issuer, last4s: last4, opened_on: opened || null })
    setName(''); setLast4(''); setOpened('')
    onSaved()
  }
  return (
    <form className="row" onSubmit={save}>
      <select value={issuer} onChange={e => setIssuer(e.target.value)}>
        {Object.entries(ISSUERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <input type="text" placeholder="Nickname, e.g. Travel card" value={name} onChange={e => setName(e.target.value)} style={{ minWidth: 220 }} />
      <input type="text" placeholder="Last 4 (optional)" value={last4} onChange={e => setLast4(e.target.value.replace(/\D/g, '').slice(0, 4))} style={{ width: 130 }} />
      <label className="muted small">Opened <input type="date" value={opened} onChange={e => setOpened(e.target.value)} /></label>
      <button className="btn primary">Add card</button>
    </form>
  )
}

function AccountRow({ a, onChanged }: { a: any; onChanged: () => void }) {
  const [edit, setEdit] = useState(false)
  const [v, setV] = useState({ name: a.name, last4s: a.last4s, opened_on: a.opened_on ?? '', closed_on: a.closed_on ?? '' })
  const save = async () => { await send(`/accounts/${a.id}`, 'PUT', { ...v, issuer: a.issuer }); setEdit(false); onChanged() }
  const del = async () => {
    if (confirm(`Delete "${a.name}" and its ${a.statements} statement(s) and all their transactions?`)) { await send(`/accounts/${a.id}`, 'DELETE'); onChanged() }
  }
  if (edit) return (
    <tr>
      <td colSpan={2}><input type="text" value={v.name} onChange={e => setV({ ...v, name: e.target.value })} /></td>
      <td><input type="text" value={v.last4s} onChange={e => setV({ ...v, last4s: e.target.value })} style={{ width: 110 }} title="Comma-separate if the card was replaced" /></td>
      <td><input type="date" value={v.opened_on} onChange={e => setV({ ...v, opened_on: e.target.value })} /></td>
      <td><input type="date" value={v.closed_on} onChange={e => setV({ ...v, closed_on: e.target.value })} /></td>
      <td className="row"><button className="btn sm primary" onClick={save}>Save</button><button className="btn sm" onClick={() => setEdit(false)}>Cancel</button></td>
    </tr>
  )
  return (
    <tr>
      <td><b>{a.name}</b></td>
      <td>{ISSUERS[a.issuer]}</td>
      <td className="muted">{a.last4s ? a.last4s.split(',').map((l: string) => `••${l}`).join(', ') : 'set on first upload'}</td>
      <td className="muted small">{a.opened_on ?? '–'}</td>
      <td className="muted small">{a.closed_on ?? '–'}</td>
      <td className="row">
        <span className="muted small">{a.statements} stmt{a.statements === 1 ? '' : 's'}</span>
        <button className="btn sm" onClick={() => setEdit(true)}>Edit</button>
        <button className="btn sm danger" onClick={del}>Delete</button>
      </td>
    </tr>
  )
}

export default function Accounts({ ctx }: { ctx: Ctx }) {
  const [accounts, setAccounts] = useState<any[]>([])
  const [cov, setCov] = useState<any>(null)
  const [stmts, setStmts] = useState<any[]>([])
  const [results, setResults] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [picks, setPicks] = useState<Record<string, number>>({})
  const fileInput = useRef<HTMLInputElement>(null)
  const covScroll = useRef<HTMLDivElement>(null)
  const [showAll, setShowAll] = useState(false)
  // Newest months are on the right; start scrolled there.
  useEffect(() => { if (covScroll.current) covScroll.current.scrollLeft = covScroll.current.scrollWidth }, [cov])

  const load = () => {
    api('/accounts').then(setAccounts)
    api('/coverage').then(setCov)
    api('/statements').then(setStmts)
  }
  useEffect(load, [ctx.version])
  const changed = () => { load(); ctx.refresh() }

  const upload = async (files: FileList | File[]) => {
    const pdfs = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.pdf'))
    if (!pdfs.length) return
    setBusy(true)
    const fd = new FormData()
    pdfs.forEach(f => fd.append('files', f))
    try {
      const r = await api<any[]>('/statements/upload', { method: 'POST', body: fd })
      setResults(prev => [...r, ...prev])
    } catch (e: any) {
      setResults(prev => [{ filename: 'upload', status: 'error', message: String(e.message ?? e) }, ...prev])
    }
    setBusy(false)
    changed()
  }
  const importAs = async (r: any, accountId: number, force = false) => {
    const res = await send('/statements/import', 'POST', { hash: r.hash, account_id: accountId, force })
    setResults(prev => prev.map(x => (x.hash === r.hash ? { ...x, ...res } : x)))
    changed()
  }
  const toggleNoActivity = async (a: any, m: string, marked: boolean) => {
    if (!marked && !confirm(`Mark ${a.name} for ${monthLabel(m, true)} as "no activity"?\n\nUse this when the issuer didn't send a statement because nothing was charged. The month then counts as $0 for this card.`)) return
    await send('/no-activity', 'POST', { account_id: a.id, month: m, on: !marked })
    changed()
  }
  const delStmt = async (s: any) => {
    if (confirm(`Remove the ${s.account_name} statement ending ${s.period_end}?`)) { await send(`/statements/${s.id}`, 'DELETE'); changed() }
  }

  const months: string[] = cov?.months ?? []
  const completeCount = months.filter(m => cov.complete[m]).length

  return (
    <>
      <div className="card">
        <h2>1 · Your cards</h2>
        <p className="muted" style={{ marginTop: -4 }}>
          Add <b>every</b> credit card you have. A month only counts as complete when each open card has its statement uploaded.
          Last-4 digits are optional: they're filled in automatically from the first statement and stay in your local database.
        </p>
        {accounts.length > 0 && (
          <div className="scroll"><table style={{ marginBottom: 12 }}>
            <thead><tr><th>Card</th><th>Issuer</th><th>Ending</th><th>Opened</th><th>Closed</th><th></th></tr></thead>
            <tbody>{accounts.map(a => <AccountRow key={a.id} a={a} onChanged={changed} />)}</tbody>
          </table></div>
        )}
        <AccountForm onSaved={changed} />
      </div>

      <div className="card">
        <h2>2 · Upload statements</h2>
        <div className={`drop ${over ? 'over' : ''}`}
          onClick={() => fileInput.current?.click()}
          onDragOver={e => { e.preventDefault(); setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={e => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files) }}>
          {busy ? 'Reading statements…' : <>Drop PDF statements here (any number, any card) or <u>click to choose</u></>}
          <input ref={fileInput} type="file" accept="application/pdf" multiple hidden onChange={e => e.target.files && upload(e.target.files)} />
        </div>
        {results.length > 0 && (
          <table style={{ marginTop: 12 }}><tbody>
            {results.map((r, i) => (
              <tr key={r.hash ?? i}>
                <td className="small">{r.filename}<div className="muted">{r.issuer ? `${ISSUERS[r.issuer]}${r.last4 ? ` ••${r.last4}` : ''} · ${r.period_start} → ${r.period_end}` : ''}</div></td>
                <td><span className={`status ${r.status}`}>{{ imported: '✓ Imported', duplicate: 'Already imported', error: '✕ Error', needs_account: 'Which card?', unreconciled: '✕ Didn’t balance' }[r.status as string] ?? r.status}</span>
                  {r.status === 'imported' && <span className="muted small"> {r.transactions} transactions</span>}
                  {r.message && r.status !== 'imported' && <div className="muted small">{r.message}</div>}
                </td>
                <td>
                  {r.status === 'needs_account' && (() => {
                    const opts = accounts.filter(a => a.issuer === r.issuer)
                    if (!opts.length) return <span className="small muted">Add a {ISSUERS[r.issuer]} card above first, then pick it here.</span>
                    const pick = picks[r.hash] ?? opts[0].id
                    return (
                      <div className="row">
                        <select value={pick} onChange={e => setPicks({ ...picks, [r.hash]: Number(e.target.value) })}>
                          {opts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                        </select>
                        <button className="btn sm primary" onClick={() => importAs(r, pick)}>Import</button>
                      </div>
                    )
                  })()}
                  {r.status === 'unreconciled' && <button className="btn sm" onClick={() => importAs(r, r.account_id, true)}>Import anyway</button>}
                </td>
              </tr>
            ))}
          </tbody></table>
        )}
      </div>

      {months.length > 0 && (
        <div className="card">
          <div className="row spread">
            <h2>3 · Coverage</h2>
            <span className="muted small">{completeCount} of {months.length} months complete · ✓ statement · 0 no activity · ◐ partial · ✕ missing · · not open</span>
          </div>
          <div className="scroll" ref={covScroll}>
            <table className="cov">
              <thead>
                <tr><th>Card</th>{months.map(m => <th key={m}>{monthLabel(m)}</th>)}</tr>
              </thead>
              <tbody>
                {cov.accounts.map((a: any) => (
                  <tr key={a.id}>
                    <td>{a.name}</td>
                    {months.map(m => {
                      const s = a.cells[m] ?? 'missing'
                      const marked = a.no_activity.includes(m)
                      const clickable = marked || s === 'missing' || s === 'partial'
                      const tip = `${a.name} · ${monthLabel(m, true)}: ${CELL[s][1]}${marked ? ' (marked by you; click to undo)' : clickable ? '. Click if no statement was issued because there was no activity' : ''}`
                      return (
                        <td key={m}>
                          <span className={`cell ${s}${clickable ? ' click' : ''}`} title={tip} onClick={() => clickable && toggleNoActivity(a, m, marked)}>{CELL[s][0]}</span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
                <tr>
                  <td><b>Month complete</b></td>
                  {months.map(m => <td key={m}>{cov.complete[m] ? <span className="cell full">✓</span> : <span className="cell missing">✕</span>}</td>)}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="muted small">
            Statement cycles don't line up with calendar months, so a month usually needs two statements per card (e.g. Sep 15–Oct 14 and Oct 15–Nov 14).
            Issuers skip the statement when nothing happened: gaps between two $0 statements are filled in automatically (0); for any other
            month with no statement, click its ✕ or ◐ to confirm there was no activity.
          </p>
        </div>
      )}

      <IncomeSources onChanged={ctx.refresh} version={ctx.version} />
      <RecurringExpenses onChanged={ctx.refresh} version={ctx.version} />

      {stmts.length > 0 && (
        <div className="card">
          <div className="row spread">
            <h2>Imported statements ({stmts.length})</h2>
            {stmts.length > 12 && <button className="btn sm" onClick={() => setShowAll(!showAll)}>{showAll ? 'Show recent' : 'Show all'}</button>}
          </div>
          <div className="scroll"><table>
            <thead><tr><th>Card</th><th>Period</th><th className="num">Transactions</th><th className="num">New balance</th><th>Check</th><th></th></tr></thead>
            <tbody>{(showAll ? stmts : stmts.slice(0, 12)).map(s => (
              <tr key={s.id}>
                <td>{s.account_name}</td>
                <td className="muted">{s.period_start} → {s.period_end}</td>
                <td className="num">{s.transactions}</td>
                <td className="num">{money(s.new_balance, true)}</td>
                <td>{s.reconciled ? <span className="status imported">✓ balances</span> : <span className="status error" title="Imported anyway">off by {money(s.recon_diff, true)}</span>}</td>
                <td><button className="btn sm danger" onClick={() => delStmt(s)}>Remove</button></td>
              </tr>
            ))}</tbody>
          </table></div>
        </div>
      )}
    </>
  )
}
