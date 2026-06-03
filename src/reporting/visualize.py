from __future__ import annotations

from datetime import datetime

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
from cycler import cycler

from config import CONFIG, logger

_PALETTE = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#CC79A7",  # pink
    "#000000",  # black
]

mpl.rcParams["axes.prop_cycle"] = cycler(color=_PALETTE)
mpl.rcParams["font.family"] = "sans-serif"

_SOURCE_NOTE = "Source: GlobalTech / AcquiredCo HRIS (post-dedup golden dataset)"


def _annotate(ax, note: str = _SOURCE_NOTE) -> None:
    """Add a data-source footnote below the chart axes."""
    ax.annotate(
        note,
        xy=(0, -0.18),
        xycoords="axes fraction",
        fontsize=6.5,
        color="grey",
    )


def _chart_headcount_by_department(ax, deduped_df: pd.DataFrame) -> None:
    counts = deduped_df["department"].value_counts().sort_values()
    ax.barh(counts.index, counts.values, color=_PALETTE[1])
    ax.set_title("1. Headcount by Department", fontsize=13, fontweight="bold")
    ax.set_xlabel("Number of Employees")
    ax.set_ylabel("Department")
    # label each bar with its value
    for i, v in enumerate(counts.values):
        ax.text(v + 5, i, str(v), va="center", fontsize=7)
    _annotate(ax)


def _chart_headcount_by_country(ax, deduped_df: pd.DataFrame) -> None:
    counts = deduped_df["country"].value_counts().head(15)
    bars = ax.bar(range(len(counts)), counts.values, color=_PALETTE[0])
    ax.set_xticks(range(len(counts)))
    ax.set_xticklabels(counts.index, rotation=45, ha="right", fontsize=8)
    ax.set_title("2. Headcount by Country (Top 15)", fontsize=13, fontweight="bold")
    ax.set_xlabel("Country")
    ax.set_ylabel("Number of Employees")
    for bar in bars:
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 5,
            str(int(bar.get_height())),
            ha="center", fontsize=6,
        )
    _annotate(ax)


def _chart_salary_by_employment_type(
    ax, deduped_df: pd.DataFrame, payroll_df: pd.DataFrame
) -> None:
    merged = deduped_df[["employee_id", "employment_type"]].merge(
        payroll_df[["employee_id", "salary_usd_annual"]],
        on="employee_id",
        how="inner",
    )
    merged = merged.dropna(subset=["salary_usd_annual", "employment_type"])

    ax.set_title(
        "3. Salary Distribution by Employment Type", fontsize=13, fontweight="bold"
    )
    ax.set_xlabel("Employment Type")
    ax.set_ylabel("Annual Salary (USD)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))

    if merged.empty:
        ax.text(0.5, 0.5, "No matching salary data", ha="center", va="center",
                transform=ax.transAxes, fontsize=11, color="grey")
        _annotate(ax)
        return

    emp_types = sorted(merged["employment_type"].unique())
    groups = [
        merged[merged["employment_type"] == et]["salary_usd_annual"].to_numpy()
        for et in emp_types
    ]

    bp = ax.boxplot(
        groups,
        tick_labels=emp_types,
        patch_artist=True,
        medianprops={"color": "black", "linewidth": 1.5},
    )
    colors = [_PALETTE[0], _PALETTE[1], _PALETTE[2]]
    for patch, colour in zip(bp["boxes"], colors):
        patch.set_facecolor(colour)

    ax.tick_params(axis="x", rotation=15)
    _annotate(ax)


def _chart_tenure_distribution(ax, deduped_df: pd.DataFrame) -> None:
    today = pd.Timestamp.today().normalize()
    tenure_years = (
        (today - deduped_df["hire_date"]).dt.days / 365.25
    ).dropna()
    tenure_years = tenure_years[tenure_years >= 0]

    ax.hist(tenure_years, bins=20, color=_PALETTE[4], edgecolor="white", linewidth=0.5)
    median_val = tenure_years.median()
    ax.axvline(
        median_val,
        color=_PALETTE[5],
        linestyle="--",
        linewidth=1.2,
        label=f"Median: {median_val:.1f} yrs",
    )
    ax.legend(fontsize=8)
    ax.set_title("4. Tenure Distribution", fontsize=13, fontweight="bold")
    ax.set_xlabel("Years of Service")
    ax.set_ylabel("Number of Employees")
    _annotate(ax)


def _chart_benefits_enrollment_by_department(
    ax, deduped_df: pd.DataFrame, benefits_df: pd.DataFrame
) -> None:
    enrolled_ids = set(benefits_df["employee_id"].dropna())
    df = deduped_df[["employee_id", "department"]].copy()
    df["enrolled"] = df["employee_id"].isin(enrolled_ids)

    rate = (
        df.groupby("department")["enrolled"]
        .mean()
        .mul(100)
        .sort_values()
    )

    bars = ax.barh(rate.index, rate.values, color=_PALETTE[2])
    ax.axvline(80, color=_PALETTE[5], linestyle="--", linewidth=1.0, label="80% target")
    ax.set_xlim(0, 105)
    ax.legend(fontsize=8)
    for bar in bars:
        w = bar.get_width()
        ax.text(w + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{w:.0f}%", va="center", fontsize=7)
    ax.set_title(
        "5. Benefits Enrollment Rate by Department", fontsize=13, fontweight="bold"
    )
    ax.set_xlabel("Enrollment Rate (%)")
    ax.set_ylabel("Department")
    _annotate(ax)


def _chart_quality_summary(ax, quality_report: pd.DataFrame) -> None:
    n = len(quality_report)
    x = range(n)
    w = 0.38

    ax.bar(
        [i - w / 2 for i in x],
        quality_report["passed"],
        width=w,
        label="Passed",
        color=_PALETTE[2],
    )
    ax.bar(
        [i + w / 2 for i in x],
        quality_report["failed"],
        width=w,
        label="Failed",
        color=_PALETTE[5],
    )

    # strip the type prefix (e.g. "NOT NULL: ") to keep labels short
    short_labels = [
        c.split(": ", 1)[-1].replace("employee_id", "emp_id")
        for c in quality_report["check"]
    ]
    ax.set_xticks(list(x))
    ax.set_xticklabels(short_labels, rotation=45, ha="right", fontsize=6)
    ax.legend(fontsize=8)
    ax.set_title("6. Data Quality Summary", fontsize=13, fontweight="bold")
    ax.set_xlabel("Check")
    ax.set_ylabel("Row Count")
    _annotate(ax)

def generate_eda_report(
    deduped_df: pd.DataFrame,
    payroll_df: pd.DataFrame,
    benefits_df: pd.DataFrame,
    quality_report: pd.DataFrame,
) -> None:
    logger.info("=" * 60)
    logger.info("STEP 5: EDA & Visualization Report")

    fig, axes = plt.subplots(2, 3, figsize=(22, 14))
    fig.suptitle(
        "GlobalTech Corp — HR Data Integration Report\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        fontsize=16,
        fontweight="bold",
        y=1.02,
    )

    _chart_headcount_by_department(axes[0][0], deduped_df)
    _chart_headcount_by_country(axes[0][1], deduped_df)
    _chart_salary_by_employment_type(axes[0][2], deduped_df, payroll_df)
    _chart_tenure_distribution(axes[1][0], deduped_df)
    _chart_benefits_enrollment_by_department(axes[1][1], deduped_df, benefits_df)
    _chart_quality_summary(axes[1][2], quality_report)

    fig.tight_layout()

    output_dir = CONFIG["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "eda_report.png"
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    logger.info(f"  EDA report saved: {output_path}")
    logger.info("STEP 5 complete.")
    