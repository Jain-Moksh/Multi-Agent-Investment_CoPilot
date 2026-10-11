export const RISK_OPTIONS = [
  {
    value: 'conservative',
    label: 'Conservative',
    description: 'Protect capital first; warnings count for more than opportunities.',
  },
  {
    value: 'moderate',
    label: 'Moderate',
    description: 'A balance of growth and safety; ups and downs are fine within limits.',
  },
  {
    value: 'aggressive',
    label: 'Aggressive',
    description: 'Chase higher growth and accept large swings along the way.',
  },
]

export const HORIZON_OPTIONS = [
  { value: 'short_term', label: 'Short term', description: 'Under about 3 months; price action matters most.' },
  { value: 'medium_term', label: 'Medium term', description: 'Roughly 3 months to a year.' },
  { value: 'long_term', label: 'Long term', description: 'More than a year; business quality matters most.' },
]

export const BASIS_LABELS = {
  stated: 'Your stated preference',
  behaviour: 'Your trading behaviour',
  blended: 'Stated and behaviour combined (the more cautious one)',
  default: 'Default (not enough information yet)',
}

export const MIN_TRADES = 5

export function optionLabel(options, value) {
  return options.find((option) => option.value === value)?.label || '-'
}
