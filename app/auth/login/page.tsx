import { AuthShell } from "@/components/auth/auth-shell";
import { LoginForm } from "@/features/auth/components/login-form";
import { sanitizeReturnTo } from "@/lib/auth/return-to";

type LoginPageProps = {
  searchParams: Promise<{ returnTo?: string | string[] }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const value = (await searchParams).returnTo;
  const returnTo = sanitizeReturnTo(Array.isArray(value) ? value[0] : value);

  return (
    <AuthShell title="欢迎回来" description="登录后继续使用你的电商图片工作台。">
      <LoginForm returnTo={returnTo} />
    </AuthShell>
  );
}
