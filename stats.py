from datetime import date, timedelta
from flask import Blueprint, render_template, request, g
from auth import login_required
from db import get_db
from insights import collect, daily_rates, line_chart, month_buckets, rates

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
        values, labels = [p["percent"] for p in points], [p["label"] for p in points]
    else:
        days = daily_rates(habits, today - timedelta(days=6 if span == "week" else 29), today)
        values = [d["percent"] for d in days]
        labels = [d["day"].strftime("%a").upper() if span == "week" else d["day"].strftime("%b %d").replace(" 0", " ")
                  for d in days]

    daily = [r for r in rows if not r["weekly"]]
    ranked = sorted(rows, key=lambda r: (-r["rate"], r["name"]))
    return render_template(
        "statistics.html",
        rows=rows, ranked=ranked, span=span, chart=line_chart(values, labels) if values else None,
        has_weekly=any(r["weekly"] for r in rows), overall_rate=overall,
        best_current=max((r["current"] for r in daily), default=0),
        best_longest=max((r["longest"] for r in daily), default=0),
        total_done=sum(r["total"] for r in rows),
    )
