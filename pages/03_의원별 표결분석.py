"""pages/03_의원별_표결분석.py — 의원별 표결분석 (독립 실행형: 공통 함수 없이 이 파일 안에 전부 포함)"""

import re
import time

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="의원별 표결분석", layout="wide")
st.title("03. 의원별 표결분석")

# ============================================================
# API 설정값
# ============================================================
BILL_LIST_API_URL = "https://open.assembly.go.kr/portal/openapi/ALLBILLV2"
VOTE_API_URL = "https://open.assembly.go.kr/portal/openapi/nojepdqqaweusdfbi"
DEFAULT_TIMEOUT = 8      # 너무 길게 기다리지 않고 빨리 실패해서 샘플 데이터로 전환할 수 있게 함

# 일부 공공기관 서버는 requests 라이브러리 기본 User-Agent(python-requests/x.x)를
# 봇 트래픽으로 간주해 차단하는 경우가 있어, 일반 브라우저처럼 보이는 헤더를 사용한다.
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}
REQUEST_DELAY = 0.15

VOTE_RESULT_MAP = {
    "찬성": "찬성", "가결": "찬성",
    "반대": "반대", "부결": "반대",
    "기권": "기권",
    "불참": "불참", "결석": "불참", "청가": "불참", "출장": "불참",
}
VALID_VOTE_VALUES = ["찬성", "반대", "기권"]


def get_api_key():
    try:
        return st.secrets["OPEN_ASSEMBLY_API_KEY"]
    except Exception:
        return None


def call_api(base_url, params, page_index=1, page_size=100):
    api_key = get_api_key()
    if not api_key:
        return [], 0, "API 키가 설정되지 않았습니다."

    query = {"KEY": api_key, "Type": "json", "pIndex": page_index, "pSize": page_size}
    query.update({k: v for k, v in params.items() if v not in (None, "")})

    # 국내 공공 API 서버 응답 지연/일시 오류 대비 최대 2회 재시도
    last_error = None
    resp = None
    for attempt in range(1):  # IP 차단 등 구조적 문제면 재시도해도 소용없어 1회만 시도
        try:
            resp = requests.get(base_url, params=query, headers=REQUEST_HEADERS, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            last_error = None
            break
        except requests.exceptions.RequestException as e:
            last_error = e
            time.sleep(1)
    if last_error is not None:
        return [], 0, f"API 호출 실패: {last_error}"

    try:
        data = resp.json()
    except ValueError:
        return [], 0, "API 응답을 JSON으로 해석할 수 없습니다."

    if "RESULT" in data:
        return [], 0, f"[{data['RESULT'].get('CODE')}] {data['RESULT'].get('MESSAGE')}"

    endpoint_key = next(iter(data.keys()), None)
    if endpoint_key is None:
        return [], 0, "API 응답 구조를 해석할 수 없습니다."

    total_count, rows = 0, []
    for section in data[endpoint_key]:
        if "head" in section:
            for h in section["head"]:
                if "list_total_count" in h:
                    total_count = h["list_total_count"]
                if "RESULT" in h and h["RESULT"].get("CODE") not in ("INFO-000", None):
                    return [], 0, f"[{h['RESULT'].get('CODE')}] {h['RESULT'].get('MESSAGE')}"
        if "row" in section:
            rows = section["row"]
    return rows, total_count, None


def fetch_all_pages(base_url, params, page_size=100, max_pages=20, progress_label=None):
    all_rows, page, total_count = [], 1, None
    bar = st.progress(0.0, text=progress_label) if progress_label else None
    while True:
        rows, total_count, err = call_api(base_url, params, page_index=page, page_size=page_size)
        if err:
            if bar:
                bar.empty()
            return all_rows, err
        all_rows.extend(rows)
        if bar and total_count:
            bar.progress(min(len(all_rows) / max(total_count, 1), 1.0), text=progress_label)
        if not rows or len(all_rows) >= total_count or page >= max_pages:
            break
        page += 1
        time.sleep(REQUEST_DELAY)
    if bar:
        bar.empty()
    if total_count and len(all_rows) < total_count:
        st.info(f"전체 {total_count}건 중 {len(all_rows)}건만 조회했습니다 (페이지 제한: {max_pages}).")
    return all_rows, None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bill_list(eraco, bill_kind=None, rgs_conf_rslt=None, max_pages=30):
    params = {"ERACO": eraco, "BILL_KND": bill_kind, "RGS_CONF_RSLT": rgs_conf_rslt}
    rows, err = fetch_all_pages(BILL_LIST_API_URL, params, page_size=100, max_pages=max_pages,
                                 progress_label="의안 목록 조회 중...")
    if err:
        st.warning(f"의안 목록 조회 오류: {err}")
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_vote_info_single(bill_id, age):
    rows, err = fetch_all_pages(VOTE_API_URL, {"AGE": age, "BILL_ID": bill_id}, page_size=300, max_pages=5)
    if err:
        return pd.DataFrame(), err
    return pd.DataFrame(rows), None


def fetch_vote_info_bulk(bill_ids, age, max_bills=30):
    if len(bill_ids) > max_bills:
        st.warning(f"선택된 의안이 {len(bill_ids)}건이라 상위 {max_bills}건만 조회합니다.")
        bill_ids = bill_ids[:max_bills]
    all_dfs, errors = [], []
    if bill_ids:
        bar = st.progress(0.0, text="의안별 표결정보 조회 중...")
        for i, bid in enumerate(bill_ids):
            df, err = fetch_vote_info_single(bid, age)
            if err:
                errors.append(f"{bid}: {err}")
            elif not df.empty:
                all_dfs.append(df)
            bar.progress((i + 1) / len(bill_ids), text=f"의안별 표결정보 조회 중... ({i+1}/{len(bill_ids)})")
            time.sleep(REQUEST_DELAY)
        bar.empty()
    if errors:
        st.warning(f"{len(errors)}건의 의안에서 표결정보를 가져오지 못해 분석에서 제외했습니다.")
    if not all_dfs:
        return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)


def standardize_vote_result(value):
    if pd.isna(value):
        return None
    return VOTE_RESULT_MAP.get(str(value).strip(), str(value).strip())


def clean_party_name(value):
    if pd.isna(value):
        return "정보없음"
    name = re.sub(r"\s+", "", str(value).strip())
    return name if name else "정보없음"


def standardize_vote_date(value):
    if pd.isna(value):
        return pd.NaT
    value = str(value).strip()
    for fmt in ("%Y%m%d %H%M%S", "%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return pd.to_datetime(value, format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.to_datetime(value, errors="coerce")


def standardize_vote_dataframe(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["assembly_no", "bill_id", "bill_no", "bill_name", "vote_date",
                                      "member_id", "member_name", "party_name", "vote_result", "committee_name"])
    out = pd.DataFrame()
    out["assembly_no"] = df.get("AGE")
    out["bill_id"] = df.get("BILL_ID")
    out["bill_no"] = df.get("BILL_NO")
    out["bill_name"] = df.get("BILL_NAME")
    out["vote_date"] = df["VOTE_DATE"].apply(standardize_vote_date) if "VOTE_DATE" in df.columns else pd.NaT
    out["member_id"] = df.get("MEMBER_NO")
    out["member_name"] = df.get("HG_NM")
    out["party_name"] = df["POLY_NM"].apply(clean_party_name) if "POLY_NM" in df.columns else "정보없음"
    out["vote_result"] = (
        df["RESULT_VOTE_MOD"].apply(standardize_vote_result) if "RESULT_VOTE_MOD" in df.columns else None
    )
    out["committee_name"] = df.get("CURR_COMMITTEE")
    return out.drop_duplicates(subset=["bill_id", "member_id"], keep="first")


def standardize_bill_list_dataframe(df):
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.drop_duplicates(subset=["BILL_ID"], keep="first").copy()
    for col in ("PPSL_DT", "RGS_RSLN_DT"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def generate_sample_vote_data(n_bills=15, n_members=60, seed=42):
    """⚠️ 실제 국회 표결 데이터가 아니며 통계적 의미가 없다. UI/기능 시연 전용."""
    rng = np.random.default_rng(seed)
    parties = ["더불어민주당", "국민의힘", "조국혁신당", "개혁신당", "무소속"]
    party_weights = [0.42, 0.38, 0.08, 0.06, 0.06]
    members = [f"샘플의원{i+1:03d}" for i in range(n_members)]
    member_party = rng.choice(parties, size=n_members, p=party_weights)
    member_ids = [f"SAMPLE{i+1:05d}" for i in range(n_members)]
    bills = [f"샘플법률{i+1:03d} 일부개정법률안" for i in range(n_bills)]
    bill_ids = [f"SAMPLE_BILL_{i+1:03d}" for i in range(n_bills)]
    committees = ["기획재정위원회", "교육위원회", "행정안전위원회", "보건복지위원회", "환경노동위원회"]
    rows = []
    base_date = pd.Timestamp("2024-06-01")
    for b_idx, (bid, bname) in enumerate(zip(bill_ids, bills)):
        vote_date = base_date + pd.Timedelta(days=int(rng.integers(0, 400)))
        committee = rng.choice(committees)
        party_lean = {p: rng.uniform(0.3, 0.95) for p in parties}
        for m_name, m_party, m_id in zip(members, member_party, member_ids):
            r = rng.random()
            if r < 0.05:
                result = "불참"
            else:
                yes_prob = party_lean[m_party]
                result = "찬성" if rng.random() < yes_prob else rng.choice(["반대", "기권"], p=[0.85, 0.15])
            rows.append({
                "assembly_no": "22", "bill_id": bid, "bill_no": f"21{b_idx+10000}",
                "bill_name": bname, "vote_date": vote_date,
                "member_id": m_id, "member_name": m_name, "party_name": m_party,
                "vote_result": result, "committee_name": committee,
            })
    return pd.DataFrame(rows)


# ---------------- 분석 지표 함수 ----------------
def compute_member_agreement_with_party(vote_df):
    """
    의원별 '소속 정당 다수 입장과의 일치율'을 계산한다.
    '정당 다수 입장과 다른 표결'로만 표현하며 '당론 위반'이라는 표현은 사용하지 않는다
    (공식 당론 자료가 없어 사후적으로 계산된 통계적 개념일 뿐임).
    """
    df = vote_df[vote_df["vote_result"].isin(VALID_VOTE_VALUES)].copy()
    if df.empty:
        return pd.DataFrame()
    party_majority = (
        df.groupby(["bill_id", "party_name", "vote_result"]).size().reset_index(name="count")
        .sort_values("count", ascending=False).drop_duplicates(subset=["bill_id", "party_name"])
        .rename(columns={"vote_result": "party_majority_position"})[["bill_id", "party_name", "party_majority_position"]]
    )
    merged = df.merge(party_majority, on=["bill_id", "party_name"], how="left")
    merged["matches_party_majority"] = merged["vote_result"] == merged["party_majority_position"]
    summary = merged.groupby(["member_id", "member_name", "party_name"]).agg(
        total_votes=("vote_result", "count"),
        matches_party_majority_count=("matches_party_majority", "sum"),
    ).reset_index()
    summary["agreement_rate"] = summary["matches_party_majority_count"] / summary["total_votes"].replace(0, np.nan)
    summary["diff_from_party_majority_count"] = summary["total_votes"] - summary["matches_party_majority_count"]
    return summary


def compute_member_similarity(vote_df, member_id, min_common_votes=10):
    """유사도 = 두 의원이 동시에 표결한 의안 중 동일한 선택을 한 비율. 공동 표결 수가 적으면 왜곡될 수 있어 최소 기준을 둠."""
    df = vote_df[vote_df["vote_result"].isin(VALID_VOTE_VALUES)]
    if df.empty or member_id not in df["member_id"].values:
        return pd.DataFrame()
    a_votes = df[df["member_id"] == member_id][["bill_id", "vote_result"]].rename(columns={"vote_result": "vote_a"})
    others = df[df["member_id"] != member_id]
    merged = others.merge(a_votes, on="bill_id", how="inner")
    merged["match"] = merged["vote_result"] == merged["vote_a"]
    result = merged.groupby(["member_id", "member_name", "party_name"]).agg(
        common_votes=("match", "count"), matching_votes=("match", "sum")
    ).reset_index()
    result = result[result["common_votes"] >= min_common_votes]
    result["similarity"] = result["matching_votes"] / result["common_votes"]
    return result.sort_values("similarity", ascending=False)


# ============================================================
# 사이드바
# ============================================================
st.sidebar.header("조회 조건")
use_sample = st.sidebar.checkbox("샘플 데이터 사용", value=False)
eraco = st.sidebar.selectbox("국회대수", ["제22대", "제21대", "제20대"], index=0)
max_bills = st.sidebar.slider("조회할 최대 의안 수", 5, 100, 20, step=5)

if use_sample:
    st.info("⚠️ 현재 샘플 데이터를 사용 중입니다. 실제 통계가 아니며 기능 시연용입니다.")
    vote_df = generate_sample_vote_data(n_bills=max_bills)
else:
    bill_list_raw = fetch_bill_list(eraco=eraco, bill_kind="법률안", rgs_conf_rslt="원안가결", max_pages=5)
    bill_list = standardize_bill_list_dataframe(bill_list_raw)
    if bill_list.empty:
        st.warning("의안 목록을 가져오지 못했습니다. 샘플 데이터를 사용해주세요.")
        st.stop()
    age_num = eraco.replace("제", "").replace("대", "")
    bill_ids = bill_list["BILL_ID"].dropna().unique().tolist()
    vote_raw = fetch_vote_info_bulk(bill_ids, age=age_num, max_bills=max_bills)
    vote_df = standardize_vote_dataframe(vote_raw)

if vote_df.empty:
    st.warning("표시할 표결 데이터가 없습니다.")
    st.stop()

parties = sorted(vote_df["party_name"].dropna().unique().tolist())
selected_party = st.sidebar.selectbox("정당 선택", ["전체"] + parties)
filtered = vote_df if selected_party == "전체" else vote_df[vote_df["party_name"] == selected_party]

members = sorted(filtered["member_name"].dropna().unique().tolist())
if not members:
    st.warning("선택 조건에 맞는 의원이 없습니다.")
    st.stop()
selected_member = st.sidebar.selectbox("의원 선택", members)

member_row = filtered[filtered["member_name"] == selected_member]
if member_row.empty:
    st.warning("선택한 의원의 표결 데이터가 없습니다.")
    st.stop()
member_id = member_row["member_id"].iloc[0]

st.subheader(f"{selected_member} 의원 표결 요약")
total_votes = len(member_row)
yes_c = int((member_row["vote_result"] == "찬성").sum())
no_c = int((member_row["vote_result"] == "반대").sum())
abstain_c = int((member_row["vote_result"] == "기권").sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("전체 표결 참여 건수", f"{total_votes:,}")
c2.metric("찬성 건수", f"{yes_c:,}")
c3.metric("반대 건수", f"{no_c:,}")
c4.metric("기권 건수", f"{abstain_c:,}")

agreement_df = compute_member_agreement_with_party(vote_df)
member_agreement = agreement_df[agreement_df["member_id"] == member_id] if not agreement_df.empty else pd.DataFrame()
if not member_agreement.empty:
    row = member_agreement.iloc[0]
    c5, c6 = st.columns(2)
    c5.metric("소속 정당 다수 입장과의 일치율", f"{row['agreement_rate']:.1%}")
    c6.metric("정당 다수 입장과 다른 표결 건수", f"{int(row['diff_from_party_majority_count']):,}")
    st.caption("⚠️ 공식 당론 자료가 없어 '정당 다수 입장'을 기준으로 계산한 것이며, '당론 위반'을 의미하지 않습니다.")

st.subheader("의원별 표결 성향")
tendency = member_row["vote_result"].value_counts(normalize=True).reset_index()
tendency.columns = ["vote_result", "ratio"]
st.plotly_chart(px.pie(tendency, names="vote_result", values="ratio", hole=0.4), use_container_width=True)

st.subheader("표결이 유사한 의원 상위 10명")
min_common = st.slider("최소 공동 표결 수 기준", 1, 50, 5,
                        help="공동 참여 의안이 너무 적으면 유사도가 왜곡될 수 있어 최소 기준을 조정할 수 있습니다.")
sim_df = compute_member_similarity(vote_df, member_id, min_common_votes=min_common)
if not sim_df.empty:
    st.dataframe(sim_df.head(10)[["member_name", "party_name", "common_votes", "similarity"]],
                 hide_index=True, use_container_width=True)
else:
    st.info("조건을 만족하는 유사 의원이 없습니다. 최소 공동 표결 수를 낮춰보세요.")

st.subheader("의원별 상세 표결 내역")
search = st.text_input("의안명 검색")
detail = member_row[["vote_date", "bill_name", "bill_no", "vote_result", "committee_name"]].sort_values(
    "vote_date", ascending=False)
if search:
    detail = detail[detail["bill_name"].str.contains(search, na=False)]
st.dataframe(detail, hide_index=True, use_container_width=True)

st.download_button(
    "의원별 표결 내역 CSV 다운로드",
    data=detail.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"{selected_member}_votes.csv",
    mime="text/csv",
)
