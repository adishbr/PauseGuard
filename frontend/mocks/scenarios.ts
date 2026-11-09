export const demoTokens = {
  payer: 'pauseguard-demo-payer',
  guardian: 'pauseguard-demo-guardian',
} as const

export const beneficiaries = {
  merchant_familiar: 'Cedar Café',
  supplier_new: 'Willow Supplies',
  recipient_flagged: 'Harbor Trading',
} as const

export const purposes = {
  purchase: 'Purchase',
  supplier_payment: 'Supplier payment',
  kyc_verification: 'KYC or verification request',
} as const

export const scenarios = [
  { title: 'Everyday purchase', tag: 'Routine', beneficiary: 'merchant_familiar', amount: '100', purpose: 'purchase' },
  { title: 'Unfamiliar supplier', tag: 'Warning', beneficiary: 'supplier_new', amount: '50000', purpose: 'supplier_payment' },
  { title: 'Coerced KYC transfer', tag: 'Guardian review', beneficiary: 'supplier_new', amount: '55000', purpose: 'kyc_verification' },
] as const
