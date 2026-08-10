import { AppShell } from "@/components/app-shell";
import { AccountPanel } from "@/features/auth/components/account-panel";

export default function AccountPage() {
  return (
    <AppShell sidebar={false}>
      <div className="account-page">
        <AccountPanel />
      </div>
    </AppShell>
  );
}
