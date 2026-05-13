import http.server
import urllib.request
import urllib.error
import json
import os
import time
import sys
from collections import Counter

PORT = int(os.environ.get("PORT", 8080))
BILI_BASE = "https://api.bilibili.com/x/web-interface"

BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
}

def fetch_bilibili(path):
    url = f"{BILI_BASE}{path}"
    req = urllib.request.Request(url, headers=BILI_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"code": -1, "message": str(e), "data": None}

def analyze_popular():
    """Fetch 3 pages (150 videos) and compute analytics."""
    all_videos = []
    now = int(time.time())
    for pn in range(1, 4):
        data = fetch_bilibili(f"/popular?ps=50&pn={pn}")
        items = data.get("data", {}).get("list", []) if data.get("code") == 0 else []
        all_videos.extend(items)
        if data.get("data", {}).get("no_more", True):
            break

    seen = set()
    unique = []
    for v in all_videos:
        aid = v.get("aid")
        if aid not in seen:
            seen.add(aid)
            unique.append(v)

    parsed = []
    for v in unique:
        stat = v.get("stat", {}) or {}
        rcmd = v.get("rcmd_reason", {}) or {}
        owner = v.get("owner", {}) or {}
        pubdate = v.get("pubdate", 0)
        age_hours = (now - pubdate) / 3600 if pubdate else 999
        parsed.append({
            "aid": v.get("aid"),
            "bvid": v.get("bvid", ""),
            "title": v.get("title", ""),
            "author": owner.get("name", ""),
            "author_mid": owner.get("mid", ""),
            "author_face": owner.get("face", ""),
            "pic": v.get("pic", ""),
            "view": stat.get("view", 0),
            "like": stat.get("like", 0),
            "coin": stat.get("coin", 0),
            "favorite": stat.get("favorite", 0),
            "share": stat.get("share", 0),
            "danmaku": stat.get("danmaku", 0),
            "reply": stat.get("reply", 0),
            "pubdate": pubdate,
            "age_hours": round(age_hours, 1),
            "his_rank": stat.get("his_rank", 0),
            "rcmd_reason": rcmd.get("content", "") or "",
            "tname": v.get("tname", ""),
            "link": f"https://www.bilibili.com/video/{v.get('bvid', '')}",
        })

    # 高热 - by likes
    by_like = sorted(parsed, key=lambda x: -x["like"])

    # 飙升 - rcmd_reason contains "飙升"
    soaring_raw = [v for v in parsed if "飙升" in v["rcmd_reason"]]

    # 潜在飙升 - recent + high engagement rate
    recent = [v for v in parsed if v["age_hours"] < 72]
    for v in recent:
        v["engagement_rate"] = round(
            (v["like"] + v["coin"] + v["favorite"] + v["reply"]) / max(v["view"], 1) * 100, 2
        )
    potential_soaring = sorted(recent, key=lambda x: -x.get("engagement_rate", 0))

    # 新热 - <24h
    recent_24h = [v for v in parsed if v["age_hours"] < 24]
    for v in recent_24h:
        v["total_interaction"] = v["like"] + v["coin"] + v["favorite"] + v["reply"] + v["danmaku"]
    new_hot = sorted(recent_24h, key=lambda x: -x["total_interaction"])

    # 分区分布
    cat_counter = Counter(v["tname"] for v in parsed)
    distribution = [{"name": k, "count": v} for k, v in cat_counter.most_common(20)]

    return {
        "total": len(parsed),
        "fetch_time": int(time.time()),
        "fetch_time_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hot": by_like[:30],
        "soaring": soaring_raw[:15],
        "potential_soaring": potential_soaring[:15],
        "new_hot": new_hot[:15],
        "distribution": distribution,
    }


class BilibiliHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/bilibili/"):
            self.handle_api_proxy()
        elif self.path == "/api/analysis":
            self.handle_analysis()
        elif self.path == "/":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def handle_api_proxy(self):
        path = self.path[len("/api/bilibili/"):]
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        target = f"/{path}?{query}" if query else f"/{path}"
        data = fetch_bilibili(target)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def handle_analysis(self):
        data = analyze_popular()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, format, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {args[0]} {args[1]} {args[2]}\n")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = http.server.HTTPServer(("0.0.0.0", PORT), BilibiliHandler)
    print(f"\n  🚀 B站数据看板 → http://localhost:{PORT}")
    print(f"  📊 API 分析接口 → http://localhost:{PORT}/api/analysis\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  👋 服务已停止")
        server.server_close()
