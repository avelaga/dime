import { useEffect, useState } from 'react'

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch('/api' + path, init)
  if (!r.ok) throw new Error((await r.text()) || r.statusText)
  return r.json()
}
export const send = (path: string, method: string, body?: unknown) =>
  api(path, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })

const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const usd2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
/** cents -> "$1,234" (whole dollars) or "$1,234.56" */
export const money = (cents: number, exact = false) => (exact ? usd2 : usd0).format(cents / 100)
export const pct = (a: number, b: number) => (b ? Math.round(((a - b) / Math.abs(b)) * 100) : null)

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const monthLabel = (ym: string, long = false) => {
  const [y, m] = ym.split('-').map(Number)
  return long ? new Date(y, m - 1).toLocaleString('en-US', { month: 'long', year: 'numeric' }) : `${MONTHS[m - 1]} ${String(y).slice(2)}`
}
export const shortDate = (iso: string) => {
  const [, m, d] = iso.split('-').map(Number)
  return `${MONTHS[m - 1]} ${d}`
}
export const ISSUERS: Record<string, string> = { chase: 'Chase', citi: 'Citi', bofa: 'Bank of America' }

// Validated categorical palette (fixed order, never cycled). Slot 8 is replaced by neutral "Other".
const LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6']
const DARK = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#0ca30c', '#9085e9']
export const OTHER = 'Other'

export function useDark() {
  const q = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null
  const [dark, setDark] = useState(!!q?.matches)
  useEffect(() => {
    if (!q) return
    const f = () => setDark(q.matches)
    q.addEventListener('change', f)
    return () => q.removeEventListener('change', f)
  }, [])
  return dark
}

/** Color follows the entity: slots are assigned by all-time rank once, so filters never repaint. */
export function makeColorOf(rankedNames: string[], dark: boolean) {
  const slots = dark ? DARK : LIGHT
  const map = new Map(rankedNames.slice(0, slots.length).map((n, i) => [n, slots[i]]))
  const other = dark ? '#6f6e69' : '#a3a29d'
  return (name: string) => map.get(name) ?? other
}
export const topN = (ranked: string[], n = 7) => ranked.slice(0, n)

export type TxnFilter = {
  month?: string; parent?: string; category?: string; q?: string; account_id?: number; year?: string; merchant?: string
  date_from?: string; date_to?: string; reimbursed?: boolean; tag?: string
}
