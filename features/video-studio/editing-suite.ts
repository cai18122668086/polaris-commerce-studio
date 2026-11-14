/** Full suites share the existing creative-input and durable preview flow. */
export function isEditingSuite(engine: string | null | undefined): boolean {
  return engine === "apple-minimal-suite" || engine === "bihuo-full-suite";
}
