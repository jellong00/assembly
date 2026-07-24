"""
pages/01_전체_표결현황.py — 전체 표결현황
데이터 출처: 열린국회정보 포털에서 다운로드한 CSV 스냅샷 (data/ 폴더)
※ 실시간 API 호출 없음. 국회 API 서버가 Streamlit Cloud(해외 IP)를 차단하는 문제를 우회하기 위해
   로컬에서 미리 받아둔 22대 국회 데이터를 사용한다.
"""

import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="전체 표결현황", layout="wide")
st.title("01. 전체 표결현황")

DATA_DIR = "data"


@st.cache_data
def load_vote_info():
    """의원별 본회의 표결정보 (data/vote_info.csv)"""
    df = pd.read_csv(f"{DATA_DIR}/vote_info.csv", dtype={"의안번호": str})
    df["표결일자"] = pd.to_datetime(df["표결일자"], errors="coerce")
    return df


try:
    vote_df = load_vote_info()
except FileNotFoundError:
    st.error(
        "데이터 파일을 찾을 수 없습니다. 레포 루트에 `data/vote_info.csv` 파일이 있는지 확인해주세요."
    )
    st.stop()

st.caption(f"📌 데이터 기준: 22대 국회 (열린국회정보 포털 다운로드 스냅샷, 총 {vote_df['의안번호'].nunique():,}개 의안)")

# ============================================================
# 사이드바 필터
# ============================================================
st.sidebar.header("조회 조건")
committee_search = st.sidebar.text_input("의안명 검색 (필터)", "")

df = vote_df
if committee_search:
    matched_bills = df[df["의안명"].str.contains(committee_search, na=False)]["의안번호"].unique()
    df = df[df["의안번호"].isin(matched_bills)]

if df.empty:
    st.warning("검색 조건에 맞는 표결 데이터가 없습니다.")
    st.stop()

# ============================================================
# 핵심 지표
# ============================================================
total_bills = df["의안번호"].nunique()
total_members = df["의원명"].nunique()
total_votes = len(df)
yes_rate = (df["표결결과"] == "찬성").mean()
no_rate = (df["표결결과"] == "반대").mean()
abstain_rate = (df["표결결과"] == "기권").mean()

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("전체 표결 의안 수", f"{total_bills:,}")
c2.metric("전체 참여 의원 수", f"{total_members:,}")
c3.metric("전체 표결 건수", f"{total_votes:,}")
c4.metric("찬성률", f"{yes_rate:.1%}")
c5.metric("반대율", f"{no_rate:.1%}")
c6.metric("기권율", f"{abstain_rate:.1%}")
st.caption("⚠️ 이 데이터셋에는 '불참(결석)' 기록이 포함되어 있지 않아, 비율은 실제 투표(찬성/반대/기권) 기준입니다.")

st.divider()

st.subheader("날짜별 표결 의안 수")
by_date = df.dropna(subset=["표결일자"]).groupby(df["표결일자"].dt.date)["의안번호"].nunique().reset_index()
by_date.columns = ["표결일자", "의안수"]
st.plotly_chart(
    px.bar(by_date, x="표결일자", y="의안수", labels={"표결일자": "날짜", "의안수": "의안 수"}),
    use_container_width=True,
)

st.subheader("표결 결과 분포")
result_dist = df["표결결과"].value_counts().reset_index()
result_dist.columns = ["표결결과", "건수"]
st.plotly_chart(px.pie(result_dist, names="표결결과", values="건수", hole=0.4), use_container_width=True)

st.subheader("최근 표결 의안 목록")
recent_bills = (
    df.dropna(subset=["표결일자"]).drop_duplicates(subset=["의안번호"])
    .sort_values("표결일자", ascending=False)[["표결일자", "의안명", "의안번호"]].head(20)
)
st.dataframe(recent_bills, use_container_width=True, hide_index=True)

st.download_button(
    "전체 표결 데이터 CSV 다운로드",
    data=df.to_csv(index=False).encode("utf-8-sig"),
    file_name="vote_data_22대.csv",
    mime="text/csv",
)
