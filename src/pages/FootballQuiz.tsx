import { DailyQuiz } from "../components/DailyQuiz";
import type { DailyQuizQuestion } from "../lib/api";

type FootballQuizProps = {
  storageScope: string | number;
  quizDate?: string;
  questions: DailyQuizQuestion[];
  loading: boolean;
  error: Error | null;
};

export function FootballQuiz({
  storageScope,
  quizDate,
  questions,
  loading,
  error,
}: FootballQuizProps) {
  return (
    <section className="page-fade space-y-3" aria-label="Football quiz">
      <DailyQuiz
        quizId="football"
        storageScope={storageScope}
        quizDate={quizDate}
        questions={questions}
        loading={loading}
        error={error}
        emptyMessage="Today's football quiz is not available yet."
      />
    </section>
  );
}
