export const ASSET_TYPES = [
  { value: 'stock', label: 'Stock', plural: 'Stocks' },
  { value: 'mutual_fund', label: 'Mutual Fund', plural: 'Mutual Funds' },
  { value: 'fd', label: 'FD', plural: 'FDs' },
  { value: 'gold', label: 'Gold', plural: 'Gold' },
  { value: 'property', label: 'Property', plural: 'Property' },
]

export function assetTypeLabel(value) {
  return ASSET_TYPES.find((type) => type.value === value)?.label || value || '-'
}

export const SOURCE_LABELS = {
  manual: 'Manual',
  tradebook_upload: 'Tradebook',
  kite_sync: 'Zerodha',
}
