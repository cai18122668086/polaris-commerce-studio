"""Create verified SuperTokens test users on the STAGING stack only and accept processing consent.

python3 -I setup_users.py --count 60 --out users.json
Talks only to 127.0.0.1 (staging API + staging SuperTokens Core). Reads the staging Core API key from
~/work/loadstg/stg.env (never printed). Writes email/password/workspace for each user.
"""
import argparse, http.cookiejar, json, os, urllib.error, urllib.request, uuid

p = argparse.ArgumentParser()
p.add_argument("--api", default="http://127.0.0.1:3410")
p.add_argument("--core", default="http://127.0.0.1:3417")
p.add_argument("--env", default=os.path.expanduser("~/work/loadstg/stg.env"))
p.add_argument("--count", type=int, default=60)
p.add_argument("--out", default="users.json")
a = p.parse_args()
for u in (a.api, a.core):
    assert u.startswith("http://127.0.0.1:"), "staging only"
KEY = dict(l.strip().split("=", 1) for l in open(a.env) if "=" in l)["STG_ST_API_KEY"]


def call(url, body=None, headers=None, opener=None, method=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, headers=h, method=method or ("POST" if data else "GET"))
    try:
        resp = (opener or urllib.request.build_opener()).open(r, timeout=30)
        return resp.status, {k.lower(): v for k, v in resp.headers.items()}, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{url} -> {e.code} {e.read()[:200]!r}")


users = []
run = uuid.uuid4().hex[:6]
for i in range(a.count):
    email = f"lt-{run}-{i:03d}@loadtest.invalid"
    pw = "Lt-" + uuid.uuid4().hex[:16] + "!a1"
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    ff = {"formFields": [{"id": "email", "value": email}, {"id": "password", "value": pw}]}
    _, _, b = call(a.api + "/api/auth/signup", ff, {"rid": "emailpassword"}, op)
    uid = b["user"]["id"]
    _, _, t = call(a.core + "/recipe/user/email/verify/token", {"userId": uid, "email": email}, {"api-key": KEY})
    call(a.core + "/recipe/user/email/verify", {"method": "token", "token": t["token"]}, {"api-key": KEY})
    _, h, _ = call(a.api + "/api/auth/signin", ff, {"rid": "emailpassword"}, op)
    csrf = {"anti-csrf": h["anti-csrf"]} if "anti-csrf" in h else {}
    _, _, ws = call(a.api + "/api/v1/workspaces", opener=op)
    _, _, c = call(a.api + "/api/v1/me/processing-consent", opener=op)
    call(a.api + "/api/v1/me/processing-consent",
         {"policyVersion": c["policy_version"], "hongKongProcessing": True, "aiTraining": True}, csrf, op)
    users.append({"email": email, "password": pw, "workspace_id": ws[0]["id"]})
json.dump(users, open(a.out, "w"), indent=1)
print(f"created {len(users)} verified users -> {a.out}")
