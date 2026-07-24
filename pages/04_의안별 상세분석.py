"""pages/04_의안별_상세분석.py — 의안별 상세분석 (독립 실행형: 공통 함수 없이 이 파일 안에 전부 포함)"""

import re
import time

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="의안별 상세분석", layout="wide")
st.title("04. 의안별 상세분석")

# ============================================================
# API 설정값
# ============================================================
BILL_LIST_API_URL = "https://open.assembly.go.kr/portal/openapi/ALLBILLV2"
VOTE_API_URL = "https://open.assembly.go.kr/portal/openapi/nojepdqqaweusdfbi"
BILL_DETAIL_API_URL = "https://open.assembly.go.kr/portal/openapi/BILLINFODETAIL"
BILL_PROPOSER_API_URL = "https://open.assembly.go.kr/portal/openapi/BILLINFOPPSR"
DEFAULT_TIMEOUT = 15     # 국내 공공 API 응답 지연을 고려해 여유 있게 설정

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

# ============================================================
# 국회대수·기간별 여당/야당 실제 이력 매핑 (수정 가능한 설정값)
# 표결일(vote_date) 기준으로 자동 적용됨. 정권 교체 등으로 정보가 바뀌면 여기만 수정하면 됨.
# 형식: (기간 시작일, 기간 종료일(없으면 None=현재까지), 여당, 주요 야당)
# ============================================================
RULING_OPPOSITION_PERIODS = [
    (pd.Timestamp("2016-05-30"), pd.Timestamp("2017-05-09"), "새누리당", "더불어민주당"),
    (pd.Timestamp("2017-05-10"), pd.Timestamp("2020-05-29"), "더불어민주당", "새누리당"),
    (pd.Timestamp("2020-05-30"), pd.Timestamp("2022-05-09"), "더불어민주당", "국민의힘"),
    (pd.Timestamp("2022-05-10"), pd.Timestamp("2024-05-29"), "국민의힘", "더불어민주당"),
    (pd.Timestamp("2024-05-30"), pd.Timestamp("2025-06-03"), "국민의힘", "더불어민주당"),
    (pd.Timestamp("2025-06-04"), None, "더불어민주당", "국민의힘"),
]


def get_ruling_opposition(vote_date):
    """표결일을 기준으로 그 시점의 여당/주요 야당을 반환한다. 해당 기간이 없으면 (None, None)."""
    if pd.isna(vote_date):
        return None, None
    d = pd.Timestamp(vote_date).normalize()
    for start, end, ruling, opposition in RULING_OPPOSITION_PERIODS:
        if d >= start and (end is None or d <= end):
            return ruling, opposition
    return None, None


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

    # 국내 공공 API 서버 응답 지연/일시 오류 대비 재시도 (지수 백오프: 1초 → 2초 → 4초)
    last_error = None
    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(base_url, params=query, headers=REQUEST_HEADERS, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            last_error = None
            break
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < 2:
                time.sleep(2 ** attempt)
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
    """⚠️ 실패 시 예외를 던진다 (빈 결과를 캐싱하지 않기 위함)."""
    params = {"ERACO": eraco, "BILL_KND": bill_kind, "RGS_CONF_RSLT": rgs_conf_rslt}
    rows, err = fetch_all_pages(BILL_LIST_API_URL, params, page_size=100, max_pages=max_pages,
                                 progress_label="의안 목록 조회 중...")
    if err:
        raise RuntimeError(err)
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_vote_info_single(bill_id, age):
    """⚠️ 실패 시 예외를 던진다 (빈 결과를 캐싱하지 않기 위함)."""
    rows, err = fetch_all_pages(VOTE_API_URL, {"AGE": age, "BILL_ID": bill_id}, page_size=300, max_pages=5)
    if err:
        raise RuntimeError(err)
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bill_detail(bill_id):
    """의안 상세정보(BILLINFODETAIL)를 조회한다. 실패해도 조용히 None 반환 (부가정보라 화면 흐름을 막지 않음)."""
    rows, err = fetch_all_pages(BILL_DETAIL_API_URL, {"BILL_ID": bill_id}, page_size=10, max_pages=1)
    if err or not rows:
        raise RuntimeError(err or "결과 없음")
    return rows[0]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bill_proposer(bill_id):
    """의안 제안자정보(BILLINFOPPSR)를 조회한다. 실패 시 예외를 던진다 (빈 결과를 캐싱하지 않기 위함)."""
    rows, err = fetch_all_pages(BILL_PROPOSER_API_URL, {"BILL_ID": bill_id}, page_size=50, max_pages=2)
    if err:
        raise RuntimeError(err)
    return pd.DataFrame(rows)


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


def compute_bipartisan_conflict(vote_df):
    """
    갈등도 = abs(여당 찬성률 - 야당 찬성률).
    여당/야당은 표결일(vote_date) 기준으로 RULING_OPPOSITION_PERIODS 매핑을 자동 적용한다.
    (공식 당론 자료가 아니라 국회대수·기간별 실제 여야 구성 이력을 코드에 정리해둔 것)
    """
    df = vote_df[vote_df["vote_result"].isin(VALID_VOTE_VALUES)].copy()
    if df.empty or "vote_date" not in df.columns:
        return pd.DataFrame()

    ruling_opp = df["vote_date"].apply(get_ruling_opposition)
    df["ruling_party"] = [x[0] for x in ruling_opp]
    df["opposition_party"] = [x[1] for x in ruling_opp]

    df["bloc"] = np.where(df["party_name"] == df["ruling_party"], "여당",
                    np.where(df["party_name"] == df["opposition_party"], "야당", "기타"))
    df = df[df["bloc"].isin(["여당", "야당"])]
    if df.empty:
        return pd.DataFrame()
    yes_rate = (
        df.assign(is_yes=(df["vote_result"] == "찬성").astype(int))
        .groupby(["bill_id", "bill_name", "bloc"])["is_yes"].mean().unstack().reset_index()
    )
    for col in ["여당", "야당"]:
        if col not in yes_rate.columns:
            yes_rate[col] = np.nan
    yes_rate["conflict_index"] = (yes_rate["여당"] - yes_rate["야당"]).abs()
    yes_rate["bipartisan_agreement_index"] = 1 - yes_rate["conflict_index"]
    return yes_rate.sort_values("conflict_index", ascending=False)


# ============================================================
# 사이드바
# ============================================================
st.sidebar.header("조회 조건")
use_sample = st.sidebar.checkbox("샘플 데이터 사용", value=False)
eraco = st.sidebar.selectbox("국회대수", ["제22대", "제21대", "제20대"], index=0)
if st.sidebar.button("🔄 캐시 지우고 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.subheader("여야 매핑 (자동 적용)")
st.sidebar.caption("API에 여당/야당 구분이 없어, 표결일 기준으로 아래 이력표를 코드에서 자동 적용합니다 (공식 당론 자료는 아님).")
with st.sidebar.expander("적용 중인 여야 이력표 보기"):
    mapping_display = pd.DataFrame(
        [
            {"기간 시작": s.strftime("%Y-%m-%d"), "기간 종료": (e.strftime("%Y-%m-%d") if e is not None else "현재"),
             "여당": r, "주요 야당": o}
            for s, e, r, o in RULING_OPPOSITION_PERIODS
        ]
    )
    st.dataframe(mapping_display, hide_index=True, use_container_width=True)
    st.caption("이 표는 파일 상단 RULING_OPPOSITION_PERIODS 에서 수정할 수 있습니다.")

if use_sample:
    st.info("⚠️ 현재 샘플 데이터를 사용 중입니다. 실제 통계가 아니며 기능 시연용입니다.")
    sample_df = generate_sample_vote_data(n_bills=15)
    bill_options = sample_df.drop_duplicates(subset=["bill_id"])[["bill_id", "bill_name"]]
else:
    try:
        bill_list_raw = fetch_bill_list(eraco=eraco, bill_kind="법률안", rgs_conf_rslt="원안가결", max_pages=5)
        bill_list = standardize_bill_list_dataframe(bill_list_raw)
    except RuntimeError as e:
        st.warning(f"의안 목록 조회 오류: {e}")
        bill_list = pd.DataFrame()

    if bill_list.empty:
        st.warning("의안 목록을 가져오지 못했습니다. 샘플 데이터를 사용해주세요.")
        st.stop()
    bill_options = bill_list.rename(columns={"BILL_ID": "bill_id", "BILL_NM": "bill_name"})[["bill_id", "bill_name"]]

search_kw = st.text_input("의안명 검색")
filtered_options = (
    bill_options[bill_options["bill_name"].str.contains(search_kw, na=False)] if search_kw else bill_options
)
if filtered_options.empty:
    st.warning("검색 결과가 없습니다.")
    st.stop()

selected_bill_name = st.selectbox("의안 선택", filtered_options["bill_name"].tolist())
selected_bill_id = filtered_options[filtered_options["bill_name"] == selected_bill_name]["bill_id"].iloc[0]

age_num = eraco.replace("제", "").replace("대", "")

if use_sample:
    bill_vote_df = sample_df[sample_df["bill_id"] == selected_bill_id]
    detail_info = None
    proposer_df = pd.DataFrame()
else:
    try:
        vote_raw = fetch_vote_info_single(selected_bill_id, age_num)
    except RuntimeError:
        vote_raw = pd.DataFrame()
    bill_vote_df = standardize_vote_dataframe(vote_raw)

    try:
        detail_info = fetch_bill_detail(selected_bill_id)
    except RuntimeError:
        detail_info = None

    try:
        proposer_df = fetch_bill_proposer(selected_bill_id)
    except RuntimeError:
        proposer_df = pd.DataFrame()

if bill_vote_df.empty:
    st.warning("이 의안에 대한 표결 데이터가 없습니다.")
    st.stop()

st.subheader("의안 기본 정보")
if detail_info:
    info_cols = st.columns(3)
    info_cols[0].markdown(f"**의안번호**: {detail_info.get('BILL_NO', '-')}")
    info_cols[0].markdown(f"**의안명**: {detail_info.get('BILL_NM', '-')}")
    info_cols[1].markdown(f"**제안일**: {detail_info.get('PPSL_DT', '-')}")
    info_cols[1].markdown(f"**소관위원회**: {detail_info.get('JRCMIT_NM', '-')}")
    info_cols[2].markdown(f"**본회의 심의결과**: {detail_info.get('RGS_CONF_RSLT', '-')}")
    info_cols[2].markdown(f"**본회의 의결일**: {detail_info.get('RGS_RSLN_DT', '-')}")
else:
    st.info("의안 상세정보를 불러오지 못했거나 샘플 데이터 모드입니다.")

if not proposer_df.empty:
    st.markdown("**제안자**")
    cols_to_show = [c for c in ["PPSR_NM", "PPSR_POLY_NM", "PPSR_KIND", "REP_DIV"] if c in proposer_df.columns]
    st.dataframe(proposer_df[cols_to_show], hide_index=True, use_container_width=True)

st.subheader("전체 찬성·반대·기권 수")
valid = bill_vote_df[bill_vote_df["vote_result"].isin(["찬성", "반대", "기권"])]
c1, c2, c3, c4 = st.columns(4)
c1.metric("찬성", int((valid["vote_result"] == "찬성").sum()))
c2.metric("반대", int((valid["vote_result"] == "반대").sum()))
c3.metric("기권", int((valid["vote_result"] == "기권").sum()))
c4.metric("불참", int((bill_vote_df["vote_result"] == "불참").sum()))

st.subheader("정당별 찬성·반대·기권 분포")
if not valid.empty:
    party_dist = valid.groupby(["party_name", "vote_result"]).size().reset_index(name="count")
    st.plotly_chart(px.bar(party_dist, x="party_name", y="count", color="vote_result", barmode="stack"),
                     use_container_width=True)

st.subheader("정당별 찬성률")
if not valid.empty:
    party_yes_rate = (
        valid.assign(is_yes=(valid["vote_result"] == "찬성").astype(int))
        .groupby("party_name")["is_yes"].mean().reset_index().rename(columns={"is_yes": "yes_rate"})
    )
    st.plotly_chart(px.bar(party_yes_rate, x="party_name", y="yes_rate"), use_container_width=True)

st.subheader("여야 갈등도 & 초당적 합의도")
conflict_df = compute_bipartisan_conflict(bill_vote_df)
if not conflict_df.empty:
    row = conflict_df.iloc[0]
    c5, c6 = st.columns(2)
    c5.metric("여야 갈등도", f"{row['conflict_index']:.2f}")
    c6.metric("초당적 합의도", f"{row['bipartisan_agreement_index']:.2f}")
    st.caption("갈등도 = abs(여당 찬성률 - 야당 찬성률). 표결일 기준 여야 이력표를 자동 적용함 (공식 당론 자료 아님).")
else:
    st.info("여야 매핑에 해당하는 정당 표결 데이터가 부족합니다.")

st.subheader("의원별 표결 결과 표")
st.dataframe(bill_vote_df[["member_name", "party_name", "vote_result", "committee_name"]],
             hide_index=True, use_container_width=True)

st.markdown(f"[관련 의안 상세정보 링크](https://likms.assembly.go.kr/bill/billDetail.do?billId={selected_bill_id})")

st.download_button(
    "의안별 표결 데이터 CSV 다운로드",
    data=bill_vote_df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"{selected_bill_id}_votes.csv",
    mime="text/csv",
)
