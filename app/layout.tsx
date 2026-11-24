import type { Metadata } from "next";
import { headers } from "next/headers";
import { Providers } from "./providers";
import { withBasePath } from "@/lib/base-path";
import "./globals.css";
import "./focus-inspired.css";
import "./commerce-theme.css";
import "./commerce-surfaces.css";
import "./commerce-workspaces.css";
import "./commerce-forms.css";
import "./commerce-readability.css";
import "./showcase-cases.css";
import "./ember-dark.generated.css";
import "./ember-dark.css";
import "./home-ember-dark.css";
import "./ember-studio.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host =
    requestHeaders.get("x-forwarded-host") ??
    requestHeaders.get("host") ??
    "localhost:3000";
  const protocol =
    requestHeaders.get("x-forwarded-proto") ??
    (host.startsWith("localhost") ? "http" : "https");
  const previewImage = new URL(withBasePath("/og.png"), `${protocol}://${host}`).toString();
  const title = "极光商绘｜电商图片工作台";
  const description =
    "从单张局部精修到整套商品详情，面向电商品牌团队的图片创作工作台。";

  return {
    title: {
      default: title,
      template: "%s｜极光商绘",
    },
    description,
    icons: {
      icon: [
        { url: withBasePath("/polaris-mark-ember.svg"), type: "image/svg+xml" },
        { url: withBasePath("/favicon.ico"), sizes: "any" },
      ],
      shortcut: withBasePath("/favicon.ico"),
      apple: [{ url: withBasePath("/apple-touch-icon.png"), sizes: "180x180" }],
    },
    manifest: withBasePath("/manifest.webmanifest"),
    openGraph: {
      title,
      description,
      type: "website",
      images: [{ url: previewImage, alt: "极光商绘电商图片工作台" }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [previewImage],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="theme-ember">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
