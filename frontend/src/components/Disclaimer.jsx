export const DISCLAIMER_TEXT = 'Educational decision support, not financial advice.'

export default function Disclaimer({ className = '' }) {
  return <p className={`text-xs text-slate-400 ${className}`}>{DISCLAIMER_TEXT}</p>
}
