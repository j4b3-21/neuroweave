"""Nodes for the NeuroWeave end-to-end research example.

Question: in this (synthetic, deterministic) field trial, how strongly is seasonal rainfall
associated with crop yield? Everything uses the standard library so the example runs offline
and produces byte-identical outputs for the same inputs and seed.
"""

from __future__ import annotations

import math
import random
import statistics
from html import escape
from pathlib import Path
from typing import Literal

from neuroweave import Figure, Markdown, Table, log_metric, node


@node(category="Data", tags=["io"])
def load_dataset(path: Path) -> Table:
    """Load a CSV file into a Table, inferring numeric columns."""
    table = Table.from_csv(path)
    print(f"Loaded {table.num_rows} rows with columns {list(table.columns)} from {path.name}")
    return table


@node(category="Data", tags=["quality"])
def validate_dataset(
    data: Table,
    required_columns: list[str] = ["rainfall_mm", "yield_t_ha"],  # noqa: B006 - never mutated
    drop_incomplete: bool = True,
) -> Table:
    """Check required columns exist and handle rows with missing values."""
    missing = [c for c in required_columns if c not in data.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")
    indices = [data.columns.index(c) for c in required_columns]
    complete = [row for row in data.rows if all(row[i] is not None for i in indices)]
    dropped = data.num_rows - len(complete)
    if dropped and not drop_incomplete:
        raise ValueError(f"{dropped} rows have missing values in {required_columns}")
    print(f"Dropped {dropped} incomplete rows; {len(complete)} remain")
    log_metric("rows_dropped", dropped)
    return Table(data.columns, tuple(complete))


@node(category="Transform")
def transform_dataset(
    data: Table,
    rainfall_unit: Literal["mm", "cm"] = "cm",
    outlier_z: float = 3.0,
) -> Table:
    """Convert rainfall units and remove yield outliers beyond ``outlier_z`` standard deviations."""
    yields = [float(v) for v in data.column("yield_t_ha")]
    mean, stdev = statistics.fmean(yields), statistics.pstdev(yields)
    y_index = data.columns.index("yield_t_ha")
    r_index = data.columns.index("rainfall_mm")
    scale = 0.1 if rainfall_unit == "cm" else 1.0
    rainfall_column = f"rainfall_{rainfall_unit}"
    columns = tuple(rainfall_column if c == "rainfall_mm" else c for c in data.columns)
    kept = []
    for row in data.rows:
        if stdev and abs(float(row[y_index]) - mean) / stdev > outlier_z:
            print(f"Removing outlier row {row}")
            continue
        values = list(row)
        values[r_index] = round(float(row[r_index]) * scale, 4)
        kept.append(tuple(values))
    log_metric("outliers_removed", data.num_rows - len(kept))
    return Table(columns, tuple(kept))


def _xy(data: Table, x: str, y: str) -> tuple[list[float], list[float]]:
    return [float(v) for v in data.column(x)], [float(v) for v in data.column(y)]


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((a - mx) ** 2 for a in xs)
    slope = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True)) / sxx
    return slope, my - slope * mx


@node(category="Analysis")
def compute_statistics(
    data: Table, x: str = "rainfall_cm", y: str = "yield_t_ha"
) -> dict[str, float]:
    """Descriptive statistics, Pearson correlation and an ordinary least-squares fit."""
    xs, ys = _xy(data, x, y)
    if len(xs) < 3:
        raise ValueError("At least three observations are required.")
    r = statistics.correlation(xs, ys)
    slope, intercept = _fit(xs, ys)
    result = {
        "n": float(len(xs)),
        "x_mean": round(statistics.fmean(xs), 6),
        "y_mean": round(statistics.fmean(ys), 6),
        "y_stdev": round(statistics.stdev(ys), 6),
        "pearson_r": round(r, 6),
        "r_squared": round(r * r, 6),
        "slope": round(slope, 6),
        "intercept": round(intercept, 6),
    }
    log_metric("pearson_r", result["pearson_r"])
    log_metric("r_squared", result["r_squared"], direction="maximize")
    return result


@node(category="Analysis", tags=["stochastic"])
def bootstrap_slope(
    data: Table,
    x: str = "rainfall_cm",
    y: str = "yield_t_ha",
    resamples: int = 500,
    confidence: float = 0.95,
) -> dict[str, float]:
    """Percentile bootstrap confidence interval for the regression slope.

    Uses ``random``, which NeuroWeave seeds deterministically per node from the run seed.
    """
    xs, ys = _xy(data, x, y)
    pairs = list(zip(xs, ys, strict=True))
    slopes = []
    for _ in range(resamples):
        sample = [random.choice(pairs) for _ in pairs]
        sx = [p[0] for p in sample]
        if len(set(sx)) < 2:
            continue
        slopes.append(_fit(sx, [p[1] for p in sample])[0])
    slopes.sort()
    alpha = (1 - confidence) / 2
    low = slopes[int(math.floor(alpha * (len(slopes) - 1)))]
    high = slopes[int(math.ceil((1 - alpha) * (len(slopes) - 1)))]
    log_metric("slope_ci_width", round(high - low, 6), direction="minimize")
    return {"confidence": confidence, "slope_low": round(low, 6), "slope_high": round(high, 6),
            "resamples": float(len(slopes))}


@node(category="Visualization")
def plot_relationship(
    data: Table, stats: dict[str, float], x: str = "rainfall_cm", y: str = "yield_t_ha",
    width: int = 640, height: int = 420,
) -> Figure:
    """Scatter plot with the fitted regression line, rendered as deterministic SVG."""
    xs, ys = _xy(data, x, y)
    pad = 56
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    x_span, y_span = (x1 - x0) or 1.0, (y1 - y0) or 1.0

    def px(v: float) -> float:
        return pad + (v - x0) / x_span * (width - 2 * pad)

    def py(v: float) -> float:
        return height - pad - (v - y0) / y_span * (height - 2 * pad)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" font-family="Helvetica, Arial, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" '
        'stroke="#334155"/>',
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" stroke="#334155"/>',
    ]
    for i in range(5):
        vx = x0 + x_span * i / 4
        vy = y0 + y_span * i / 4
        parts.append(f'<text x="{px(vx):.1f}" y="{height - pad + 18}" font-size="11" '
                     f'text-anchor="middle" fill="#475569">{vx:.1f}</text>')
        parts.append(f'<text x="{pad - 8}" y="{py(vy) + 4:.1f}" font-size="11" '
                     f'text-anchor="end" fill="#475569">{vy:.2f}</text>')
    for vx, vy in zip(xs, ys, strict=True):
        parts.append(f'<circle cx="{px(vx):.2f}" cy="{py(vy):.2f}" r="4" fill="#2563eb" '
                     'fill-opacity="0.75"/>')
    slope, intercept = stats["slope"], stats["intercept"]
    parts.append(
        f'<line x1="{px(x0):.2f}" y1="{py(slope * x0 + intercept):.2f}" '
        f'x2="{px(x1):.2f}" y2="{py(slope * x1 + intercept):.2f}" stroke="#dc2626" '
        'stroke-width="2"/>'
    )
    parts.append(f'<text x="{width / 2}" y="{height - 14}" font-size="12" text-anchor="middle" '
                 f'fill="#0f172a">{escape(x)}</text>')
    parts.append(f'<text x="16" y="{height / 2}" font-size="12" text-anchor="middle" '
                 f'transform="rotate(-90 16 {height / 2})" fill="#0f172a">{escape(y)}</text>')
    parts.append(f'<text x="{width / 2}" y="28" font-size="14" text-anchor="middle" '
                 f'fill="#0f172a">{escape(y)} vs {escape(x)} '
                 f'(r = {stats["pearson_r"]:.3f}, n = {int(stats["n"])})</text>')
    parts.append("</svg>")
    return Figure("\n".join(parts))


@node(category="Reporting")
def write_report(
    stats: dict[str, float], interval: dict[str, float], figure: Figure,
    title: str = "Rainfall and crop yield",
) -> Markdown:
    """Assemble a Markdown report from computed results. Contains no hand-written numbers."""
    rows = "\n".join(f"| {key} | {value:g} |" for key, value in sorted(stats.items()))
    lines = [
        f"# {title}",
        "",
        "## Results",
        "",
        "| statistic | value |",
        "|---|---|",
        rows,
        "",
        f"Bootstrap {interval['confidence']:.0%} interval for the slope: "
        f"[{interval['slope_low']:g}, {interval['slope_high']:g}] "
        f"({int(interval['resamples'])} resamples).",
        "",
        "## Figure",
        "",
        figure.svg,
        "",
        "## Interpretation limits",
        "",
        "Correlation in an observational dataset does not establish causation. The data in "
        "this example are synthetic.",
        "",
    ]
    return Markdown("\n".join(lines))
