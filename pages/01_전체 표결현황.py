"""pages/01_전체_표결현황.py — 전체 표결현황"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px

from api_utils import fetch_bill_list, fetch_vote_info_bulk
from data_utils import (
    standardize_bill_list_dataframe, standardize_vote_dataframe,
    generate_sample_vote_data, check_required_columns,
)

st.set_page_config(page_title="전체 표결현황", layout="wide")
st.title("01. 전체 표결현황")

# ---------------- 사이드바 ----------------
st.sidebar.header("조회 조건")
use_sample = st.sidebar.checkbox("샘플 데이터 사용", value=True,
                                  help="API 키가 없거나 실제 데이터를 아직 테스트하지 않았다면 체크하세요.")
eraco = st.sidebar.selectbox("국회대수", ["제22대", "제21대", "제20대"], index=0)
bill_kind = st.sidebar.selectbox("의안 종류 필터", ["전체", "법률안", "예산안", "동의안", "결의안"], index=1)
max_bills = st.sidebar.slider("조회할 최대 의안 수", min_value=5, max_value=100, value=20, step=5,
                              help="의안 수가 많을수록 API 호출 시간이 오래 걸립니다.")

if use_sample:
    st.info("⚠️ 현재 샘플 데이터를 사용 중입니다. 실제 통계가 아니며 기능 시연용입니다.")
    vote_df = generate_sample_vote_data(n_bills=max_bills)
else:
    kind_param = None if bill_kind == "전체" else bill_kind
    bill_list_raw = fetch_bill_list(eraco=eraco, bill_kind=kind_param, rgs_conf_rslt="원안가결", max_pages=5)
    bill_list = standardize_bill_list_dataframe(bill_list_raw)

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

# ---------------- 핵심 지표 ----------------
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

# ---------------- 날짜별 표결 의안 수 ----------------
st.subheader("날짜별 표결 의안 수")
if vote_df["vote_date"].notna().any():
    by_date = (
        vote_df.dropna(subset=["vote_date"])
        .groupby(vote_df["vote_date"].dt.date)["bill_id"].nunique()
        .reset_index(name="bill_count")
    )
    by_date.columns = ["vote_date", "bill_count"]
    fig1 = px.bar(by_date, x="vote_date", y="bill_count", labels={"vote_date": "날짜", "bill_count": "의안 수"})
    st.plotly_chart(fig1, use_container_width=True)
    st.caption("⚠️ 기록표결(전자표결) 기준으로, 모든 본회의 안건을 대표하지 않을 수 있습니다.")
else:
    st.info("표결일자 정보가 없어 날짜별 차트를 표시할 수 없습니다.")

# ---------------- 표결 결과 분포 ----------------
st.subheader("표결 결과 분포")
result_dist = vote_df["vote_result"].value_counts().reset_index()
result_dist.columns = ["vote_result", "count"]
fig2 = px.pie(result_dist, names="vote_result", values="count", hole=0.4)
st.plotly_chart(fig2, use_container_width=True)
st.caption("⚠️ '불참'은 실제 표결 결과값이며, API 응답 누락을 의미하지 않습니다.")

# ---------------- 최근 표결 의안 목록 ----------------
st.subheader("최근 표결 의안 목록")
recent_bills = (
    vote_df.dropna(subset=["vote_date"])
    .drop_duplicates(subset=["bill_id"])
    .sort_values("vote_date", ascending=False)
    [["vote_date", "bill_name", "bill_no", "committee_name"]]
    .head(20)
)
st.dataframe(recent_bills, use_container_width=True, hide_index=True)

# ---------------- CSV 다운로드 ----------------
st.download_button(
    "전체 표결 데이터 CSV 다운로드",
    data=vote_df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"vote_data_{eraco}.csv",
    mime="text/csv",
)
