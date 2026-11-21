import { money } from '../lib'

/** Income vs. actual spending (one-offs included) → saved and savings rate. Hidden until income is entered. */
export default function CashFlow({ income, spent, saved, note }: { income: number | null; spent: number; saved: number; note?: string }) {
  if (income === null || income === undefined) return null
  const rate = income > 0 ? Math.round((saved / income) * 100) : null
  return (
    <div className="card">
      <div className="row spread"><h2>Cash flow</h2>{note && <span className="muted small">{note}</span>}</div>
      <div className="cashflow">
        <div><div className="label">Take-home income</div><div className="v">{money(income)}</div></div>
        <div className="op">−</div>
        <div><div className="label">Spent (incl. one-offs)</div><div className="v">{money(spent)}</div></div>
        <div className="op">=</div>
        <div><div className="label">{saved >= 0 ? 'Saved' : 'Overspent'}</div><div className={`v ${saved >= 0 ? 'down' : 'up'}`}>{money(Math.abs(saved))}</div></div>
        <div><div className="label">Savings rate</div><div className={`v ${rate !== null && rate < 0 ? 'up' : ''}`}>{rate === null ? '–' : `${rate}%`}</div></div>
      </div>
    </div>
  )
}
