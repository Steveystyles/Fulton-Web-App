import { DailyQuiz } from "../components/DailyQuiz";
import { PageContainer } from "../components/PageContainer";
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
    <PageContainer title="GENERAL QUIZ" number="3">
      <DailyQuiz
        quizDate={quizDate}
        questions={questions}
        loading={loading}
        error={error}
        emptyMessage="Today's general knowledge quiz is not available yet."
      />
    </PageContainer>
  );
}
