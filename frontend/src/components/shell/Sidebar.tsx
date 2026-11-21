import { motion } from "motion/react";
import { NavLink, useLocation } from "react-router-dom";
import { SPRING } from "../../lib/motion";
import Icon, { type IconName } from "../Icon";
import { Kbd } from "../ui/Primitives";

const NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Overview", icon: "overview", end: true },
  { to: "/products", label: "Products", icon: "products" },
  { to: "/approvals", label: "Approvals", icon: "inbox" },
  { to: "/recommendations", label: "Recommendations", icon: "recommendations" },
  { to: "/monitoring", label: "Monitoring", icon: "monitoring" },
];

/** The Price Tracker mark: a price tag on petrol with a saffron eyelet. */
export function Mark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={`shrink-0 ${className}`} aria-hidden>
      <rect x="0.5" y="0.5" width="31" height="31" rx="7.5" className="fill-band stroke-on-band/10" />
      <path d="M7 16l5.2-6.2h11.3c.8 0 1.5.7 1.5 1.5v9.4c0 .8-.7 1.5-1.5 1.5H12.2Z" fill="none" className="stroke-on-band" strokeWidth={2} strokeLinejoin="round" />
      <circle cx="12.6" cy="16" r="1.6" className="fill-warn-fill" />
      <path d="M16.5 18.2h5" className="stroke-on-band/60" strokeWidth={1.6} strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <Mark />
      {!compact && (
        <span className="whitespace-nowrap text-[15px] font-semibold tracking-[-0.03em]">
          Price <span className="text-muted">Tracker</span>
        </span>
      )}
    </span>
  );
}

interface Props {
  pending: number;
  reviewer: string;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  onNavigate?: () => void;
  /** Distinguishes the desktop rail from the mobile drawer (separate indicator animations). */
  id?: string;
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("") || "?";

/** Product navigation. Collapses to an icon rail (labels move to tooltips). */
export default function Sidebar({ pending, reviewer, collapsed = false, onToggleCollapsed, onNavigate, id = "rail" }: Props) {
  const { pathname } = useLocation();
  const isActive = (to: string, end?: boolean) => (end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`));

  const item = (active: boolean) =>
    `group relative flex h-9 items-center gap-3 rounded-[8px] text-[13px] font-medium transition-colors duration-150 ${
      collapsed ? "justify-center px-0" : "px-2.5"
    } ${active ? "text-ink" : "text-muted hover:bg-ink/[0.04] hover:text-ink"}`;

  const tip = (label: string) =>
    collapsed ? (
      <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-[6px] bg-ink px-2 py-1 text-[12px] font-medium text-surface opacity-0 shadow-pop transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100">
        {label}
      </span>
    ) : null;

  return (
    <div className="flex h-full flex-col px-3 pb-3 pt-4">
      <div className={`flex h-9 items-center ${collapsed ? "justify-center" : "pl-1.5"}`}>
        <NavLink to="/" onClick={onNavigate} className="rounded-[8px]" aria-label="Price Tracker overview">
          <Logo compact={collapsed} />
        </NavLink>
      </div>

      <nav aria-label="Main" className="mt-7 flex flex-col gap-0.5">
        {!collapsed && <div className="eyebrow mb-2 px-2.5 text-[10px] text-faint">Pricing desk</div>}
        {NAV.map((n) => {
          const active = isActive(n.to, n.end);
          return (
            <NavLink key={n.to} to={n.to} end={n.end} onClick={onNavigate} className={item(active)} aria-label={collapsed ? n.label : undefined}>
              {active && (
                <motion.span layoutId={`${id}-nav`} transition={SPRING} className="absolute inset-0 rounded-[8px] bg-raised shadow-xs ring-1 ring-line" aria-hidden>
                  <span className="absolute inset-y-2 left-0 w-[3px] rounded-r-full bg-brand" />
                </motion.span>
              )}
              <Icon name={n.icon} className={`relative ${active ? "text-ink" : ""}`} />
              {!collapsed && <span className="relative flex-1">{n.label}</span>}
              {n.to === "/approvals" && pending > 0 && (
                <span
                  className={`num grid place-items-center rounded-full bg-warn-fill font-semibold text-gray-900 ${
                    collapsed ? "absolute right-[7px] top-[2px] h-4 min-w-[16px] px-1 text-[10px] ring-2 ring-rail" : "relative h-5 min-w-[20px] px-1.5 text-[11px]"
                  }`}
                  aria-label={`${pending} pending`}
                >
                  {pending}
                </span>
              )}
              {tip(n.label)}
            </NavLink>
          );
        })}
      </nav>

      <NavLink
        to="/add"
        onClick={onNavigate}
        className={`mt-4 flex h-9 items-center gap-3 rounded-[8px] border border-dashed text-[13px] font-medium transition-colors duration-150 ${
          collapsed ? "justify-center px-0" : "px-2.5"
        } ${isActive("/add") ? "border-brand bg-raised text-ink" : "border-line-strong text-muted hover:border-gray-300 hover:bg-raised/60 hover:text-ink"} group relative`}
        aria-label={collapsed ? "Add product" : undefined}
      >
        <Icon name="plus" />
        {!collapsed && <span>Add product</span>}
        {tip("Add product")}
      </NavLink>

      <div className="mt-auto flex flex-col gap-1">
        {/* One place for the toggle, in both states. */}
        {onToggleCollapsed && (
          <button
            className={`${item(false)} w-full`}
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
          >
            <Icon name={collapsed ? "expand" : "collapse"} />
            {!collapsed && <span className="flex-1 text-left">Collapse</span>}
            {!collapsed && <Kbd>[</Kbd>}
            {tip("Expand sidebar  [")}
          </button>
        )}
        <div className={`mb-1 border-t border-line ${collapsed ? "mx-1" : "mx-1.5"}`} />
        <NavLink
          to="/settings"
          onClick={onNavigate}
          className={`${item(isActive("/settings"))} h-12`}
          aria-label="Settings: profile, alert recipients, appearance"
        >
          {isActive("/settings") && (
            <motion.span layoutId={`${id}-nav`} transition={SPRING} className="absolute inset-0 rounded-[8px] bg-raised shadow-xs ring-1 ring-line" aria-hidden />
          )}
          <span
            className={`relative grid h-8 w-8 shrink-0 place-items-center rounded-full text-[11px] font-semibold tracking-wide ${
              reviewer ? "bg-brand text-on-brand" : "border border-dashed border-line-strong text-muted"
            }`}
            aria-hidden
          >
            {reviewer ? initials(reviewer) : <Icon name="user" className="h-3.5 w-3.5" />}
          </span>
          {!collapsed && (
            <span className="relative min-w-0 flex-1 leading-tight">
              <span className="block truncate text-[13px] font-medium text-ink">{reviewer || "Add your name"}</span>
              <span className="block text-[11px] font-normal text-muted">{reviewer ? "Pricing desk · Settings" : "Used in the price log"}</span>
            </span>
          )}
          {!collapsed && <Icon name="settings" className="relative h-4 w-4 text-faint" />}
          {tip("Settings")}
        </NavLink>
      </div>
    </div>
  );
}
