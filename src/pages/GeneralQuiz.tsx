import { DailyQuiz } from "../components/DailyQuiz";
import type { DailyQuizQuestion } from "../lib/api";

type GeneralQuizProps = {
  quizDate?: string;
  questions: DailyQuizQuestion[];
  loading: boolean;
  error: Error | null;
};

export function GeneralQuiz({
  quizDate,
  questions,
  loading,
  error,
}: GeneralQuizProps) {
  return (
    <section className="page-fade space-y-3" aria-label="General knowledge quiz">
      <DailyQuiz
        quizDate={quizDate}
        questions={questions}
        loading={loading}
        error={error}
        emptyMessage="Today's general knowledge quiz is not available yet."
      />
    </section>
  );
}
