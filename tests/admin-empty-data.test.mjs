import test from "node:test";
import assert from "node:assert/strict";
import { canManage, normalizeAdminOverview, normalizeCommerceAccess, normalizeCommerceOverview, normalizeList, normalizeLogDetail } from "../features/admin/api/normalize.ts";

test("后台列表接口返回空对象或 null 时，补成空列表", () => {
  for (const payload of [{}, null, undefined, { items: null }, "oops"]) {
    const list = normalizeList(payload);
    assert.deepEqual(list.items, []);
    assert.deepEqual(list.pagination, { total: 0, limit: 0, offset: 0, has_more: false });
  }
});

test("后台列表接口的真实数据原样保留", () => {
  const payload = { items: [{ id: "u1" }], pagination: { total: 31, limit: 20, offset: 20, has_more: true }, can_manage: true };
  assert.deepEqual(normalizeList(payload), payload);
});

test("工作台概览缺字段时数字补 0，抓取会话补空对象", () => {
  const overview = normalizeAdminOverview({ users: { total: 3 } });
  assert.deepEqual(overview.users, { total: 3, active: 0, disabled: 0, recent_signups: 0 });
  assert.equal(overview.usage.jobs_failed + overview.usage.crawl_tasks_failed, 0);
  assert.deepEqual(Object.entries(overview.crawler_sessions), []);
  assert.equal(overview.generated_at, null);
});

test("任务详情、客户运营概览与权限缺字段时可安全渲染", () => {
  const detail = normalizeLogDetail({ id: "job_1" });
  for (const key of ["events", "items", "assets", "input_assets", "output_assets", "intermediate_assets"]) assert.deepEqual(detail[key], []);
  assert.deepEqual(normalizeCommerceOverview({}), { customers: 0, paid_fen: 0, refunded_fen: 0, pending_refunds: 0, open_cases: 0 });
  assert.deepEqual(normalizeCommerceAccess({}).permissions, []);
  assert.equal(canManage({}), false);
  assert.equal(canManage({ can_manage: "yes" }), false);
  assert.equal(canManage({ can_manage: true }), true);
});
