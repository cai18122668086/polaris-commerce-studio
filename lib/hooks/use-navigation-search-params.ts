"use client";

import { useSearchParams } from "next/navigation";
import { useMemo, useSyncExternalStore } from "react";

const navigationEvent = "polaris:navigation-search";
let subscribers = 0;
let restoreHistory: (() => void) | undefined;

function observeHistory() {
  const history = window.history;
  const push = history.pushState;
  const replace = history.replaceState;
  const pushed: History["pushState"] = function (this: History, ...args) {
    push.apply(this, args);
    window.dispatchEvent(new Event(navigationEvent));
  };
  const replaced: History["replaceState"] = function (this: History, ...args) {
    replace.apply(this, args);
    window.dispatchEvent(new Event(navigationEvent));
  };
  history.pushState = pushed;
  history.replaceState = replaced;
  return () => {
    if (history.pushState === pushed) history.pushState = push;
    if (history.replaceState === replaced) history.replaceState = replace;
  };
}

function subscribe(onChange: () => void) {
  if (subscribers++ === 0) restoreHistory = observeHistory();
  window.addEventListener("popstate", onChange);
  window.addEventListener(navigationEvent, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(navigationEvent, onChange);
    if (--subscribers === 0) { restoreHistory?.(); restoreHistory = undefined; }
  };
}

const browserSearch = () => window.location.search;

/** Track router links and native Back/Forward, including restored route trees. */
export function useNavigationSearchParams() {
  const routeSearch = useSearchParams().toString();
  const search = useSyncExternalStore(subscribe, browserSearch, () => routeSearch);
  return useMemo(() => new URLSearchParams(search), [search]);
}
