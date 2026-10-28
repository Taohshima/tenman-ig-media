"""Publish queued posts to Instagram (@tenman_honten) and the Facebook page.

Each queue/<YYYY-MM-DD>/post.json looks like:
  {"publish_at": "2026-11-02T19:00:00+09:00", "caption": "...", "media": [{"type": "IMAGE"|"VIDEO", "url": "https://..."}],
   "approved_by": "...", "dry_run": false, "facebook": true}
A post is handled once publish_at has passed and queue/<date>/result.json does not exist yet.
dry_run=true creates the Instagram container(s) and checks they are ready, but publishes nothing.
"""
import datetime, glob, json, os, time, urllib.error, urllib.parse, urllib.request

V = "v21.0"
IG = "17841453767359170"
PAGE = "105225182223732"
TOK = os.environ["META_TOKEN"]
NOW = datetime.datetime.now(datetime.timezone.utc)


def call(method, path, **params):
    params.setdefault("access_token", TOK)
    data = urllib.parse.urlencode(params).encode()
    url = f"https://graph.facebook.com/{V}/{path}"
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}")
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", {})
            return {"error": msg.get("message", str(e.code)), "code": msg.get("code")}
        except Exception:
            return {"error": f"http {e.code}"}


def wait_ready(cid, limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        st = call("GET", cid, fields="status_code,status")
        code = st.get("status_code")
        if code == "FINISHED":
            return True, st
        if code in ("ERROR", "EXPIRED"):
            return False, st
        time.sleep(10)
    return False, {"error": "timeout"}


def container(item, caption=None, child=False):
    p = {}
    if item["type"] == "VIDEO":
        p["media_type"] = "REELS" if not child else "VIDEO"
        p["video_url"] = item["url"]
    else:
        p["image_url"] = item["url"]
    if child:
        p["is_carousel_item"] = "true"
    if caption is not None:
        p["caption"] = caption
    return call("POST", f"{IG}/media", **p)


def instagram(post):
    media, cap = post["media"], post["caption"]
    if len(media) == 1:
        c = container(media[0], cap)
        if "id" not in c:
            return {"ok": False, "step": "container", **c}
        ok, st = wait_ready(c["id"])
        if not ok:
            return {"ok": False, "step": "processing", **st}
        root = c["id"]
    else:
        kids = []
        for m in media:
            c = container(m, child=True)
            if "id" not in c:
                return {"ok": False, "step": "child", **c}
            ok, st = wait_ready(c["id"])
            if not ok:
                return {"ok": False, "step": "child-processing", **st}
            kids.append(c["id"])
        c = call("POST", f"{IG}/media", media_type="CAROUSEL", children=",".join(kids), caption=cap)
        if "id" not in c:
            return {"ok": False, "step": "carousel", **c}
        ok, st = wait_ready(c["id"])
        if not ok:
            return {"ok": False, "step": "carousel-processing", **st}
        root = c["id"]
    if post.get("dry_run"):
        return {"ok": True, "dry_run": True, "container": root}
    pub = call("POST", f"{IG}/media_publish", creation_id=root)
    if "id" not in pub:
        return {"ok": False, "step": "publish", **pub}
    info = call("GET", pub["id"], fields="permalink,timestamp")
    return {"ok": True, "media_id": pub["id"], "permalink": info.get("permalink")}


def facebook(post):
    if post.get("dry_run") or not post.get("facebook", True):
        return {"skipped": True}
    pt = call("GET", PAGE, fields="access_token").get("access_token")
    if not pt:
        return {"ok": False, "error": "no page token"}
    media, cap = post["media"], post["caption"]
    if len(media) == 1 and media[0]["type"] == "VIDEO":
        r = call("POST", f"{PAGE}/videos", file_url=media[0]["url"], description=cap, access_token=pt)
    elif len(media) == 1:
        r = call("POST", f"{PAGE}/photos", url=media[0]["url"], message=cap, access_token=pt)
    else:
        ids = []
        for m in media:
            if m["type"] != "IMAGE":
                continue
            u = call("POST", f"{PAGE}/photos", url=m["url"], published="false", access_token=pt)
            if "id" in u:
                ids.append({"media_fbid": u["id"]})
        r = call("POST", f"{PAGE}/feed", message=cap, attached_media=json.dumps(ids), access_token=pt)
    return {"ok": "id" in r or "post_id" in r, **r}


handled = 0
for path in sorted(glob.glob("queue/*/post.json")):
    d = os.path.dirname(path)
    if os.path.exists(f"{d}/result.json"):
        continue
    post = json.load(open(path))
    due = datetime.datetime.fromisoformat(post["publish_at"])
    if due > NOW:
        continue
    res = {"handled_at": NOW.isoformat(timespec="seconds"), "instagram": instagram(post)}
    res["facebook"] = facebook(post) if res["instagram"].get("ok") else {"skipped": "instagram failed"}
    s = json.dumps(res, ensure_ascii=False, indent=1)
    assert TOK not in s
    open(f"{d}/result.json", "w").write(s)
    print(d, s)
    handled += 1
print(f"handled {handled}")
