"""pages/02_정당별_표결분석.py — 정당별 표결분석"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px

from api_utils import fetch_bill_list, fetch_vote_info_bulk
from data_utils import standardize_bill_list_dataframe, standardize_vote_dataframe, generate_sample_vote_data
from metrics import compute_party_majority_ratio, compute_rice_index, compute_bipartisan_conflict

st.set_page_config(page_title="정당별 표결분석", layout="wide")
st.title("02. 정당별 표결분석")

# ---------------- 사이드바 ----------------
st.sidebar.header("조회 조건")
use_sample = st.sidebar.checkbox("샘플 데이터 사용", value=True)
eraco = st.sidebar.selectbox("국회대수", ["제22대", "제21대", "제20대"], index=0)
max_bills = st.sidebar.slider("조회할 최대 의안 수", 5, 100, 20, step=5)

st.sidebar.subheader("여야 매핑 설정 (분석용)")
st.sidebar.caption("API에 여당/야당 구분이 없어 아래 값을 직접 수정할 수 있습니다 (공식 자료 아님).")
ruling_input = st.sidebar.text_input("여당 (콤마로 구분 가능)", "국민의힘")
opposition_input = st.sidebar.text_input("주요 야당 (콤마로 구분 가능)", "더불어민주당")
ruling_parties = [p.strip() for p in ruling_input.split(",") if p.strip()]
opposition_parties = [p.strip() for p in opposition_input.split(",") if p.strip()]

if use_sample:
    st.info("⚠️ 현재 샘플 데이터를 사용 중입니다. 실제 통계가 아니며 기능 시연용입니다.")
    vote_df = generate_sample_vote_data(n_bills=max_bills)
else:
    bill_list_raw = fetch_bill_list(eraco=eraco, bill_kind="법률안", rgs_conf_rslt="원안가결", max_pages=5)
    bill_list = standardize_bill_list_dataframe(bill_list_raw)
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
    fig1 = px.bar(party_dist, x="party_name", y="count", color="vote_result", barmode="stack",
                  labels={"party_name": "정당", "count": "표결 건수", "vote_result": "표결결과"})
    st.plotly_chart(fig1, use_container_width=True)

st.subheader("정당별 평균 표결 참여율")
total_by_member = df.groupby(["party_name", "member_id"]).size().reset_index(name="votes")
participation = (
    df[df["vote_result"] != "불참"].groupby(["party_name", "member_id"]).size().reset_index(name="participated")
)
part_merged = total_by_member.merge(participation, on=["party_name", "member_id"], how="left").fillna(0)
part_merged["rate"] = part_merged["participated"] / part_merged["votes"].replace(0, pd.NA)
party_participation = part_merged.groupby("party_name")["rate"].mean().reset_index()
st.plotly_chart(
    px.bar(party_participation, x="party_name", y="rate", labels={"rate": "평균 참여율", "party_name": "정당"}),
    use_container_width=True,
)
st.caption("⚠️ '불참'은 표결 결과값 기준으로 계산했으며, API 응답 누락을 불참으로 자동 간주하지 않습니다.")

st.subheader("정당별 표결 결집도")
majority_df = compute_party_majority_ratio(df)
rice_df = compute_rice_index(df)
tab1, tab2 = st.tabs(["다수 표결 비율", "Rice Index"])
with tab1:
    if not majority_df.empty:
        avg_majority = majority_df.groupby("party_name")["majority_ratio"].mean().reset_index()
        st.plotly_chart(px.bar(avg_majority, x="party_name", y="majority_ratio"), use_container_width=True)
        st.caption("다수 표결 비율 = max(찬성,반대,기권) / 정당 내 참여자 수 (불참 제외)")
    else:
        st.info("결집도를 계산할 데이터가 부족합니다.")
with tab2:
    if not rice_df.empty:
        avg_rice = rice_df.groupby("party_name")["rice_index"].mean().reset_index()
        st.plotly_chart(px.bar(avg_rice, x="party_name", y="rice_index"), use_container_width=True)
        st.caption("Rice Index = abs(찬성-반대) / (찬성+반대). 찬성·반대가 모두 0인 의안은 결측 처리.")
    else:
        st.info("Rice Index를 계산할 데이터가 부족합니다.")

st.subheader("여야 간 표결 갈등도 & 초당적 합의도")
conflict_df = compute_bipartisan_conflict(df, ruling_parties, opposition_parties)
if not conflict_df.empty:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**갈등도가 높은 의안 (상위 10)**")
        st.dataframe(
            conflict_df.sort_values("conflict_index", ascending=False)[["bill_name", "conflict_index"]].head(10),
            hide_index=True, use_container_width=True,
        )
    with col2:
        st.markdown("**초당적 합의가 높은 의안 (상위 10)**")
        st.dataframe(
            conflict_df.sort_values("bipartisan_agreement_index", ascending=False)
            [["bill_name", "bipartisan_agreement_index"]].head(10),
            hide_index=True, use_container_width=True,
        )
    st.caption("갈등도 = abs(여당 찬성률 - 야당 찬성률). 여야 매핑은 사이드바에서 직접 설정한 값을 기준으로 함 (공식 자료 아님).")
else:
    st.info("여야 매핑에 해당하는 정당의 표결 데이터가 부족합니다. 사이드바의 여야 매핑을 확인해주세요.")

st.subheader("정당 간 표결 유사도 히트맵")
if not valid.empty:
    pivot = valid.pivot_table(
        index="bill_id", columns="party_name", values="vote_result",
        aggfunc=lambda x: x.mode().iat[0] if not x.mode().empty else None,
    )
    sim_matrix = pd.DataFrame(index=pivot.columns, columns=pivot.columns, dtype=float)
    for p1 in pivot.columns:
        for p2 in pivot.columns:
            common = pivot[[p1, p2]].dropna()
            sim_matrix.loc[p1, p2] = (common[p1] == common[p2]).mean() if not common.empty else None
    fig_heat = px.imshow(sim_matrix.astype(float), text_auto=".2f", color_continuous_scale="Blues",
                         labels=dict(color="유사도"))
    st.plotly_chart(fig_heat, use_container_width=True)
    st.caption("유사도 = 두 정당의 (의안별 다수 입장 기준) 동일 방향 표결 비율. 참고용 지표이며 인과관계를 의미하지 않습니다.")

st.download_button(
    "정당별 표결 데이터 CSV 다운로드",
    data=df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"party_vote_{eraco}.csv",
    mime="text/csv",
)
