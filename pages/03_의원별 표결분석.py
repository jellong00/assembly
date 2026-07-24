"""
pages/03_의원별_표결분석.py — 의원별 표결분석
데이터 출처: 열린국회정보 포털에서 다운로드한 CSV 스냅샷 (data/ 폴더). 실시간 API 호출 없음.
"""

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="의원별 표결분석", layout="wide")
st.title("03. 의원별 표결분석")

DATA_DIR = "data"
VALID_VOTE_VALUES = ["찬성", "반대", "기권"]


@st.cache_data
def load_vote_info():
    df = pd.read_csv(f"{DATA_DIR}/vote_info.csv", dtype={"의안번호": str})
    df["표결일자"] = pd.to_datetime(df["표결일자"], errors="coerce")
    return df


@st.cache_data
def load_member_info():
    """국회의원 인적사항 (data/member_info.csv) — 선거구, 재선/당선 이력 등 부가정보"""
    try:
        return pd.read_csv(f"{DATA_DIR}/member_info.csv")
    except FileNotFoundError:
        return pd.DataFrame()


def compute_member_agreement_with_party(vote_df):
    """
    의원별 '소속 정당 다수 입장과의 일치율'을 계산한다.
    '정당 다수 입장과 다른 표결'로만 표현하며 '당론 위반'이라는 표현은 사용하지 않는다
    (공식 당론 자료가 없어 사후적으로 계산된 통계적 개념일 뿐임).
    """
    df = vote_df[vote_df["표결결과"].isin(VALID_VOTE_VALUES)].copy()
    if df.empty:
        return pd.DataFrame()
    party_majority = (
        df.groupby(["의안번호", "정당명", "표결결과"]).size().reset_index(name="count")
        .sort_values("count", ascending=False).drop_duplicates(subset=["의안번호", "정당명"])
        .rename(columns={"표결결과": "정당다수입장"})[["의안번호", "정당명", "정당다수입장"]]
    )
    merged = df.merge(party_majority, on=["의안번호", "정당명"], how="left")
    merged["정당다수와일치"] = merged["표결결과"] == merged["정당다수입장"]
    summary = merged.groupby(["의원명", "정당명"]).agg(
        전체표결건수=("표결결과", "count"),
        정당다수일치건수=("정당다수와일치", "sum"),
    ).reset_index()
    summary["일치율"] = summary["정당다수일치건수"] / summary["전체표결건수"].replace(0, np.nan)
    summary["다른표결건수"] = summary["전체표결건수"] - summary["정당다수일치건수"]
    return summary


def compute_member_similarity(vote_df, member_name, min_common_votes=10):
    """유사도 = 두 의원이 동시에 표결한 의안 중 동일한 선택을 한 비율."""
    df = vote_df[vote_df["표결결과"].isin(VALID_VOTE_VALUES)]
    if df.empty or member_name not in df["의원명"].values:
        return pd.DataFrame()
    a_votes = df[df["의원명"] == member_name][["의안번호", "표결결과"]].rename(columns={"표결결과": "vote_a"})
    others = df[df["의원명"] != member_name]
    merged = others.merge(a_votes, on="의안번호", how="inner")
    merged["match"] = merged["표결결과"] == merged["vote_a"]
    result = merged.groupby(["의원명", "정당명"]).agg(
        공동표결수=("match", "count"), 일치표결수=("match", "sum")
    ).reset_index()
    result = result[result["공동표결수"] >= min_common_votes]
    result["유사도"] = result["일치표결수"] / result["공동표결수"]
    return result.sort_values("유사도", ascending=False)


try:
    vote_df = load_vote_info()
except FileNotFoundError:
    st.error("데이터 파일을 찾을 수 없습니다. 레포 루트에 `data/vote_info.csv` 파일이 있는지 확인해주세요.")
    st.stop()

member_info_df = load_member_info()

st.caption("📌 데이터 기준: 22대 국회 (열린국회정보 포털 다운로드 스냅샷)")

# ============================================================
# 사이드바
# ============================================================
st.sidebar.header("조회 조건")
parties = sorted(vote_df["정당명"].dropna().unique().tolist())
selected_party = st.sidebar.selectbox("정당 선택", ["전체"] + parties)
filtered = vote_df if selected_party == "전체" else vote_df[vote_df["정당명"] == selected_party]

members = sorted(filtered["의원명"].dropna().unique().tolist())
if not members:
    st.warning("선택 조건에 맞는 의원이 없습니다.")
    st.stop()
selected_member = st.sidebar.selectbox("의원 선택", members)

member_row = filtered[filtered["의원명"] == selected_member]
if member_row.empty:
    st.warning("선택한 의원의 표결 데이터가 없습니다.")
    st.stop()

st.subheader(f"{selected_member} 의원 표결 요약")

# 인적사항 부가정보 (있으면 표시)
if not member_info_df.empty:
    info_row = member_info_df[member_info_df["이름"] == selected_member]
    if not info_row.empty:
        info = info_row.iloc[0]
        ic1, ic2, ic3, ic4 = st.columns(4)
        ic1.markdown(f"**선거구**: {info.get('선거구', '-')}")
        ic2.markdown(f"**대표 위원회**: {info.get('대표 위원회', '-')}")
        ic3.markdown(f"**재선**: {info.get('재선', '-')}")
        ic4.markdown(f"**당선 이력**: {info.get('당선', '-')}")

total_votes = len(member_row)
yes_c = int((member_row["표결결과"] == "찬성").sum())
no_c = int((member_row["표결결과"] == "반대").sum())
abstain_c = int((member_row["표결결과"] == "기권").sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("전체 표결 참여 건수", f"{total_votes:,}")
c2.metric("찬성 건수", f"{yes_c:,}")
c3.metric("반대 건수", f"{no_c:,}")
c4.metric("기권 건수", f"{abstain_c:,}")

agreement_df = compute_member_agreement_with_party(vote_df)
member_agreement = agreement_df[agreement_df["의원명"] == selected_member] if not agreement_df.empty else pd.DataFrame()
if not member_agreement.empty:
    row = member_agreement.iloc[0]
    c5, c6 = st.columns(2)
    c5.metric("소속 정당 다수 입장과의 일치율", f"{row['일치율']:.1%}")
    c6.metric("정당 다수 입장과 다른 표결 건수", f"{int(row['다른표결건수']):,}")
    st.caption("⚠️ 공식 당론 자료가 없어 '정당 다수 입장'을 기준으로 계산한 것이며, '당론 위반'을 의미하지 않습니다.")

st.subheader("의원별 표결 성향")
tendency = member_row["표결결과"].value_counts(normalize=True).reset_index()
tendency.columns = ["표결결과", "비율"]
st.plotly_chart(px.pie(tendency, names="표결결과", values="비율", hole=0.4), use_container_width=True)

st.subheader("표결이 유사한 의원 상위 10명")
min_common = st.slider("최소 공동 표결 수 기준", 1, 50, 5,
                        help="공동 참여 의안이 너무 적으면 유사도가 왜곡될 수 있어 최소 기준을 조정할 수 있습니다.")
sim_df = compute_member_similarity(vote_df, selected_member, min_common_votes=min_common)
if not sim_df.empty:
    st.dataframe(sim_df.head(10)[["의원명", "정당명", "공동표결수", "유사도"]],
                 hide_index=True, use_container_width=True)
else:
    st.info("조건을 만족하는 유사 의원이 없습니다. 최소 공동 표결 수를 낮춰보세요.")

st.subheader("의원별 상세 표결 내역")
search = st.text_input("의안명 검색")
detail = member_row[["표결일자", "의안명", "의안번호", "표결결과"]].sort_values("표결일자", ascending=False)
if search:
    detail = detail[detail["의안명"].str.contains(search, na=False)]
st.dataframe(detail, hide_index=True, use_container_width=True)

st.download_button(
    "의원별 표결 내역 CSV 다운로드",
    data=detail.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"{selected_member}_votes.csv",
    mime="text/csv",
)
