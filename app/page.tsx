import { AppShell } from "@/components/app-shell";
import { ToolDirectory } from "@/components/tool-directory";

export const metadata = {
  title: "AI 功能大全",
};

export default function Home() {
  return (
    <AppShell>
      <div className="tool-market-page">
        <ToolDirectory />
      </div>
    </AppShell>
  );
}
