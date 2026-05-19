import type { HTMLAttributes, ReactNode } from "react";

type CardProps = HTMLAttributes<HTMLElement> & {
  as?: "article" | "section" | "div";
  children: ReactNode;
};

export function Card({
  as = "section",
  className = "",
  children,
  ...props
}: CardProps) {
  const classes = [
    "max-w-full overflow-hidden rounded-3xl border border-slate-200 bg-white p-4 shadow-soft",
    className,
  ].join(" ");

  if (as === "article") {
    return (
      <article className={classes} {...props}>
        {children}
      </article>
    );
  }

  if (as === "div") {
    return (
      <div className={classes} {...props}>
        {children}
      </div>
    );
  }

  return (
    <section className={classes} {...props}>
      {children}
    </section>
  );
}
