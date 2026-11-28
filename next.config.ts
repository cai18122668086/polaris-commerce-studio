import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 开发预览挂在子路径下时（如手机预览的 /site）通过环境变量指定；生产不设置，保持根路径。
  basePath: process.env.POLARIS_BASE_PATH || undefined,
};

export default nextConfig;
