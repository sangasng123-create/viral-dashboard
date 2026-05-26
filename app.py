from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from data_loader import build_match_key, load_data


st.set_page_config(
    page_title="바이럴 운영 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


DARK_CSS = """
<style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(59,130,246,0.18), transparent 28%),
            radial-gradient(circle at top right, rgba(16,185,129,0.10), transparent 22%),
            linear-gradient(180deg, #0a0f1f 0%, #111827 52%, #0b1220 100%);
        color: #e5eefc;
    }
    .block-container {
        padding-top: 1.4rem;
        padding-bottom: 2rem;
        max-width: 1480px;
    }
    .panel {
        background: rgba(15, 23, 42, 0.76);
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 22px;
        padding: 1.2rem 1.3rem;
        margin-bottom: 1rem;
        box-shadow: 0 16px 38px rgba(2, 6, 23, 0.22);
    }
    div[data-testid="stMetric"] {
        background: rgba(15, 23, 42, 0.82);
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 18px;
        padding: 18px 18px 14px 18px;
        box-shadow: 0 12px 32px rgba(2, 6, 23, 0.28);
    }
    div[data-testid="stMetric"] label {
        color: #8fb4ff;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 18px;
        overflow: hidden;
    }
    .hero-title {
        font-size: 2rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        margin-bottom: 0.2rem;
    }
    .hero-subtitle {
        color: #9db2ce;
        font-size: 0.98rem;
    }
    .badge {
        display: inline-block;
        margin-top: 0.7rem;
        margin-right: 0.45rem;
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        background: rgba(59, 130, 246, 0.14);
        border: 1px solid rgba(96, 165, 250, 0.28);
        color: #dbeafe;
        font-size: 0.82rem;
    }
</style>
"""


TABLE_FALLBACK_COLUMNS = {
    "perf_latest_collected_at": "",
    "perf_debug_rows": "",
    "match_nt_source": "",
    "match_nt_detail": "",
    "match_nt_keyword": "",
    "unmatched_reason": "",
    "match_method": "",
    "match_status": "",
    "match_key": "",
}

CHART_COLORS = {
    "cost": "#60a5fa",
    "payment_amount": "#f59e0b",
    "inflow_count": "#22c55e",
    "payment_count": "#f97316",
    "roas": "#38bdf8",
}

DISPLAY_NAMES = {
    "cost": "비용",
    "payment_amount": "결제금액",
    "inflow_count": "유입수",
    "payment_count": "결제수",
    "roas": "ROAS",
}


@st.cache_data(show_spinner=False, ttl=300)
def get_dashboard_data() -> dict[str, pd.DataFrame]:
    return load_data()


def main() -> None:
    st.markdown(DARK_CSS, unsafe_allow_html=True)

    if st.sidebar.button("원본 다시 불러오기", use_container_width=True):
        get_dashboard_data.clear()
        st.session_state.pop("dashboard_data", None)

    if "dashboard_data" not in st.session_state:
        try:
            st.session_state["dashboard_data"] = get_dashboard_data()
        except Exception as exc:
            st.error(f"대시보드 로딩 실패: {exc}")
            return

    data = st.session_state["dashboard_data"]
    matched_df = ensure_table_columns(data["matched"].copy())
    performance_df = data["performance"].copy()
    source_meta = data["source_path"].iloc[0]

    render_header(source_meta, matched_df)
    filtered_df = render_filters(matched_df)
    filtered_performance_df = filter_performance_by_matched_rows(filtered_df, performance_df)

    render_kpi_section(filtered_df)
    render_chart_section(filtered_df)
    render_tables(filtered_df)

    st.markdown("---")
    render_performance_totals(filtered_performance_df)


def ensure_table_columns(df: pd.DataFrame) -> pd.DataFrame:
    working_df = df.copy()
    for column, default_value in TABLE_FALLBACK_COLUMNS.items():
        if column not in working_df.columns:
            working_df[column] = default_value
    return working_df


def render_header(source_meta: pd.Series, matched_df: pd.DataFrame) -> None:
    matched_count = int(matched_df["is_matched"].fillna(False).astype(bool).sum())
    total_count = len(matched_df)
    coverage = matched_count / total_count * 100 if total_count else 0

    source_url = str(source_meta.get("source_url", ""))
    collection_rule = str(source_meta.get("collection_rule", ""))
    latest_collection_date = str(source_meta.get("latest_collection_date", ""))
    load_errors = str(source_meta.get("load_errors", ""))

    st.markdown(
        f"""
        <div class="panel">
            <div class="hero-title">바이럴 운영 관리사 대시보드</div>
            <div class="hero-subtitle">
                공개 Google Sheets 원본 DB와 NT 성과 원본을 Python에서 집계해 통합한 Streamlit 대시보드
            </div>
            <div class="badge">원본 시트: {source_url}</div>
            <div class="badge">매칭률: {coverage:.1f}% ({matched_count}/{total_count})</div>
            <div class="badge">집계 규칙: {collection_rule or "미기재"}</div>
            <div class="badge">최신 수집일: {latest_collection_date or "미기재"}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if load_errors:
        st.warning(f"일부 시트 로딩 실패: {load_errors}")


def render_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("필터")

    valid_dates = df["date"].dropna()
    today = pd.Timestamp.today().date()
    min_date = valid_dates.min().date() if not valid_dates.empty else today
    max_date = valid_dates.max().date() if not valid_dates.empty else today

    date_range = st.sidebar.date_input(
        "기간",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    platforms = sorted(values_without_blank(df["platform"]))
    workers = sorted(values_without_blank(df["worker"]))
    products = sorted(values_without_blank(df["product_name"]))
    managers = sorted(values_without_blank(df["manager"]))
    transfer_options = sorted(values_without_blank(df["transfer_status"]))

    selected_platforms = st.sidebar.multiselect("플랫폼", platforms, default=platforms)
    selected_workers = st.sidebar.multiselect("작업자", workers)
    selected_products = st.sidebar.multiselect("상품명", products)
    selected_managers = st.sidebar.multiselect("담당자", managers)
    selected_transfers = st.sidebar.multiselect("이체 여부", transfer_options, default=transfer_options)

    filtered = df.copy()

    if len(date_range) == 2:
        start_date, end_date = map(pd.Timestamp, date_range)
        end_dt = end_date + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        filtered = filtered[
            filtered["date"].isna()
            | ((filtered["date"] >= start_date) & (filtered["date"] <= end_dt))
        ]

    if selected_platforms:
        filtered = filtered[filtered["platform"].isin(selected_platforms)]
    if selected_workers:
        filtered = filtered[filtered["worker"].isin(selected_workers)]
    if selected_products:
        filtered = filtered[filtered["product_name"].isin(selected_products)]
    if selected_managers:
        filtered = filtered[filtered["manager"].isin(selected_managers)]
    if selected_transfers:
        filtered = filtered[filtered["transfer_status"].isin(selected_transfers)]

    return filtered.sort_values(["date", "platform", "worker"], ascending=[False, True, True])


def render_kpi_section(df: pd.DataFrame) -> None:
    st.subheader("핵심 KPI")
    primary_metrics, secondary_metrics = build_kpis(df)

    first_primary_row = st.columns(2)
    for column, metric in zip(first_primary_row, primary_metrics[:2], strict=False):
        with column:
            st.metric(metric["label"], metric["value"])

    second_primary_row = st.columns(2)
    for column, metric in zip(second_primary_row, primary_metrics[2:], strict=False):
        with column:
            st.metric(metric["label"], metric["value"])

    st.caption("운영 판단에 바로 쓰는 핵심 지표를 먼저 배치했습니다.")
    secondary_columns = st.columns(len(secondary_metrics))
    for column, metric in zip(secondary_columns, secondary_metrics, strict=False):
        with column:
            st.metric(metric["label"], metric["value"])


def build_kpis(df: pd.DataFrame) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    total_cost = float(df["cost"].fillna(0).sum())
    total_payment_amount = float(df["payment_amount"].fillna(0).sum())
    total_payment_count = float(df["payment_count"].fillna(0).sum())
    roas = (total_payment_amount / total_cost * 100) if total_cost else 0

    primary = [
        {"label": "총 비용", "value": format_currency(total_cost)},
        {"label": "결제금액", "value": format_currency(total_payment_amount)},
        {"label": "ROAS", "value": format_percent(roas)},
        {"label": "결제수", "value": format_number(total_payment_count)},
    ]

    secondary = [
        {"label": "총 작업 수", "value": format_number(len(df))},
        {"label": "고객수", "value": format_number(df["customer_count"].fillna(0).sum())},
        {"label": "유입수", "value": format_number(df["inflow_count"].fillna(0).sum())},
        {"label": "클릭수", "value": format_number(df["page_count"].fillna(0).sum())},
    ]
    return primary, secondary


def render_chart_section(df: pd.DataFrame) -> None:
    st.subheader("성과 흐름과 효율")

    platform_perf = summarize_by_platform(df)
    daily_trend = build_time_series(df, "D")
    monthly_trend = build_time_series(df, "M")
    worker_perf = summarize_by_worker(df, limit=7)

    top_left, top_right = st.columns(2)
    with top_left:
        st.plotly_chart(build_platform_performance_chart(platform_perf), use_container_width=True)
    with top_right:
        st.plotly_chart(build_daily_trend_chart(daily_trend), use_container_width=True)

    middle_left, middle_right = st.columns(2)
    with middle_left:
        st.plotly_chart(build_monthly_trend_chart(monthly_trend), use_container_width=True)
    with middle_right:
        st.plotly_chart(build_platform_roas_scatter(platform_perf), use_container_width=True)

    bottom_left, bottom_right = st.columns(2)
    with bottom_left:
        st.plotly_chart(build_worker_performance_chart(worker_perf), use_container_width=True)
    with bottom_right:
        st.plotly_chart(build_payment_share_donut(platform_perf), use_container_width=True)


def summarize_by_platform(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["platform", "cost", "payment_amount", "inflow_count", "payment_count", "roas"])

    grouped = (
        df.groupby("platform", dropna=False, as_index=False)[["cost", "payment_amount", "inflow_count", "payment_count"]]
        .sum()
        .fillna(0)
    )
    grouped["platform"] = grouped["platform"].replace("", "미기재")
    grouped["roas"] = grouped.apply(
        lambda row: (row["payment_amount"] / row["cost"] * 100) if row["cost"] else 0,
        axis=1,
    )
    return grouped.sort_values("payment_amount", ascending=False)


def summarize_by_worker(df: pd.DataFrame, limit: int = 7) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["worker", "cost", "payment_amount"])

    grouped = (
        df.groupby("worker", dropna=False, as_index=False)[["cost", "payment_amount"]]
        .sum()
        .fillna(0)
    )
    grouped["worker"] = grouped["worker"].replace("", "미기재")
    grouped = grouped.sort_values("payment_amount", ascending=False).head(limit)
    return grouped.sort_values("payment_amount", ascending=True)


def build_time_series(df: pd.DataFrame, frequency: str) -> pd.DataFrame:
    dated = df.loc[df["date"].notna()].copy()
    if dated.empty:
        return pd.DataFrame(columns=["period", "inflow_count", "payment_count", "cost", "payment_amount"])

    if frequency == "D":
        dated["period"] = dated["date"].dt.normalize()
    else:
        dated["period"] = dated["date"].dt.to_period(frequency).dt.to_timestamp()

    grouped = (
        dated.groupby("period", as_index=False)[["inflow_count", "payment_count", "cost", "payment_amount"]]
        .sum()
        .sort_values("period")
    )
    return grouped


def build_platform_performance_chart(df: pd.DataFrame):
    if df.empty:
        return empty_figure("플랫폼별 투자 대비 매출")

    melted = df.melt(
        id_vars="platform",
        value_vars=["cost", "payment_amount"],
        var_name="metric",
        value_name="value",
    )
    melted["metric_label"] = melted["metric"].map(DISPLAY_NAMES)

    fig = px.bar(
        melted,
        x="platform",
        y="value",
        color="metric_label",
        barmode="group",
        color_discrete_map={
            DISPLAY_NAMES["cost"]: CHART_COLORS["cost"],
            DISPLAY_NAMES["payment_amount"]: CHART_COLORS["payment_amount"],
        },
        title="플랫폼별 투자 대비 매출",
    )
    fig.update_traces(
        hovertemplate="플랫폼=%{x}<br>지표=%{fullData.name}<br>금액=%{y:,.0f}원<extra></extra>"
    )
    apply_currency_yaxis(fig)
    apply_common_layout(fig)
    return fig


def build_daily_trend_chart(df: pd.DataFrame):
    if df.empty:
        return empty_figure("일별 유입과 결제 흐름")

    melted = df.melt(
        id_vars="period",
        value_vars=["inflow_count", "payment_count"],
        var_name="metric",
        value_name="value",
    )
    melted["metric_label"] = melted["metric"].map(DISPLAY_NAMES)

    fig = px.line(
        melted,
        x="period",
        y="value",
        color="metric_label",
        markers=True,
        color_discrete_map={
            DISPLAY_NAMES["inflow_count"]: CHART_COLORS["inflow_count"],
            DISPLAY_NAMES["payment_count"]: CHART_COLORS["payment_count"],
        },
        title="일별 유입과 결제 흐름",
    )
    fig.update_traces(
        hovertemplate="일자=%{x|%Y-%m-%d}<br>지표=%{fullData.name}<br>수치=%{y:,.0f}<extra></extra>"
    )
    apply_count_yaxis(fig)
    apply_common_layout(fig)
    return fig


def build_monthly_trend_chart(df: pd.DataFrame):
    if df.empty:
        return empty_figure("월별 집행 대비 회수")

    melted = df.melt(
        id_vars="period",
        value_vars=["cost", "payment_amount"],
        var_name="metric",
        value_name="value",
    )
    melted["metric_label"] = melted["metric"].map(DISPLAY_NAMES)

    fig = px.line(
        melted,
        x="period",
        y="value",
        color="metric_label",
        markers=True,
        color_discrete_map={
            DISPLAY_NAMES["cost"]: CHART_COLORS["cost"],
            DISPLAY_NAMES["payment_amount"]: CHART_COLORS["payment_amount"],
        },
        title="월별 집행 대비 회수",
    )
    fig.update_traces(
        hovertemplate="월=%{x|%Y-%m}<br>지표=%{fullData.name}<br>금액=%{y:,.0f}원<extra></extra>"
    )
    apply_currency_yaxis(fig)
    apply_common_layout(fig)
    return fig


def build_platform_roas_scatter(df: pd.DataFrame):
    if df.empty:
        return empty_figure("유입 대비 효율 높은 플랫폼")

    fig = px.scatter(
        df,
        x="inflow_count",
        y="roas",
        size="payment_amount",
        color="platform",
        text="platform",
        custom_data=["payment_amount"],
        title="유입 대비 효율 높은 플랫폼",
    )
    fig.update_traces(
        textposition="top center",
        hovertemplate=(
            "플랫폼=%{text}<br>"
            "유입수=%{x:,.0f}<br>"
            "ROAS=%{y:.1f}%<br>"
            "결제금액=%{customdata[0]:,.0f}원<extra></extra>"
        ),
    )
    fig.update_xaxes(title="유입수", tickformat=",.0f")
    fig.update_yaxes(title="ROAS (%)", ticksuffix="%", tickformat=",.1f")
    apply_common_layout(fig)
    return fig


def build_worker_performance_chart(df: pd.DataFrame):
    if df.empty:
        return empty_figure("상위 작업자 집행 대비 매출")

    melted = df.melt(
        id_vars="worker",
        value_vars=["cost", "payment_amount"],
        var_name="metric",
        value_name="value",
    )
    melted["metric_label"] = melted["metric"].map(DISPLAY_NAMES)

    fig = px.bar(
        melted,
        x="value",
        y="worker",
        orientation="h",
        color="metric_label",
        barmode="group",
        color_discrete_map={
            DISPLAY_NAMES["cost"]: CHART_COLORS["cost"],
            DISPLAY_NAMES["payment_amount"]: CHART_COLORS["payment_amount"],
        },
        title="상위 작업자 집행 대비 매출",
    )
    fig.update_traces(
        hovertemplate="작업자=%{y}<br>지표=%{fullData.name}<br>금액=%{x:,.0f}원<extra></extra>"
    )
    fig.update_xaxes(title="금액")
    apply_currency_xaxis(fig)
    apply_common_layout(fig)
    return fig


def build_payment_share_donut(df: pd.DataFrame):
    if df.empty:
        return empty_figure("플랫폼별 결제금액 비중")

    chart_df = df.loc[df["payment_amount"] > 0, ["platform", "payment_amount"]].copy()
    if chart_df.empty:
        chart_df = pd.DataFrame({"platform": ["결제 없음"], "payment_amount": [1]})

    fig = px.pie(
        chart_df,
        names="platform",
        values="payment_amount",
        hole=0.58,
        title="플랫폼별 결제금액 비중",
    )
    fig.update_traces(
        textinfo="percent+label",
        hovertemplate="플랫폼=%{label}<br>결제금액=%{value:,.0f}원<extra></extra>",
    )
    apply_common_layout(fig)
    return fig


def render_tables(df: pd.DataFrame) -> None:
    st.subheader("작업 상세 리스트")
    detail_columns = [
        "date",
        "platform",
        "worker",
        "product_name",
        "manager",
        "transfer_status",
        "cost",
        "keyword",
        "customer_count",
        "inflow_count",
        "page_count",
        "payment_count",
        "payment_amount",
        "match_status",
    ]
    detail_df = df.reindex(columns=detail_columns).copy()
    detail_df = detail_df.rename(
        columns={
            "date": "일자",
            "platform": "플랫폼",
            "worker": "작업자",
            "product_name": "상품명",
            "manager": "담당자",
            "transfer_status": "이체여부",
            "cost": "비용",
            "keyword": "키워드",
            "customer_count": "고객수",
            "inflow_count": "유입수",
            "page_count": "클릭수",
            "payment_count": "결제수",
            "payment_amount": "결제금액",
            "match_status": "매칭상태",
        }
    )
    if "일자" in detail_df.columns:
        detail_df["일자"] = pd.to_datetime(detail_df["일자"], errors="coerce").dt.strftime("%Y-%m-%d")
        detail_df["일자"] = detail_df["일자"].fillna("")
    for currency_column in ["비용", "결제금액"]:
        if currency_column in detail_df.columns:
            detail_df[currency_column] = detail_df[currency_column].fillna(0).map(format_currency)
    st.dataframe(detail_df, use_container_width=True, hide_index=True)

    unmatched_df = df.loc[df["match_status"] == "미매칭", [
        "date",
        "platform",
        "worker",
        "product_name",
        "keyword",
        "unmatched_reason",
    ]].copy()
    unmatched_df = unmatched_df.rename(
        columns={
            "date": "일자",
            "platform": "플랫폼",
            "worker": "작업자",
            "product_name": "상품명",
            "keyword": "키워드",
            "unmatched_reason": "미매칭 사유",
        }
    )
    if "일자" in unmatched_df.columns:
        unmatched_df["일자"] = pd.to_datetime(unmatched_df["일자"], errors="coerce").dt.strftime("%Y-%m-%d")
        unmatched_df["일자"] = unmatched_df["일자"].fillna("")

    st.subheader("매칭 실패 리스트")
    st.dataframe(unmatched_df, use_container_width=True, hide_index=True)


def render_performance_totals(performance_df: pd.DataFrame) -> None:
    st.subheader("원본 효율 DB 전체 합계")
    kpis = build_performance_kpis(performance_df)
    columns = st.columns(len(kpis))
    for column, metric in zip(columns, kpis, strict=False):
        with column:
            st.metric(metric["label"], metric["value"])
    st.caption("현재 필터에 걸린 매칭 행과 연결된 효율 DB 기준 합계입니다.")


def build_performance_kpis(df: pd.DataFrame) -> list[dict[str, str]]:
    if df.empty:
        return [
            {"label": "고객수", "value": "0"},
            {"label": "유입수", "value": "0"},
            {"label": "클릭수", "value": "0"},
            {"label": "결제수", "value": "0"},
            {"label": "결제금액", "value": format_currency(0)},
        ]

    return [
        {"label": "고객수", "value": format_number(df["customer_count"].fillna(0).sum())},
        {"label": "유입수", "value": format_number(df["inflow_count"].fillna(0).sum())},
        {"label": "클릭수", "value": format_number(df["page_count"].fillna(0).sum())},
        {"label": "결제수", "value": format_number(df["payment_count"].fillna(0).sum())},
        {"label": "결제금액", "value": format_currency(df["payment_amount"].fillna(0).sum())},
    ]


def filter_performance_by_matched_rows(
    matched_df: pd.DataFrame,
    performance_df: pd.DataFrame,
) -> pd.DataFrame:
    if matched_df.empty or performance_df.empty:
        return performance_df.iloc[0:0].copy()

    keys = set(
        matched_df.loc[matched_df["is_matched"].fillna(False)]
        .apply(
            lambda row: build_match_key(row["matched_nt_source"] or row["match_nt_source"], row["match_nt_detail"], row["match_nt_keyword"]),
            axis=1,
        )
        .tolist()
    )
    if not keys:
        return performance_df.iloc[0:0].copy()

    working = performance_df.copy()
    working["match_key"] = working.apply(
        lambda row: build_match_key(row["nt_source"], row["nt_detail"], row["nt_keyword"]),
        axis=1,
    )
    return working.loc[working["match_key"].isin(keys)].copy()


def values_without_blank(series: pd.Series) -> list[str]:
    return [value for value in series.dropna().astype(str).tolist() if value.strip()]


def format_currency(value: float) -> str:
    return f"₩{float(value):,.0f}"


def format_percent(value: float) -> str:
    return f"{float(value):,.1f}%"


def format_number(value: float | int) -> str:
    return f"{float(value):,.0f}"


def apply_currency_yaxis(fig) -> None:
    fig.update_yaxes(tickprefix="₩", tickformat=",.0f")


def apply_currency_xaxis(fig) -> None:
    fig.update_xaxes(tickprefix="₩", tickformat=",.0f")


def apply_count_yaxis(fig) -> None:
    fig.update_yaxes(tickformat=",.0f")


def apply_common_layout(fig) -> None:
    fig.update_layout(
        paper_bgcolor="rgba(15, 23, 42, 0.0)",
        plot_bgcolor="rgba(15, 23, 42, 0.0)",
        font=dict(color="#e5eefc"),
        legend_title_text="",
        margin=dict(l=20, r=20, t=60, b=20),
        hoverlabel=dict(bgcolor="#0f172a", font_color="#e5eefc"),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(148, 163, 184, 0.12)")


def empty_figure(title: str):
    fig = px.scatter(title=title)
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text="표시할 데이터가 없습니다.",
                showarrow=False,
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                font=dict(color="#9db2ce", size=14),
            )
        ],
    )
    apply_common_layout(fig)
    return fig


if __name__ == "__main__":
    main()
