import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/project-session.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { VideoProjectSession } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

function fixture() {
  const data = new Map();
  const storage = { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) };
  const rows = new Map();
  const replays = new Map();
  const calls = [];
  let beforeWrite;
  const api = {
    projects: async () => [...rows.values()],
    project: async id => { if (!rows.has(id)) throw { status: 404 }; return rows.get(id); },
    versions: async () => [], tasks: async () => [],
    write: async (id, body) => {
      calls.push(structuredClone(body));
      if (replays.has(body.request_id)) return replays.get(body.request_id);
      await beforeWrite?.(body);
      const current = rows.get(id);
      if ((current?.revision ?? 0) !== body.expected_revision) throw { status: 409 };
      const project = { id, revision: body.expected_revision + 1, content: structuredClone(body.content), updated_at: "2026-11-04", created_at: "2026-11-04" };
      rows.set(id, project);
      const result = { project, ...(body.restore_version_id ? {
        version: { id: crypto.randomUUID(), project_id: id, kind: "draft", snapshot: project.content },
      } : {}) };
      replays.set(body.request_id, result);
      return result;
    },
    importLegacy: async () => { throw new Error("not used"); },
  };
  const session = new VideoProjectSession(api, storage, "recovery:verified-user:workspace-A");
  return { session, rows, calls, data, storage, api, setWrite: callback => { beforeWrite = callback; } };
}

function edit(session, text) { session.edit({ ...session.state.content, draft: { ...session.state.content.draft, text } }); }

test("editing during a slow save never replaces newer text, and both revisions persist serially", async () => {
  const f = fixture();
  await f.session.initialize();
  const gate = deferred();
  f.setWrite(() => gate.promise);
  edit(f.session, "first edit");
  const saving = f.session.save();
  await new Promise(resolve => setTimeout(resolve, 0));
  edit(f.session, "newer edit during request");
  gate.resolve();
  await saving;
  assert.equal(f.session.state.content.draft.text, "newer edit during request");
  await f.session.save();
  assert.equal(f.rows.get(f.session.state.projectId).content.draft.text, "newer edit during request");
  assert.equal(f.session.state.revision, 2);
  assert.equal(f.data.size, 0);
  f.session.dispose();
});

test("an unknown demo submission retries its exact key and does not duplicate the action", async () => {
  const f = fixture();
  await f.session.initialize();
  edit(f.session, "confirmed");
  let fail = true;
  f.setWrite(() => { if (fail) { fail = false; throw new Error("response lost"); } });
  await assert.rejects(f.session.save("demo"));
  const first = f.calls[0];
  assert.equal(f.session.state.status, "error");
  assert.ok(f.data.has(f.session.recoveryKey));
  await f.session.save("demo");
  assert.equal(f.calls.length, 2);
  assert.deepEqual(f.calls[1], first);
  assert.equal(f.session.state.revision, 1);
  f.session.dispose();
});

test("double-click confirmation shares one submission", async () => {
  const f = fixture();
  await f.session.initialize();
  edit(f.session, "confirmed");
  await Promise.all([f.session.save("demo"), f.session.save("demo")]);
  assert.equal(f.calls.length, 1);
  f.session.dispose();
});

test("restoring a version saves pending edits and replays the same restore on an unknown result", async () => {
  const f = fixture();
  await f.session.initialize();
  edit(f.session, "historical script");
  await f.session.save();
  const version = {
    id: crypto.randomUUID(), project_id: f.session.state.projectId, kind: "confirmed",
    snapshot: structuredClone(f.session.state.content),
  };
  edit(f.session, "current unsaved draft");
  f.setWrite(body => {
    if (body.restore_version_id) throw new Error("restore response lost");
  });
  const restoring = f.session.restoreVersion(version);
  assert.equal(f.session.restoreVersion(version), restoring);
  await assert.rejects(restoring);
  assert.equal(f.calls[1].content.draft.text, "current unsaved draft");
  const request = f.calls[2];
  assert.equal(request.restore_version_id, version.id);
  assert.equal(request.expected_revision, 2);
  assert.deepEqual(JSON.parse(f.data.get(f.session.recoveryKey)).pending, request);
  assert.equal(f.session.state.content.draft.text, "historical script");
  f.setWrite(undefined);
  await f.session.restoreVersion(version);
  assert.deepEqual(f.calls.slice(2), [request, request]);
  assert.equal(f.session.state.revision, 3);
  assert.equal(f.rows.get(version.project_id).content.draft.text, "historical script");
  assert.equal(f.session.state.history[0].kind, "draft");
  assert.equal(f.session.state.history[0].snapshot.draft.text, "historical script");
  assert.equal(f.data.size, 0);
  f.session.dispose();
});

test("a stale device preserves its local text and can save a separate project", async () => {
  const f = fixture();
  await f.session.initialize();
  edit(f.session, "base");
  await f.session.save();
  const oldId = f.session.state.projectId;
  f.rows.set(oldId, { ...f.rows.get(oldId), revision: 2, content: { ...f.session.state.content, draft: { ...f.session.state.content.draft, text: "other device" } } });
  edit(f.session, "this device");
  await assert.rejects(f.session.save());
  assert.equal(f.session.state.status, "conflict");
  assert.equal(f.rows.get(oldId).content.draft.text, "other device");
  await f.session.saveAsNew();
  assert.notEqual(f.session.state.projectId, oldId);
  assert.equal(f.rows.get(f.session.state.projectId).content.draft.text, "this device");
  f.session.dispose();
});

test("reload offers explicit scoped recovery and never silently replaces server data", async () => {
  const f = fixture();
  await f.session.initialize();
  edit(f.session, "unsaved local edit");
  f.session.dispose();
  const reopened = new VideoProjectSession(f.api, f.storage, f.session.recoveryKey);
  await reopened.initialize();
  assert.equal(reopened.state.content.draft.text, "");
  assert.equal(reopened.state.recovery.content.draft.text, "unsaved local edit");
  assert.equal(f.rows.size, 0);
  reopened.restoreRecovery();
  await reopened.save();
  assert.equal(reopened.state.content.draft.text, "unsaved local edit");
  const otherUser = new VideoProjectSession(f.api, f.storage, "recovery:other-user:workspace-A");
  await otherUser.initialize();
  assert.equal(otherUser.state.recovery, undefined);
  reopened.dispose(); otherUser.dispose();
});

test("revoking an editor during a slow request never starts a follow-up write or removes recovery", async () => {
  const f = fixture();
  await f.session.initialize();
  const gate = deferred();
  f.setWrite(() => gate.promise);
  edit(f.session, "first edit");
  const saving = f.session.save();
  await new Promise(resolve => setTimeout(resolve, 0));
  edit(f.session, "new edit before signout");
  f.session.dispose();
  gate.resolve();
  await saving;
  assert.equal(f.calls.length, 1);
  assert.equal(JSON.parse(f.data.get(f.session.recoveryKey)).content.draft.text, "new edit before signout");
});

test("cloud saving works when browser storage is unavailable", async () => {
  const f = fixture();
  const denied = { getItem() { throw new Error("storage denied"); }, setItem() { throw new Error("storage denied"); }, removeItem() { throw new Error("storage denied"); } };
  const session = new VideoProjectSession(f.api, denied, "unavailable");
  await session.initialize();
  assert.equal(session.state.status, "saved");
  edit(session, "server remains authoritative");
  await session.save();
  assert.equal(session.state.status, "saved");
  assert.equal(f.rows.get(session.state.projectId).content.draft.text, "server remains authoritative");
  session.dispose();
});
