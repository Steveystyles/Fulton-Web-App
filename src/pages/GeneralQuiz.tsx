import { BookOpen, Lightbulb, Music, Sparkles } from "lucide-react";
import { PlaceholderPage } from "../components/PlaceholderPage";

const categories = [
  { label: "History", icon: BookOpen },
  { label: "Music", icon: Music },
  { label: "Mixed", icon: Lightbulb },
];

export function GeneralQuiz() {
  return (
    <PlaceholderPage
      title="GENERAL QUIZ"
      number="3"
      message="General knowledge round coming soon."
    >
      <div className="mt-5 grid gap-2">
        {categories.map(({ label, icon: Icon }) => (
          <div
            key={label}
            className="flex min-h-14 items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-3"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white text-saints-red shadow-sm">
              <Icon aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            </span>
            <span className="font-black text-slate-900">{label}</span>
            <Sparkles
              aria-hidden="true"
              className="ml-auto h-5 w-5 text-slate-300"
              strokeWidth={2.4}
            />
          </div>
        ))}
      </div>
    </PlaceholderPage>
  );
}
