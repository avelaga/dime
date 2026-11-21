import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, makeColorOf, TxnFilter, useDark } from './lib'
import MonthView from './views/MonthView'
import YearView from './views/YearView'
import Trends from './views/Trends'
import Transactions from './views/Transactions'
import Insights from './views/Insights'
import Accounts from './views/Accounts'
import Fire from './views/Fire'

type Tab = 'month' | 'year' | 'trends' | 'transactions' | 'insights' | 'fire' | 'accounts'
const TABS: [Tab, string][] = [['month', 'Monthly'], ['year', 'Yearly'], ['trends', 'Trends'], ['transactions', 'Transactions'], ['insights', 'Insights'], ['fire', 'FIRE'], ['accounts', 'Accounts & Upload']]

export type Ctx = {
  version: number
  refresh: () => void
  colorOf: (name: string) => string
  rankedParents: string[]
  goTxns: (f: TxnFilter) => void
  goMonth: (month: string, openParent?: string) => void
}

// URL hash: "#trends", "#year/2026", "#month/2026-05", "#month/2026-05/Food%20%26%20Dining" (Back button works for
// drill-downs). `month` holds the second segment: a YYYY-MM month, or a YYYY year on the year tab.
type Route = { tab: Tab | null; month?: string; open?: string }
function parseHash(): Route {
  const [t, month, open] = location.hash.slice(1).split('/')
  const tab = TABS.some(([k]) => k === t) ? (t as Tab) : null
  return { tab, month: month || undefined, open: open ? decodeURIComponent(open) : undefined }
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash)
  const tab = route.tab
  const setTab = (t: Tab) => { setRoute({ tab: t }); history.replaceState(null, '', `#${t}`) }
  useEffect(() => {
    const onPop = () => setRoute(parseHash())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const [version, setVersion] = useState(0)
  const [txnFilter, setTxnFilter] = useState<TxnFilter>({})
  const [rankedParents, setRanked] = useState<string[]>([])
  const [cat, setCat] = useState<any>(null)
  const dark = useDark()
  const refresh = useCallback(() => setVersion(v => v + 1), [])
  const wasRunning = useRef(false)

  useEffect(() => {
    if (tab === null)
      api<any[]>('/accounts').then(a => setTab(a.some(x => x.statements > 0) ? 'month' : 'accounts'))
  }, [tab])

  // Color slots assigned once by all-time spend so every view agrees.
  useEffect(() => { api('/trends').then(t => setRanked(t.series)) }, [version])

  // Poll background categorization; refresh views when it finishes.
  useEffect(() => {
    let timer: number
    const poll = async () => {
      try {
        const s = await api('/categorize/status')
        setCat(s)
        if (wasRunning.current && !s.running) refresh()
        wasRunning.current = s.running
        timer = window.setTimeout(poll, s.running ? 1500 : 5000)
      } catch { timer = window.setTimeout(poll, 5000) }
    }
    poll()
    return () => clearTimeout(timer)
  }, [refresh])

  const colorOf = useMemo(() => makeColorOf(rankedParents, dark), [rankedParents, dark])
  const ctx: Ctx = {
    version, refresh, colorOf, rankedParents,
    goTxns: f => { setTxnFilter(f); history.pushState(null, '', '#transactions'); setRoute({ tab: 'transactions' }) },
    goMonth: (month, open) => {
      history.pushState(null, '', `#month/${month}${open ? `/${encodeURIComponent(open)}` : ''}`)
      setRoute({ tab: 'month', month, open })
      window.scrollTo(0, 0)
    },
  }

  return (
    <div className="app">
      <header className="top">
        <h1 className="brand"><img src="/logo.png" alt="" className="logo" />Dime</h1>
        <nav className="tabs">
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? 'on' : ''} onClick={() => { if (k === 'transactions') setTxnFilter({}); setTab(k) }}>{label}</button>
          ))}
        </nav>
        {cat && (
          <span className="pill" title={cat.llm_available ? `Local model: ${cat.model}` : 'Ollama not reachable: using keyword rules'}>
            {cat.running ? `Categorizing merchants… ${cat.done}/${cat.total}` : cat.llm_available ? `● ${cat.model}` : '○ keyword rules (Ollama off)'}
          </span>
        )}
      </header>
      {tab === 'month' && <MonthView key={`${route.month}|${route.open}`} ctx={ctx} initialMonth={route.month} initialOpen={route.open} />}
      {tab === 'year' && <YearView key={route.month} ctx={ctx} initialYear={route.month} />}
      {tab === 'trends' && <Trends ctx={ctx} />}
      {tab === 'transactions' && <Transactions ctx={ctx} initial={txnFilter} />}
      {tab === 'insights' && <Insights ctx={ctx} />}
      {tab === 'fire' && <Fire ctx={ctx} />}
      {tab === 'accounts' && <Accounts ctx={ctx} />}
    </div>
  )
}
