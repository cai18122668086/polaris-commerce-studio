import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "极光商绘｜AI 电商图片工作台",
    template: "%s｜极光商绘",
  },
  description:
    "面向电商品牌团队的 AI 图片工作台，支持像素级局部修改与智能详情套图规划。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
