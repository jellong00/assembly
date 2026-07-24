"""pages/02_정당별_표결분석.py — 정당별 표결분석 (독립 실행형: 공통 함수 없이 이 파일 안에 전부 포함)"""

import re
import time

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="정당별 표결분석", layout="wide")
st.title("02. 정당별 표결분석")

# ============================================================
# API 설정값
# ============================================================
BILL_LIST_API_URL = "https://open.assembly.go.kr/portal/openapi/ALLBILLV2"
VOTE_API_URL = "https://open.assembly.go.kr/portal/openapi/nojepdqqaweusdfbi"
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
    """정상: {"<엔드포인트명>":[{"head":...},{"row":...}]} / 오류: {"RESULT":{"CODE":...,"MESSAGE":...}}"""
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


def fetch_vote_info_bulk(bill_ids, age, max_bills=30):
    if len(bill_ids) > max_bills:
        st.warning(f"선택된 의안이 {len(bill_ids)}건이라 상위 {max_bills}건만 조회합니다.")
        bill_ids = bill_ids[:max_bills]
    all_dfs, errors = [], []
    if bill_ids:
        bar = st.progress(0.0, text="의안별 표결정보 조회 중...")
        for i, bid in enumerate(bill_ids):
            try:
                df = fetch_vote_info_single(bid, age)
                if not df.empty:
                    all_dfs.append(df)
            except RuntimeError as e:
                errors.append(f"{bid}: {e}")
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
def compute_party_majority_ratio(vote_df):
    """다수 표결 비율 = max(찬성,반대,기권) / 정당 내 참여자 수 (불참 제외)"""
    df = vote_df[vote_df["vote_result"].isin(VALID_VOTE_VALUES)]
    if df.empty:
        return pd.DataFrame()
    grouped = df.groupby(["bill_id", "bill_name", "party_name", "vote_result"]).size().unstack(fill_value=0)
    for col in VALID_VOTE_VALUES:
        if col not in grouped.columns:
            grouped[col] = 0
    grouped["total"] = grouped[VALID_VOTE_VALUES].sum(axis=1)
    grouped["majority_ratio"] = grouped[VALID_VOTE_VALUES].max(axis=1) / grouped["total"].replace(0, np.nan)
    return grouped.reset_index()


def compute_rice_index(vote_df):
    """Rice Index = abs(찬성-반대) / (찬성+반대). 찬성·반대 모두 0이면 결측."""
    df = vote_df[vote_df["vote_result"].isin(["찬성", "반대"])]
    if df.empty:
        return pd.DataFrame()
    grouped = df.groupby(["bill_id", "bill_name", "party_name", "vote_result"]).size().unstack(fill_value=0)
    for col in ["찬성", "반대"]:
        if col not in grouped.columns:
            grouped[col] = 0
    denom = grouped["찬성"] + grouped["반대"]
    grouped["rice_index"] = np.where(denom == 0, np.nan, (grouped["찬성"] - grouped["반대"]).abs() / denom)
    return grouped.reset_index()


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
max_bills = st.sidebar.slider("조회할 최대 의안 수", 5, 100, 20, step=5)
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
    vote_df = generate_sample_vote_data(n_bills=max_bills)
else:
    try:
        bill_list_raw = fetch_bill_list(eraco=eraco, bill_kind="법률안", rgs_conf_rslt="원안가결", max_pages=5)
        bill_list = standardize_bill_list_dataframe(bill_list_raw)
    except RuntimeError as e:
        st.warning(f"의안 목록 조회 오류: {e}")
        bill_list = pd.DataFrame()

    if bill_list.empty:
        st.warning("의안 목록을 가져오지 못했습니다. 샘플 데이터를 사용하거나 조건을 조정해주세요.")
        st.stop()
    age_num = eraco.replace("제", "").replace("대", "")
    bill_ids = bill_list["BILL_ID"].dropna().unique().tolist()
    vote_raw = fetch_vote_info_bulk(bill_ids, age=age_num, max_bills=max_bills)
    vote_df = standardize_vote_dataframe(vote_raw)

if vote_df.empty:
    st.warning("표시할 표결 데이터가 없습니다.")
    st.stop()

parties = sorted(vote_df["party_name"].dropna().unique().tolist())
selected_parties = st.sidebar.multiselect("정당 선택 (비우면 전체)", parties, default=parties)
df = vote_df[vote_df["party_name"].isin(selected_parties)] if selected_parties else vote_df

st.subheader("정당별 찬성·반대·기권 비율")
valid = df[df["vote_result"].isin(["찬성", "반대", "기권"])]
if valid.empty:
    st.info("유효한 표결(찬성/반대/기권) 데이터가 부족합니다.")
else:
    party_dist = valid.groupby(["party_name", "vote_result"]).size().reset_index(name="count")
    party_total = party_dist.groupby("party_name")["count"].transform("sum")
    party_dist["ratio"] = party_dist["count"] / party_total
    st.plotly_chart(px.bar(party_dist, x="party_name", y="ratio", color="vote_result", barmode="stack",
                            labels={"party_name": "정당", "ratio": "비율", "vote_result": "표결결과"},
                            text=party_dist["ratio"].apply(lambda x: f"{x:.0%}")),
                     use_container_width=True)
    st.caption("각 막대는 정당 내 표결 건수를 100%로 두고, 찬성/반대/기권이 차지하는 비율을 나타냅니다.")

st.subheader("정당별 평균 표결 참여율")
total_by_member = df.groupby(["party_name", "member_id"]).size().reset_index(name="votes")
participation = df[df["vote_result"] != "불참"].groupby(["party_name", "member_id"]).size().reset_index(name="participated")
part_merged = total_by_member.merge(participation, on=["party_name", "member_id"], how="left").fillna(0)
part_merged["rate"] = part_merged["participated"] / part_merged["votes"].replace(0, pd.NA)
party_participation = part_merged.groupby("party_name")["rate"].mean().reset_index()
st.plotly_chart(px.bar(party_participation, x="party_name", y="rate",
                        labels={"rate": "평균 참여율", "party_name": "정당"}), use_container_width=True)
st.caption("⚠️ '불참'은 표결 결과값 기준으로 계산했으며, API 응답 누락을 불참으로 자동 간주하지 않습니다.")

st.subheader("여야 간 표결 갈등도 & 초당적 합의도")
conflict_df = compute_bipartisan_conflict(df)
if not conflict_df.empty:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**갈등도가 높은 의안 (상위 10)**")
        st.dataframe(conflict_df.sort_values("conflict_index", ascending=False)[["bill_name", "conflict_index"]].head(10),
                     hide_index=True, use_container_width=True)
    with col2:
        st.markdown("**초당적 합의가 높은 의안 (상위 10)**")
        st.dataframe(conflict_df.sort_values("bipartisan_agreement_index", ascending=False)
                     [["bill_name", "bipartisan_agreement_index"]].head(10), hide_index=True, use_container_width=True)
    st.markdown(
        "📌 **계산식**\n"
        "- 여당 찬성률 = 표결일 기준 그 시점 여당 소속 의원 중 찬성한 비율 (찬성/반대/기권만 참여로 집계, 불참 제외)\n"
        "- 야당 찬성률 = 같은 방식으로 계산한 주요 야당의 찬성률\n"
        "- 갈등도(conflict_index) = abs(여당 찬성률 − 야당 찬성률) → 0에 가까울수록 여야가 비슷하게 투표, 1에 가까울수록 정반대로 투표\n"
        "- 초당적 합의도(bipartisan_agreement_index) = 1 − 갈등도\n"
        "- 여당/야당 구분은 표결일 기준 이력표(사이드바 '적용 중인 여야 이력표 보기')를 자동 적용한 것이며 공식 당론 자료가 아닙니다."
    )
else:
    st.info("여야 매핑에 해당하는 정당의 표결 데이터가 부족하거나, 표결일이 이력표 범위 밖에 있습니다.")

st.subheader("정당 간 표결 유사도 히트맵")
if not valid.empty:
    pivot = valid.pivot_table(index="bill_id", columns="party_name", values="vote_result",
                               aggfunc=lambda x: x.mode().iat[0] if not x.mode().empty else None)
    sim_matrix = pd.DataFrame(index=pivot.columns, columns=pivot.columns, dtype=float)
    for p1 in pivot.columns:
        for p2 in pivot.columns:
            if p1 == p2:
                # 같은 정당끼리는 자기 자신과의 비교이므로 1.0으로 고정
                # (같은 이름의 컬럼을 두 번 선택하면 pandas가 컬럼을 중복으로 취급해
                #  Series가 아닌 DataFrame이 반환되면서 대입 시 ValueError가 발생함)
                sim_matrix.loc[p1, p2] = 1.0
                continue
            common = pivot[[p1, p2]].dropna()
            common.columns = ["a", "b"]  # 컬럼명 충돌 방지
            sim_matrix.loc[p1, p2] = (common["a"] == common["b"]).mean() if not common.empty else None
    st.plotly_chart(px.imshow(sim_matrix.astype(float), text_auto=".2f", color_continuous_scale="Blues",
                               labels=dict(color="유사도")), use_container_width=True)
    st.caption("유사도 = 두 정당의 (의안별 다수 입장 기준) 동일 방향 표결 비율. 참고용 지표이며 인과관계를 의미하지 않습니다.")

st.download_button(
    "정당별 표결 데이터 CSV 다운로드",
    data=df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"party_vote_{eraco}.csv",
    mime="text/csv",
)
