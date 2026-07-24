"""
pages/01_전체_표결현황.py
전체 표결현황
"""

import re
import time

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# ============================================================
# 페이지 설정
# ============================================================

st.set_page_config(
    page_title="전체 표결현황",
    layout="wide",
)

st.title("01. 전체 표결현황")


# ============================================================
# API 설정
# ============================================================

BILL_LIST_API_URL = (
    "https://open.assembly.go.kr/portal/openapi/ALLBILLV2"
)

VOTE_API_URL = (
    "https://open.assembly.go.kr/portal/openapi/nojepdqqaweusdfbi"
)

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 60

REQUEST_DELAY = 0.3
MAX_RETRIES = 3

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

VOTE_RESULT_MAP = {
    "찬성": "찬성",
    "가결": "찬성",
    "반대": "반대",
    "부결": "반대",
    "기권": "기권",
    "불참": "불참",
    "결석": "불참",
    "청가": "불참",
    "출장": "불참",
}

VALID_VOTE_RESULTS = [
    "찬성",
    "반대",
    "기권",
]


# ============================================================
# API 키
# ============================================================

def get_api_key():
    """
    Streamlit Secrets에서 열린국회정보 API 키를 가져온다.
    """
    try:
        api_key = st.secrets["OPEN_ASSEMBLY_API_KEY"]

        if not api_key:
            return None

        return str(api_key).strip()

    except Exception:
        return None


# ============================================================
# API 오류 메시지
# ============================================================

def make_request_error_message(error):
    """
    API 키가 포함된 요청 URL 전체가 화면에 노출되지 않도록
    오류 종류만 안전하게 반환한다.
    """

    if isinstance(error, requests.exceptions.ConnectTimeout):
        return (
            "국회 API 서버에 연결하지 못했습니다. "
            "연결 시간이 초과되었습니다."
        )

    if isinstance(error, requests.exceptions.ReadTimeout):
        return (
            "국회 API 서버에는 연결되었지만 "
            "응답을 제한 시간 안에 받지 못했습니다."
        )

    if isinstance(error, requests.exceptions.SSLError):
        return (
            "국회 API 서버와의 보안 연결 과정에서 "
            "SSL 오류가 발생했습니다."
        )

    if isinstance(error, requests.exceptions.ConnectionError):
        return (
            "국회 API 서버와 네트워크 연결을 "
            "설정하지 못했습니다."
        )

    if isinstance(error, requests.exceptions.HTTPError):
        status_code = None

        if error.response is not None:
            status_code = error.response.status_code

        if status_code:
            return f"국회 API가 HTTP {status_code} 오류를 반환했습니다."

        return "국회 API가 HTTP 오류를 반환했습니다."

    return (
        "국회 API 요청 중 오류가 발생했습니다. "
        f"오류 유형: {type(error).__name__}"
    )


# ============================================================
# API 호출
# ============================================================

def call_api(
    base_url,
    params,
    page_index=1,
    page_size=100,
):
    """
    열린국회정보 API 한 페이지를 호출한다.

    반환값:
    rows, total_count, error_message
    """

    api_key = get_api_key()

    if not api_key:
        return (
            [],
            0,
            (
                "API 키가 설정되지 않았습니다. "
                "Streamlit Cloud Secrets 또는 "
                ".streamlit/secrets.toml을 확인하십시오."
            ),
        )

    query = {
        "KEY": api_key,
        "Type": "json",
        "pIndex": page_index,
        "pSize": page_size,
    }

    query.update(
        {
            key: value
            for key, value in params.items()
            if value not in (None, "")
        }
    )

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    last_error = None
    response = None

    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(
                base_url,
                params=query,
                timeout=(
                    CONNECT_TIMEOUT,
                    READ_TIMEOUT,
                ),
            )

            response.raise_for_status()
            last_error = None
            break

        except requests.exceptions.RequestException as error:
            last_error = error

            if attempt < MAX_RETRIES - 1:
                wait_seconds = 2 ** attempt
                time.sleep(wait_seconds)

    if last_error is not None:
        return (
            [],
            0,
            make_request_error_message(last_error),
        )

    if response is None:
        return (
            [],
            0,
            "국회 API 응답을 받지 못했습니다.",
        )

    try:
        data = response.json()

    except ValueError:
        response_preview = response.text[:300]

        return (
            [],
            0,
            (
                "국회 API 응답을 JSON으로 해석할 수 없습니다. "
                f"응답 앞부분: {response_preview}"
            ),
        )

    if not isinstance(data, dict):
        return (
            [],
            0,
            "국회 API 응답 형식이 예상과 다릅니다.",
        )

    # 최상위 오류 응답
    if "RESULT" in data:
        result = data.get("RESULT", {})

        return (
            [],
            0,
            (
                f"[{result.get('CODE', '오류코드 없음')}] "
                f"{result.get('MESSAGE', '오류 메시지 없음')}"
            ),
        )

    endpoint_key = next(iter(data.keys()), None)

    if endpoint_key is None:
        return (
            [],
            0,
            "국회 API 응답에서 데이터 항목을 찾을 수 없습니다.",
        )

    endpoint_data = data.get(endpoint_key)

    if not isinstance(endpoint_data, list):
        return (
            [],
            0,
            "국회 API 응답 내부 구조가 예상과 다릅니다.",
        )

    total_count = 0
    rows = []

    for section in endpoint_data:
        if not isinstance(section, dict):
            continue

        if "head" in section:
            head_items = section.get("head", [])

            if isinstance(head_items, list):
                for head_item in head_items:
                    if not isinstance(head_item, dict):
                        continue

                    if "list_total_count" in head_item:
                        try:
                            total_count = int(
                                head_item["list_total_count"]
                            )
                        except (TypeError, ValueError):
                            total_count = 0

                    result = head_item.get("RESULT")

                    if isinstance(result, dict):
                        result_code = result.get("CODE")

                        if result_code not in (
                            "INFO-000",
                            None,
                        ):
                            return (
                                [],
                                0,
                                (
                                    f"[{result_code}] "
                                    f"{result.get('MESSAGE', '')}"
                                ),
                            )

        if "row" in section:
            section_rows = section.get("row", [])

            if isinstance(section_rows, list):
                rows = section_rows

    return rows, total_count, None


# ============================================================
# 페이지네이션
# ============================================================

def fetch_all_pages(
    base_url,
    params,
    page_size=100,
    max_pages=20,
    progress_label=None,
):
    """
    API 페이지네이션을 처리한다.

    중간 페이지에서 실패하면 지금까지 받은 데이터와
    오류 메시지를 함께 반환한다.
    """

    all_rows = []
    page = 1
    total_count = None

    progress_bar = None

    if progress_label:
        progress_bar = st.progress(
            0.0,
            text=progress_label,
        )

    while page <= max_pages:
        rows, total_count, error = call_api(
            base_url=base_url,
            params=params,
            page_index=page,
            page_size=page_size,
        )

        if error:
            if progress_bar:
                progress_bar.empty()

            return all_rows, error

        if not rows:
            break

        all_rows.extend(rows)

        if progress_bar and total_count:
            progress_ratio = min(
                len(all_rows) / max(total_count, 1),
                1.0,
            )

            progress_bar.progress(
                progress_ratio,
                text=(
                    f"{progress_label} "
                    f"({len(all_rows):,}/{total_count:,})"
                ),
            )

        if total_count and len(all_rows) >= total_count:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    if progress_bar:
        progress_bar.empty()

    if (
        total_count
        and len(all_rows) < total_count
        and page > max_pages
    ):
        st.info(
            f"전체 {total_count:,}건 중 "
            f"{len(all_rows):,}건만 조회했습니다. "
            f"페이지 제한: {max_pages}"
        )

    return all_rows, None


# ============================================================
# 의안 목록 조회
# ============================================================

@st.cache_data(
    ttl=3600,
    show_spinner=False,
)
def fetch_bill_list(
    eraco,
    bill_kind=None,
    rgs_conf_rslt=None,
    max_pages=5,
):
    """
    의안정보 통합 API에서 의안 목록을 조회한다.
    """

    params = {
        "ERACO": eraco,
        "BILL_KND": bill_kind,
        "RGS_CONF_RSLT": rgs_conf_rslt,
    }

    rows, error = fetch_all_pages(
        base_url=BILL_LIST_API_URL,
        params=params,
        page_size=100,
        max_pages=max_pages,
        progress_label="의안 목록 조회 중",
    )

    if error:
        raise RuntimeError(error)

    return pd.DataFrame(rows)


# ============================================================
# 표결정보 조회
# ============================================================

@st.cache_data(
    ttl=3600,
    show_spinner=False,
)
def fetch_vote_info_single(
    bill_id,
    age,
):
    """
    단일 의안의 국회의원별 본회의 표결정보를 조회한다.
    """

    params = {
        "AGE": age,
        "BILL_ID": bill_id,
    }

    rows, error = fetch_all_pages(
        base_url=VOTE_API_URL,
        params=params,
        page_size=300,
        max_pages=5,
    )

    if error:
        raise RuntimeError(error)

    return pd.DataFrame(rows)


def fetch_vote_info_bulk(
    bill_ids,
    age,
    max_bills=20,
):
    """
    여러 의안의 표결정보를 순차적으로 조회한다.
    """

    selected_bill_ids = list(bill_ids)[:max_bills]

    all_dataframes = []
    errors = []

    if not selected_bill_ids:
        return pd.DataFrame(), errors

    progress_bar = st.progress(
        0.0,
        text="의안별 표결정보 조회 중",
    )

    for index, bill_id in enumerate(selected_bill_ids):
        try:
            vote_data = fetch_vote_info_single(
                bill_id=bill_id,
                age=age,
            )

            if not vote_data.empty:
                all_dataframes.append(vote_data)

        except RuntimeError as error:
            errors.append(
                {
                    "bill_id": bill_id,
                    "error": str(error),
                }
            )

        progress_bar.progress(
            (index + 1) / len(selected_bill_ids),
            text=(
                "의안별 표결정보 조회 중 "
                f"({index + 1}/{len(selected_bill_ids)})"
            ),
        )

        time.sleep(REQUEST_DELAY)

    progress_bar.empty()

    if not all_dataframes:
        return pd.DataFrame(), errors

    combined = pd.concat(
        all_dataframes,
        ignore_index=True,
    )

    return combined, errors


# ============================================================
# 데이터 정리 함수
# ============================================================

def standardize_vote_result(value):
    """
    표결 결과를 찬성·반대·기권·불참으로 표준화한다.
    """

    if pd.isna(value):
        return None

    normalized = str(value).strip()

    return VOTE_RESULT_MAP.get(
        normalized,
        normalized,
    )


def clean_party_name(value):
    """
    정당명의 앞뒤 및 내부 공백을 제거한다.
    """

    if pd.isna(value):
        return "정보없음"

    name = re.sub(
        r"\s+",
        "",
        str(value).strip(),
    )

    return name if name else "정보없음"


def standardize_vote_date(value):
    """
    다양한 표결일자 형식을 pandas datetime으로 변환한다.
    """

    if pd.isna(value):
        return pd.NaT

    value = str(value).strip()

    formats = (
        "%Y%m%d %H%M%S",
        "%Y%m%d",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    )

    for date_format in formats:
        try:
            return pd.to_datetime(
                value,
                format=date_format,
            )

        except (ValueError, TypeError):
            continue

    return pd.to_datetime(
        value,
        errors="coerce",
    )


def get_column_or_default(
    dataframe,
    column_name,
    default_value=None,
):
    """
    데이터프레임에 컬럼이 있으면 반환하고,
    없으면 동일 길이의 기본값 Series를 반환한다.
    """

    if column_name in dataframe.columns:
        return dataframe[column_name]

    return pd.Series(
        [default_value] * len(dataframe),
        index=dataframe.index,
    )


def standardize_vote_dataframe(dataframe):
    """
    표결정보 API 응답을 분석용 표준 컬럼으로 변환한다.
    """

    standard_columns = [
        "assembly_no",
        "bill_id",
        "bill_no",
        "bill_name",
        "vote_date",
        "member_id",
        "member_name",
        "party_name",
        "vote_result",
        "committee_name",
    ]

    if dataframe is None or dataframe.empty:
        return pd.DataFrame(
            columns=standard_columns
        )

    output = pd.DataFrame(
        index=dataframe.index
    )

    output["assembly_no"] = get_column_or_default(
        dataframe,
        "AGE",
    )

    output["bill_id"] = get_column_or_default(
        dataframe,
        "BILL_ID",
    )

    output["bill_no"] = get_column_or_default(
        dataframe,
        "BILL_NO",
    )

    # 표결 API에서 의안명 필드명이 다를 가능성에 대비
    if "BILL_NAME" in dataframe.columns:
        output["bill_name"] = dataframe["BILL_NAME"]

    elif "BILL_NM" in dataframe.columns:
        output["bill_name"] = dataframe["BILL_NM"]

    else:
        output["bill_name"] = None

    if "VOTE_DATE" in dataframe.columns:
        output["vote_date"] = dataframe[
            "VOTE_DATE"
        ].apply(standardize_vote_date)

    else:
        output["vote_date"] = pd.NaT

    output["member_id"] = get_column_or_default(
        dataframe,
        "MEMBER_NO",
    )

    output["member_name"] = get_column_or_default(
        dataframe,
        "HG_NM",
    )

    if "POLY_NM" in dataframe.columns:
        output["party_name"] = dataframe[
            "POLY_NM"
        ].apply(clean_party_name)

    else:
        output["party_name"] = "정보없음"

    if "RESULT_VOTE_MOD" in dataframe.columns:
        output["vote_result"] = dataframe[
            "RESULT_VOTE_MOD"
        ].apply(standardize_vote_result)

    else:
        output["vote_result"] = None

    output["committee_name"] = get_column_or_default(
        dataframe,
        "CURR_COMMITTEE",
    )

    output = output.dropna(
        subset=["bill_id", "member_id"],
        how="all",
    )

    output = output.drop_duplicates(
        subset=["bill_id", "member_id"],
        keep="first",
    )

    return output.reset_index(drop=True)


def standardize_bill_list_dataframe(dataframe):
    """
    의안 목록 API 응답을 정리한다.
    """

    if dataframe is None or dataframe.empty:
        return pd.DataFrame()

    if "BILL_ID" not in dataframe.columns:
        raise ValueError(
            "의안 목록 API 응답에 BILL_ID 컬럼이 없습니다."
        )

    output = dataframe.copy()

    output = output.dropna(
        subset=["BILL_ID"]
    )

    output = output.drop_duplicates(
        subset=["BILL_ID"],
        keep="first",
    )

    for column in (
        "PPSL_DT",
        "RGS_RSLN_DT",
    ):
        if column in output.columns:
            output[column] = pd.to_datetime(
                output[column],
                errors="coerce",
            )

    # 최신 의결일 우선
    if "RGS_RSLN_DT" in output.columns:
        output = output.sort_values(
            by="RGS_RSLN_DT",
            ascending=False,
            na_position="last",
        )

    elif "PPSL_DT" in output.columns:
        output = output.sort_values(
            by="PPSL_DT",
            ascending=False,
            na_position="last",
        )

    return output.reset_index(drop=True)


def check_required_columns(
    dataframe,
    required_columns,
    context_label="데이터",
):
    """
    필수 컬럼의 존재 여부를 확인한다.
    """

    missing_columns = [
        column
        for column in required_columns
        if column not in dataframe.columns
    ]

    if missing_columns:
        st.error(
            f"{context_label}에 필요한 컬럼이 없습니다: "
            f"{missing_columns}"
        )

        return False

    return True


# ============================================================
# 샘플 데이터
# ============================================================

def generate_sample_vote_data(
    n_bills=15,
    n_members=60,
    seed=42,
):
    """
    대시보드 기능 확인용 샘플 데이터를 생성한다.
    실제 국회 표결 데이터가 아니다.
    """

    random_generator = np.random.default_rng(seed)

    parties = [
        "더불어민주당",
        "국민의힘",
        "조국혁신당",
        "개혁신당",
        "무소속",
    ]

    party_weights = [
        0.42,
        0.38,
        0.08,
        0.06,
        0.06,
    ]

    members = [
        f"샘플의원{index + 1:03d}"
        for index in range(n_members)
    ]

    member_parties = random_generator.choice(
        parties,
        size=n_members,
        p=party_weights,
    )

    member_ids = [
        f"SAMPLE_MEMBER_{index + 1:05d}"
        for index in range(n_members)
    ]

    bills = [
        f"샘플법률{index + 1:03d} 일부개정법률안"
        for index in range(n_bills)
    ]

    bill_ids = [
        f"SAMPLE_BILL_{index + 1:03d}"
        for index in range(n_bills)
    ]

    committees = [
        "기획재정위원회",
        "교육위원회",
        "행정안전위원회",
        "보건복지위원회",
        "환경노동위원회",
    ]

    rows = []
    base_date = pd.Timestamp("2024-06-01")

    for bill_index, (
        bill_id,
        bill_name,
    ) in enumerate(
        zip(
            bill_ids,
            bills,
        )
    ):
        vote_date = (
            base_date
            + pd.Timedelta(
                days=int(
                    random_generator.integers(
                        0,
                        400,
                    )
                )
            )
        )

        committee = random_generator.choice(
            committees
        )

        party_yes_probability = {
            party: random_generator.uniform(
                0.3,
                0.95,
            )
            for party in parties
        }

        for (
            member_name,
            member_party,
            member_id,
        ) in zip(
            members,
            member_parties,
            member_ids,
        ):
            if random_generator.random() < 0.05:
                vote_result = "불참"

            else:
                yes_probability = (
                    party_yes_probability[
                        member_party
                    ]
                )

                if (
                    random_generator.random()
                    < yes_probability
                ):
                    vote_result = "찬성"

                else:
                    vote_result = (
                        random_generator.choice(
                            ["반대", "기권"],
                            p=[0.85, 0.15],
                        )
                    )

            rows.append(
                {
                    "assembly_no": "22",
                    "bill_id": bill_id,
                    "bill_no": (
                        f"22{bill_index + 10000}"
                    ),
                    "bill_name": bill_name,
                    "vote_date": vote_date,
                    "member_id": member_id,
                    "member_name": member_name,
                    "party_name": member_party,
                    "vote_result": vote_result,
                    "committee_name": committee,
                }
            )

    return pd.DataFrame(rows)


# ============================================================
# 사이드바
# ============================================================

st.sidebar.header("조회 조건")

use_sample = st.sidebar.checkbox(
    "샘플 데이터 사용",
    value=False,
    help=(
        "실제 API 연결이 되지 않을 때 "
        "대시보드 기능을 확인하기 위한 옵션입니다."
    ),
)

eraco = st.sidebar.selectbox(
    "국회대수",
    [
        "제22대",
        "제21대",
        "제20대",
    ],
    index=0,
)

bill_kind = st.sidebar.selectbox(
    "의안 종류",
    [
        "전체",
        "법률안",
        "예산안",
        "동의안",
        "결의안",
    ],
    index=1,
)

resolution_result = st.sidebar.selectbox(
    "본회의 처리결과",
    [
        "전체",
        "원안가결",
        "수정가결",
        "부결",
        "폐기",
        "철회",
    ],
    index=0,
)

max_bills = st.sidebar.slider(
    "조회할 최대 의안 수",
    min_value=5,
    max_value=100,
    value=20,
    step=5,
    help=(
        "의안 수가 많아질수록 "
        "표결정보 API 호출 횟수가 증가합니다."
    ),
)

if st.sidebar.button(
    "캐시 지우고 새로고침",
):
    st.cache_data.clear()
    st.rerun()


# ============================================================
# 데이터 불러오기
# ============================================================

if use_sample:
    st.info(
        "현재 샘플 데이터를 사용하고 있습니다. "
        "실제 국회 표결 통계가 아닙니다."
    )

    vote_df = generate_sample_vote_data(
        n_bills=max_bills
    )

else:
    bill_kind_parameter = (
        None
        if bill_kind == "전체"
        else bill_kind
    )

    resolution_parameter = (
        None
        if resolution_result == "전체"
        else resolution_result
    )

    try:
        bill_list_raw = fetch_bill_list(
            eraco=eraco,
            bill_kind=bill_kind_parameter,
            rgs_conf_rslt=resolution_parameter,
            max_pages=5,
        )

        bill_list = (
            standardize_bill_list_dataframe(
                bill_list_raw
            )
        )

    except RuntimeError as error:
        st.error(
            f"의안 목록 조회 오류: {error}"
        )
        bill_list = pd.DataFrame()

    except ValueError as error:
        st.error(
            f"의안 목록 처리 오류: {error}"
        )
        bill_list = pd.DataFrame()

    if bill_list.empty:
        st.warning(
            "의안 목록을 가져오지 못했습니다. "
            "Streamlit Cloud에서는 국회 서버 연결이 "
            "차단되거나 지연될 수 있습니다."
        )
        st.stop()

    age_number = (
        eraco
        .replace("제", "")
        .replace("대", "")
    )

    bill_ids = (
        bill_list["BILL_ID"]
        .dropna()
        .drop_duplicates()
        .head(max_bills)
        .tolist()
    )

    vote_raw, vote_errors = fetch_vote_info_bulk(
        bill_ids=bill_ids,
        age=age_number,
        max_bills=max_bills,
    )

    if vote_errors:
        st.warning(
            f"선택한 {len(bill_ids):,}개 의안 중 "
            f"{len(vote_errors):,}개 의안의 표결정보를 "
            "가져오지 못했습니다."
        )

        with st.expander(
            "표결정보 조회 실패 내역"
        ):
            error_dataframe = pd.DataFrame(
                vote_errors
            )

            st.dataframe(
                error_dataframe,
                use_container_width=True,
                hide_index=True,
            )

    vote_df = standardize_vote_dataframe(
        vote_raw
    )


# ============================================================
# 기본 검증
# ============================================================

if vote_df.empty:
    st.warning(
        "표시할 표결 데이터가 없습니다."
    )
    st.stop()

required_columns = [
    "bill_id",
    "member_id",
    "vote_result",
    "vote_date",
]

if not check_required_columns(
    vote_df,
    required_columns,
    "표결 데이터",
):
    st.stop()


# ============================================================
# 핵심 지표
# ============================================================

total_bills = vote_df[
    "bill_id"
].nunique()

total_target_members = vote_df[
    "member_id"
].nunique()

participated_df = vote_df[
    vote_df["vote_result"].isin(
        VALID_VOTE_RESULTS
    )
]

total_participated_members = participated_df[
    "member_id"
].nunique()

total_vote_records = len(vote_df)

valid_votes = vote_df[
    vote_df["vote_result"].isin(
        VALID_VOTE_RESULTS
    )
]

if valid_votes.empty:
    yes_rate = 0
    no_rate = 0
    abstain_rate = 0

else:
    yes_rate = (
        valid_votes["vote_result"] == "찬성"
    ).mean()

    no_rate = (
        valid_votes["vote_result"] == "반대"
    ).mean()

    abstain_rate = (
        valid_votes["vote_result"] == "기권"
    ).mean()

metric_columns = st.columns(7)

metric_columns[0].metric(
    "조회 의안 수",
    f"{total_bills:,}",
)

metric_columns[1].metric(
    "표결 대상 의원 수",
    f"{total_target_members:,}",
)

metric_columns[2].metric(
    "실제 참여 의원 수",
    f"{total_participated_members:,}",
)

metric_columns[3].metric(
    "표결 기록 수",
    f"{total_vote_records:,}",
)

metric_columns[4].metric(
    "찬성률",
    f"{yes_rate:.1%}",
)

metric_columns[5].metric(
    "반대율",
    f"{no_rate:.1%}",
)

metric_columns[6].metric(
    "기권율",
    f"{abstain_rate:.1%}",
)

st.caption(
    "찬성률·반대율·기권율은 "
    "찬성·반대·기권 표결만을 분모로 계산합니다. "
    "불참은 제외됩니다."
)

st.divider()


# ============================================================
# 날짜별 표결 의안 수
# ============================================================

st.subheader("날짜별 표결 의안 수")

valid_date_df = vote_df.dropna(
    subset=["vote_date"]
).copy()

if not valid_date_df.empty:
    valid_date_df["vote_day"] = (
        valid_date_df["vote_date"].dt.date
    )

    by_date = (
        valid_date_df
        .groupby("vote_day")["bill_id"]
        .nunique()
        .reset_index(name="bill_count")
    )

    figure_by_date = px.bar(
        by_date,
        x="vote_day",
        y="bill_count",
        labels={
            "vote_day": "표결일",
            "bill_count": "의안 수",
        },
    )

    st.plotly_chart(
        figure_by_date,
        use_container_width=True,
    )

    st.caption(
        "기록표결 또는 전자표결 자료를 기준으로 하므로 "
        "모든 본회의 안건을 포함한다고 단정할 수 없습니다."
    )

else:
    st.info(
        "표결일자 정보가 없어 "
        "날짜별 차트를 표시할 수 없습니다."
    )


# ============================================================
# 표결 결과 분포
# ============================================================

st.subheader("표결 결과 분포")

result_distribution = (
    vote_df["vote_result"]
    .fillna("정보없음")
    .value_counts()
    .rename_axis("vote_result")
    .reset_index(name="count")
)

figure_result = px.pie(
    result_distribution,
    names="vote_result",
    values="count",
    hole=0.4,
)

st.plotly_chart(
    figure_result,
    use_container_width=True,
)

st.caption(
    "불참은 API의 표결 결과값을 기준으로 집계하며, "
    "API 응답 누락을 자동으로 불참 처리하지 않습니다."
)


# ============================================================
# 최근 표결 의안 목록
# ============================================================

st.subheader("최근 표결 의안 목록")

recent_columns = [
    "vote_date",
    "bill_name",
    "bill_no",
    "committee_name",
]

available_recent_columns = [
    column
    for column in recent_columns
    if column in vote_df.columns
]

recent_bills = (
    vote_df
    .dropna(subset=["vote_date"])
    .drop_duplicates(subset=["bill_id"])
    .sort_values(
        by="vote_date",
        ascending=False,
    )
    [available_recent_columns]
    .head(20)
)

if recent_bills.empty:
    st.info(
        "최근 표결 의안 목록을 표시할 수 없습니다."
    )

else:
    st.dataframe(
        recent_bills,
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# 원자료 확인
# ============================================================

with st.expander("표결 원자료 보기"):
    st.dataframe(
        vote_df,
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# CSV 다운로드
# ============================================================

st.download_button(
    label="전체 표결 데이터 CSV 다운로드",
    data=vote_df.to_csv(
        index=False
    ).encode("utf-8-sig"),
    file_name=(
        f"vote_data_{eraco}.csv"
    ),
    mime="text/csv",
)
