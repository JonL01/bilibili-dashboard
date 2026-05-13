import http.server
import urllib.request
import urllib.error
import json
import os
import time
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def generate_insights():
    """Generate multi-angle data insights for hot content."""
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
        duration = v.get("duration", 0)
        parsed.append({
            "aid": v.get("aid"),
            "bvid": v.get("bvid", ""),
            "title": v.get("title", ""),
            "author": owner.get("name", ""),
            "author_mid": owner.get("mid", ""),
            "view": stat.get("view", 0),
            "like": stat.get("like", 0),
            "coin": stat.get("coin", 0),
            "favorite": stat.get("favorite", 0),
            "share": stat.get("share", 0),
            "danmaku": stat.get("danmaku", 0),
            "reply": stat.get("reply", 0),
            "pubdate": pubdate,
            "age_hours": round(age_hours, 1),
            "tname": v.get("tname", ""),
            "duration": duration,
            "link": f"https://www.bilibili.com/video/{v.get('bvid', '')}",
        })

    by_like = sorted(parsed, key=lambda x: -x["like"])

    def _topic(title):
        t = title
        for sep in ["【", "(", "（", "[", "{", "！", "?", "？"]:
            if sep in t:
                t = t.split(sep)[0]
        t = t.strip().rstrip("，,、 ")
        if not t:
            t = title[:15]
        if len(t) > 16:
            t = t[:16] + "…"
        return t

    def _fmt(n):
        if n >= 100000000:
            return f"{n/100000000:.1f}亿"
        if n >= 10000:
            return f"{n/10000:.1f}万"
        return str(n)

    def generate_angles(v, like_rate, coin_rate, share_rate, fav_rate, reply_rate, danmaku_rate):
        title = v["title"]
        topic = _topic(title)
        age_hours = v["age_hours"]
        view = v["view"]
        angles = []

        if coin_rate > 10:
            angles.append(
                f"📚 专业分析型 — {topic}：为什么能拿到{coin_rate}%的高投币率？\n"
                f"基于内容的信息密度与实用价值，从用户决策心理的角度，"
                f"拆解观众主动投币推荐的深层动机与内容价值锚点。"
            )

        if like_rate > 8 or share_rate > 0.8:
            anchor = f"{like_rate}%点赞率" if like_rate > 8 else f"{share_rate}%分享率"
            angles.append(
                f"🔥 大众热议型 — {topic}！观众为什么疯狂互动？\n"
                f"聚焦内容触发情感共鸣的关键帧与叙事节奏，"
                f"拆解这些设计为什么能让观众产生强烈互动意愿，"
                f"还原大家对{topic}的真实讨论与情绪投射。"
            )

        if reply_rate > 0.3 or danmaku_rate > 0.3:
            angles.append(
                f"🎬 现场纪实型 — 评论区都在热议！{topic}\n"
                f"汇总评论区里观众的真实反馈与讨论焦点，"
                f"还原大家对{topic}的第一反应与情感连接，"
                f"补充更多普通人的真实视角与经历。"
            )

        if age_hours < 12 and view > 100000:
            angles.append(
                f"⚡ 趋势预判型 — {topic}：新晋爆款潜力分析\n"
                f"基于内容发布{int(age_hours)}小时即获得{_fmt(view)}播放的表现，"
                f"从选题时机与受众匹配度的维度，预判其破圈潜力与持续传播能力。"
            )

        if len(angles) < 3 and (like_rate > 5 or view > 300000):
            angles.append(
                f"📊 数据洞察型 — {topic}：互动数据深度解读\n"
                f"综合分析{_fmt(view)}播放与{like_rate}%点赞率的数据组合，"
                f"解读内容在不同受众群体中的表现差异与传播路径特征。"
            )

        if not angles:
            angles.append(
                f"📌 基础观察型 — {topic}：高热内容特征分析\n"
                f"作为综合热门内容，在选题方向与内容质量上具备参考价值，"
                f"建议关注同类内容的创作模式与受众偏好特征。"
            )

        return angles[:3]

    def get_insight(v):
        vv = max(v["view"], 1)
        like_rate = round(v["like"] / vv * 100, 2)
        coin_rate = round(v["coin"] / max(v["like"], 1) * 100, 2)
        share_rate = round(v["share"] / vv * 100, 2)
        fav_rate = round(v["favorite"] / vv * 100, 2)
        reply_rate = round(v["reply"] / vv * 100, 2)
        danmaku_rate = round(v["danmaku"] / vv * 100, 2)

        engagement_score = round(
            (v["like"] * 1 + v["coin"] * 3 + v["favorite"] * 2 + v["share"] * 2 + v["reply"] * 1.5 + v["danmaku"] * 1)
            / max(v["view"], 1) * 100, 2
        )

        hot_score = round(
            (v["like"] * 0.3 + v["coin"] * 0.5 + v["favorite"] * 0.3 + v["share"] * 0.4 + v["view"] * 0.01) / 100, 1
        )

        tags = []
        if like_rate > 8: tags.append("高点赞率")
        if coin_rate > 20: tags.append("高投币率(强烈推荐)")
        elif coin_rate > 10: tags.append("高投币率")
        if share_rate > 1: tags.append("高传播力")
        if fav_rate > 5: tags.append("高收藏率(干货)")
        if reply_rate > 0.5: tags.append("高讨论度")
        if danmaku_rate > 0.5: tags.append("弹幕活跃")
        if v["age_hours"] < 24 and v["view"] > 300000: tags.append("新晋爆款")
        if v["duration"] < 120: tags.append("短视频")
        elif v["duration"] < 600: tags.append("中视频")
        else: tags.append("长视频")

        angles = generate_angles(v, like_rate, coin_rate, share_rate, fav_rate, reply_rate, danmaku_rate)

        return {
            "hot_score": hot_score,
            "engagement_score": engagement_score,
            "like_rate": like_rate,
            "coin_rate": coin_rate,
            "share_rate": share_rate,
            "fav_rate": fav_rate,
            "reply_rate": reply_rate,
            "danmaku_rate": danmaku_rate,
            "tags": tags,
            "angles": angles,
        }

    hot_insights = []
    for v in by_like[:20]:
        ins = get_insight(v)
        hot_insights.append({
            "aid": v["aid"],
            "bvid": v["bvid"],
            "title": v["title"],
            "author": v["author"],
            "tname": v["tname"],
            "view": v["view"],
            "like": v["like"],
            "coin": v["coin"],
            "favorite": v["favorite"],
            "share": v["share"],
            "duration": v["duration"],
            "age_hours": v["age_hours"],
            "pubdate": v["pubdate"],
            "link": v["link"],
            **ins,
        })

    def fetch_summary(v):
        real = ""
        try:
            data = fetch_bilibili(f"/view?aid={v['aid']}")
            if data.get("code") == 0:
                d = data["data"]
                pages = d.get("pages", [])
                part = pages[0].get("part", "") if pages else ""
                desc = d.get("desc", "").strip()
                raw = (part or desc).strip()
                if raw and raw != v["title"]:
                    real = raw[:200]
        except:
            pass
        if not real:
            real = f"📊 {_fmt(v['view'])}播放 · {_fmt(v['like'])}点赞 · {_fmt(v['coin'])}投币 · {_fmt(v['favorite'])}收藏"
        return (v["aid"], real)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(fetch_summary, v): v for v in hot_insights}
        for fut in as_completed(futs):
            aid, summary = fut.result()
            for v in hot_insights:
                if v["aid"] == aid:
                    v["summary"] = summary[:200]
                    break

    cat_stats = {}
    for v in parsed:
        cat = v["tname"]
        if cat not in cat_stats:
            cat_stats[cat] = {"count": 0, "total_view": 0, "total_like": 0, "total_coin": 0}
        cat_stats[cat]["count"] += 1
        cat_stats[cat]["total_view"] += v["view"]
        cat_stats[cat]["total_like"] += v["like"]
        cat_stats[cat]["total_coin"] += v["coin"]

    cat_insights = []
    for cat, s in sorted(cat_stats.items(), key=lambda x: -x[1]["count"]):
        avg_like_rate = round(s["total_like"] / max(s["total_view"], 1) * 100, 2)
        avg_coin_rate = round(s["total_coin"] / max(s["total_like"], 1) * 100, 2)
        cat_insights.append({
            "name": cat,
            "count": s["count"],
            "total_view": s["total_view"],
            "avg_like_rate": avg_like_rate,
            "avg_coin_rate": avg_coin_rate,
        })

    time_buckets = {"00-06": 0, "06-09": 0, "09-12": 0, "12-14": 0, "14-18": 0, "18-21": 0, "21-24": 0}
    for v in parsed:
        hour = time.localtime(v["pubdate"]).tm_hour
        if hour < 6: time_buckets["00-06"] += 1
        elif hour < 9: time_buckets["06-09"] += 1
        elif hour < 12: time_buckets["09-12"] += 1
        elif hour < 14: time_buckets["12-14"] += 1
        elif hour < 18: time_buckets["14-18"] += 1
        elif hour < 21: time_buckets["18-21"] += 1
        else: time_buckets["21-24"] += 1

    return {
        "fetch_time": int(time.time()),
        "hot_insights": hot_insights,
        "cat_insights": cat_insights,
        "time_distribution": [{"bucket": k, "count": v} for k, v in time_buckets.items()],
        "total_analyzed": len(parsed),
    }


class BilibiliHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/bilibili/"):
            self.handle_api_proxy()
        elif self.path == "/api/analysis":
            self.handle_analysis()
        elif self.path == "/api/insights":
            self.handle_insights()
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
        self.send_json(data)

    def handle_insights(self):
        data = generate_insights()
        self.send_json(data)

    def send_json(self, data):
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
