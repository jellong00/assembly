"""
pages/04_의안별_상세분석.py — 의안별 상세분석
데이터 출처: 열린국회정보 포털에서 다운로드한 CSV 스냅샷 (data/ 폴더). 실시간 API 호출 없음.
"""

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="의안별 상세분석", layout="wide")
st.title("04. 의안별 상세분석")

DATA_DIR = "data"
VALID_VOTE_VALUES = ["찬성", "반대", "기권"]
VOTE_COLOR_MAP = {"찬성": "#1f77b4", "반대": "#d62728", "기권": "#7f7f7f"}  # 찬성=파랑, 반대=빨강, 기권=회색

@st.cache_data
def load_vote_info():
    df = pd.read_csv(f"{DATA_DIR}/vote_info.csv", dtype={"의안번호": str})
    df["표결일자"] = pd.to_datetime(df["표결일자"], errors="coerce")
    return df


@st.cache_data
def load_bill_detail():
    return pd.read_csv(f"{DATA_DIR}/bill_detail.csv", dtype={"의안번호": str})


@st.cache_data
def load_bill_proposer():
    return pd.read_csv(f"{DATA_DIR}/bill_proposer.csv", dtype={"의안번호": str})


@st.cache_data
def load_bill_summary():
    return pd.read_csv(f"{DATA_DIR}/bill_vote_summary.csv", dtype={"의안번호": str})


def compute_bipartisan_conflict(vote_df):
    """
    갈등도 = abs(여당 찬성률 - 야당 찬성률).
    22대 국회 기준으로 더불어민주당을 여당, 나머지 정당 전체를 야당으로 고정해서 계산한다.
    """
    df = vote_df[vote_df["표결결과"].isin(VALID_VOTE_VALUES)].copy()
    if df.empty:
        return pd.DataFrame()
    df["진영"] = np.where(df["정당명"] == "더불어민주당", "여당", "야당")
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
    bill_detail_df = load_bill_detail()
    bill_summary_df = load_bill_summary()
except FileNotFoundError as e:
    st.error(f"데이터 파일을 찾을 수 없습니다: {e}. 레포 루트에 `data/` 폴더가 있는지 확인해주세요.")
    st.stop()

try:
    bill_proposer_df = load_bill_proposer()
except FileNotFoundError:
    bill_proposer_df = pd.DataFrame()

st.caption("📌 데이터 기준: 22대 국회 (열린국회정보 포털 다운로드 스냅샷)")

st.sidebar.header("조회 조건")

bill_options = vote_df.drop_duplicates(subset=["의안번호"])[["의안번호", "의안명"]]
search_kw = st.text_input("의안명 검색")
filtered_options = (
    bill_options[bill_options["의안명"].str.contains(search_kw, na=False)] if search_kw else bill_options
)
if filtered_options.empty:
    st.warning("검색 결과가 없습니다.")
    st.stop()

selected_bill_name = st.selectbox("의안 선택", filtered_options["의안명"].tolist())
selected_bill_no = filtered_options[filtered_options["의안명"] == selected_bill_name]["의안번호"].iloc[0]

bill_vote_df = vote_df[vote_df["의안번호"] == selected_bill_no]
if bill_vote_df.empty:
    st.warning("이 의안에 대한 표결 데이터가 없습니다.")
    st.stop()

detail_row = bill_detail_df[bill_detail_df["의안번호"] == selected_bill_no]
summary_row = bill_summary_df[bill_summary_df["의안번호"] == selected_bill_no]
proposer_rows = (
    bill_proposer_df[bill_proposer_df["의안번호"] == selected_bill_no] if not bill_proposer_df.empty else pd.DataFrame()
)

st.subheader("의안 기본 정보")
if not detail_row.empty:
    d = detail_row.iloc[0]
    info_cols = st.columns(3)
    info_cols[0].markdown(f"**의안번호**: {d.get('의안번호', '-')}")
    info_cols[0].markdown(f"**의안명**: {d.get('의안명', '-')}")
    info_cols[1].markdown(f"**제안일**: {d.get('제안일', '-')}")
    info_cols[1].markdown(f"**소관위원회**: {d.get('소관위원회명', '-')}")
    info_cols[2].markdown(f"**본회의 심의결과**: {d.get('본회의 심의결과', '-')}")
    info_cols[2].markdown(f"**본회의 의결일**: {d.get('본회의 심의 의결일', '-')}")
else:
    st.info("이 의안의 상세정보(제안일·소관위원회 등)를 찾을 수 없습니다.")

if not summary_row.empty:
    s = summary_row.iloc[0]
    st.caption(
        f"📊 재적의원 {s.get('재적의원수', '-')}명 중 {s.get('총투표수', '-')}명 투표 "
        f"(찬성 {s.get('찬성수', '-')} · 반대 {s.get('반대수', '-')} · 기권 {s.get('기권수', '-')}) "
        f"→ {s.get('표결결과', '-')}"
    )

if not proposer_rows.empty:
    st.markdown("**제안자**")
    cols_to_show = [c for c in ["제안자구분", "제안자정당명", "제안자명", "대표발의 구분"] if c in proposer_rows.columns]
    st.dataframe(proposer_rows[cols_to_show], hide_index=True, use_container_width=True)
else:
    st.caption("제안자 정보 없음 (위원회 대안 등 개별 제안자 기록이 없는 의안일 수 있습니다).")

st.subheader("전체 찬성·반대·기권 수")
valid = bill_vote_df[bill_vote_df["표결결과"].isin(VALID_VOTE_VALUES)]
c1, c2, c3 = st.columns(3)
c1.metric("찬성", int((valid["표결결과"] == "찬성").sum()))
c2.metric("반대", int((valid["표결결과"] == "반대").sum()))
c3.metric("기권", int((valid["표결결과"] == "기권").sum()))

st.subheader("정당별 찬성·반대·기권 분포")
if not valid.empty:
    party_dist = valid.groupby(["정당명", "표결결과"]).size().reset_index(name="count")
    st.plotly_chart(
        px.bar(party_dist, x="정당명", y="count", color="표결결과", barmode="stack",
               color_discrete_map=VOTE_COLOR_MAP),
        use_container_width=True,
    )

st.subheader("정당별 찬성률")
if not valid.empty:
    party_yes_rate = (
        valid.assign(is_yes=(valid["표결결과"] == "찬성").astype(int))
        .groupby("정당명")["is_yes"].mean().reset_index().rename(columns={"is_yes": "찬성률"})
    )
    st.plotly_chart(px.bar(party_yes_rate, x="정당명", y="찬성률"), use_container_width=True)

st.subheader("여야 갈등도 & 초당적 합의도")
conflict_df = compute_bipartisan_conflict(bill_vote_df)
if not conflict_df.empty:
    row = conflict_df.iloc[0]
    c5, c6 = st.columns(2)
    c5.metric("여야 갈등도", f"{row['갈등도']:.2f}")
    c6.metric("초당적 합의도", f"{row['초당적합의도']:.2f}")
    st.caption("갈등도 = abs(여당 찬성률 - 야당 찬성률). 더불어민주당을 여당, 나머지 정당 전체를 야당으로 고정 계산 (공식 당론 자료 아님).")
else:
    st.info("표결 데이터가 부족하여 갈등도를 계산할 수 없습니다.")

st.subheader("의원별 표결 결과 표")
st.dataframe(bill_vote_df[["의원명", "정당명", "표결결과"]], hide_index=True, use_container_width=True)

if not detail_row.empty and pd.notna(detail_row.iloc[0].get("의안ID")):
    bill_id = detail_row.iloc[0]["의안ID"]
    st.markdown(f"[관련 의안 상세정보 링크](https://likms.assembly.go.kr/bill/billDetail.do?billId={bill_id})")

st.download_button(
    "의안별 표결 데이터 CSV 다운로드",
    data=bill_vote_df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"{selected_bill_no}_votes.csv",
    mime="text/csv",
)
