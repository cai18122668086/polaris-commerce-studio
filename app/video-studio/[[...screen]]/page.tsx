import { notFound } from "next/navigation";
import type { StudioScreen } from "@/components/video-studio/video-studio";
import { VideoStudioGate } from "@/components/video-studio/video-studio-gate";

export const metadata = {
  title: "视频创作空间",
  description: "极光商绘视频创作空间：文案、声音与数字人口播。",
};

const screens = new Set(["create", "avatars", "voices", "library", "works", "editing"]);

export default async function VideoStudioPage({ params }: { params: Promise<{ screen?: string[] }> }) {
  const { screen = [] } = await params;
  if (screen.length > 1 || (screen[0] && !screens.has(screen[0]))) notFound();
  return <VideoStudioGate screen={(screen[0] ?? "home") as StudioScreen} />;
}
