import { ArrowLeft, ArrowRight } from "lucide-react";
import { useMemo, type Ref } from "react";
import { Link, useLocation } from "react-router-dom";
import { useToday } from "./DailyJourney";
import { navigateWithFreshRelease } from "./AppUpdateReloader";
import type { ActivityId } from "../lib/api";

const games: Array<{ id: ActivityId; href: string; label: string }> = [
  { id: "wordle", href: "/wordle", label: "Wordle" },
  { id: "quiz", href: "/quiz", label: "Quiz" },
  { id: "map", href: "/map", label: "Map" },
];

export function GameNavigation({ navRef }: { navRef?: Ref<HTMLElement> }) {
  const { pathname } = useLocation();
  const { data } = useToday();
  const available = useMemo(() => games.filter(game => game.id !== "map" || pathname === "/map" || data?.activities.some(item => item.id === "map" && item.status !== "unavailable")), [data, pathname]);
  const index = available.findIndex(game => game.href === pathname);
  if (index < 0) return null;
  const previous = available[(index - 1 + available.length) % available.length];
  const next = available[(index + 1) % available.length];
  const sameDestination = previous.id === next.id;
  return <nav ref={navRef} aria-label="Game navigation" className={`game-navigation ${pathname === "/map" ? "relative" : "fixed inset-x-0 bottom-0 z-1000"}`}>
    <Link to={previous.href} onClick={event => navigateWithFreshRelease(event, previous.href)} aria-label={`Previous game: ${previous.label}`} className="game-navigation__link saints-focus"><ArrowLeft aria-hidden="true" className="h-4 w-4 shrink-0"/>{!sameDestination ? <span>{previous.label}</span> : null}</Link>
    {sameDestination ? <span className="game-navigation__destination">{next.label}</span> : <span className="game-navigation__divider" aria-hidden="true" />}
    <Link to={next.href} onClick={event => navigateWithFreshRelease(event, next.href)} aria-label={`Next game: ${next.label}`} className="game-navigation__link saints-focus">{!sameDestination ? <span>{next.label}</span> : null}<ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0"/></Link>
  </nav>;
}
