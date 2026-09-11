import { HelpButton } from "../components/HelpButton";
import { CircleHelp, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DailyQuiz } from "../components/DailyQuiz";
import { useAuth } from "../context/AuthContext";
import { api, type DailyQuestionsResponse } from "../lib/api";

type QuizCategory = "football" | "general";

const options: Array<{
  value: QuizCategory;
  label: string;
  icon: typeof CircleHelp;
}> = [
  { value: "football", label: "Football", icon: CircleHelp },
  { value: "general", label: "General knowledge", icon: UsersRound },
];

export function Quiz() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const category: QuizCategory = params.get("category") === "general" ? "general" : "football";
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [dailyQuestions, setDailyQuestions] = useState<DailyQuestionsResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    async function loadDailyQuestions(force = false) {
      try {
        const response = await api.dailyQuestions({ force });
        if (active) {
          setDailyQuestions(response);
          setError(null);
        }
      } catch (caughtError) {
        if (active) {
          setError(caughtError instanceof Error ? caughtError : new Error("Daily quiz failed to load."));
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    function refreshWhenVisible() {
      if (document.visibilityState === "visible") {
        void loadDailyQuestions(true);
      }
    }

    // The app may stay open across midnight, so do not reuse yesterday's cached quiz.
    void loadDailyQuestions(true);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [refreshVersion]);

  const questions =
    category === "football"
      ? dailyQuestions?.football ?? []
      : dailyQuestions?.general ?? [];

  return (
    <section className="page-fade min-w-0 space-y-2" aria-label="Daily quiz">
      <div className="grid min-w-0 grid-cols-[repeat(2,minmax(0,1fr))_2.75rem] gap-2" aria-label="Quiz type">
        {options.map((option) => {
          const Icon = option.icon;
          const active = option.value === category;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => setParams({ category: option.value })}
              aria-pressed={active}
              className={[
                "flex min-h-11 min-w-0 items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-sm font-black transition focus:outline-none focus:ring-4 focus:ring-saints-red/20",
                active
                  ? "border-saints-black bg-saints-black text-white shadow-sm"
                  : "border-saints-line bg-white text-slate-700 hover:border-saints-red/40",
              ].join(" ")}
            >
              <Icon aria-hidden="true" className="h-4 w-4 shrink-0" strokeWidth={2.5} />
              <span className="min-w-0 leading-tight [overflow-wrap:anywhere]">{option.label}</span>
            </button>
          );
        })}
        <HelpButton compact title="How to play the quiz"><p>Pick one answer, then confirm with Next question or Finish round. You can change your choice before confirming. Confirmed answers are saved and cannot be changed. All three answers are revealed at the end. There is no timer.</p></HelpButton>
      </div>

      <DailyQuiz
        key={`${user?.id}:${category}:${dailyQuestions?.date}`}
        category={category}
        storageScope={user?.id ?? 0}
        quizDate={dailyQuestions?.date}
        questions={questions}
        loading={loading}
        error={error}
        serverResult={dailyQuestions?.results[category] ?? null}
        serverAnswers={dailyQuestions?.progress[category] ?? []}
        onRefresh={() => setRefreshVersion(value => value + 1)}
      />
    </section>
  );
}
