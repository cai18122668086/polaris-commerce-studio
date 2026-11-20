"use client";

import { createContext, useContext } from "react";

/** True only for platform administrators: review receipts, attempt counts and diagnostics. */
export const InternalToolsContext = createContext(false);

export function useInternalTools() {
  return useContext(InternalToolsContext);
}
