"use client";

import { useSearchParams } from "next/navigation";
import { useMemo, useSyncExternalStore } from "react";

function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

const browserSearch = () => window.location.search;

/** Track router links and native Back/Forward, including restored route trees. */
export function useNavigationSearchParams() {
  const routeSearch = useSearchParams().toString();
  const search = useSyncExternalStore(subscribe, browserSearch, () => routeSearch);
  return useMemo(() => new URLSearchParams(search), [search]);
}
