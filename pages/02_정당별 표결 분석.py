"""
pages/02_정당별_표결분석.py — 정당별 표결분석
데이터 출처: 열린국회정보 포털에서 다운로드한 CSV 스냅샷 (data/ 폴더). 실시간 API 호출 없음.
"""

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="정당별 표결분석", layout="wide")
st.title("02. 정당별 표결분석")

DATA_DIR = "data"
VALID_VOTE_VALUES = ["찬성", "반대", "기권"]
VOTE_COLOR_MAP = {"찬성": "#1f77b4", "반대": "#d62728", "기권": "#7f7f7f"}  # 찬성=파랑, 반대=빨강, 기권=회색

# ============================================================
# 국회대수·기간별 여당/야당 실제 이력 매핑 (수정 가능한 설정값)
# 표결일 기준으로 자동 적용됨. 정권 교체 등으로 정보가 바뀌면 여기만 수정하면 됨.
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
    if pd.isna(vote_date):
        return None, None
    d = pd.Timestamp(vote_date).normalize()
    for start, end, ruling, opposition in RULING_OPPOSITION_PERIODS:
        if d >= start and (end is None or d <= end):
            return ruling, opposition
    return None, None


@st.cache_data
def load_vote_info():
    df = pd.read_csv(f"{DATA_DIR}/vote_info.csv", dtype={"의안번호": str})
    df["표결일자"] = pd.to_datetime(df["표결일자"], errors="coerce")
    return df


def compute_bipartisan_conflict(vote_df):
    """갈등도 = abs(여당 찬성률 - 야당 찬성률). 여당/야당은 표결일 기준 이력표를 자동 적용."""
    df = vote_df[vote_df["표결결과"].isin(VALID_VOTE_VALUES)].copy()
    if df.empty:
        return pd.DataFrame()
    ruling_opp = df["표결일자"].apply(get_ruling_opposition)
    df["여당"] = [x[0] for x in ruling_opp]
    df["야당"] = [x[1] for x in ruling_opp]
    df["진영"] = np.where(df["정당명"] == df["여당"], "여당",
                    np.where(df["정당명"] == df["야당"], "야당", "기타"))
    df = df[df["진영"].isin(["여당", "야당"])]
    if df.empty:
        return pd.DataFrame()
    yes_rate = (
        df.assign(is_yes=(df["표결결과"] == "찬성").astype(int))
        .groupby(["의안번호", "의안명", "진영"])["is_yes"].mean().unstack().reset_index()
    )
    for col in ["여당", "야당"]:
        if col not in yes_rate.columns:
            yes_rate[col] = np.nan
    yes_rate["갈등도"] = (yes_rate["여당"] - yes_rate["야당"]).abs()
    yes_rate["초당적합의도"] = 1 - yes_rate["갈등도"]
    return yes_rate.sort_values("갈등도", ascending=False)


try:
    vote_df = load_vote_info()
except FileNotFoundError:
    st.error("데이터 파일을 찾을 수 없습니다. 레포 루트에 `data/vote_info.csv` 파일이 있는지 확인해주세요.")
    st.stop()

st.caption(f"📌 데이터 기준: 22대 국회 (열린국회정보 포털 다운로드 스냅샷)")

# ============================================================
# 사이드바
# ============================================================
st.sidebar.header("조회 조건")
st.sidebar.subheader("여야 매핑 (자동 적용)")
st.sidebar.caption("데이터에 여당/야당 구분이 없어, 표결일 기준으로 아래 이력표를 코드에서 자동 적용합니다 (공식 당론 자료는 아님).")
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

parties = sorted(vote_df["정당명"].dropna().unique().tolist())
selected_parties = st.sidebar.multiselect("정당 선택 (비우면 전체)", parties, default=parties)
df = vote_df[vote_df["정당명"].isin(selected_parties)] if selected_parties else vote_df

st.subheader("정당별 찬성·반대·기권 비율")
valid = df[df["표결결과"].isin(VALID_VOTE_VALUES)]
if valid.empty:
    st.info("유효한 표결(찬성/반대/기권) 데이터가 부족합니다.")
else:
    party_dist = valid.groupby(["정당명", "표결결과"]).size().reset_index(name="count")
    party_total = party_dist.groupby("정당명")["count"].transform("sum")
    party_dist["ratio"] = party_dist["count"] / party_total
    st.plotly_chart(
        px.bar(party_dist, x="정당명", y="ratio", color="표결결과", barmode="stack",
               labels={"정당명": "정당", "ratio": "비율", "표결결과": "표결결과"},
               text=party_dist["ratio"].apply(lambda x: f"{x:.0%}"),
               color_discrete_map=VOTE_COLOR_MAP),
        use_container_width=True,
    )
    st.caption("각 막대는 정당 내 표결 건수를 100%로 두고, 찬성/반대/기권이 차지하는 비율을 나타냅니다.")

st.subheader("정당별 표결 참여율")
total_bills_in_view = df["의안번호"].nunique()
party_member_count = df.groupby("정당명")["의원명"].nunique()
party_vote_count = df.groupby("정당명").size()
party_participation = (party_vote_count / (party_member_count * total_bills_in_view)).reset_index()
party_participation.columns = ["정당명", "참여율"]
st.plotly_chart(
    px.bar(party_participation, x="정당명", y="참여율", labels={"정당명": "정당", "참여율": "표결 참여율"}),
    use_container_width=True,
)
st.caption(
    "참여율 = (해당 정당 소속 의원의 실제 표결 건수) ÷ (정당 소속 의원 수 × 전체 의안 수). "
    "⚠️ 이 데이터셋에는 '불참' 기록이 없어, 소속 의원 수 대비 실제 표결 참여 비율로 근사 계산한 값입니다."
)

st.subheader("여야 간 표결 갈등도 & 초당적 합의도")
conflict_df = compute_bipartisan_conflict(df)
if not conflict_df.empty:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**갈등도가 높은 의안 (상위 10)**")
        st.dataframe(conflict_df.sort_values("갈등도", ascending=False)[["의안명", "갈등도"]].head(10),
                     hide_index=True, use_container_width=True)
    with col2:
        st.markdown("**초당적 합의가 높은 의안 (상위 10)**")
        st.dataframe(conflict_df.sort_values("초당적합의도", ascending=False)[["의안명", "초당적합의도"]].head(10),
                     hide_index=True, use_container_width=True)
    st.markdown(
        "📌 **계산식**\n"
        "- 여당 찬성률 = 표결일 기준 그 시점 여당 소속 의원 중 찬성한 비율\n"
        "- 야당 찬성률 = 같은 방식으로 계산한 주요 야당의 찬성률\n"
        "- 갈등도 = abs(여당 찬성률 − 야당 찬성률) → 0에 가까울수록 여야가 비슷하게 투표, 1에 가까울수록 정반대\n"
        "- 초당적 합의도 = 1 − 갈등도\n"
        "- 여당/야당 구분은 표결일 기준 이력표(사이드바 '적용 중인 여야 이력표 보기')를 자동 적용한 것이며 공식 당론 자료가 아닙니다."
    )
else:
    st.info("여야 매핑에 해당하는 정당의 표결 데이터가 부족하거나, 표결일이 이력표 범위 밖에 있습니다.")

st.subheader("정당 간 표결 유사도 히트맵")
if not valid.empty:
    pivot = valid.pivot_table(index="의안번호", columns="정당명", values="표결결과",
                               aggfunc=lambda x: x.mode().iat[0] if not x.mode().empty else None)
    sim_matrix = pd.DataFrame(index=pivot.columns, columns=pivot.columns, dtype=float)
    for p1 in pivot.columns:
        for p2 in pivot.columns:
            if p1 == p2:
                sim_matrix.loc[p1, p2] = 1.0
                continue
            common = pivot[[p1, p2]].dropna()
            common.columns = ["a", "b"]
            sim_matrix.loc[p1, p2] = (common["a"] == common["b"]).mean() if not common.empty else None
    st.plotly_chart(px.imshow(sim_matrix.astype(float), text_auto=".2f", color_continuous_scale="Blues",
                               labels=dict(color="유사도")), use_container_width=True)
    st.caption("유사도 = 두 정당의 (의안별 다수 입장 기준) 동일 방향 표결 비율. 참고용 지표이며 인과관계를 의미하지 않습니다.")

st.download_button(
    "정당별 표결 데이터 CSV 다운로드",
    data=df.to_csv(index=False).encode("utf-8-sig"),
    file_name="party_vote_22대.csv",
    mime="text/csv",
)
