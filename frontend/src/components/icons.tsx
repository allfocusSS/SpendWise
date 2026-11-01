/** Inline SVG icons, thin 1.6px strokes (decorative: always paired with visible text or an aria-label). */
import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function Icon({ children, ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className="size-4"
      {...props}
    >
      {children}
    </svg>
  )
}

// --- Actions ------------------------------------------------------------------------------
export const PlusIcon = (props: IconProps) => <Icon {...props}><path d="M12 5v14M5 12h14" /></Icon>
export const PencilIcon = (props: IconProps) => <Icon {...props}><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" /></Icon>
export const TrashIcon = (props: IconProps) => <Icon {...props}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></Icon>
export const CloseIcon = (props: IconProps) => <Icon {...props}><path d="M18 6 6 18M6 6l12 12" /></Icon>
export const RefreshIcon = (props: IconProps) => <Icon {...props}><path d="M20 12a8 8 0 0 1-14 5.3L4 15M4 12a8 8 0 0 1 14-5.3L20 9M20 4v5h-5M4 20v-5h5" /></Icon>
export const SearchIcon = (props: IconProps) => <Icon {...props}><><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4-4" /></></Icon>
export const FilterIcon = (props: IconProps) => <Icon {...props}><path d="M4 6h16M7 12h10M10 18h4" /></Icon>
export const ChevronDownIcon = (props: IconProps) => <Icon {...props}><path d="m6 9 6 6 6-6" /></Icon>
export const ChevronLeftIcon = (props: IconProps) => <Icon {...props}><path d="m15 6-6 6 6 6" /></Icon>
export const ChevronRightIcon = (props: IconProps) => <Icon {...props}><path d="m9 6 6 6-6 6" /></Icon>
export const ArrowRightIcon = (props: IconProps) => <Icon {...props}><path d="M5 12h14M13 6l6 6-6 6" /></Icon>
export const SidebarIcon = (props: IconProps) => <Icon {...props}><><rect x="3.5" y="4.5" width="17" height="15" rx="2" /><path d="M9.5 4.5v15" /></></Icon>
export const MenuIcon = (props: IconProps) => <Icon {...props}><path d="M4 7h16M4 12h16M4 17h16" /></Icon>

// --- States -------------------------------------------------------------------------------
export const AlertIcon = (props: IconProps) => <Icon {...props}><><circle cx="12" cy="12" r="9" /><path d="M12 8v4.5M12 16h.01" /></></Icon>
export const CalendarIcon = (props: IconProps) => <Icon {...props}><><rect x="3.5" y="5" width="17" height="15" rx="2" /><path d="M8 3v4M16 3v4M3.5 10h17" /></></Icon>
export const ReceiptIcon = (props: IconProps) => <Icon {...props}><><path d="M6 3h12v18l-3-2-3 2-3-2-3 2Z" /><path d="M9 8h6M9 12h6" /></></Icon>
export const ChartIcon = (props: IconProps) => <Icon {...props}><><path d="M4 4v16h16" /><path d="m7 15 4-4 3 3 5-6" /></></Icon>

// --- Navigation ---------------------------------------------------------------------------
export const DashboardIcon = (props: IconProps) => <Icon {...props}><><rect x="3.5" y="3.5" width="7" height="9" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="5" rx="1.5" /><rect x="13.5" y="11.5" width="7" height="9" rx="1.5" /><rect x="3.5" y="15.5" width="7" height="5" rx="1.5" /></></Icon>
export const TransactionsIcon = (props: IconProps) => <Icon {...props}><path d="M7 4 3.5 7.5 7 11M3.5 7.5H17M17 13l3.5 3.5L17 20M20.5 16.5H7" /></Icon>
export const TagIcon = (props: IconProps) => <Icon {...props}><><path d="M3.5 12.6V4.5a1 1 0 0 1 1-1h8.1a1 1 0 0 1 .7.3l7.4 7.4a1 1 0 0 1 0 1.4l-8.1 8.1a1 1 0 0 1-1.4 0l-7.4-7.4a1 1 0 0 1-.3-.7Z" /><circle cx="8.5" cy="8.5" r="1.25" /></></Icon>
export const AnalyticsIcon = (props: IconProps) => <Icon {...props}><><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></></Icon>

// --- Money --------------------------------------------------------------------------------
export const WalletIcon = (props: IconProps) => <Icon {...props}><><path d="M19 7V5.5A1.5 1.5 0 0 0 17.5 4h-12A1.5 1.5 0 0 0 4 5.5v13A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16" /><path d="M14 10h6.5v6H14a3 3 0 0 1 0-6Z" /></></Icon>
export const ArrowDownLeftIcon = (props: IconProps) => <Icon {...props}><path d="M17 7 7 17M16 17H7V8" /></Icon>
export const ArrowUpRightIcon = (props: IconProps) => <Icon {...props}><path d="M7 17 17 7M8 7h9v9" /></Icon>
export const PiggyIcon = (props: IconProps) => <Icon {...props}><><path d="M5 11a7 6 0 0 1 12.5-3.6L20 6v4h1.5v3H20a7 7 0 0 1-3 3.5V19h-3v-1.5h-4V19H7v-2.6A6.5 6.5 0 0 1 5 11Z" /><path d="M15.5 10.5h.01" /></></Icon>
export const SwatchIcon = (props: IconProps) => <Icon {...props}><><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="3.5" /></></Icon>

// --- Categories (used for the default categories; custom ones get a monogram) ---------------
export const CartIcon = (props: IconProps) => <Icon {...props}><><path d="M3 4h2.5l2 11h10l2-8H6.5" /><circle cx="9" cy="19.5" r="1.25" /><circle cx="16.5" cy="19.5" r="1.25" /></></Icon>
export const CupIcon = (props: IconProps) => <Icon {...props}><><path d="M4 9h12v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5Z" /><path d="M16 10h1.5a2.5 2.5 0 0 1 0 5H16M8 3v3M12 3v3" /></></Icon>
export const CarIcon = (props: IconProps) => <Icon {...props}><><path d="M5 16V11l2-5h10l2 5v5" /><path d="M3.5 16h17v2.5h-17zM7 18.5V20M17 18.5V20" /><circle cx="8" cy="13" r=".75" /><circle cx="16" cy="13" r=".75" /></></Icon>
export const HomeIcon = (props: IconProps) => <Icon {...props}><path d="M4 10.5 12 4l8 6.5V20h-5.5v-6h-5v6H4Z" /></Icon>
export const HeartIcon = (props: IconProps) => <Icon {...props}><path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10Z" /></Icon>
export const FilmIcon = (props: IconProps) => <Icon {...props}><><rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M8 5v14M16 5v14M3.5 9.5H8M3.5 14.5H8M16 9.5h4.5M16 14.5h4.5" /></></Icon>
export const BagIcon = (props: IconProps) => <Icon {...props}><><path d="M5 8h14l-1 12H6Z" /><path d="M9 8V6.5a3 3 0 0 1 6 0V8" /></></Icon>
export const BookIcon = (props: IconProps) => <Icon {...props}><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5ZM20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5Z" /></Icon>
export const BriefcaseIcon = (props: IconProps) => <Icon {...props}><><rect x="3.5" y="7.5" width="17" height="12" rx="1.5" /><path d="M9 7.5V5.5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M3.5 12.5h17" /></></Icon>
export const LaptopIcon = (props: IconProps) => <Icon {...props}><><rect x="5" y="5" width="14" height="10" rx="1" /><path d="M3 19h18l-2-4H5Z" /></></Icon>
export const GiftIcon = (props: IconProps) => <Icon {...props}><><rect x="4" y="9" width="16" height="11" rx="1" /><path d="M3 9h18M12 9v11M12 9S10.5 4 8 5s1 4 4 4ZM12 9s1.5-5 4-4-1 4-4 4Z" /></></Icon>
export const CoinsIcon = (props: IconProps) => <Icon {...props}><><ellipse cx="9" cy="7" rx="5.5" ry="2.5" /><path d="M3.5 7v4c0 1.4 2.5 2.5 5.5 2.5M3.5 11v4c0 1.4 2.5 2.5 5.5 2.5" /><ellipse cx="15" cy="13" rx="5.5" ry="2.5" /><path d="M9.5 13v4c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5v-4" /></></Icon>
