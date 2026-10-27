import { AppShell } from "@/components/app-shell";
import { AccountPanel } from "@/features/auth/components/account-panel";
import { CreditAccountPanel } from "@/features/billing/components/credit-account";

import styles from "./page.module.css";

export default function AccountPage() {
  return (
    <AppShell sidebar={false}>
      <div className={`account-page ${styles.page}`}>
        <CreditAccountPanel />
        <AccountPanel />
      </div>
    </AppShell>
  );
}
