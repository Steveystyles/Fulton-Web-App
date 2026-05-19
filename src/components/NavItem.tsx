import type { LucideIcon } from "lucide-react";
import { NavLink } from "react-router-dom";

type NavItemProps = {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
};

export function NavItem({ to, label, icon: Icon, end = false }: NavItemProps) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        [
          "group flex min-h-16 flex-1 flex-col items-center justify-center gap-1 rounded-2xl px-1 text-xs font-bold transition",
          isActive
            ? "bg-red-50 text-saints-red"
            : "text-slate-500 hover:bg-slate-100 hover:text-slate-900",
        ].join(" ")
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            aria-hidden="true"
            className="h-5 w-5"
            strokeWidth={isActive ? 2.8 : 2.2}
          />
          <span className="leading-none">{label}</span>
        </>
      )}
    </NavLink>
  );
}
