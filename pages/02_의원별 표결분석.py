"""pages/03_의원별_표결분석.py — 의원별 표결분석"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px

from api_utils import fetch_bill_list, fetch_vote_info_bulk
from data_utils import standardize_bill_list_dataframe, standardize_vote_dataframe, generate_sample_vote_data
from metrics import compute_member_agreement_with_party, compute_member_similarity

st.set_page_config(page_title="의원별 표결분석", layout="wide")
st.title("03. 의원별 표결분석")

st.sidebar.header("조회 조건")
use_sample = st.sidebar.checkbox("샘플 데이터 사용", value=True)
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
