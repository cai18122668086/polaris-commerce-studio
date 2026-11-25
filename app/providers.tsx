"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { AuthBoundary } from "@/components/auth/auth-boundary";
import { CreditShortfallNotice } from "@/components/credit-shortfall-notice";
import { initializeAuthClient } from "@/lib/auth/client";
import { getAuthMode } from "@/lib/auth/config";
import { captureSignupSource } from "@/lib/auth/signup-source";
import { createQueryClient } from "@/lib/query/query-client";

export function Providers({ children }: { children: React.ReactNode }) {
  if (getAuthMode() !== "development") initializeAuthClient();
  const [queryClient] = useState(createQueryClient);
  // 记下访客是从哪个 ?from= 链接进来的（注册来源）
  useEffect(() => captureSignupSource(window.location.search), []);

  return (
    <QueryClientProvider client={queryClient}>
      <AuthBoundary>{children}</AuthBoundary>
      <CreditShortfallNotice />
    </QueryClientProvider>
  );
}
