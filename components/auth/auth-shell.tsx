import Link from "next/link";
import { BrandMark } from "@/components/brand-mark";

export function AuthShell({ title, description, children, footer }: { title: string; description: string; children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <main className="auth-page"><section className="auth-card" aria-labelledby="auth-title">
      <Link className="auth-card__brand" href="/" aria-label="极光商绘"><BrandMark /></Link>
      <div className="auth-card__heading"><p className="auth-card__eyebrow">极光商绘账号</p><h1 id="auth-title">{title}</h1><p>{description}</p></div>
      {children}{footer ? <div className="auth-card__footer">{footer}</div> : null}
    </section></main>
  );
}
