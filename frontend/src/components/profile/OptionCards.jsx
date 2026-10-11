import { Check } from 'lucide-react'

export default function OptionCards({ name, options, value, onChange }) {
  return (
    <div role="radiogroup" aria-label={name} className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {options.map((option) => {
        const selected = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(selected ? null : option.value)}
            className={`relative rounded-xl border p-4 text-left transition-colors ${
              selected
                ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100'
                : 'border-slate-200 bg-white hover:border-indigo-300'
            }`}
          >
            {selected && (
              <span className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-white">
                <Check size={12} />
              </span>
            )}
            <p className="text-sm font-semibold text-slate-900">{option.label}</p>
            <p className="mt-1 text-xs text-slate-500">{option.description}</p>
          </button>
        )
      })}
    </div>
  )
}
