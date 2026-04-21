from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable
from urllib.error import HTTPError, URLError

import pandas as pd


SPREADSHEET_ID = "1NeeQNSiG9D9u5U290vyW_LKIn9Siyd9EinwZaUXzIiM"
SPREADSHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
SHEET_GIDS = {
    "(DB)블로그(완료건 기준)": "198507325",
    "(DB)인스타그램(완료건 기준)": "1485104371",
    "(DB)유튜브(완료건 기준)": "534722161",
    "(DB)X(완료건 기준)": "1433936261",
    "(DB)커뮤니티": "1056422214",
    "(DB)브랜드커넥트": "255349713",
    "(DB)바이럴 효율": "1675730631",
}

PAID_COLUMNS = [
    "row_id",
    "date",
    "platform",
    "platform_group",
    "worker",
    "product_name",
    "manager",
    "transfer_status",
    "cost",
    "keyword",
    "url",
    "notes",
    "source_sheet",
    "match_nt_source",
    "match_nt_detail",
    "match_nt_keyword",
]

PERFORMANCE_METRICS = [
    "customer_count",
    "inflow_count",
    "page_count",
    "payment_count",
    "payment_amount",
    "payment_count_attributed",
    "payment_amount_attributed",
]

LATEST_SNAPSHOT_METRICS = [
    "customer_count",
    "inflow_count",
    "page_count",
]

MAX_VALUE_METRICS = [
    "payment_count",
    "payment_amount",
    "payment_count_attributed",
    "payment_amount_attributed",
]


@dataclass(frozen=True)
class WorkbookSheets:
    paid: dict[str, str]
    performance: str


def load_data() -> dict[str, pd.DataFrame]:
    raw_data, load_errors = load_google_public_sheets_data()
    sheets = identify_sheets(raw_data.keys())

    paid_frames: list[pd.DataFrame] = []
    for platform_group, sheet_name in sheets.paid.items():
        standardized = standardize_paid_sheet(raw_data.get(sheet_name, pd.DataFrame()), platform_group, sheet_name)
        if not standardized.empty:
            paid_frames.append(standardized)

    paid_df = pd.concat(paid_frames, ignore_index=True) if paid_frames else pd.DataFrame(columns=PAID_COLUMNS)
    paid_df = finalize_paid_df(paid_df)

    performance_raw = raw_data.get(sheets.performance, pd.DataFrame())
    performance_collection_dates = extract_collection_date(performance_raw)
    performance_df = finalize_performance_df(performance_raw)

    matched_df, unmatched_df = match_paid_with_performance(paid_df, performance_df)

    if performance_collection_dates.notna().any():
        latest_collection_date = performance_collection_dates.max().strftime("%Y-%m-%d")
        earliest_collection_date = performance_collection_dates.min().strftime("%Y-%m-%d")
    else:
        latest_collection_date = ""
        earliest_collection_date = ""

    source_meta = pd.DataFrame(
        [
            {
                "source_url": SPREADSHEET_URL,
                "collection_rule": "키별 최신 수집일 유지, 트래픽은 최신 기준·결제는 최대값 기준",
                "latest_collection_date": latest_collection_date,
                "earliest_collection_date": earliest_collection_date,
                "load_errors": " | ".join(load_errors),
            }
        ]
    )

    return {
        "paid": paid_df,
        "performance": performance_df,
        "matched": matched_df,
        "unmatched": unmatched_df,
        "source_path": source_meta,
    }


def build_csv_url(spreadsheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"


def load_google_public_sheets_data() -> tuple[dict[str, pd.DataFrame], list[str]]:
    data: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    for sheet_name, gid in SHEET_GIDS.items():
        csv_url = build_csv_url(SPREADSHEET_ID, gid)
        try:
            data[sheet_name] = pd.read_csv(csv_url)
        except pd.errors.EmptyDataError:
            data[sheet_name] = pd.DataFrame()
        except (HTTPError, URLError, TimeoutError, ConnectionError, OSError) as exc:
            data[sheet_name] = pd.DataFrame()
            errors.append(f"{sheet_name}: {exc.__class__.__name__}")

    return data, errors


def identify_sheets(sheet_names: Iterable[str]) -> WorkbookSheets:
    paid: dict[str, str] = {}
    performance = ""

    for name in sheet_names:
        compact = normalize_sheet_name(name)
        if "db" not in compact:
            continue
        if "바이럴효율" in compact:
            performance = name
        elif "블로그" in compact:
            paid["블로그"] = name
        elif "인스타그램" in compact:
            paid["인스타그램"] = name
        elif "유튜브" in compact:
            paid["유튜브"] = name
        elif re.search(r"\bx\b", name.lower()):
            paid["X"] = name
        elif "커뮤니티" in compact:
            paid["커뮤니티"] = name
        elif "브랜드커넥트" in compact:
            paid["브랜드커넥트"] = name

    if not performance:
        raise ValueError("'(DB)바이럴 효율' 시트를 찾지 못했습니다.")

    return WorkbookSheets(paid=paid, performance=performance)


def normalize_sheet_name(value: str) -> str:
    return re.sub(r"\s+", "", clean_text(value)).lower()


def standardize_paid_sheet(df: pd.DataFrame, platform_group: str, sheet_name: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=PAID_COLUMNS)

    clean_df = df.copy()
    clean_df.columns = [sanitize_column_name(col) for col in clean_df.columns]
    clean_df = clean_df.loc[:, ~clean_df.columns.str.startswith("unnamed_")]
    clean_df = clean_df.dropna(how="all").copy()

    if platform_group == "커뮤니티":
        standardized = pd.DataFrame(
            {
                "date": to_datetime_series(get_series(clean_df, "날짜")),
                "platform": get_series(clean_df, "플랫폼").map(clean_text),
                "platform_group": platform_group,
                "worker": get_series(clean_df, "플랫폼").map(clean_text),
                "product_name": get_series(clean_df, "키워드").map(clean_text),
                "manager": "",
                "transfer_status": "",
                "cost": to_numeric_series(get_series(clean_df, "비용")),
                "keyword": get_series(clean_df, "키워드").map(clean_text),
                "url": "",
                "notes": get_series(clean_df, "비고").map(clean_text),
                "source_sheet": sheet_name,
            }
        )
    else:
        link_column = next((col for col in clean_df.columns if col.endswith("링크")), "")
        standardized = pd.DataFrame(
            {
                "date": to_datetime_series(
                    get_series(clean_df, "업로드날짜")
                    if "업로드날짜" in clean_df.columns
                    else get_series(clean_df, "날짜")
                ),
                "platform": platform_group,
                "platform_group": platform_group,
                "worker": get_series(clean_df, "작업자").map(clean_text),
                "product_name": (
                    get_series(clean_df, "제안제품") if "제안제품" in clean_df.columns else get_series(clean_df, "제품명")
                ).map(clean_text),
                "manager": get_series(clean_df, "담당자").map(clean_text),
                "transfer_status": get_series(clean_df, "이체여부").map(clean_transfer_status),
                "cost": to_numeric_series(
                    get_series(clean_df, "유상비용") if "유상비용" in clean_df.columns else get_series(clean_df, "비용")
                ),
                "keyword": get_series(clean_df, "키워드").map(clean_text),
                "url": get_series(clean_df, link_column).map(clean_text) if link_column else "",
                "notes": get_series(clean_df, "비고").map(clean_text),
                "source_sheet": sheet_name,
            }
        )

    standardized["row_id"] = [f"{platform_group}-{idx + 1}" for idx in range(len(standardized))]
    standardized = standardized.reindex(columns=PAID_COLUMNS[:-3])
    standardized = standardized.dropna(how="all", subset=["date", "worker", "product_name", "cost", "keyword"])
    return standardized


def finalize_paid_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=PAID_COLUMNS)

    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["platform"] = result["platform"].fillna(result["platform_group"]).map(clean_text)
    result["worker"] = result["worker"].map(clean_text)
    result["product_name"] = result["product_name"].map(clean_text)
    result["manager"] = result["manager"].map(clean_text)
    result["transfer_status"] = result["transfer_status"].map(clean_transfer_status)
    result["keyword"] = result["keyword"].map(clean_text)
    result["url"] = result["url"].map(clean_text)
    result["notes"] = result["notes"].map(clean_text)
    result["cost"] = to_numeric_series(result["cost"]).fillna(0)
    result["match_nt_detail"] = result["worker"].map(normalize_match_text)
    result["match_nt_keyword"] = result["keyword"].map(normalize_match_text)
    result["match_nt_source"] = result.apply(build_primary_nt_source, axis=1)
    return result.reindex(columns=PAID_COLUMNS)


def finalize_performance_df(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    working.columns = [sanitize_column_name(col) for col in working.columns]

    column_map = {
        "채널속성": "channel_type",
        "ntsource": "nt_source",
        "ntmedium": "nt_medium",
        "ntdetail": "nt_detail",
        "ntkeyword": "nt_keyword",
        "고객수": "customer_count",
        "유입수": "inflow_count",
        "페이지수": "page_count",
        "결제수": "payment_count",
        "결제금액": "payment_amount",
        "결제수+14일기여도추정": "payment_count_attributed",
        "결제금액+14일기여도추정": "payment_amount_attributed",
    }
    working = working.rename(columns=column_map)

    required = list(column_map.values())
    for column in required:
        if column not in working.columns:
            working[column] = 0 if column in PERFORMANCE_METRICS else ""

    working = working[required].dropna(how="all").copy()
    working["collected_at"] = extract_collection_date(df)
    working["row_order"] = range(len(working))
    working["nt_source"] = working["nt_source"].map(normalize_nt_source)
    working["nt_detail"] = working["nt_detail"].map(normalize_match_text)
    working["nt_keyword"] = working["nt_keyword"].map(normalize_match_text)

    for metric in PERFORMANCE_METRICS:
        working[metric] = to_numeric_series(working[metric]).fillna(0)

    return collapse_cumulative_performance_rows(working, ["nt_source", "nt_detail", "nt_keyword"])


def match_paid_with_performance(
    paid_df: pd.DataFrame,
    performance_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if paid_df.empty:
        empty = paid_df.copy()
        for metric in PERFORMANCE_METRICS:
            empty[metric] = 0
        empty["match_status"] = "미매칭"
        empty["is_matched"] = False
        empty["match_key"] = ""
        empty["matched_nt_source"] = ""
        empty["match_method"] = ""
        empty["perf_debug_rows"] = ""
        empty["perf_latest_collected_at"] = ""
        empty["unmatched_reason"] = "유상작업 데이터 없음"
        return empty, empty.copy()

    perf_lookup = performance_df.copy()
    perf_lookup["match_key"] = perf_lookup.apply(
        lambda row: build_match_key(row["nt_source"], row["nt_detail"], row["nt_keyword"]),
        axis=1,
    )
    perf_map = perf_lookup.set_index("match_key").to_dict(orient="index")
    perf_candidates = perf_lookup.to_dict(orient="records")
    used_perf_keys: set[str] = set()

    records: list[dict] = []
    for _, row in paid_df.iterrows():
        matched: dict | None = None
        matched_source = ""
        match_method = ""

        for candidate_source in build_nt_source_candidates(row):
            key = build_match_key(candidate_source, row["match_nt_detail"], row["match_nt_keyword"])
            if key in perf_map and key not in used_perf_keys:
                matched = perf_map[key]
                matched_source = candidate_source
                match_method = "direct_key"
                used_perf_keys.add(key)
                break

        if matched is None:
            reverse_match = find_reverse_match(row, perf_candidates, used_perf_keys)
            if reverse_match is not None:
                matched = reverse_match
                matched_source = reverse_match.get("nt_source", "")
                match_method = "reverse_inference"
                used_perf_keys.add(reverse_match.get("match_key", ""))

        record = row.to_dict()
        record["match_key"] = build_match_key(
            matched_source or row["match_nt_source"],
            row["match_nt_detail"],
            row["match_nt_keyword"],
        )
        record["matched_nt_source"] = matched_source

        if matched is not None:
            for metric in PERFORMANCE_METRICS:
                record[metric] = matched.get(metric, 0)
            record["match_status"] = "매칭"
            record["is_matched"] = True
            record["match_method"] = match_method
            record["perf_debug_rows"] = matched.get("perf_debug_rows", "")
            record["perf_latest_collected_at"] = matched.get("perf_latest_collected_at", "")
            record["unmatched_reason"] = ""
        else:
            for metric in PERFORMANCE_METRICS:
                record[metric] = 0
            record["match_status"] = "미매칭"
            record["is_matched"] = False
            record["match_method"] = ""
            record["perf_debug_rows"] = ""
            record["perf_latest_collected_at"] = ""
            record["unmatched_reason"] = infer_unmatched_reason(row)

        records.append(record)

    matched_df = pd.DataFrame(records)
    unmatched_df = matched_df.loc[matched_df["match_status"] == "미매칭"].copy()
    return matched_df, unmatched_df


def build_primary_nt_source(row: pd.Series) -> str:
    candidates = build_nt_source_candidates(row)
    return candidates[0] if candidates else ""


def build_nt_source_candidates(row: pd.Series) -> list[str]:
    platform_group = clean_text(row.get("platform_group", ""))
    platform_value = clean_text(row.get("platform", ""))

    if platform_group == "블로그":
        return ["naverblog", "naver"]
    if platform_group == "인스타그램":
        return ["instagram"]
    if platform_group == "유튜브":
        return ["youtube"]
    if platform_group == "X":
        return ["x", "twitter"]
    if platform_group == "브랜드커넥트":
        return ["nshoplive"]
    if platform_group == "커뮤니티":
        normalized_platform = normalize_nt_source(platform_value)
        return [normalized_platform] if normalized_platform else []
    return [normalize_nt_source(platform_group)]


def build_match_key(nt_source: str, nt_detail: str, nt_keyword: str) -> str:
    return "||".join(
        [
            normalize_nt_source(nt_source),
            normalize_match_text(nt_detail),
            normalize_match_text(nt_keyword),
        ]
    )


def infer_unmatched_reason(row: pd.Series) -> str:
    if not row.get("match_nt_keyword"):
        return "직접 매칭용 키워드 없음"
    if not row.get("match_nt_detail"):
        return "작업자 없음"
    if not row.get("match_nt_source"):
        return "nt_source 추론 불가"
    return "성과 DB에 일치 키 없음"


def extract_collection_date(df: pd.DataFrame) -> pd.Series:
    candidate_columns = {
        "수집일",
        "수집일자",
        "조회시작일",
        "조회종료일",
        "집계일",
        "기준일",
        "date",
        "collectedat",
    }
    for column in df.columns:
        if sanitize_column_name(column) in candidate_columns:
            return parse_flexible_date_series(df[column])
    return pd.Series([pd.NaT] * len(df), index=df.index, dtype="datetime64[ns]")


def collapse_cumulative_performance_rows(
    working: pd.DataFrame,
    key_columns: list[str],
) -> pd.DataFrame:
    if working.empty:
        return pd.DataFrame(
            columns=key_columns
            + PERFORMANCE_METRICS
            + ["perf_debug_rows", "perf_latest_collected_at"]
        )

    working = working.copy()
    working["effective_collected_at"] = working["collected_at"]

    if working["effective_collected_at"].notna().sum() == 0:
        grouped = (
            working.groupby(key_columns, dropna=False, as_index=False)[PERFORMANCE_METRICS]
            .sum()
            .sort_values(key_columns)
            .reset_index(drop=True)
        )
        grouped["perf_debug_rows"] = ""
        grouped["perf_latest_collected_at"] = ""
        return grouped

    collapsed_rows: list[dict] = []
    for _, group in working.groupby(key_columns, dropna=False, sort=False):
        if group.empty:
            continue

        if group["effective_collected_at"].notna().any():
            latest_timestamp = group["effective_collected_at"].max()
            latest_group = group.loc[group["effective_collected_at"].eq(latest_timestamp)].copy()
        else:
            latest_group = group.sort_values("row_order").tail(1).copy()

        if latest_group.empty:
            continue

        row_data = {
            "nt_source": latest_group.iloc[0]["nt_source"],
            "nt_detail": latest_group.iloc[0]["nt_detail"],
            "nt_keyword": latest_group.iloc[0]["nt_keyword"],
            "perf_debug_rows": " | ".join(
                latest_group.apply(
                    lambda row: (
                        f"{clean_text(row.get('channel_type'))}/"
                        f"{clean_text(row.get('nt_source'))}/"
                        f"{clean_text(row.get('nt_detail'))}/"
                        f"{clean_text(row.get('nt_keyword'))}"
                    ),
                    axis=1,
                ).tolist()
            ),
            "perf_latest_collected_at": (
                latest_group["collected_at"].dropna().max().strftime("%Y-%m-%d")
                if latest_group["collected_at"].notna().any()
                else ""
            ),
        }

        for metric in LATEST_SNAPSHOT_METRICS:
            row_data[metric] = latest_group[metric].sum()

        for metric in MAX_VALUE_METRICS:
            row_data[metric] = group[metric].max()

        collapsed_rows.append(row_data)

    return pd.DataFrame(collapsed_rows).sort_values(key_columns).reset_index(drop=True)


def find_reverse_match(
    row: pd.Series,
    perf_candidates: list[dict],
    used_perf_keys: set[str],
) -> dict | None:
    source_candidates = set(build_nt_source_candidates(row))
    worker = row.get("match_nt_detail", "")
    if not source_candidates or not worker:
        return None

    relevant = [
        candidate
        for candidate in perf_candidates
        if (
            candidate.get("match_key", "") not in used_perf_keys
            and candidate.get("nt_source") in source_candidates
            and candidate.get("nt_detail") == worker
        )
    ]
    if not relevant:
        return None

    scored: list[tuple[int, dict]] = []
    for candidate in relevant:
        score = reverse_match_score(row, candidate)
        if score > 0:
            scored.append((score, candidate))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    top_score, top_candidate = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -1

    if top_score < 2:
        return None
    if top_score == second_score:
        return None
    return top_candidate


def reverse_match_score(row: pd.Series, candidate: dict) -> int:
    score = 0
    paid_product = normalize_product_token(row.get("product_name", ""))
    candidate_keyword = normalize_product_token(candidate.get("nt_keyword", ""))
    paid_keyword = normalize_match_text(row.get("keyword", ""))

    if paid_keyword and paid_keyword == candidate.get("nt_keyword", ""):
        score += 5

    if paid_product and candidate_keyword:
        if paid_product in candidate_keyword or candidate_keyword in paid_product:
            score += 3

    paid_date = row.get("date")
    keyword_date = extract_date_from_keyword(candidate.get("nt_keyword", ""))
    if pd.notna(paid_date) and keyword_date is not None:
        if abs((paid_date.normalize() - keyword_date).days) <= 21:
            score += 2

    if score == 0 and candidate_keyword and candidate_keyword not in {"-", "shoppinglive"}:
        score += 1

    return score


def sanitize_column_name(value: object) -> str:
    text = clean_text(value)
    text = text.replace(" ", "")
    text = text.replace("/", "_")
    text = text.replace("(", "")
    text = text.replace(")", "")
    text = text.replace(".", "")
    text = text.replace("-", "")
    text = text.replace("_", "")
    return text.lower()


def clean_transfer_status(value: object) -> str:
    text = clean_text(value).lower()
    if text in {"o", "y", "yes", "완료"}:
        return "완료"
    if text in {"x", "n", "no", "미이체"}:
        return "미이체"
    return "미기재" if text else "미기재"


def clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "nat", "none"}:
        return ""
    return text


def normalize_match_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value)).lower()
    return re.sub(r"\s+", "", text)


def normalize_nt_source(value: object) -> str:
    text = normalize_match_text(value)
    aliases = {
        "blog": "naverblog",
        "블로그": "naverblog",
        "인스타": "instagram",
        "인스타그램": "instagram",
        "유튜브": "youtube",
        "youtube": "youtube",
        "x": "x",
        "twitter": "x",
        "커뮤니티": "community",
        "브랜드커넥트": "nshoplive",
        "naverblog": "naverblog",
        "naver": "naver",
        "instagram": "instagram",
        "nshoplive": "nshoplive",
        "toss": "toss",
        "cafe": "cafe",
        "카페": "cafe",
    }
    return aliases.get(text, text)


def normalize_product_token(value: object) -> str:
    text = normalize_match_text(value)
    return re.sub(r"[^a-z0-9가-힣]", "", text)


def extract_date_from_keyword(value: object) -> pd.Timestamp | None:
    text = clean_text(value)
    match = re.match(r"^(\d{8}|\d{6})", text)
    if not match:
        return None

    date_token = match.group(1)
    if len(date_token) == 8:
        parsed = pd.to_datetime(date_token, format="%Y%m%d", errors="coerce")
    else:
        parsed = pd.to_datetime(date_token, format="%y%m%d", errors="coerce")

    if pd.isna(parsed):
        return None
    return parsed.normalize()


def to_datetime_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="datetime64[ns]")
    return parse_flexible_date_series(series)


def to_numeric_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="float64")
    cleaned = (
        series.astype(str)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "-": pd.NA})
        .str.replace(",", "", regex=False)
        .str.replace("₩", "", regex=False)
        .str.replace("원", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace(r"[^\d\.\-]", "", regex=True)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def get_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([""] * len(df), index=df.index)


def parse_flexible_date_series(series: pd.Series) -> pd.Series:
    text = (
        series.astype(str)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "NaT": pd.NA, "None": pd.NA})
    )
    normalized = (
        text.str.replace(r"\s+", "", regex=True)
        .str.replace(".", "-", regex=False)
        .str.replace("/", "-", regex=False)
    )

    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    formats = ["%Y-%m-%d", "%y-%m-%d", "%Y%m%d", "%y%m%d"]

    for fmt in formats:
        mask = parsed.isna() & normalized.notna()
        if not mask.any():
            break
        parsed.loc[mask] = pd.to_datetime(normalized.loc[mask], format=fmt, errors="coerce")

    remaining = parsed.isna() & normalized.notna()
    if remaining.any():
        parsed.loc[remaining] = pd.to_datetime(normalized.loc[remaining], errors="coerce")

    return parsed
