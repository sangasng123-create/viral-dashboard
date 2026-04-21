from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from data_loader import load_data


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
            radial-gradient(circle at top right, rgba(16,185,129,0.12), transparent 24%),
            linear-gradient(180deg, #0a0f1f 0%, #111827 52%, #0b1220 100%);
        color: #e5eefc;
    }
    .block-container {
        padding-top: 1.4rem;
        padding-bottom: 2rem;
        max-width: 1500px;
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
    .panel {
        background: rgba(15, 23, 42, 0.74);
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 22px;
        padding: 1.2rem 1.3rem;
        margin-bottom: 1rem;
        box-shadow: 0 16px 38px rgba(2, 6, 23, 0.22);
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
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        background: rgba(59, 130, 246, 0.14);
        border: 1px solid rgba(96, 165, 250, 0.28);
        color: #dbeafe;
        font-size: 0.82rem;
    }
    h2, h3 {
        letter-spacing: -0.02em;
    }
</style>
"""


@st.cache_data(show_spinner=False, ttl=300)
def get_dashboard_data() -> dict[str, pd.DataFrame]:
    return load_data()


def main() -> None:
    st.markdown(DARK_CSS, unsafe_allow_html=True)
    refresh_clicked = st.sidebar.button("원본 다시 불러오기", use_container_width=True)

    if refresh_clicked:
        get_dashboard_data.clear()
        try:
            st.session_state["dashboard_data"] = get_dashboard_data()
        except Exception as exc:
            st.sidebar.error(f"데이터 새로고침 실패: {exc}")

    if "dashboard_data" not in st.session_state:
        try:
            st.session_state["dashboard_data"] = get_dashboard_data()
        except Exception as exc:
            st.error(f"대시보드 로딩 실패: {exc}")
            return

    data = st.session_state["dashboard_data"]
    matched_df = data["matched"].copy()
    performance_df = data["performance"].copy()
    source_meta = data["source_path"].iloc[0]

    render_header(source_meta, matched_df)
    filtered_df = render_filters(matched_df)

    matched_kpi = build_matched_kpis(filtered_df)
    performance_kpi = build_performance_kpis(performance_df)
    render_kpis("매칭 기준 KPI", matched_kpi)
    render_kpis("원본 효율 DB 전체 합계", performance_kpi)
    render_charts(filtered_df)
    render_tables(filtered_df)


def render_header(source_meta: pd.Series, matched_df: pd.DataFrame) -> None:
    matched_count = int(matched_df["is_matched"].fillna(False).astype(bool).sum())
    total_count = len(matched_df)
    coverage = matched_count / total_count * 100 if total_count else 0
    source_path = source_meta["source_url"]
    collection_rule = source_meta.get("collection_rule", "")
    latest_collection_date = source_meta.get("latest_collection_date", "")
    load_errors = source_meta.get("load_errors", "")
    st.markdown(
        f"""
        <div class="panel">
            <div class="hero-title">바이럴 운영 관리자 대시보드</div>
            <div class="hero-subtitle">
                공개 Google Sheets 원본 DB와 NT 성과 원본을 Python에서 재계산해 통합한 Streamlit MVP
            </div>
            <div class="badge">원본 시트: {source_path}</div>
            <div class="badge">매칭률: {coverage:.1f}% ({matched_count}/{total_count})</div>
            <div class="badge">집계 규칙: {collection_rule}</div>
            <div class="badge">최신 수집일: {latest_collection_date or "미사용"}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if load_errors:
        st.warning(f"일부 시트 로딩 실패: {load_errors}")


def render_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("필터")

    valid_dates = df["date"].dropna()
    min_date = valid_dates.min().date() if not valid_dates.empty else pd.Timestamp.today().date()
    max_date = valid_dates.max().date() if not valid_dates.empty else pd.Timestamp.today().date()

    date_range = st.sidebar.date_input(
        "기간",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    platforms = sorted(option for option in df["platform"].dropna().unique().tolist() if option)
    workers = sorted(option for option in df["worker"].dropna().unique().tolist() if option)
    products = sorted(option for option in df["product_name"].dropna().unique().tolist() if option)
    managers = sorted(option for option in df["manager"].dropna().unique().tolist() if option)
    transfer_options = sorted(option for option in df["transfer_status"].dropna().unique().tolist() if option)

    selected_platforms = st.sidebar.multiselect("플랫폼", platforms, default=platforms)
    selected_workers = st.sidebar.multiselect("작업자", workers)
    selected_products = st.sidebar.multiselect("제품명", products)
    selected_managers = st.sidebar.multiselect("담당자", managers)
    selected_transfers = st.sidebar.multiselect("이체 여부", transfer_options, default=transfer_options)

    filtered = df.copy()
    if len(date_range) == 2:
        start_date, end_date = map(pd.Timestamp, date_range)
        filtered = filtered[
            filtered["date"].isna()
            | ((filtered["date"] >= start_date) & (filtered["date"] <= end_date + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)))
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

    st.sidebar.caption(f"필터 결과: {len(filtered):,}건")
    return filtered


def build_matched_kpis(df: pd.DataFrame) -> dict[str, float]:
    cost = df["cost"].sum()
    payment_amount = df["payment_amount"].sum()
    roas = payment_amount / cost * 100 if cost else 0
    return {
        "총 작업 수": float(len(df)),
        "총 비용": float(cost),
        "매칭 고객수": float(df["customer_count"].sum()),
        "매칭 유입수": float(df["inflow_count"].sum()),
        "매칭 페이지수": float(df["page_count"].sum()),
        "매칭 결제수": float(df["payment_count"].sum()),
        "매칭 결제금액": float(payment_amount),
        "매칭 ROAS": float(roas),
    }


def build_performance_kpis(df: pd.DataFrame) -> dict[str, float]:
    payment_amount = df["payment_amount"].sum()
    attributed_amount = df["payment_amount_attributed"].sum()
    return {
        "효율DB 고객수": float(df["customer_count"].sum()),
        "효율DB 유입수": float(df["inflow_count"].sum()),
        "효율DB 페이지수": float(df["page_count"].sum()),
        "효율DB 결제수": float(df["payment_count"].sum()),
        "효율DB 결제금액": float(payment_amount),
        "효율DB 기여결제금액": float(attributed_amount),
    }


def render_kpis(title: str, kpi: dict[str, float]) -> None:
    st.markdown(f"### {title}")
    labels = list(kpi.keys())
    columns = st.columns(4)
    for idx, label in enumerate(labels):
        with columns[idx % 4]:
            value = kpi[label]
            if any(token in label for token in ["작업 수", "고객수", "유입수", "페이지수", "결제수"]):
                st.metric(label, f"{value:,.0f}")
            elif "ROAS" in label:
                st.metric(label, f"{value:,.1f}%")
            else:
                st.metric(label, f"{value:,.0f}")


def render_charts(df: pd.DataFrame) -> None:
    left, right = st.columns((1.1, 0.9))
    with left:
        st.markdown("### 플랫폼별 비용 vs 결제금액")
        platform_summary = summarize_by_platform(df)
        if platform_summary.empty:
            st.info("표시할 플랫폼 요약 데이터가 없습니다.")
        else:
            chart_df = platform_summary.melt(
                id_vars="platform",
                value_vars=["총비용", "결제금액"],
                var_name="지표",
                value_name="금액",
            )
            fig = px.bar(
                chart_df,
                x="platform",
                y="금액",
                color="지표",
                barmode="group",
                template="plotly_dark",
                color_discrete_sequence=["#60a5fa", "#34d399"],
                labels={
                    "platform": "플랫폼",
                    "금액": "금액",
                    "지표": "지표",
                },
            )
            fig.update_layout(
                height=360,
                margin=dict(l=12, r=12, t=12, b=12),
                legend_title_text="",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.25)",
            )
            st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("### 일자별 유입수 추이")
        daily = (
            df.dropna(subset=["date"])
            .assign(date_only=lambda frame: frame["date"].dt.date)
            .groupby("date_only", as_index=False)[["inflow_count", "payment_count"]]
            .sum()
        )
        if daily.empty:
            st.info("표시할 날짜 데이터가 없습니다.")
        else:
            fig = px.line(
                daily,
                x="date_only",
                y=["inflow_count", "payment_count"],
                template="plotly_dark",
                color_discrete_sequence=["#38bdf8", "#f59e0b"],
                labels={"date_only": "일자", "value": "수치", "variable": "지표"},
            )
            fig.update_layout(
                height=360,
                margin=dict(l=12, r=12, t=12, b=12),
                legend_title_text="",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.25)",
            )
            st.plotly_chart(fig, use_container_width=True)


def render_tables(df: pd.DataFrame) -> None:
    st.markdown("### 플랫폼별 성과 요약")
    st.dataframe(format_summary_table(summarize_by_platform(df)), use_container_width=True, hide_index=True)

    st.markdown("### 작업자별 성과 요약")
    worker_summary = summarize_by_worker(df)
    st.dataframe(format_summary_table(worker_summary), use_container_width=True, hide_index=True)

    st.markdown("### 작업 상세 리스트")
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
        "match_method",
        "perf_latest_collected_at",
        "perf_debug_rows",
    ]
    detail_df = df[detail_columns].sort_values(["date", "platform", "worker"], ascending=[False, True, True]).copy()
    detail_df["date"] = detail_df["date"].dt.strftime("%Y-%m-%d").fillna("")
    st.dataframe(detail_df, use_container_width=True, hide_index=True)

    st.markdown("### 매칭 실패 리스트")
    unmatched = df[df["match_status"] == "미매칭"][
        [
            "date",
            "platform",
            "worker",
            "product_name",
            "manager",
            "transfer_status",
            "cost",
            "keyword",
            "match_nt_source",
            "match_nt_detail",
            "match_nt_keyword",
            "match_method",
            "perf_latest_collected_at",
            "perf_debug_rows",
            "unmatched_reason",
        ]
    ].copy()
    unmatched["date"] = unmatched["date"].dt.strftime("%Y-%m-%d").fillna("")
    st.dataframe(unmatched, use_container_width=True, hide_index=True)


def summarize_by_platform(df: pd.DataFrame) -> pd.DataFrame:
    summary = (
        df.groupby("platform", dropna=False)
        .agg(
            작업수=("row_id", "count"),
            총비용=("cost", "sum"),
            고객수=("customer_count", "sum"),
            유입수=("inflow_count", "sum"),
            페이지수=("page_count", "sum"),
            결제수=("payment_count", "sum"),
            결제금액=("payment_amount", "sum"),
            매칭건수=("is_matched", "sum"),
        )
        .reset_index()
        .rename(columns={"platform": "platform"})
    )
    summary["ROAS"] = summary.apply(
        lambda row: row["결제금액"] / row["총비용"] * 100 if row["총비용"] else 0,
        axis=1,
    )
    summary["매칭률"] = summary.apply(
        lambda row: row["매칭건수"] / row["작업수"] * 100 if row["작업수"] else 0,
        axis=1,
    )
    return summary.sort_values("총비용", ascending=False).reset_index(drop=True)


def summarize_by_worker(df: pd.DataFrame) -> pd.DataFrame:
    working_df = df.copy()
    working_df["worker"] = working_df["worker"].fillna("").astype(str).str.strip()
    working_df = working_df[working_df["worker"].ne("")].copy()

    summary = (
        working_df.groupby("worker", dropna=False)
        .agg(
            작업수=("row_id", "count"),
            총비용=("cost", "sum"),
            고객수=("customer_count", "sum"),
            유입수=("inflow_count", "sum"),
            페이지수=("page_count", "sum"),
            결제수=("payment_count", "sum"),
            결제금액=("payment_amount", "sum"),
            매칭건수=("is_matched", "sum"),
        )
        .reset_index()
        .rename(columns={"worker": "작업자"})
    )
    summary["ROAS"] = summary.apply(
        lambda row: row["결제금액"] / row["총비용"] * 100 if row["총비용"] else 0,
        axis=1,
    )
    summary["매칭률"] = summary.apply(
        lambda row: row["매칭건수"] / row["작업수"] * 100 if row["작업수"] else 0,
        axis=1,
    )
    return summary.sort_values("총비용", ascending=False).reset_index(drop=True)


def format_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    for column in formatted.columns:
        if column in {"platform", "작업자"}:
            continue
        if column in {"ROAS", "매칭률"}:
            formatted[column] = formatted[column].map(lambda value: f"{value:,.1f}%")
        else:
            formatted[column] = formatted[column].map(lambda value: f"{value:,.0f}")
    return formatted



if __name__ == "__main__":
    main()
