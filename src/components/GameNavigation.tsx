import { ArrowLeft, ArrowRight } from "lucide-react";
import { useMemo, type Ref } from "react";
import { Link, useLocation } from "react-router-dom";
import { useToday } from "./DailyJourney";
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
  return <nav ref={navRef} aria-label="Game navigation" className={`game-navigation mx-auto flex w-full max-w-[430px] items-center gap-2 border-t border-slate-200 bg-white/95 px-3 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] ${pathname === "/map" ? "relative" : "fixed inset-x-0 bottom-0 z-[1000] shadow-[0_-8px_24px_rgba(15,23,42,0.12)] backdrop-blur"}`}>
    <Link to={previous.href} aria-label={`Previous game: ${previous.label}`} className="saints-focus flex min-h-12 min-w-0 flex-1 items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-2 text-sm font-black text-slate-950"><ArrowLeft aria-hidden="true" className="h-5 w-5 shrink-0"/><span>{previous.label}</span></Link>
    <Link to={next.href} aria-label={`Next game: ${next.label}`} className="saints-focus flex min-h-12 min-w-0 flex-1 items-center justify-center gap-2 rounded-xl bg-saints-black px-2 text-sm font-black text-white"><span>{next.label}</span><ArrowRight aria-hidden="true" className="h-5 w-5 shrink-0"/></Link>
  </nav>;
}
