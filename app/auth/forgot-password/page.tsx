import { AuthShell } from "@/components/auth/auth-shell";
import { ForgotPasswordForm } from "@/features/auth/components/password-reset-form";

export default function ForgotPasswordPage() {
  return (
    <AuthShell title="找回密码" description="输入注册邮箱，我们会发送密码重置链接。">
      <ForgotPasswordForm />
    </AuthShell>
  );
}
