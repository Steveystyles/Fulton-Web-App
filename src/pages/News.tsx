import { Newspaper } from "lucide-react";
import { Card } from "../components/Card";
import { PageContainer } from "../components/PageContainer";

const headlines = [
  "Latest football headlines will appear here.",
  "Saints fixture notes placeholder.",
  "Weekend quiz-night talking points placeholder.",
];

export function News() {
  return (
    <PageContainer title="NEWS" number="5">
      <Card>
        <div className="flex items-start gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-saints-black text-white">
            <Newspaper aria-hidden="true" className="h-6 w-6" strokeWidth={2.4} />
          </div>
          <div>
            <p className="text-xl font-black leading-tight text-slate-950">
              News hub placeholder
            </p>
            <p className="mt-2 text-base font-semibold leading-relaxed text-slate-600">
              Latest football headlines will appear here.
            </p>
          </div>
        </div>
      </Card>

      <section className="space-y-3" aria-label="News placeholder cards">
        {headlines.map((headline, index) => (
          <Card key={headline} as="article" className="p-4">
            <p className="text-xs font-black uppercase tracking-normal text-saints-red">
              Story {index + 1}
            </p>
            <h3 className="mt-2 text-lg font-black leading-tight text-slate-950">
              {headline}
            </h3>
            <p className="mt-2 text-sm font-semibold leading-relaxed text-slate-600">
              Static placeholder content for the future news section.
            </p>
          </Card>
        ))}
      </section>
    </PageContainer>
  );
}
