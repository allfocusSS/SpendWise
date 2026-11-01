import type { ComponentType, SVGProps } from 'react'

import { tint } from '../lib/styles'
import {
  BagIcon,
  BookIcon,
  BriefcaseIcon,
  CarIcon,
  CartIcon,
  CoinsIcon,
  CupIcon,
  FilmIcon,
  GiftIcon,
  HeartIcon,
  HomeIcon,
  LaptopIcon,
} from './icons'

// Icons for the seeded default categories (matched by name, presentation only).
// Any other category is shown with its initial.
const ICONS: Record<string, ComponentType<SVGProps<SVGSVGElement>>> = {
  groceries: CartIcon,
  'restaurants & cafes': CupIcon,
  transport: CarIcon,
  'housing & utilities': HomeIcon,
  health: HeartIcon,
  entertainment: FilmIcon,
  shopping: BagIcon,
  education: BookIcon,
  'other expenses': CoinsIcon,
  salary: BriefcaseIcon,
  freelance: LaptopIcon,
  gifts: GiftIcon,
  'other income': CoinsIcon,
}

const SIZES = {
  sm: { box: 'size-7 rounded-md text-xs', icon: 'size-3.5' },
  md: { box: 'size-8 rounded-lg text-xs', icon: 'size-4' },
  lg: { box: 'size-10 rounded-lg text-sm', icon: 'size-5' },
}

/** Category mark: its icon (or initial) on a soft tint of the category colour. */
export function CategoryIcon({ name, color, size = 'md' }: { name: string; color: string; size?: keyof typeof SIZES }) {
  const Icon = ICONS[name.trim().toLowerCase()]
  const s = SIZES[size]
  return (
    <span
      className={`grid shrink-0 place-items-center font-semibold ${s.box}`}
      style={{ backgroundColor: tint(color, 14), color, boxShadow: `inset 0 0 0 1px ${tint(color, 28)}` }}
      aria-hidden="true"
    >
      {Icon ? <Icon className={s.icon} strokeWidth={1.8} /> : name.trim().charAt(0).toUpperCase() || '?'}
    </span>
  )
}
