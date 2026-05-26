"""
Servicio de análisis avanzado para mantenimiento.

Outliers IQR, K-means puro, histogramas y tendencias temporales.
No depende de scikit-learn, pandas ni numpy.
"""
import logging
import math
import random
from datetime import date, datetime, timedelta

from sqlalchemy import func, case
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

RESOLVED_STATUSES = ("RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED")

VALID_METRICS = {"time_invested", "rating_attention", "rating_speed"}


def _dt_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0)


def _dt_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_metric_col(metric: str):
    """Devuelve la columna SQLAlchemy del modelo MaintTicket para el metric dado."""
    from itcj2.apps.maint.models.ticket import MaintTicket

    mapping = {
        "time_invested": MaintTicket.time_invested_minutes,
        "rating_attention": MaintTicket.rating_attention,
        "rating_speed": MaintTicket.rating_speed,
    }
    col = mapping.get(metric)
    if col is None:
        raise ValueError(f"Métrica inválida: {metric}. Válidas: {sorted(VALID_METRICS)}")
    return col


def _load_resolved_tickets(
    db: Session,
    from_date: date,
    to_date: date,
    metric_col,
    category_id: int | None = None,
):
    """Carga id, ticket_number y valor de la métrica para tickets resueltos."""
    from itcj2.apps.maint.models.ticket import MaintTicket

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    filters = [
        MaintTicket.status.in_(RESOLVED_STATUSES),
        MaintTicket.resolved_at >= dt_start,
        MaintTicket.resolved_at <= dt_end,
        metric_col.isnot(None),
    ]
    if category_id:
        filters.append(MaintTicket.category_id == category_id)

    return (
        db.query(MaintTicket.id, MaintTicket.ticket_number, metric_col)
        .filter(*filters)
        .all()
    )


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Percentil p (0-100) sobre lista ordenada, interpolación lineal."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return float(sorted_vals[-1])
    frac = idx - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


# ─────────────────────────────────────────────────────────────────────────────
# Outliers (IQR)
# ─────────────────────────────────────────────────────────────────────────────

def get_outliers(
    db: Session,
    from_date: date,
    to_date: date,
    metric: str = "time_invested",
    category_id: int | None = None,
) -> dict:
    """Detección de outliers por IQR sobre tickets resueltos en el rango."""
    if metric not in VALID_METRICS:
        raise ValueError(f"Métrica inválida: {metric}")

    metric_col = _get_metric_col(metric)
    rows = _load_resolved_tickets(db, from_date, to_date, metric_col, category_id)

    if not rows:
        return {
            "range": {"from": str(from_date), "to": str(to_date)},
            "metric": metric,
            "data": {"q1": None, "q3": None, "lower_fence": None, "upper_fence": None,
                     "count_below": 0, "count_above": 0, "outliers_below": [], "outliers_above": []},
        }

    values = sorted(float(r[2]) for r in rows)
    q1 = _percentile(values, 25)
    q3 = _percentile(values, 75)
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr

    below = [(r[0], r[1], float(r[2])) for r in rows if float(r[2]) < lower_fence]
    above = [(r[0], r[1], float(r[2])) for r in rows if float(r[2]) > upper_fence]

    def _sample(lst, n=10):
        return [{"id": r[0], "ticket_number": r[1], "value": r[2]} for r in lst[:n]]

    return {
        "range": {"from": str(from_date), "to": str(to_date)},
        "metric": metric,
        "data": {
            "q1": round(q1, 2),
            "q3": round(q3, 2),
            "lower_fence": round(lower_fence, 2),
            "upper_fence": round(upper_fence, 2),
            "count_below": len(below),
            "count_above": len(above),
            "outliers_below": _sample(below),
            "outliers_above": _sample(above),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# K-means (pure Python)
# ─────────────────────────────────────────────────────────────────────────────

def _euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _mean_centroid(points: list[list[float]]) -> list[float]:
    if not points:
        return [0.0, 0.0, 0.0]
    n = len(points)
    dims = len(points[0])
    return [sum(p[d] for p in points) / n for d in range(dims)]


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalización a [0, 1]. Devuelve [0.5]*n si todos iguales."""
    mn = min(values)
    mx = max(values)
    if mx == mn:
        return [0.5] * len(values)
    return [(v - mn) / (mx - mn) for v in values]


def get_kmeans(
    db: Session,
    from_date: date,
    to_date: date,
    k: int = 3,
    category_id: int | None = None,
) -> dict:
    """
    K-means sobre tickets resueltos usando:
    [time_invested_minutes_norm, rating_attention, rating_speed].

    Seed fijo → resultados deterministas.
    Convergencia: max 50 iteraciones o delta centroide < 0.01.
    """
    from itcj2.apps.maint.models.ticket import MaintTicket

    if k < 1 or k > 20:
        raise ValueError("k debe estar entre 1 y 20")

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    filters = [
        MaintTicket.status.in_(RESOLVED_STATUSES),
        MaintTicket.resolved_at >= dt_start,
        MaintTicket.resolved_at <= dt_end,
        MaintTicket.time_invested_minutes.isnot(None),
        MaintTicket.rating_attention.isnot(None),
        MaintTicket.rating_speed.isnot(None),
    ]
    if category_id:
        filters.append(MaintTicket.category_id == category_id)

    rows = (
        db.query(
            MaintTicket.id,
            MaintTicket.ticket_number,
            MaintTicket.time_invested_minutes,
            MaintTicket.rating_attention,
            MaintTicket.rating_speed,
        )
        .filter(*filters)
        .all()
    )

    if len(rows) < k:
        return {
            "range": {"from": str(from_date), "to": str(to_date)},
            "k": k,
            "data": {
                "clusters": [],
                "note": f"Datos insuficientes ({len(rows)} tickets, k={k})",
            },
        }

    # Normalize time_invested
    time_vals = [float(r[2]) for r in rows]
    time_norm = _normalize(time_vals)

    points = [
        [time_norm[i], float(rows[i][3]), float(rows[i][4])]
        for i in range(len(rows))
    ]

    # Initialize centroids with fixed seed
    rng = random.Random(42)
    indices = rng.sample(range(len(points)), k)
    centroids = [points[i][:] for i in indices]

    assignments = [0] * len(points)
    max_iter = 50
    tol = 0.01

    for _ in range(max_iter):
        # Assign
        new_assignments = [
            min(range(k), key=lambda ci: _euclidean(p, centroids[ci]))
            for p in points
        ]

        # Check convergence
        changed = sum(1 for a, b in zip(assignments, new_assignments) if a != b)
        assignments = new_assignments

        # Recompute centroids
        new_centroids = []
        for ci in range(k):
            cluster_pts = [points[j] for j, a in enumerate(assignments) if a == ci]
            new_centroids.append(_mean_centroid(cluster_pts) if cluster_pts else centroids[ci][:])

        # Delta check
        max_delta = max(
            _euclidean(centroids[ci], new_centroids[ci]) for ci in range(k)
        )
        centroids = new_centroids
        if max_delta < tol:
            break

    # Build result
    clusters = []
    for ci in range(k):
        cluster_rows = [(rows[j][0], rows[j][1]) for j, a in enumerate(assignments) if a == ci]
        clusters.append(
            {
                "cluster_id": ci,
                "centroid": [round(v, 4) for v in centroids[ci]],
                "size": len(cluster_rows),
                "sample_tickets": [
                    {"id": r[0], "ticket_number": r[1]} for r in cluster_rows[:5]
                ],
            }
        )

    return {
        "range": {"from": str(from_date), "to": str(to_date)},
        "k": k,
        "data": {"clusters": clusters},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Distribution (histogram)
# ─────────────────────────────────────────────────────────────────────────────

def get_distribution(
    db: Session,
    from_date: date,
    to_date: date,
    metric: str = "time_invested",
    bins: int = 10,
    category_id: int | None = None,
) -> dict:
    """Histograma de bins iguales para la métrica dada."""
    if metric not in VALID_METRICS:
        raise ValueError(f"Métrica inválida: {metric}")
    if bins < 2 or bins > 100:
        raise ValueError("bins debe estar entre 2 y 100")

    metric_col = _get_metric_col(metric)
    rows = _load_resolved_tickets(db, from_date, to_date, metric_col, category_id)

    if not rows:
        return {
            "range": {"from": str(from_date), "to": str(to_date)},
            "metric": metric,
            "bins": bins,
            "data": {"bins": []},
        }

    values = [float(r[2]) for r in rows]
    mn = min(values)
    mx = max(values)

    if mn == mx:
        return {
            "range": {"from": str(from_date), "to": str(to_date)},
            "metric": metric,
            "bins": 1,
            "data": {"bins": [{"lower": mn, "upper": mx, "count": len(values)}]},
        }

    step = (mx - mn) / bins
    bin_counts = [0] * bins

    for v in values:
        idx = int((v - mn) / step)
        if idx >= bins:
            idx = bins - 1
        bin_counts[idx] += 1

    bin_list = [
        {
            "lower": round(mn + i * step, 4),
            "upper": round(mn + (i + 1) * step, 4),
            "count": bin_counts[i],
        }
        for i in range(bins)
    ]

    return {
        "range": {"from": str(from_date), "to": str(to_date)},
        "metric": metric,
        "bins": bins,
        "data": {"bins": bin_list},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Trends
# ─────────────────────────────────────────────────────────────────────────────

def get_trends(
    db: Session,
    from_date: date,
    to_date: date,
    granularity: str = "day",
    category_id: int | None = None,
) -> dict:
    """Serie temporal de creación, resolución, cancelación y tiempo promedio."""
    from itcj2.apps.maint.models.ticket import MaintTicket

    if granularity not in ("day", "week", "month"):
        raise ValueError("granularity debe ser day, week o month")

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    # Format string for truncation
    fmt_map = {"day": "YYYY-MM-DD", "week": "IYYY-IW", "month": "YYYY-MM"}
    fmt = fmt_map[granularity]

    cat_filter = []
    if category_id:
        cat_filter.append(MaintTicket.category_id == category_id)

    # Created
    created_rows = (
        db.query(
            func.to_char(MaintTicket.created_at, fmt).label("period"),
            func.count(MaintTicket.id).label("count"),
        )
        .filter(
            MaintTicket.created_at >= dt_start,
            MaintTicket.created_at <= dt_end,
            *cat_filter,
        )
        .group_by(func.to_char(MaintTicket.created_at, fmt))
        .order_by(func.to_char(MaintTicket.created_at, fmt))
        .all()
    )

    # Resolved
    resolved_rows = (
        db.query(
            func.to_char(MaintTicket.resolved_at, fmt).label("period"),
            func.count(MaintTicket.id).label("count"),
            func.avg(MaintTicket.time_invested_minutes).label("avg_minutes"),
        )
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES),
            MaintTicket.resolved_at >= dt_start,
            MaintTicket.resolved_at <= dt_end,
            *cat_filter,
        )
        .group_by(func.to_char(MaintTicket.resolved_at, fmt))
        .order_by(func.to_char(MaintTicket.resolved_at, fmt))
        .all()
    )

    # Canceled
    canceled_rows = (
        db.query(
            func.to_char(MaintTicket.canceled_at, fmt).label("period"),
            func.count(MaintTicket.id).label("count"),
        )
        .filter(
            MaintTicket.status == "CANCELED",
            MaintTicket.canceled_at >= dt_start,
            MaintTicket.canceled_at <= dt_end,
            MaintTicket.canceled_at.isnot(None),
            *cat_filter,
        )
        .group_by(func.to_char(MaintTicket.canceled_at, fmt))
        .order_by(func.to_char(MaintTicket.canceled_at, fmt))
        .all()
    )

    # Merge all periods
    all_periods = sorted(
        {r.period for r in created_rows}
        | {r.period for r in resolved_rows}
        | {r.period for r in canceled_rows}
    )

    created_map = {r.period: r.count for r in created_rows}
    resolved_map = {r.period: r.count for r in resolved_rows}
    avg_map = {r.period: r.avg_minutes for r in resolved_rows}
    canceled_map = {r.period: r.count for r in canceled_rows}

    labels = all_periods
    created = [created_map.get(p, 0) for p in labels]
    resolved = [resolved_map.get(p, 0) for p in labels]
    canceled = [canceled_map.get(p, 0) for p in labels]
    avg_resolution_minutes = [
        round(float(avg_map[p]), 1) if avg_map.get(p) is not None else None
        for p in labels
    ]

    return {
        "range": {"from": str(from_date), "to": str(to_date)},
        "granularity": granularity,
        "data": {
            "labels": labels,
            "created": created,
            "resolved": resolved,
            "canceled": canceled,
            "avg_resolution_minutes": avg_resolution_minutes,
        },
    }
