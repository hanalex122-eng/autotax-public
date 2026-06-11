"""REPAIR MODE — performance instrumentation (additive, low-overhead).

Captures real timing evidence instead of guesses:
  - HTTP request duration per endpoint  (record_request)
  - OCR upload pipeline stage durations (PipelineTimer)
  - Slow DB queries via SQLAlchemy events (setup_db_profiling)

Everything is logged with a greppable prefix AND kept in a bounded in-memory
ring buffer, exposed (admin-only) at GET /admin/perf so numbers are visible
without Railway log access.

Design rules: no new dependencies, no behaviour change, fail-soft everywhere.
"""
import time
import logging
import threading
from collections import deque, defaultdict

logger = logging.getLogger("autotax.perf")

# Bounded buffers — GIL-protected appends; deque(maxlen) auto-evicts oldest.
_MAXLEN = 500
_requests = deque(maxlen=_MAXLEN)     # {ts, method, path, status, ms}
_pipelines = deque(maxlen=_MAXLEN)    # {ts, name, total_ms, stages:{}}
_slow_queries = deque(maxlen=_MAXLEN) # {ts, ms, sql}
_lock = threading.Lock()

# Thresholds (ms) — above these we escalate to WARNING / record as "slow".
SLOW_REQUEST_MS = 1000
SLOW_QUERY_MS = 200

# Paths we don't want to spam the buffer with (health checks, static).
_IGNORE_PATHS = {"/health", "/favicon.ico", "/sw.js", "/robots.txt"}


def record_request(method, path, status, ms):
    """Record one HTTP request's total duration."""
    try:
        if path in _IGNORE_PATHS:
            return
        with _lock:
            _requests.append({"ts": time.time(), "method": method, "path": path,
                              "status": status, "ms": round(ms, 1)})
        lvl = logging.WARNING if ms >= SLOW_REQUEST_MS else logging.INFO
        logger.log(lvl, "[TIMING] %s %s -> %s %.0fms", method, path, status, ms)
    except Exception:
        pass


def record_pipeline(name, total_ms, stages):
    """Record an OCR/upload pipeline run with per-stage breakdown."""
    try:
        rounded = {k: round(v, 1) for k, v in stages.items()}
        with _lock:
            _pipelines.append({"ts": time.time(), "name": name,
                               "total_ms": round(total_ms, 1), "stages": rounded})
        logger.info("[PIPE] %s total=%.0fms %s", name, total_ms,
                    {k: round(v) for k, v in stages.items()})
    except Exception:
        pass


def record_query(ms, sql):
    """Record a DB query if it exceeds SLOW_QUERY_MS."""
    try:
        if ms < SLOW_QUERY_MS:
            return
        snippet = " ".join((sql or "").split())[:300]
        with _lock:
            _slow_queries.append({"ts": time.time(), "ms": round(ms, 1), "sql": snippet})
        logger.warning("[SLOWQ] %.0fms %s", ms, snippet[:200])
    except Exception:
        pass


class PipelineTimer:
    """Mark-based stage timer — insert .mark('label') at each stage boundary.

    Uses marks (not context managers) so instrumenting an existing function
    needs only single-line inserts, with no re-indentation of real code.
    """
    __slots__ = ("name", "_t0", "_last", "stages")

    def __init__(self, name):
        self.name = name
        self._t0 = time.perf_counter()
        self._last = self._t0
        self.stages = {}

    def mark(self, label):
        try:
            now = time.perf_counter()
            self.stages[label] = self.stages.get(label, 0.0) + (now - self._last) * 1000
            self._last = now
        except Exception:
            pass

    def finish(self):
        total = (time.perf_counter() - self._t0) * 1000
        record_pipeline(self.name, total, self.stages)
        return {"total_ms": round(total, 1),
                "stages": {k: round(v, 1) for k, v in self.stages.items()}}


def _pct(vals, p):
    if not vals:
        return 0
    s = sorted(vals)
    k = int(round((p / 100.0) * (len(s) - 1)))
    return s[k]


def summary():
    """Aggregate view for GET /admin/perf."""
    with _lock:
        reqs = list(_requests)
        pipes = list(_pipelines)
        slowq = list(_slow_queries)

    by_path = defaultdict(list)
    for r in reqs:
        by_path[(r["method"], r["path"])].append(r["ms"])
    endpoints = []
    for (m, p), vals in by_path.items():
        endpoints.append({"method": m, "path": p, "count": len(vals),
                          "p50": round(_pct(vals, 50), 1),
                          "p95": round(_pct(vals, 95), 1),
                          "max": round(max(vals), 1)})
    endpoints.sort(key=lambda x: x["p95"], reverse=True)

    pipe_summary = {}
    for pr in pipes:
        agg = pipe_summary.setdefault(pr["name"], {"count": 0, "totals": []})
        agg["count"] += 1
        agg["totals"].append(pr["total_ms"])
    pipe_agg = []
    for name, a in pipe_summary.items():
        pipe_agg.append({"name": name, "count": a["count"],
                         "p50_ms": round(_pct(a["totals"], 50), 1),
                         "p95_ms": round(_pct(a["totals"], 95), 1),
                         "max_ms": round(max(a["totals"]), 1)})

    return {
        "requests_tracked": len(reqs),
        "slowest_endpoints": endpoints[:15],
        "pipeline_aggregates": pipe_agg,
        "recent_pipelines": pipes[-20:],
        "slow_queries": slowq[-20:],
        "thresholds": {"slow_request_ms": SLOW_REQUEST_MS, "slow_query_ms": SLOW_QUERY_MS},
    }


def setup_db_profiling(engine):
    """Attach SQLAlchemy cursor-execute timers to log/record slow queries."""
    from sqlalchemy import event

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        context._perf_t0 = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        t0 = getattr(context, "_perf_t0", None)
        if t0 is not None:
            record_query((time.perf_counter() - t0) * 1000, statement)
