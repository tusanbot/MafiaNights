# ratings_manager.py
import json
import os
import statistics
import datetime

RATINGS_FILE = "ratings.json"
COUNTER_FILE = "event_counter.json"

def _ensure_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)

# ساخت فایل‌ها اگر نبودند
_ensure_file(RATINGS_FILE, {})
_ensure_file(COUNTER_FILE, {"last_event": 421})   # شما گفتی قبلا 421 انجام شده

def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class RatingManager:
    """
    مدیریت امتیازدهی:
    - ساخت event جدید (مثلاً event_422)
    - ثبت/تغییر رأی هر voter برای هر target در یک event
    - محدودیت تغییر رأی: حداکثر 3 بار تغییر
    - محاسبه میانگین برای event، ماه، کلی
    """
    def __init__(self):
        self._ratings = _load(RATINGS_FILE)    # ساختار: { "event_422": { "targets": { "<uid>": { "voters": { "<voter>": {"score":int,"changes":int} } } }, "created": "YYYY-MM-DD" } }
        self._counter = _load(COUNTER_FILE)

    # ---------- event helper ----------
    def next_event_id(self):
        # افزایش و نگهداری شمارنده — بازگشتی به صورت "event_422"
        self._counter["last_event"] += 1
        _save(COUNTER_FILE, self._counter)
        return f"event_{self._counter['last_event']}"

    def current_event_id(self):
        # برمی‌گرداند شناسهٔ بعدی که هنوز ایجاد نشده — برای سازگاری caller بهتر است از next_event_id استفاده کنه
        return f"event_{self._counter['last_event']+1}"

    def create_event(self, event_id=None, players=None):
        """
        ایجاد event جدید. اگر event_id داده نشود از next_event_id استفاده می‌کند.
        players: لیست uid بازیکنانِ حاضر (برای ثبت ترتیب در پیام)
        """
        if event_id is None:
            event_id = self.next_event_id()
        if event_id in self._ratings:
            return event_id
        self._ratings[event_id] = {
            "created": datetime.date.today().isoformat(),
            "players": players or [],
            "targets": {}   # هر target uid -> {"voters": { voter_uid: {"score":int,"changes":int} } }
        }
        _save(RATINGS_FILE, self._ratings)
        return event_id

    # ---------- vote API ----------
    def _ensure_target(self, event_id, target_uid):
        ev = self._ratings.setdefault(event_id, {"created": datetime.date.today().isoformat(), "players": [], "targets": {}})
        ev["targets"].setdefault(str(target_uid), {"voters": {}})

    def record_vote(self, event_id, voter_uid, target_uid, score):
        """
        ثبت رأی:
        - اگر voter == target -> خطا (نمیتونه به خودش امتیاز بده)
        - اگر voter خارج از گروه باشد این لایه بررسی نمی‌کند؛ caller باید بررسی کند
        Returns: (ok:bool, reason:str, stats:dict)
        stats contain updated average and counts for the target
        """
        if int(voter_uid) == int(target_uid):
            return False, "cannot_rate_self", None

        score = int(score)
        if score < 1 or score > 5:
            return False, "score_invalid", None

        self._ensure_target(event_id, target_uid)
        voters = self._ratings[event_id]["targets"][str(target_uid)]["voters"]

        voter_str = str(voter_uid)
        if voter_str not in voters:
            # ثبت اولیه
            voters[voter_str] = {"score": score, "changes": 0}
            _save(RATINGS_FILE, self._ratings)
            return True, "recorded", self._compute_target_stats(event_id, target_uid)
        else:
            # تغییر رأی — بررسی محدودیت تغییر (حداکثر 3 بار تغییر)
            current = voters[voter_str]
            if current["changes"] >= 3:
                return False, "changes_exhausted", self._compute_target_stats(event_id, target_uid)
            # اعمال تغییر: افزایش شمارش changes و به‌روزرسانی score
            current["score"] = score
            current["changes"] += 1
            _save(RATINGS_FILE, self._ratings)
            return True, "updated", self._compute_target_stats(event_id, target_uid)

    def _compute_target_stats(self, event_id, target_uid):
        """میانگین و تعداد رأی‌ها برای target در یک event"""
        t = self._ratings.get(event_id, {}).get("targets", {}).get(str(target_uid), {})
        voters = t.get("voters", {})
        scores = [v["score"] for v in voters.values()]
        if not scores:
            return {"average": None, "count": 0}
        avg = sum(scores) / len(scores)
        return {"average": round(avg, 2), "count": len(scores)}

    # ---------- aggregate queries ----------
    def event_summary(self, event_id):
        """خلاصهٔ کامل event — میانگین هر بازیکن"""
        ev = self._ratings.get(event_id)
        if not ev:
            return {}
        out = {}
        for target, data in ev.get("targets", {}).items():
            scores = [v["score"] for v in data.get("voters", {}).values()]
            avg = round(sum(scores) / len(scores), 2) if scores else None
            out[int(target)] = {"average": avg, "count": len(scores)}
        return out

    def monthly_leaderboard(self, year, month, top_n=10):
        """میانگین ماهانه: میانگین تمام eventهایی که در همان ماه ایجاد شده‌اند"""
        totals = {}
        for eid, ev in self._ratings.items():
            created = ev.get("created")
            if not created:
                continue
            y,m,_ = created.split("-")
            if int(y) == year and int(m) == month:
                for target, data in ev.get("targets", {}).items():
                    tid = int(target)
                    scores = [v["score"] for v in data.get("voters", {}).values()]
                    if not scores:
                        continue
                    totals.setdefault(tid, []).append(sum(scores)/len(scores))
        # حالا میانگین هر بازیکن در آن ماه
        avgdict = {tid: round(sum(vals)/len(vals),2) for tid, vals in totals.items()}
        # مرتب و top_n
        sorted_items = sorted(avgdict.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return sorted_items

    def overall_leaderboard(self, top_n=10):
        """میانگین کلی تمام eventها"""
        totals = {}
        counts = {}
        for eid, ev in self._ratings.items():
            for target, data in ev.get("targets", {}).items():
                tid = int(target)
                scores = [v["score"] for v in data.get("voters", {}).values()]
                if not scores:
                    continue
                totals.setdefault(tid, []).extend(scores)
        avgdict = {tid: round(sum(vals)/len(vals),2) for tid, vals in totals.items()}
        sorted_items = sorted(avgdict.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return sorted_items

    # ---------- voter info ----------
    def voter_info(self, event_id, voter_uid, target_uid):
        """اطلاعات اینکه voter برای یک target چه داده و چند بار تغییر کرده"""
        ev = self._ratings.get(event_id, {})
        t = ev.get("targets", {}).get(str(target_uid), {})
        v = t.get("voters", {}).get(str(voter_uid))
        if not v:
            return None
        return v  # {"score": int, "changes": int}

    # ---------- persistence ----------
    def save(self):
        _save(RATINGS_FILE, self._ratings)

# نمونهٔ استفاده:
# rm = RatingManager()
# eid = rm.create_event(players=[1111,2222])
# ok, reason, stats = rm.record_vote(eid, voter_uid=3333, target_uid=1111, score=5)
