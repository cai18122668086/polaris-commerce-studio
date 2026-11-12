type AutomaticRun = { signature: string; preparationId?: string };

// Deliberately memory-only: restoring a page cannot authorize a new paid call.
export class EditingAutomaticRun {
  private run?: AutomaticRun;
  start(signature: string): AutomaticRun {
    this.run = { signature };
    return this.run;
  }
  get active(): AutomaticRun | undefined { return this.run; }
  cancel(): void { this.run = undefined; }
  cancelUnless(signature: string): void {
    if (this.run?.signature !== signature) this.cancel();
  }
  prepared(run: AutomaticRun | undefined, id: string): void {
    if (run && this.run === run) run.preparationId = id;
  }
  take(signature: string, preparationId: string): boolean {
    if (this.run?.signature !== signature || this.run?.preparationId !== preparationId) return false;
    this.cancel();
    return true;
  }
}
