"""dashboard.py - statistics and Plotly charts built from the analysis results."""
import pandas as pd
import plotly.express as px

import validator

BLUE = "#1E6FD9"
ORANGE = "#E4572E"
AMBER = "#F5A623"
GREY = "#8A94A6"


def results_dataframe(results):
    rows = []
    for rec in results:
        rows.append({
            "File": rec["file_name"],
            "Department": rec["department"],
            "Completeness %": rec["completeness"],
            "Requires review": bool(rec["requires_review"]),
        })
    return pd.DataFrame(rows, columns=["File", "Department", "Completeness %", "Requires review"])


def summary_metrics(results):
    df = results_dataframe(results)
    total = len(df)
    needs_review = int(df["Requires review"].sum()) if total else 0
    return {
        "total": total,
        "complete": total - needs_review,
        "needs_review": needs_review,
        "average": round(float(df["Completeness %"].mean()), 1) if total else 0.0,
    }


def department_table(results):
    df = results_dataframe(results)
    if df.empty:
        return pd.DataFrame(columns=["Department", "Documents", "Complete", "Requires review", "Average completeness %"])
    grouped = df.groupby("Department").agg(
        Documents=("File", "count"),
        Requires_review=("Requires review", "sum"),
        Average=("Completeness %", "mean"),
    ).reset_index()
    grouped["Complete"] = grouped["Documents"] - grouped["Requires_review"]
    grouped["Average"] = grouped["Average"].round(1)
    grouped = grouped.rename(columns={"Requires_review": "Requires review", "Average": "Average completeness %"})
    grouped["Requires review"] = grouped["Requires review"].astype(int)
    return grouped[["Department", "Documents", "Complete", "Requires review", "Average completeness %"]]


def gaps_table(results):
    """How often each checklist category is Missing or Unclear."""
    rows = []
    for rec in results:
        for item in rec["checklist"].values():
            if item["status"] in (validator.MISSING, validator.UNCLEAR):
                rows.append({"Category": item["label"], "Status": item["status"]})
    if not rows:
        return pd.DataFrame(columns=["Category", "Status", "Documents"])
    df = pd.DataFrame(rows)
    return df.groupby(["Category", "Status"]).size().reset_index(name="Documents")


def _style(fig):
    fig.update_layout(
        paper_bgcolor="white", plot_bgcolor="white", font=dict(color="#1F2A37"),
        margin=dict(l=10, r=10, t=50, b=10), legend_title_text="",
    )
    return fig


def pie_figure(results):
    m = summary_metrics(results)
    df = pd.DataFrame({
        "Result": ["Complete", "Requires clinician review"],
        "Documents": [m["complete"], m["needs_review"]],
    })
    fig = px.pie(df, names="Result", values="Documents", hole=0.45, title="Complete vs incomplete documents",
                 color="Result", color_discrete_map={"Complete": BLUE, "Requires clinician review": ORANGE})
    fig.update_traces(textinfo="value+percent")
    return _style(fig)


def missing_bar_figure(results):
    gaps = gaps_table(results)
    if gaps.empty:
        return None
    order = gaps.groupby("Category")["Documents"].sum().sort_values().index.tolist()
    fig = px.bar(gaps, x="Documents", y="Category", color="Status", orientation="h",
                 title="Missing or unclear documentation categories",
                 color_discrete_map={validator.MISSING: ORANGE, validator.UNCLEAR: AMBER},
                 category_orders={"Category": order})
    fig.update_xaxes(dtick=1)
    fig.update_yaxes(title_text="")
    return _style(fig)


def department_bar_figure(results):
    dept = department_table(results)
    if dept.empty:
        return None
    fig = px.bar(dept, x="Department", y="Average completeness %", text="Average completeness %",
                 title="Average completeness by department", color_discrete_sequence=[BLUE])
    fig.update_yaxes(range=[0, 100])
    fig.update_traces(textposition="outside")
    return _style(fig)
