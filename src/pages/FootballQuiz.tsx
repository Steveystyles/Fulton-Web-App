import { CircleHelp } from "lucide-react";
import { PlaceholderPage } from "../components/PlaceholderPage";

export function FootballQuiz() {
  return (
    <PlaceholderPage
      title="FOOTBALL QUIZ"
      number="2"
      message="Football quiz placeholder."
    >
      <div className="mt-5 flex min-h-20 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 text-slate-400">
        <CircleHelp aria-hidden="true" className="h-8 w-8" strokeWidth={2.4} />
      </div>
    </PlaceholderPage>
  );
}
