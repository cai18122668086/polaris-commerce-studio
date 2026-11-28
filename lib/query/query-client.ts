import { MutationCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/api-error";
import { reportCreditShortfall } from "@/lib/billing/insufficient-credits";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    // Every paid submission is a mutation; a 402 anywhere raises the 「充值积分」 notice.
    mutationCache: new MutationCache({
      onError(error) {
        if (error instanceof ApiError && error.status === 402) reportCreditShortfall(error.details);
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry(failureCount, error) {
          const status =
            typeof error === "object" && error !== null && "status" in error
              ? Number(error.status)
              : undefined;
          if (status !== undefined && status < 500) {
            return false;
          }
          return failureCount < 2;
        },
        refetchOnWindowFocus: true,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
