import assert from "node:assert/strict";

export async function assertTaskNavigation({ cdp, origin, navigate, evaluate, waitForValue }) {
  const a = `rep_${"a".repeat(32)}`;
  const b = `rep_${"b".repeat(32)}`;
  const legacy = "job_legacy_replica";
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.__navigationWrites = [];
    window.__navigationErrors = [];
    addEventListener('error', event => window.__navigationErrors.push(event.error?.stack ?? event.message));
    addEventListener('unhandledrejection', event => window.__navigationErrors.push(String(event.reason)));
    window.__navigationMode = "replica";
    window.__slowReplica = false;
    const beforeNavigationFixture = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = new URL(typeof input === "string" ? input : input.url, location.href);
      if (!url.pathname.startsWith("/api/v1/")) return beforeNavigationFixture(input, init);
      const method = init?.method ?? input?.method ?? "GET";
      if (method !== "GET") { window.__navigationWrites.push(url.pathname); return Response.json({ error: { message: "Navigation must remain read only" } }, { status: 405 }); }
      const job = (id, type = "detail_pack", region = "domestic") => ({
        id, workspace_id: "ws-browser-test", type, display_name: id === "${legacy}" ? "一键复刻 · 旧任务" : id,
        created_at: "2026-11-02T01:00:00Z", updated_at: "2026-11-02T01:00:00Z", status: "failed", stage: "failed", progress: 0,
        expected_item_count: 1, succeeded_item_count: 0, failed_item_count: 1, allowed_actions: [],
        configuration: { settings: { market_region: region, product_name: id, instruction: id }, input: {} },
        items: [], assets: [], plan: null, error_code: null, error_message: null,
        cost: { usage_completeness: "none", actual_credits: 0, estimated_credits: 0 }
      });
      let body;
      if (url.pathname === "/api/v1/workspaces") body = [{ id: "ws-browser-test", name: "Browser test", role: "owner" }];
      else if (url.pathname === "/api/v1/me") body = { id: "browser-test", display_name: "Browser test", email: "browser@example.invalid", email_verified: true, status: "active" };
      else if (url.pathname.endsWith("/processing-consent")) body = { accepted: true };
      else if (url.pathname.endsWith("/credits")) body = { enforcement_enabled: true, balance_credits: 100, available_credits: 100, reserved_credits: 0, pricing: [] };
      else if (url.pathname === "/api/v1/runtime") body = { capabilities: { features: {}, detail_pack: { availability: "available", execution: "provider" } } };
      else if (url.pathname.endsWith("/replica/records")) body = window.__navigationMode === "replica" ? ["${a}", "${b}"].map((id, index) => ({ id, status: "failed", method: index ? "style" : "exact", created_at: "2026-11-02T00:0" + (2-index) + ":00Z", updated_at: "2026-11-02T00:02:00Z", job_ids: [], progress: 0, expected: 1, generated: 0 })) : [];
      else if (url.pathname.endsWith("/jobs")) body = { items: window.__navigationMode === "replica" ? [job("${legacy}", "reference_remix")] : [job("job_detail_a"), job("job_detail_b"), job("job_cross_a", "detail_pack", "international"), job("job_cross_b", "detail_pack", "international")], total: 4, has_more: false, next_cursor: null };
      else if (url.pathname.includes("/replica/documents/") || url.pathname.endsWith("/replica/jobs/${legacy}/session")) {
        const id = url.pathname.endsWith("/session") ? "${b}" : url.pathname.split("/").at(-1);
        if (window.__slowReplica && id === "${a}") await new Promise(resolve => setTimeout(resolve, 700));
        body = { id, kind: "session", status: "failed", created_at: "2026-11-02T00:00:00Z", payload: { replication_method: id === "${a}" ? "exact" : "style", replica_speed: id === "${a}" ? "standard" : "fast", facts: id === "${a}" ? "Task A facts" : "Task B facts", error: id === "${a}" ? "Task A failure" : "Task B failure", product_asset_ids: [], references: [], plans: [], job_ids: [] } };
      }
      else if (/\\/jobs\\/job_(detail|cross)_[ab]$/.test(url.pathname)) body = job(url.pathname.split("/").at(-1), "detail_pack", url.pathname.includes("job_cross") ? "international" : "domestic");
      else if (url.pathname.includes("/announcements")) body = { items: [] };
      else if (url.pathname.endsWith("/product-platforms") || url.pathname.endsWith("/support-cases")) body = [];
      else return Response.json({ error: { message: "Unmocked navigation fixture" } }, { status: 404 });
      return Response.json(body);
    };
  ` });

  const facts = `document.querySelector('textarea[maxlength="20000"]')?.value`;
  const openTask = async href => {
    await evaluate(cdp, `document.querySelector('[aria-label^="打开任务中心"]').click()`);
    const link = `document.querySelector(${JSON.stringify(`#task-drawer a[href="${href}"]`)})`;
    await waitForValue(cdp, `!!${link}`);
    await evaluate(cdp, `${link}.click()`);
    await waitForValue(cdp, `document.querySelector('#task-drawer')?.getAttribute('aria-hidden') === 'true'`);
  };

  await navigate(cdp, `${origin}/style-replica?sessionId=${a}`);
  await waitForValue(cdp, `${facts} === "Task A facts"`);
  await openTask(`/style-replica?sessionId=${b}`);
  await waitForValue(cdp, `${facts} === "Task B facts"`);
  assert.equal(await evaluate(cdp, `document.querySelector('input[name="replication-method"]:checked')?.value`), "style");
  await evaluate(cdp, "history.back()");
  await waitForValue(cdp, `${facts} === "Task A facts"`);
  await evaluate(cdp, "history.forward()");
  await waitForValue(cdp, `${facts} === "Task B facts"`);

  await evaluate(cdp, "window.__slowReplica = true");
  await openTask(`/style-replica?sessionId=${a}`);
  await waitForValue(cdp, `new URL(location.href).searchParams.get('sessionId') === '${a}'`);
  await openTask(`/style-replica?sessionId=${b}`);
  await waitForValue(cdp, `${facts} === "Task B facts"`);
  await new Promise(resolve => setTimeout(resolve, 900));
  assert.equal(await evaluate(cdp, facts), "Task B facts", "the late response for A must not replace B");
  assert.equal(await evaluate(cdp, "new URL(location.href).searchParams.get('sessionId')"), b);

  await evaluate(cdp, `document.querySelector('[aria-label="新建复刻任务"]').click()`);
  await waitForValue(cdp, `location.search === '' && ${facts} === ''`);
  await new Promise(resolve => setTimeout(resolve, 300));
  assert.equal(await evaluate(cdp, `JSON.parse(localStorage.getItem('polaris-replica:ws-browser-test')).sessionId ?? null`), null);
  await openTask(`/style-replica?jobId=${legacy}`);
  await waitForValue(cdp, `${facts} === "Task B facts"`);
  await waitForValue(cdp, `new URL(location.href).searchParams.get('sessionId') === '${b}'`);

  // These workspaces share URL-controlled job selection, including Back to a
  // draft. Verify both domestic and cross-border links through the real drawer.
  await evaluate(cdp, "window.__navigationMode = 'detail'");
  for (const [route, prefix] of [["detail-pack", "detail"], ["crossborder-detail", "cross"]]) {
    await openTask(`/workspace/${route}?jobId=job_${prefix}_a`);
    const input = `document.querySelector('input[placeholder="例如：鎏金焕亮精华液"]')?.value`;
    await waitForValue(cdp, `${input} === 'job_${prefix}_a'`);
    await openTask(`/workspace/${route}?jobId=job_${prefix}_b`);
    await waitForValue(cdp, `${input} === 'job_${prefix}_b'`);
    await evaluate(cdp, "history.back()");
    await waitForValue(cdp, `${input} === 'job_${prefix}_a'`);
  }
  assert.deepEqual(await evaluate(cdp, "window.__navigationWrites"), [], "viewing and switching tasks must not submit generation or retry requests");

  await navigate(cdp, `${origin}/account?jobId=job_support_a#help`);
  const supportJob = `document.querySelector('.support-cases input')?.value`;
  await waitForValue(cdp, `${supportJob} === 'job_support_a'`);
  await evaluate(cdp, `history.pushState(null, '', '/account?jobId=job_support_b#help'); dispatchEvent(new PopStateEvent('popstate'))`);
  await waitForValue(cdp, `${supportJob} === 'job_support_b'`);
  await evaluate(cdp, "history.back()");
  await waitForValue(cdp, `${supportJob} === 'job_support_a'`);
  assert.deepEqual(await evaluate(cdp, "window.__navigationWrites"), [], "support navigation must not create a support case");
}
