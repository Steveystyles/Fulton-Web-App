import { DailyQuiz } from "../components/DailyQuiz";
import { PageContainer } from "../components/PageContainer";
import type { DailyQuizQuestion } from "../lib/api";

type FootballQuizProps = {
  quizDate?: string;
  questions: DailyQuizQuestion[];
  loading: boolean;
  error: Error | null;
};

export function FootballQuiz({
  quizDate,
  questions,
  loading,
  error,
}: FootballQuizProps) {
  return (
    <PageContainer title="FOOTBALL QUIZ" number="2">
      <DailyQuiz
        quizDate={quizDate}
        questions={questions}
        loading={loading}
        error={error}
        emptyMessage="Today's football quiz is not available yet."
      />
    </PageContainer>
  );
}
