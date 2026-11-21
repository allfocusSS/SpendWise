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
  sm: { box: 'size-8 text-xs', icon: 'size-3.5' },
  md: { box: 'size-[38px] text-xs', icon: 'size-[17px]' },
  lg: { box: 'size-11 text-sm', icon: 'size-5' },
}

/** Category mark: its icon (or initial) in a round tint of the category colour with a soft ring. */
export function CategoryIcon({ name, color, size = 'md' }: { name: string; color: string; size?: keyof typeof SIZES }) {
  const Icon = ICONS[name.trim().toLowerCase()]
  const s = SIZES[size]
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-full font-semibold ${s.box}`}
      style={{ backgroundColor: tint(color, 13), color, boxShadow: `inset 0 0 0 1.5px ${tint(color, 40)}` }}
      aria-hidden="true"
    >
      {Icon ? <Icon className={s.icon} strokeWidth={1.8} /> : name.trim().charAt(0).toUpperCase() || '?'}
    </span>
  )
}
