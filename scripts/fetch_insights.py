"""Fetch @tenman_honten account and per-post metrics from the Graph API (read only).

Writes data/latest.json, data/history/<date>.json and appends data/followers.csv.
The access token comes from the META_TOKEN environment variable and is never written out.
"""
import csv, datetime, json, os, urllib.error, urllib.parse, urllib.request

V = "v21.0"
IG = "17841453767359170"
TOK = os.environ["META_TOKEN"]
JST = datetime.timezone(datetime.timedelta(hours=9))


def get(path, **params):
    params["access_token"] = TOK
    url = f"https://graph.facebook.com/{V}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
            return {"error": body.get("error", {}).get("message", str(e.code))}
        except Exception:
            return {"error": f"http {e.code}"}


def media_metrics(m):
    out = {}
    names = ["reach", "saved", "shares", "total_interactions", "views", "follows", "profile_visits"]
    for name in names:
        r = get(f"{m['id']}/insights", metric=name)
        if "data" in r and r["data"]:
            vals = r["data"][0].get("values") or [{}]
            out[name] = vals[0].get("value", r["data"][0].get("total_value", {}).get("value"))
    return out


now = datetime.datetime.now(JST)
acct = get(IG, fields="username,followers_count,follows_count,media_count")
media = get(f"{IG}/media", fields="id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count", limit=30)
posts = []
for m in media.get("data", []):
    m["metrics"] = media_metrics(m)
    m["caption_head"] = (m.pop("caption", "") or "").split("\n")[0][:60]
    posts.append(m)

since = int((now - datetime.timedelta(days=28)).timestamp())
until = int(now.timestamp())
daily = {}
for metric in ["follower_count", "reach"]:
    r = get(f"{IG}/insights", metric=metric, period="day", since=since, until=until)
    if "data" in r and r["data"]:
        daily[metric] = [{"date": v["end_time"][:10], "value": v["value"]} for v in r["data"][0].get("values", [])]
    else:
        daily[metric] = r

snap = {"fetched_at": now.isoformat(timespec="minutes"), "account": acct, "daily": daily, "posts": posts}
s = json.dumps(snap, ensure_ascii=False, indent=1)
assert TOK not in s
os.makedirs("data/history", exist_ok=True)
open("data/latest.json", "w").write(s)
open(f"data/history/{now:%Y-%m-%d}.json", "w").write(s)
new = not os.path.exists("data/followers.csv")
with open("data/followers.csv", "a", newline="") as f:
    w = csv.writer(f)
    if new:
        w.writerow(["date", "followers", "media_count"])
    w.writerow([f"{now:%Y-%m-%d %H:%M}", acct.get("followers_count"), acct.get("media_count")])
print(f"ok: {len(posts)} posts, followers={acct.get('followers_count')}")
