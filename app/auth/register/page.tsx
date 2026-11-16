import { AuthShell } from "@/components/auth/auth-shell";
import { WelcomeCreditsBanner } from "@/components/welcome-credits";
import { RegisterForm } from "@/features/auth/components/register-form";
import { sanitizeReturnTo } from "@/lib/auth/return-to";

type RegisterPageProps = {
  searchParams: Promise<{ returnTo?: string | string[]; invite?: string | string[] }>;
};

export default async function RegisterPage({ searchParams }: RegisterPageProps) {
  const { returnTo: value, invite } = await searchParams;
  const returnTo = sanitizeReturnTo(Array.isArray(value) ? value[0] : value);

  return (
    <AuthShell title="创建账号">
      <WelcomeCreditsBanner compact />
      <RegisterForm returnTo={returnTo} invite={typeof invite === "string" ? invite : undefined} />
    </AuthShell>
  );
}
