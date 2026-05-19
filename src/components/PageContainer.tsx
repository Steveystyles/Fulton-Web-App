import type { ReactNode } from "react";

type PageContainerProps = {
  title: string;
  number: string;
  children: ReactNode;
};

export function PageContainer({ title, number, children }: PageContainerProps) {
  const headingId = `${title.toLowerCase().replace(/\s+/g, "-")}-title`;

  return (
    <section className="page-fade space-y-4" aria-labelledby={headingId}>
      <div className="max-w-full overflow-hidden rounded-[2rem] bg-saints-black text-white shadow-soft">
        <div className="relative p-5">
          <div className="absolute -right-4 -top-8 h-24 w-24 rounded-full border-[18px] border-saints-red/[0.35]" />
          <div className="relative flex items-end justify-between gap-4">
            <h2
              id={headingId}
              className="max-w-[12rem] text-3xl font-black leading-none tracking-normal"
            >
              {title}
            </h2>
            <span
              className="text-7xl font-black leading-[0.8] text-saints-red"
              aria-label={`${title} page number ${number}`}
            >
              {number}
            </span>
          </div>
        </div>
      </div>
      {children}
    </section>
  );
}
