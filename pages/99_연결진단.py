import requests
import streamlit as st

st.set_page_config(
    page_title="API 연결 진단",
    layout="wide",
)

st.title("국회 API 연결 진단")

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

ASSEMBLY_HOME_URL = "https://open.assembly.go.kr"
BILL_API_URL = "https://open.assembly.go.kr/portal/openapi/ALLBILLV2"


def get_api_key():
    try:
        return st.secrets["OPEN_ASSEMBLY_API_KEY"]
    except Exception:
        return None


st.write(
    "국회 홈페이지 연결과 Open API 연결을 각각 검사합니다. "
    "이 페이지는 분석용이 아니라 오류 원인 확인용입니다."
)

if st.button("연결 테스트 실행"):
    api_key = get_api_key()

    st.subheader("1. 국회 홈페이지 연결")

    try:
        response = requests.get(
            ASSEMBLY_HOME_URL,
            headers=REQUEST_HEADERS,
            timeout=(10, 30),
        )

        st.success(
            f"국회 홈페이지 연결 성공: HTTP {response.status_code}"
        )

    except requests.exceptions.ConnectTimeout:
        st.error(
            "국회 홈페이지 연결 실패: 연결 시간 초과\n\n"
            "Streamlit Cloud와 국회 서버 사이의 네트워크 문제 또는 "
            "접속 IP 제한 가능성이 있습니다."
        )

    except requests.exceptions.ReadTimeout:
        st.error(
            "국회 홈페이지에는 연결됐지만 응답을 받는 데 시간이 초과됐습니다."
        )

    except requests.exceptions.RequestException as e:
        st.error(
            f"국회 홈페이지 연결 오류: {type(e).__name__}: {e}"
        )

    st.subheader("2. 의안 목록 API 연결")

    if not api_key:
        st.error(
            "OPEN_ASSEMBLY_API_KEY가 설정되지 않았습니다. "
            "Streamlit Secrets를 확인하십시오."
        )

    else:
        params = {
            "KEY": api_key,
            "Type": "json",
            "pIndex": 1,
            "pSize": 1,
            "ERACO": "제22대",
        }

        try:
            response = requests.get(
                BILL_API_URL,
                params=params,
                headers=REQUEST_HEADERS,
                timeout=(10, 60),
            )

            st.write(f"요청 상태 코드: {response.status_code}")
            st.write(f"실제 요청 주소: {response.url.replace(api_key, '***')}")

            response.raise_for_status()

            try:
                data = response.json()
                st.success("국회 Open API 연결 및 JSON 응답 성공")
                st.json(data)

            except ValueError:
                st.error("응답을 JSON으로 해석할 수 없습니다.")
                st.code(response.text[:1000])

        except requests.exceptions.ConnectTimeout:
            st.error(
                "API 서버 연결 실패: 연결 시간 초과\n\n"
                "홈페이지 연결은 되는데 API만 실패한다면 "
                "API 엔드포인트 제한 또는 국회 API 서버 문제일 가능성이 큽니다."
            )

        except requests.exceptions.ReadTimeout:
            st.error(
                "API 서버에는 연결됐지만 응답을 제한 시간 안에 받지 못했습니다."
            )

        except requests.exceptions.HTTPError as e:
            st.error(
                f"API HTTP 오류: {e.response.status_code}"
            )
            st.code(e.response.text[:1000])

        except requests.exceptions.RequestException as e:
            st.error(
                f"API 요청 오류: {type(e).__name__}: {e}"
            )
