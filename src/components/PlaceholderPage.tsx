import type { ReactNode } from "react";
import { Card } from "./Card";
import { PageContainer } from "./PageContainer";

type PlaceholderPageProps = {
  title: string;
  number: string;
  message: string;
  children?: ReactNode;
};

export function PlaceholderPage({
  title,
  number,
  message,
  children,
}: PlaceholderPageProps) {
  return (
    <PageContainer title={title} number={number}>
      <Card>
        <p className="text-lg font-extrabold text-slate-950">{message}</p>
        {children}
      </Card>
    </PageContainer>
  );
}
