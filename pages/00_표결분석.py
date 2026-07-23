import requests
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="표결 분석 대시보드", page_icon="📊", layout="wide")
st.title("📊 정당 일치율 분석 대시보드")

BASE_URL = "https://open.assembly.go.kr/portal/openapi"
VOTE_ENDPOINT = "nojepdqqaweusdfbi"   # 국회의원 본회의 표결정보
BILL_ENDPOINT = "ALLBILLV2"          # 의안정보 통합 API
MEMBER_ENDPOINT = "ALLNAMEMBER"      # 국회의원 인적사항 통합 API

VALID_VOTES = ["찬성", "반대", "기권"]  # 불참 등은 일치율 계산에서 제외
REELE_CANDIDATES = ["REELE_GBN_NM", "REELE_GBN", "SELECT_GBN_NM"]  # 재선여부 필드명 후보


# ────────────────────────────────
# API 호출 함수
# ────────────────────────────────

def _request(endpoint_id, params):
    """공통 요청 함수. (DataFrame, 메타정보) 반환."""
    url = f"{BASE_URL}/{endpoint_id}"
    try:
        res = requests.get(url, params=params, timeout=20)
        res.raise_for_status()
        data = res.json()
    except requests.exceptions.RequestException as e:
        return pd.DataFrame(), {"CODE": "NETWORK_ERROR", "MESSAGE": str(e)}
    except ValueError:
        return pd.DataFrame(), {"CODE": "JSON_ERROR", "MESSAGE": "JSON 파싱 실패"}

    if "RESULT" in data:
        return pd.DataFrame(), data["RESULT"]

    try:
        rows = data[endpoint_id][1]["row"]
    except (KeyError, IndexError, TypeError):
        return pd.DataFrame(), {"CODE": "PARSE_ERROR", "MESSAGE": "응답 구조를 해석할 수 없습니다."}

    return pd.DataFrame(rows), {"CODE": "INFO-000", "MESSAGE": "정상"}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bill_list(api_key, eraco="제22대", bill_knd="법률안", max_pages=30):
    all_rows = []
    p = 1
    while p <= max_pages:
        params = {"KEY": api_key, "Type": "json", "pIndex": p, "pSize": 100,
                  "ERACO": eraco, "BILL_KND": bill_knd}
        df, meta = _request(BILL_ENDPOINT, params)
        if df.empty:
            break
        all_rows.append(df)
        if len(df) < 100:
            break
        p += 1
    return pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_vote_by_bill(api_key, bill_id, age="22"):
    params = {"KEY": api_key, "Type": "json", "pIndex": 1, "pSize": 1000,
              "BILL_ID": bill_id, "AGE": age}
    df, meta = _request(VOTE_ENDPOINT, params)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_member_info(api_key, age="22"):
    all_rows = []
    p = 1
    while p <= 10:
        params = {"KEY": api_key, "Type": "json", "pIndex": p, "pSize": 100, "AGE": age}
        df, meta = _request(MEMBER_ENDPOINT, params)
        if df.empty:
            break
        all_rows.append(df)
        if len(df) < 100:
            break
        p += 1
    return pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_full_dataset(api_key, eraco="제22대", max_bills=50):
    """의안 목록 -> 표결까지 간 의안만 필터 -> 의안별 표결정보 수집 -> 인적사항"""
    bill_df = fetch_bill_list(api_key, eraco=eraco)
    if bill_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    voted_bills = bill_df[
        bill_df["RGS_CONF_RSLT"].notna() & (bill_df["RGS_CONF_RSLT"] != "")
    ].copy().head(max_bills)

    vote_frames = []
    for _, row in voted_bills.iterrows():
        vdf = fetch_vote_by_bill(api_key, row["BILL_ID"])
        if not vdf.empty:
            vdf = vdf.copy()
            vdf["BILL_KND"] = row.get("BILL_KND")
            vote_frames.append(vdf)

    vote_df = pd.concat(vote_frames, ignore_index=True) if vote_frames else pd.DataFrame()
    member_df = fetch_member_info(api_key)
    return bill_df, voted_bills, vote_df, member_df


# ────────────────────────────────
# 분석 함수
# ────────────────────────────────

def compute_concordance(vote_df, group_cols=("BILL_ID", "POLY_NM")):
    """의안 x 정당(표결 시점 기준) 다수결 방향 계산 -> 개인별 일치여부 부여"""
    df = vote_df.copy()
    df = df[df["RESULT_VOTE_MOD"].isin(VALID_VOTES)]

    majority = (
        df.groupby(list(group_cols))["RESULT_VOTE_MOD"]
        .agg(lambda x: x.value_counts().idxmax())
        .rename("정당다수결")
        .reset_index()
    )
    df = df.merge(majority, on=list(group_cols), how="left")
    df["일치여부"] = df["RESULT_VOTE_MOD"] == df["정당다수결"]
    return df


def merge_votes_with_members(vote_df, member_df):
    """MONA_CD 기준 조인, 없으면 이름+정당으로 보정"""
    if member_df.empty:
        return vote_df

    vote_df = vote_df.copy()
    member_df = member_df.copy()

    if "MONA_CD" in vote_df.columns and "MONA_CD" in member_df.columns:
        member_suffixed = member_df.add_suffix("_인적")
        merged = vote_df.merge(member_suffixed, left_on="MONA_CD",
                                right_on="MONA_CD_인적", how="left")
    else:
        vote_df["_join_key"] = vote_df["HG_NM"].astype(str) + "_" + vote_df["POLY_NM"].astype(str)
        member_df["_join_key"] = member_df["HG_NM"].astype(str) + "_" + member_df["POLY_NM"].astype(str)
        member_suffixed = member_df.add_suffix("_인적")
        merged = vote_df.merge(member_suffixed, left_on="_join_key",
                                right_on="_join_key_인적", how="left")
    return merged


def get_reele_col(merged_df):
    for c in [f"{c}_인적" for c in REELE_CANDIDATES]:
        if c in merged_df.columns:
            return c
    return None


def member_concordance_summary(df, member_cols):
    agg = (
        df.groupby(member_cols)["일치여부"]
        .agg(표결건수="count", 일치건수="sum")
        .reset_index()
    )
    agg["일치율"] = (agg["일치건수"] / agg["표결건수"] * 100).round(1)
    agg["이탈률"] = (100 - agg["일치율"]).round(1)
    return agg


# ────────────────────────────────
# 화면 구성
# ────────────────────────────────

api_key = st.secrets.get("ASSEMBLY_API_KEY", "")
if not api_key:
    st.error("Streamlit Cloud의 Settings > Secrets에 ASSEMBLY_API_KEY를 등록해주세요.")
    st.stop()

with st.sidebar:
    st.header("⚙️ 데이터 설정")
    eraco = st.selectbox("국회 대수", ["제22대", "제21대"], index=0)
    max_bills = st.slider("분석할 의안 수 (최대)", 10, 200, 50, step=10,
                           help="의안 1건당 API 1회 호출 — 값이 클수록 로딩이 오래 걸려요")
    load_btn = st.button("🔄 데이터 불러오기", use_container_width=True)

if "loaded" not in st.session_state:
    st.session_state["loaded"] = False

if load_btn or not st.session_state["loaded"]:
    with st.spinner(f"의안 최대 {max_bills}건의 표결 데이터를 수집 중... (시간이 걸릴 수 있어요)"):
        bill_df, voted_bills, vote_df, member_df = load_full_dataset(api_key, eraco, max_bills)

    if vote_df.empty:
        st.warning("표결 데이터를 가져오지 못했어요. API 키/파라미터를 확인해주세요.")
        st.stop()

    st.session_state.update({
        "vote_df": vote_df, "member_df": member_df, "loaded": True,
    })

vote_df = st.session_state["vote_df"]
member_df = st.session_state["member_df"]

st.caption(f"수집된 의안 수: {vote_df['BILL_ID'].nunique()}건 · 표결 레코드 수: {len(vote_df):,}건")

conc_df = compute_concordance(vote_df, group_cols=("BILL_ID", "POLY_NM"))
merged = merge_votes_with_members(conc_df, member_df) if not member_df.empty else conc_df
reele_col = get_reele_col(merged)

st.sidebar.divider()
st.sidebar.header("🔍 필터")

parties = sorted(vote_df["POLY_NM"].dropna().unique().tolist())
sel_parties = st.sidebar.multiselect("정당 선택", parties, default=parties)

if reele_col:
    reele_opts = sorted(merged[reele_col].dropna().unique().tolist())
    sel_reele = st.sidebar.multiselect("재선여부", reele_opts, default=reele_opts)
else:
    sel_reele = None
    st.sidebar.caption("ℹ️ 인적사항 데이터와 조인되지 않아 재선여부 필터를 쓸 수 없어요.")

date_range = None
if "VOTE_DATE" in merged.columns:
    merged["VOTE_DATE_dt"] = pd.to_datetime(merged["VOTE_DATE"], errors="coerce")
    valid_dates = merged["VOTE_DATE_dt"].dropna()
    if not valid_dates.empty:
        min_d, max_d = valid_dates.min().to_pydatetime(), valid_dates.max().to_pydatetime()
        if min_d < max_d:
            date_range = st.sidebar.slider("표결일자 범위", min_value=min_d, max_value=max_d,
                                            value=(min_d, max_d))

filtered = merged[merged["POLY_NM"].isin(sel_parties)]
if sel_reele is not None:
    filtered = filtered[filtered[reele_col].isin(sel_reele)]
if date_range:
    filtered = filtered[(filtered["VOTE_DATE_dt"] >= date_range[0]) & (filtered["VOTE_DATE_dt"] <= date_range[1])]

if filtered.empty:
    st.warning("필터 조건에 맞는 데이터가 없어요. 필터를 조정해주세요.")
    st.stop()

# ── KPI ──
col1, col2, col3 = st.columns(3)
overall_rate = filtered["일치여부"].mean() * 100
by_party_rate = filtered.groupby("POLY_NM")["일치여부"].mean() * 100
most_deviant_party = by_party_rate.idxmin() if not by_party_rate.empty else "-"
n_bills = filtered["BILL_ID"].nunique()

col1.metric("전체 평균 일치율", f"{overall_rate:.1f}%")
col2.metric("최다 이탈 정당", str(most_deviant_party),
            f"{by_party_rate.min():.1f}% 일치" if not by_party_rate.empty else "")
col3.metric("분석 대상 표결 건수", f"{n_bills}건")

st.divider()

# ── 정당별 일치율 ──
st.subheader("정당별 일치율")
party_summary = (
    filtered.groupby("POLY_NM")["일치여부"].mean().mul(100).round(1)
    .reset_index().rename(columns={"일치여부": "일치율"})
    .sort_values("일치율", ascending=False)
)
fig1 = px.bar(party_summary, x="POLY_NM", y="일치율", text="일치율",
              labels={"POLY_NM": "정당", "일치율": "일치율(%)"},
              color="일치율", color_continuous_scale="Blues")
fig1.update_traces(texttemplate="%{text}%", textposition="outside")
fig1.update_layout(yaxis_range=[0, 105], coloraxis_showscale=False)
st.plotly_chart(fig1, use_container_width=True)

# ── 재선여부별 이탈률 비교 ──
st.subheader("재선 여부별 이탈률 비교")
if reele_col:
    member_summary = member_concordance_summary(filtered, member_cols=["HG_NM", "POLY_NM", reele_col])
    fig2 = px.box(member_summary, x=reele_col, y="이탈률", color=reele_col, points="all",
                  labels={reele_col: "재선여부", "이탈률": "이탈률(%)"})
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("인적사항 데이터와 조인이 되지 않아 재선여부별 비교를 표시할 수 없어요.")
    member_summary = member_concordance_summary(filtered, member_cols=["HG_NM", "POLY_NM"])

# ── 의원별 랭킹 테이블 ──
st.subheader("의원별 일치율 랭킹")
rank_cols = ["HG_NM", "POLY_NM"] + ([reele_col] if reele_col else []) + ["표결건수", "일치율", "이탈률"]
rank_df = member_summary[rank_cols]

st.caption("🔻 이탈률 상위 10명")
top10 = rank_df.sort_values("이탈률", ascending=False).head(10)
st.dataframe(top10.style.background_gradient(subset=["이탈률"], cmap="Reds"),
             use_container_width=True, hide_index=True)

with st.expander("전체 의원 랭킹 보기 (정렬 가능)"):
    st.dataframe(rank_df.sort_values("일치율", ascending=False),
                 use_container_width=True, hide_index=True)
