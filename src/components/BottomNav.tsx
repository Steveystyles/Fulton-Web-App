import { CircleHelp, Hash, MapPinned, Newspaper, House } from "lucide-react";
import { NavItem } from "./NavItem";

const navItems = [
  { to: "/", label: "Today", icon: House, end: true },
  { to: "/wordle", label: "Wordle", icon: Hash },
  { to: "/quiz", label: "Quiz", icon: CircleHelp },
  { to: "/map", label: "Map", icon: MapPinned },
  { to: "/news", label: "News", icon: Newspaper },
];

export function BottomNav() {

  return (
    <nav
      aria-label="Bottom navigation"
      className="bottom-nav border-t border-saints-line bg-saints-paper/95 px-1.5 pb-[max(0.35rem,env(safe-area-inset-bottom))] pt-1.5 shadow-nav backdrop-blur-xl"
    >
      <div className="mx-auto flex w-full max-w-[430px] gap-1">
        {navItems.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
      </div>
    </nav>
  );
}
