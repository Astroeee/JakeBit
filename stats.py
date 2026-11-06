from datetime import date, timedelta
from flask import Blueprint, render_template, request, g
from auth import login_required
from db import get_db
from insights import collect, daily_rates, month_buckets, rates, trend_bars

bp = Blueprint("stats", __name__)


@bp.route("/statistics")
@login_required
def statistics():
    db = get_db()
    today = date.today()
    habits = collect(db, g.user["id"], today)
    rows, overall = rates(habits, today)

    span = request.args.get("range", "week")
    if span not in ("week", "month", "year"):
        span = "week"
    if span == "year":
        points = month_buckets(habits, today)
        bars = trend_bars([p["percent"] for p in points], [p["label"].upper() for p in points], len(points) - 1)
    else:
        days = daily_rates(habits, today - timedelta(days=6 if span == "week" else 29), today)
        if span == "week":
            labels = [d["day"].strftime("%a").upper() for d in days]
        else:                                    # 30 bars: label every fifth day so they stay readable
            labels = [str(d["day"].day) if i % 5 == 0 or i == len(days) - 1 else "" for i, d in enumerate(days)]
        bars = trend_bars([d["percent"] for d in days], labels, len(days) - 1)

    daily = [r for r in rows if not r["weekly"]]
    ranked = sorted(rows, key=lambda r: (-r["rate"], r["name"]))
    return render_template(
        "statistics.html",
        rows=rows, ranked=ranked, span=span, bars=bars,
        has_weekly=any(r["weekly"] for r in rows), overall_rate=overall,
        best_current=max((r["current"] for r in daily), default=0),
        best_longest=max((r["longest"] for r in daily), default=0),
        total_done=sum(r["total"] for r in rows),
    )
