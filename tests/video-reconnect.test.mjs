import assert from "node:assert/strict";
import test from "node:test";
import { reconnectDelay } from "../features/video-studio/reconnect.ts";

test("reconnect backs off 2, 4, 8, 16 s and then waits at most 30 s", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 20].map(reconnectDelay), [2000, 4000, 8000, 16000, 30000, 30000, 30000]);
});
