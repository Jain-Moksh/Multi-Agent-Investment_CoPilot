import ReactMarkdown from 'react-markdown'

const COMPONENTS = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
  h1: ({ children }) => <h3 className="mb-2 mt-3 text-base font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-2 mt-3 text-base font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1 mt-3 text-sm font-semibold first:mt-0">{children}</h4>,
  strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-indigo-600 underline hover:text-indigo-800">
      {children}
    </a>
  ),
  code: ({ children }) => <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-xs">{children}</code>,
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-4 border-slate-200 pl-3 text-slate-600">{children}</blockquote>
  ),
}

export default function Markdown({ children }) {
  return (
    <div className="text-sm leading-relaxed text-slate-800">
      <ReactMarkdown components={COMPONENTS}>{children}</ReactMarkdown>
    </div>
  )
}
