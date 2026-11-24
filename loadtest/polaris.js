// 极光商绘 staging 压测脚本（k6）。只允许打 127.0.0.1 上的 staging 栈，见 README。
// 环境变量：USERS=users.json DATA=图片目录 API=http://127.0.0.1:3410 VAPI=http://127.0.0.1:3411
//          STAGES=full|p10|p25|p50|smoke|debug  POLL_LIMIT=150（单个任务最多轮询秒数）
import http from 'k6/http';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { Trend, Counter } from 'k6/metrics';

const API = __ENV.API || 'http://127.0.0.1:3410';
const VAPI = __ENV.VAPI || 'http://127.0.0.1:3411';
if (!/^http:\/\/127\.0\.0\.1:/.test(API) || !/^http:\/\/127\.0\.0\.1:/.test(VAPI)) throw new Error('staging only');
const users = new SharedArray('users', () => JSON.parse(open(__ENV.USERS)));
const PRODUCT = new Uint8Array(open(__ENV.DATA + '/product.png', 'b'));
const REFERENCE = new Uint8Array(open(__ENV.DATA + '/reference.png', 'b'));
const POLL_LIMIT = Number(__ENV.POLL_LIMIT || 150);

const jobSeconds = new Trend('job_e2e_seconds', false);
const jobOutcome = new Counter('job_outcome');

const full = [
  { duration: '30s', target: 10 }, { duration: '5m', target: 10 },
  { duration: '30s', target: 25 }, { duration: '5m', target: 25 },
  { duration: '30s', target: 50 }, { duration: '5m', target: 50 },
  { duration: '30s', target: 0 },
];
const hold = n => [{ duration: '30s', target: n }, { duration: '5m', target: n }, { duration: '15s', target: 0 }];
const smoke = [{ duration: '20s', target: 3 }, { duration: '1m', target: 3 }, { duration: '10s', target: 0 }];
export const options = {
  scenarios: __ENV.STAGES === 'debug'
    ? { debug: { executor: 'per-vu-iterations', vus: Number(__ENV.DVUS || 2), iterations: Number(__ENV.DITERS || 6), maxDuration: '6m' } }
    : { mixed: { executor: 'ramping-vus', startVUs: 0, stages: __ENV.STAGES === 'smoke' ? smoke : /^p\d+$/.test(__ENV.STAGES || '') ? hold(Number(__ENV.STAGES.slice(1))) : full, gracefulRampDown: '20s', gracefulStop: '30s' } },
  noCookiesReset: true, // 会话 cookie 跨迭代保留（像真实浏览器一样只登录一次）
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max', 'count'],
  // 403 CREDIT_PILOT_REQUIRED 是正式站当前配置下的预期结果，不计入失败
  thresholds: { 'http_req_duration{gen:no}': ['p(95)<2000'] },
};

let st = null; // 每个 VU 自己的登录状态（cookie 由 k6 per-VU jar 保存）
const OK = http.expectedStatuses({ min: 200, max: 299 });

function hdr(extra) { return Object.assign({ 'Content-Type': 'application/json', 'anti-csrf': st ? st.csrf : '' }, extra || {}); }
function uuid() { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16); }); }
function idem() { return hdr({ 'Idempotency-Key': uuid() }); }
function get(base, path, name, gen) { return dbg(http.get(base + path, { headers: hdr(), tags: { name, gen: gen ? 'yes' : 'no' } })); }
function send(method, base, path, body, name, headers, gen, expected) {
  return dbg(http.request(method, base + path, body === null ? null : JSON.stringify(body),
    { headers: headers || hdr(), tags: { name, gen: gen ? 'yes' : 'no' }, responseCallback: expected || OK }));
}
function json(r) { try { return r.json(); } catch (e) { return null; } }
function dbg(r) { if (__ENV.DEBUG === "2" || (__ENV.DEBUG && (r.status < 200 || r.status >= 300))) console.warn(`VU${__VU} it${__ITER} ${r.status} ${r.request.method} ${r.url} ${String(r.body).slice(0, 160)}`); return r; }
function think(a, b) { sleep(a + Math.random() * (b - a)); }

function login() {
  const u = users[(__VU - 1) % users.length];
  const body = { formFields: [{ id: 'email', value: u.email }, { id: 'password', value: u.password }] };
  const r = http.post(API + '/api/auth/signin', JSON.stringify(body),
    { headers: { 'Content-Type': 'application/json', rid: 'emailpassword' }, tags: { name: 'POST /auth/signin', gen: 'no' } });
  check(r, { 'signin 200': x => x.status === 200 });
  if (r.status !== 200) { sleep(2); return false; }
  st = { csrf: r.headers['Anti-Csrf'] || r.headers['anti-csrf'] || '', ws: u.workspace_id };
  get(API, '/api/v1/me', 'GET /me');
  return true;
}

function register() {
  const jar = new http.CookieJar();
  const email = `lt-reg-${uuid().slice(0, 12)}@loadtest.invalid`;
  const body = { formFields: [{ id: 'email', value: email }, { id: 'password', value: 'Lt-' + uuid().slice(0, 16) + '!a1' }] };
  const r = http.post(API + '/api/auth/signup', JSON.stringify(body),
    { jar, headers: { 'Content-Type': 'application/json', rid: 'emailpassword' }, tags: { name: 'POST /auth/signup', gen: 'no' } });
  check(r, { 'signup 200': x => x.status === 200 });
}

function upload(src) {
  const buf = new Uint8Array(src.length + 16);
  buf.set(src); for (let i = 0; i < 16; i++) buf[src.length + i] = Math.random() * 256 | 0; // 让每次上传内容唯一
  const r = http.post(`${API}/api/v1/workspaces/${st.ws}/assets`,
    { file: http.file(buf.buffer, 'product.png', 'image/png'), origin_kind: 'upload', media_kind: 'image' },
    { headers: { 'anti-csrf': st.csrf, 'Idempotency-Key': uuid() }, tags: { name: 'POST /assets (upload)', gen: 'no' } });
  dbg(r); check(r, { 'upload 201': x => x.status === 201 });
  const j = json(r); return j && j.id;
}

function pollJob(path, name, done, every, limit) {
  const t0 = Date.now(); let j = null;
  while ((Date.now() - t0) / 1000 < limit) {
    sleep(every);
    j = json(get(API, path, name));
    if (j && done(j.status)) break;
  }
  return { j, secs: (Date.now() - t0) / 1000 };
}
const TERMINAL = s => ['completed', 'failed', 'partial', 'cancelled'].indexOf(s) >= 0;
function outcome(kind, res) {
  const s = (res.j && res.j.status) || 'none';
  const tag = TERMINAL(s) ? s : 'not_finished';
  jobOutcome.add(1, { kind, result: tag });
  if (TERMINAL(s)) jobSeconds.add(res.secs, { kind });
}

function browse() {
  const B = `/api/v1/workspaces/${st.ws}`;
  get(API, '/api/v1/runtime', 'GET /runtime');
  get(API, '/api/v1/announcements/current', 'GET /announcements/current');
  get(API, '/api/v1/workspaces', 'GET /workspaces');
  get(API, B + '/creation-summary', 'GET /creation-summary');
  think(0.5, 1.5);
  const jobs = json(get(API, B + '/jobs?limit=20', 'GET /jobs'));
  get(API, B + '/assets?limit=24', 'GET /assets');
  get(API, '/api/v1/inspiration/cases', 'GET /inspiration/cases');
  if (jobs && jobs.items && jobs.items.length) {
    const id = jobs.items[Math.floor(Math.random() * jobs.items.length)].id;
    get(API, `${B}/jobs/${id}`, 'GET /jobs/{id}');
  }
  get(API, B + '/credits', 'GET /credits');
}

function imageJob() {
  const B = `/api/v1/workspaces/${st.ws}`;
  const a = upload(PRODUCT); if (!a) return;
  const types = ['white_background', 'scene_main', 'change_background'];
  const body = { type: 'product_image', intent: 'submit', display_name: 'lt-image', input: { product_asset_ids: [a] },
    configuration: { task_type: types[Math.floor(Math.random() * types.length)], image_count: 1 } };
  const r = send('POST', API, B + '/jobs', body, 'POST /jobs (image)', idem(), true);
  const j = json(r); if (r.status !== 202 || !j) return;
  outcome('image', pollJob(`${B}/jobs/${j.id}`, 'GET /jobs/{id}', TERMINAL, 3, POLL_LIMIT));
}

function detailJob() {
  const B = `/api/v1/workspaces/${st.ws}`;
  const a = upload(PRODUCT); if (!a) return;
  const body = { type: 'detail_pack', intent: 'submit', display_name: 'lt-detail', input: { product_groups: [{ group_key: 'primary', asset_ids: [a] }] },
    configuration: { detail_skill: 'refined', product_name: '压测商品', selling_points: ['压测卖点'], platform_code: 'tmall', market_region: 'domestic', page_count: 3, auto_start_after_plan: false } };
  const r = send('POST', API, B + '/jobs', body, 'POST /jobs (detail)', idem(), true);
  const j = json(r); if (r.status !== 202 || !j) return;
  const planned = pollJob(`${B}/jobs/${j.id}`, 'GET /jobs/{id}', s => s !== 'queued' && s !== 'planning' && s !== 'draft', 3, 90);
  const p = planned.j;
  if (!p || p.status !== 'awaiting_confirmation' || !p.plan) { outcome('detail_plan', planned); return; }
  jobSeconds.add(planned.secs, { kind: 'detail_plan' }); jobOutcome.add(1, { kind: 'detail_plan', result: 'planned' });
  think(2, 5);
  const c = send('POST', API, `${B}/jobs/${j.id}/plan/confirm`, { expected_revision: p.plan.revision, approval_text: '我已审阅完整方案，确认按此生成。',
    approval_document_sha256: p.plan.payload.refined_approval.document_sha256 }, 'POST /jobs/{id}/plan/confirm', idem(), true);
  if (c.status !== 202) return;
  outcome('detail', pollJob(`${B}/jobs/${j.id}`, 'GET /jobs/{id}', TERMINAL, 4, POLL_LIMIT));
}

function replicaJob() {
  const B = `/api/v1/workspaces/${st.ws}`;
  const a = upload(PRODUCT); const b = upload(REFERENCE); if (!a || !b) return;
  const r = send('POST', API, B + '/replica/sessions', { request_id: uuid(), product_asset_ids: [a], references: [{ asset_id: b, title: '主图', aspect_ratio: '1:1' }], facts: '压测品牌' },
    'POST /replica/sessions', null, true);
  const d = json(r); if (r.status !== 202 || !d) return;
  const an = pollJob(`${B}/replica/documents/${d.id}`, 'GET /replica/documents/{id}', s => s !== 'analysing', 3, 60);
  if (!an.j || an.j.status !== 'awaiting_confirmation') { outcome('replica_plan', an); return; }
  jobSeconds.add(an.secs, { kind: 'replica_plan' });
  const c = send('POST', API, `${B}/replica/sessions/${d.id}/confirm`, { plan_hash: an.j.payload.plan_hash, instructions: [] }, 'POST /replica/sessions/{id}/confirm', null, true);
  const cj = json(c); if (c.status !== 202 || !cj) return;
  const jid = cj.payload.job_ids[0];
  outcome('replica', pollJob(`${B}/jobs/${jid}`, 'GET /jobs/{id}', TERMINAL, 3, POLL_LIMIT));
}

function videoJob() {
  const VB = `/api/v1/video-studio/workspaces/${st.ws}`;
  get(VAPI, '/api/v1/video-studio/access', 'GET /video-studio/access');
  get(VAPI, VB + '/projects', 'GET /video/projects');
  get(VAPI, VB + '/avatars', 'GET /video/avatars');
  get(VAPI, VB + '/voices', 'GET /video/voices');
  get(VAPI, VB + '/credit-prices', 'GET /video/credit-prices');
  think(1, 3);
  const pid = uuid();
  const content = { draft: { name: '压测口播', text: '这是一段压测口播文案，用来验证视频任务提交与状态轮询。', avatarId: 'qy-model-9001', voiceId: 'qy-voice-lt-voice-1',
    speed: 1, emotion: '自然', language: 'auto', quality: '1080P', drive: 'text' }, product_facts: '', references: [], media: [] };
  const pr = send('PUT', VAPI, `${VB}/projects/${pid}`, { content, expected_revision: 0, request_id: uuid(), action: 'save' }, 'PUT /video/projects/{id}');
  const pj = json(pr); if (pr.status !== 200 || !pj) return;
  const rid = uuid();
  const s = send('POST', VAPI, VB + '/generation-tasks', { request_id: rid, kind: 'lipsync', avatar_id: 'qy-model-9001', project_id: pid, expected_revision: pj.project.revision },
    'POST /video/generation-tasks', null, true);
  if (s.status !== 200 && s.status !== 202) return;
  const t0 = Date.now(); let last = null;
  while ((Date.now() - t0) / 1000 < 75) {
    sleep(5);
    const g = json(get(VAPI, `${VB}/generation-requests/${rid}`, 'GET /video/generation-requests/{id}'));
    last = g && g.job && g.job.status;
    if (last && ['completed', 'failed', 'cancelled', 'awaiting_review'].indexOf(last) >= 0) break;
  }
  jobOutcome.add(1, { kind: 'video', result: last || 'none' });
  get(VAPI, VB + '/tasks', 'GET /video/tasks');
}

function credits() {
  const B = `/api/v1/workspaces/${st.ws}`;
  get(API, B + '/credits', 'GET /credits');
  get(API, B + '/credits/packages', 'GET /credits/packages');
  get(API, B + '/credits/membership', 'GET /credits/membership');
  get(API, B + '/credits/ledger', 'GET /credits/ledger');
  const quote = { type: 'product_image', intent: 'submit', input: { product_asset_ids: ['asset_quote_only'] }, configuration: { task_type: 'white_background', image_count: 1 } };
  send('POST', API, B + '/credits/quote', quote, 'POST /credits/quote', null, false, http.expectedStatuses({ min: 200, max: 299 }, 404, 422));
  // 下单意向：正式站当前未开积分充值试点，预期 403 CREDIT_PILOT_REQUIRED，不发生任何支付
  send('POST', API, B + '/credits/purchases', { package_id: 'starter' }, 'POST /credits/purchases', idem(), false, http.expectedStatuses({ min: 200, max: 299 }, 403, 422));
}

export default function () {
  if (!st && !login()) return;
  const x = Math.random() * 100;
  if (x < 3) register();
  else if (x < 43) browse();
  else if (x < 63) imageJob();
  else if (x < 73) detailJob();
  else if (x < 83) replicaJob();
  else if (x < 93) videoJob();
  else credits();
  think(1, 3);
}

export function handleSummary(data) {
  return { [(__ENV.OUT || '.') + '/summary.json']: JSON.stringify(data, null, 1) };
}
