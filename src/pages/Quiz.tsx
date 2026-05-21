import { CircleHelp, UsersRound } from "lucide-react";
import { useMemo, useState } from "react";
import { DailyQuiz } from "../components/DailyQuiz";
import type { DailyQuizQuestion } from "../lib/api";

type QuizCategory = "football" | "general";

type QuizProps = {
  storageScope: string | number;
  quizDate?: string;
  footballQuestions: DailyQuizQuestion[];
  generalQuestions: DailyQuizQuestion[];
  loading: boolean;
  error: Error | null;
};

const quizOptions: Array<{
  value: QuizCategory;
  label: string;
  icon: typeof CircleHelp;
}> = [
  { value: "football", label: "Football", icon: CircleHelp },
  { value: "general", label: "General knowledge", icon: UsersRound },
];

export function Quiz({
  storageScope,
  quizDate,
  footballQuestions,
  generalQuestions,
  loading,
  error,
}: QuizProps) {
  const [category, setCategory] = useState<QuizCategory>("football");
  const activeQuestions = category === "football" ? footballQuestions : generalQuestions;
  const emptyMessage =
    category === "football"
      ? "Today's football quiz is not available yet."
      : "Today's general knowledge quiz is not available yet.";

  const questionCountLabel = useMemo(() => {
    const footballCount = footballQuestions.length;
    const generalCount = generalQuestions.length;
    return `${footballCount} football / ${generalCount} general`;
  }, [footballQuestions.length, generalQuestions.length]);

  return (
    <section className="page-fade space-y-3" aria-label="Daily quiz">
      <div className="grid grid-cols-2 gap-2" aria-label="Quiz type">
        {quizOptions.map((option) => {
          const Icon = option.icon;
          const active = option.value === category;

          return (
            <button
              key={option.value}
              type="button"
              onClick={() => setCategory(option.value)}
              className={[
                "flex min-h-12 items-center justify-center gap-2 rounded-2xl border px-2 text-sm font-black transition focus:outline-none focus:ring-4 focus:ring-saints-red/20",
                active
                  ? "border-saints-black bg-saints-black text-white shadow-sm"
                  : "border-saints-line bg-white text-slate-700 hover:border-saints-red/40 hover:bg-saints-redSoft",
              ].join(" ")}
            >
              <Icon aria-hidden="true" className="h-4 w-4 shrink-0" strokeWidth={2.5} />
              <span className="min-w-0 leading-tight">{option.label}</span>
            </button>
          );
        })}
      </div>

      <p className="sr-only">{questionCountLabel}</p>

      <DailyQuiz
        quizId={category}
        storageScope={storageScope}
        quizDate={quizDate}
        questions={activeQuestions}
        loading={loading}
        error={error}
        emptyMessage={emptyMessage}
      />
    </section>
  );
}
