import Link from "next/link";

import { BackButton } from "@/components/status-page/back-button";
import { StatusPage, statusPageStyles as styles } from "@/components/status-page/status-page";

export const metadata = { title: "页面不存在", robots: { index: false } };

export default function NotFound() {
  return (
    <StatusPage code="404" title="这个页面不存在" text="链接可能已失效，或者页面已经移动。">
      <Link className={`${styles.btn} ${styles.primary}`} href="/">返回首页</Link>
      <BackButton className={styles.btn} />
    </StatusPage>
  );
}
