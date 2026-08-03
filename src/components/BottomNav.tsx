import { CircleHelp, Hash, MapPinned, Newspaper, Trophy } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { NavItem } from "./NavItem";

const navItems = [
  { to: "/scores", label: "Scores", icon: Trophy, end: true },
  { to: "/wordle", label: "Wordle", icon: Hash },
  { to: "/quiz", label: "Quiz", icon: CircleHelp },
  { to: "/news", label: "News", icon: Newspaper },
  { to: "/map", label: "Map", icon: MapPinned },
];

export function BottomNav() {
  const { availableAnnouncements } = useAuth();
  const mapAvailable = availableAnnouncements.some(
    (announcement) => announcement.kind === "daily-map-promo",
  );
  const visibleNavItems = navItems.filter((item) => item.to !== "/map" || mapAvailable);

  return (
    <nav
      aria-label="Bottom navigation"
      className="bottom-nav border-t border-saints-line bg-saints-paper/95 px-1.5 pb-[max(0.35rem,env(safe-area-inset-bottom))] pt-1.5 shadow-nav backdrop-blur-xl"
    >
      <div className="mx-auto flex w-full max-w-[430px] gap-1">
        {visibleNavItems.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
      </div>
    </nav>
  );
}
