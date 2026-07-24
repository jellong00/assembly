"""pages/01_전체_표결현황.py — 전체 표결현황 (독립 실행형: 공통 함수 없이 이 파일 안에 전부 포함)"""

import re
import time

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="전체 표결현황", layout="wide")
st.title("01. 전체 표결현황")

# ============================================================
# API 설정값 (실제 확인된 엔드포인트)
# ============================================================
BILL_LIST_API_URL = "https://open.assembly.go.kr/portal/openapi/ALLBILLV2"          # 의안정보 통합 API (BILL_ID 확보용)
VOTE_API_URL = "https://open.assembly.go.kr/portal/openapi/nojepdqqaweusdfbi"        # 국회의원 본회의 표결정보
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


def get_api_key():
    """secrets.toml 또는 Streamlit Cloud Secrets에서 API 키를 읽어온다."""
    try:
        return st.secrets["OPEN_ASSEMBLY_API_KEY"]
    except Exception:
        return None


def call_api(base_url, params, page_index=1, page_size=100):
    """
    Open API 공통 호출 함수 (1페이지).
    정상 응답: {"<엔드포인트명>": [{"head":[...]},{"row":[...]}]}
    오류 응답: {"RESULT":{"CODE":"ERROR-...", "MESSAGE":"..."}}  (엔드포인트명 래핑 없음)
    """
    api_key = get_api_key()
    if not api_key:
        return [], 0, "API 키가 설정되지 않았습니다. .streamlit/secrets.toml 또는 Streamlit Cloud Secrets를 확인하세요."

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

    total_count = 0
    rows = []
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
    """페이지네이션 처리를 포함한 전체 조회."""
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
    """
    의안정보 통합 API(ALLBILLV2)로 의안 목록(BILL_ID 포함)을 조회한다.
    ⚠️ 실패 시 예외를 던진다 (빈 결과를 캐싱하지 않기 위함).
       @st.cache_data는 함수가 정상 반환했을 때만 결과를 캐싱하므로,
       여기서 raise 하면 실패한 호출은 절대 캐싱되지 않고 다음 호출에서 다시 시도된다.
    """
    params = {"ERACO": eraco, "BILL_KND": bill_kind, "RGS_CONF_RSLT": rgs_conf_rslt}
    rows, err = fetch_all_pages(BILL_LIST_API_URL, params, page_size=100, max_pages=max_pages,
                                 progress_label="의안 목록 조회 중...")
    if err:
        raise RuntimeError(err)
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_vote_info_single(bill_id, age):
    """단일 의안(BILL_ID)의 의원별 본회의 표결정보를 조회한다. 실패 시 예외를 던진다 (캐싱 방지)."""
    rows, err = fetch_all_pages(VOTE_API_URL, {"AGE": age, "BILL_ID": bill_id}, page_size=300, max_pages=5)
    if err:
        raise RuntimeError(err)
    return pd.DataFrame(rows)


def fetch_vote_info_bulk(bill_ids, age, max_bills=30):
    """여러 의안의 표결정보를 순차 조회 (호출 횟수 제한 고려)."""
    if len(bill_ids) > max_bills:
        st.warning(f"선택된 의안이 {len(bill_ids)}건이라 상위 {max_bills}건만 조회합니다. "
                   f"사이드바에서 조회 건수를 조정할 수 있습니다.")
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
    """표결결과 값을 표준 값(찬성/반대/기권/불참)으로 변환한다."""
    if pd.isna(value):
        return None
    return VOTE_RESULT_MAP.get(str(value).strip(), str(value).strip())


def clean_party_name(value):
    """정당명 앞뒤/내부 공백을 정리한다."""
    if pd.isna(value):
        return "정보없음"
    name = re.sub(r"\s+", "", str(value).strip())
    return name if name else "정보없음"


def standardize_vote_date(value):
    """'YYYYMMDD HHMMSS' 등 다양한 날짜 문자열을 datetime으로 변환한다."""
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
    """
    표결정보 API 원본 응답을 표준 컬럼(assembly_no, bill_id, bill_no, bill_name, vote_date,
    member_id, member_name, party_name, vote_result, committee_name)으로 변환한다.
    """
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
    """ALLBILLV2 원본 응답을 정리한다."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.drop_duplicates(subset=["BILL_ID"], keep="first").copy()
    for col in ("PPSL_DT", "RGS_RSLN_DT"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def check_required_columns(df, required_cols, context_label="데이터"):
    """필수 컬럼 존재 여부를 확인하고, 없으면 안내한다."""
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.warning(f"{context_label}에 필요한 컬럼이 없습니다: {missing}. API 응답 필드명 변경 여부를 확인해주세요.")
        return False
    return True


def generate_sample_vote_data(n_bills=15, n_members=60, seed=42):
    """
    분석 기능 테스트용 샘플 데이터를 생성한다.
    ⚠️ 실제 국회 표결 데이터가 아니며 통계적 의미가 없다. UI/기능 시연 전용.
    """
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


# ============================================================
# 사이드바
# ============================================================
st.sidebar.header("조회 조건")
use_sample = st.sidebar.checkbox("샘플 데이터 사용", value=False,
                                  help="API 키가 없거나 실제 데이터를 아직 테스트하지 않았다면 체크하세요.")
eraco = st.sidebar.selectbox("국회대수", ["제22대", "제21대", "제20대"], index=0)
bill_kind = st.sidebar.selectbox("의안 종류 필터", ["전체", "법률안", "예산안", "동의안", "결의안"], index=1)
max_bills = st.sidebar.slider("조회할 최대 의안 수", min_value=5, max_value=100, value=20, step=5,
                              help="의안 수가 많을수록 API 호출 시간이 오래 걸립니다.")
if st.sidebar.button("🔄 캐시 지우고 새로고침"):
    st.cache_data.clear()
    st.rerun()

if use_sample:
    st.info("⚠️ 현재 샘플 데이터를 사용 중입니다. 실제 통계가 아니며 기능 시연용입니다.")
    vote_df = generate_sample_vote_data(n_bills=max_bills)
else:
    kind_param = None if bill_kind == "전체" else bill_kind
    try:
        bill_list_raw = fetch_bill_list(eraco=eraco, bill_kind=kind_param, rgs_conf_rslt="원안가결", max_pages=5)
        bill_list = standardize_bill_list_dataframe(bill_list_raw)
    except RuntimeError as e:
        st.warning(f"의안 목록 조회 오류: {e}")
        bill_list = pd.DataFrame()

    if bill_list.empty:
        st.warning("의안 목록을 가져오지 못했습니다. API 키 또는 조회 조건을 확인하거나 샘플 데이터를 사용해주세요.")
        st.stop()

    age_num = eraco.replace("제", "").replace("대", "")
    bill_ids = bill_list["BILL_ID"].dropna().unique().tolist()
    vote_raw = fetch_vote_info_bulk(bill_ids, age=age_num, max_bills=max_bills)
    vote_df = standardize_vote_dataframe(vote_raw)

if vote_df.empty:
    st.warning("표시할 표결 데이터가 없습니다.")
    st.stop()

if not check_required_columns(vote_df, ["bill_id", "member_id", "vote_result", "vote_date"], "표결 데이터"):
    st.stop()

# ============================================================
# 핵심 지표
# ============================================================
total_bills = vote_df["bill_id"].nunique()
total_members = vote_df["member_id"].nunique()
total_votes = len(vote_df)
valid = vote_df[vote_df["vote_result"].isin(["찬성", "반대", "기권"])]
yes_rate = (valid["vote_result"] == "찬성").mean() if not valid.empty else 0
no_rate = (valid["vote_result"] == "반대").mean() if not valid.empty else 0
abstain_rate = (valid["vote_result"] == "기권").mean() if not valid.empty else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("전체 표결 의안 수", f"{total_bills:,}")
c2.metric("전체 참여 의원 수", f"{total_members:,}")
c3.metric("전체 표결 건수", f"{total_votes:,}")
c4.metric("찬성률", f"{yes_rate:.1%}")
c5.metric("반대율", f"{no_rate:.1%}")
c6.metric("기권율", f"{abstain_rate:.1%}")

st.divider()

st.subheader("날짜별 표결 의안 수")
if vote_df["vote_date"].notna().any():
    by_date = vote_df.dropna(subset=["vote_date"]).groupby(vote_df["vote_date"].dt.date)["bill_id"].nunique().reset_index()
    by_date.columns = ["vote_date", "bill_count"]
    st.plotly_chart(px.bar(by_date, x="vote_date", y="bill_count",
                            labels={"vote_date": "날짜", "bill_count": "의안 수"}), use_container_width=True)
    st.caption("⚠️ 기록표결(전자표결) 기준으로, 모든 본회의 안건을 대표하지 않을 수 있습니다.")
else:
    st.info("표결일자 정보가 없어 날짜별 차트를 표시할 수 없습니다.")

st.subheader("표결 결과 분포")
result_dist = vote_df["vote_result"].value_counts().reset_index()
result_dist.columns = ["vote_result", "count"]
st.plotly_chart(px.pie(result_dist, names="vote_result", values="count", hole=0.4), use_container_width=True)
st.caption("⚠️ '불참'은 실제 표결 결과값이며, API 응답 누락을 의미하지 않습니다.")

st.subheader("최근 표결 의안 목록")
recent_bills = (
    vote_df.dropna(subset=["vote_date"]).drop_duplicates(subset=["bill_id"])
    .sort_values("vote_date", ascending=False)[["vote_date", "bill_name", "bill_no", "committee_name"]].head(20)
)
st.dataframe(recent_bills, use_container_width=True, hide_index=True)

st.download_button(
    "전체 표결 데이터 CSV 다운로드",
    data=vote_df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"vote_data_{eraco}.csv",
    mime="text/csv",
)
