import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import anthropic
import httpx
from datetime import datetime, timedelta

st.set_page_config(page_title="한국 주식 분석기", page_icon="📈", layout="wide")
st.title("📈 한국 주식 차트 분석기")

# 세션 상태 초기화
for key in ["df", "ticker", "last_updated"]:
    if key not in st.session_state:
        st.session_state[key] = None

# 기간 → 날짜 변환
period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730}

# 사이드바
with st.sidebar:
    st.header("설정")
    ticker_input = st.text_input("종목코드", "005930",
                                  help="예: 005930(삼성전자), 035720(카카오), 000660(SK하이닉스)")
    period = st.select_slider("조회 기간", list(period_days.keys()), value="3mo",
                               format_func=lambda x: {"1mo":"1개월","3mo":"3개월","6mo":"6개월","1y":"1년","2y":"2년"}[x])
    api_key = st.text_input("Anthropic API 키 (AI 전망용)", type="password")

    analyze_btn  = st.button("분석 시작", type="primary", use_container_width=True)
    refresh_btn  = st.button("새로고침", use_container_width=True,
                              help="최신 데이터로 업데이트")

    if st.session_state.last_updated:
        st.caption(f"마지막 업데이트: {st.session_state.last_updated}")

st.caption("인기 종목: 005930(삼성전자) · 000660(SK하이닉스) · 035720(카카오) · 005380(현대차) · 035420(NAVER)")

def load_data(ticker_input, period):
    """FinanceDataReader로 주가 데이터 로드"""
    start = (datetime.now() - timedelta(days=period_days[period])).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker_input.strip(), start)
    if df.empty:
        return None
    df = df[["Open","High","Low","Close","Volume"]].copy()
    df["MA5"]  = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))
    return df

# 분석 시작 또는 새로고침
if analyze_btn or refresh_btn:
    with st.spinner("데이터 불러오는 중..."):
        df = load_data(ticker_input, period)
    if df is None:
        st.error("데이터를 찾을 수 없습니다. 종목코드를 확인해주세요.")
        st.stop()
    st.session_state.df = df
    st.session_state.ticker = ticker_input.strip()
    st.session_state.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 데이터가 있으면 표시
if st.session_state.df is not None:
    df     = st.session_state.df
    ticker = st.session_state.ticker

    # 차트
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
                        subplot_titles=["캔들 차트 + 이동평균선", "거래량", "RSI"])
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                                  low=df["Low"], close=df["Close"],
                                  increasing_line_color="red", decreasing_line_color="blue",
                                  name="주가"), row=1, col=1)
    for col, color, lname in [("MA5","orange","5일"), ("MA20","green","20일"), ("MA60","purple","60일")]:
        fig.add_trace(go.Scatter(x=df.index, y=df[col], name=f"MA{lname}",
                                  line=dict(color=color, width=1.2)), row=1, col=1)
    bar_colors = ["red" if c >= o else "blue" for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=bar_colors,
                          showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                              line=dict(color="darkorange", width=1.5)), row=3, col=1)
    fig.add_hrect(y0=70, y1=100, fillcolor="red",  opacity=0.05, row=3, col=1)
    fig.add_hrect(y0=0,  y1=30,  fillcolor="blue", opacity=0.05, row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red",  line_width=1, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="blue", line_width=1, row=3, col=1)
    fig.update_layout(height=680, xaxis_rangeslider_visible=False,
                       legend=dict(orientation="h", y=1.02), margin=dict(t=60, b=20))
    st.plotly_chart(fig, use_container_width=True)

    # 핵심 지표
    latest     = df.iloc[-1]
    prev       = df.iloc[-2]
    change_pct = float((latest["Close"] - prev["Close"]) / prev["Close"] * 100)
    rsi_val    = float(latest["RSI"])
    rsi_label  = "과매수" if rsi_val > 70 else "과매도" if rsi_val < 30 else "중립"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("현재가",    f"{float(latest['Close']):,.0f}원", f"{change_pct:+.2f}%")
    c2.metric("RSI",      f"{rsi_val:.1f}", rsi_label)
    c3.metric("5일 평균",  f"{float(latest['MA5']):,.0f}원")
    c4.metric("52주 고가", f"{float(df['High'].max()):,.0f}원")
    c5.metric("52주 저가", f"{float(df['Low'].min()):,.0f}원")

    st.divider()

    # 자동 차트 분석
    st.subheader("자동 차트 분석 및 전망")

    def auto_analyze(df, latest, rsi_val, change_pct):
        close  = float(latest["Close"])
        ma5    = float(latest["MA5"])
        ma20   = float(latest["MA20"])
        ma60   = float(latest["MA60"])
        high52 = float(df["High"].max())
        low52  = float(df["Low"].min())
        pos52  = (close - low52) / (high52 - low52) * 100 if high52 != low52 else 50
        lines  = []

        if ma5 > ma20 > ma60:
            lines.append("이동평균선이 단기>중기>장기 순으로 정렬되어 있어 **상승 추세**가 확인됩니다.")
        elif ma5 < ma20 < ma60:
            lines.append("이동평균선이 단기<중기<장기 순으로 정렬되어 있어 **하락 추세**가 지속되고 있습니다.")
        else:
            lines.append("이동평균선이 혼조세로, 뚜렷한 방향성 없이 **횡보 중**입니다.")

        if ma5 > ma20 and df["MA5"].iloc[-5] < df["MA20"].iloc[-5]:
            lines.append("최근 5일선이 20일선을 위로 돌파 — **골든크로스** 발생, 단기 매수 신호입니다.")
        elif ma5 < ma20 and df["MA5"].iloc[-5] > df["MA20"].iloc[-5]:
            lines.append("최근 5일선이 20일선을 아래로 이탈 — **데드크로스** 발생, 단기 주의가 필요합니다.")

        if rsi_val >= 80:
            lines.append(f"RSI {rsi_val:.1f} — **심한 과매수** 구간. 신규 매수 자제하세요.")
        elif rsi_val >= 70:
            lines.append(f"RSI {rsi_val:.1f} — **과매수** 구간. 단기 차익 실현 매물이 나올 수 있습니다.")
        elif rsi_val <= 20:
            lines.append(f"RSI {rsi_val:.1f} — **심한 과매도** 구간. 기술적 반등 가능성이 있습니다.")
        elif rsi_val <= 30:
            lines.append(f"RSI {rsi_val:.1f} — **과매도** 구간. 저점 매수 기회를 고려해볼 수 있습니다.")
        else:
            lines.append(f"RSI {rsi_val:.1f} — **중립** 구간. 과열도 침체도 아닌 안정적인 상태입니다.")

        if pos52 >= 90:
            lines.append(f"52주 범위 **{pos52:.0f}% 위치** — 신고가 근처. 고점 리스크에 주의하세요.")
        elif pos52 <= 10:
            lines.append(f"52주 범위 **{pos52:.0f}% 위치** — 저점 구간. 추가 하락 가능성도 열려 있습니다.")
        else:
            lines.append(f"52주 범위의 **{pos52:.0f}% 위치**에 있습니다.")

        if change_pct >= 5:
            lines.append(f"전일 대비 **+{change_pct:.2f}%** 급등. 거래량과 함께 확인이 필요합니다.")
        elif change_pct <= -5:
            lines.append(f"전일 대비 **{change_pct:.2f}%** 급락. 원인 파악 후 대응하세요.")

        score = sum([ma5 > ma20, ma20 > ma60, rsi_val < 60, rsi_val > 40, change_pct > 0])
        lines.append("---")
        if score >= 4:
            lines.append("**종합 의견:** 여러 지표가 긍정적입니다. 단기 상승 흐름이 이어질 가능성이 있으나, 과매수 여부를 꼭 확인하세요.")
        elif score >= 3:
            lines.append("**종합 의견:** 지표가 혼조세입니다. 뚜렷한 방향성이 나올 때까지 관망이 무난합니다.")
        else:
            lines.append("**종합 의견:** 하락 압력이 우세합니다. 추가 하락에 대비하고 손절 기준을 명확히 하세요.")

        lines.append("*※ 기술적 지표 기반 자동 분석입니다. 투자 결정은 본인 판단 하에 하세요.*")
        return "\n\n".join(lines)

    st.info(auto_analyze(df, latest, rsi_val, change_pct))

    # Claude AI 심층 분석
    st.divider()
    st.subheader("Claude AI 심층 분석")
    if not api_key:
        st.caption("왼쪽 사이드바에 API 키를 입력하면 AI 심층 분석을 받을 수 있어요.")
    else:
        if st.button("Claude AI로 심층 분석하기", type="secondary"):
            summary = (f"종목: {ticker}, 현재가: {float(latest['Close']):,.0f}원 ({change_pct:+.2f}%), "
                       f"RSI: {rsi_val:.1f}, MA5: {float(latest['MA5']):,.0f}, "
                       f"MA20: {float(latest['MA20']):,.0f}, MA60: {float(latest['MA60']):,.0f}, "
                       f"52주고가: {float(df['High'].max()):,.0f}, 52주저가: {float(df['Low'].min()):,.0f}")
            with st.spinner("Claude AI 분석 중... (최대 30초)"):
                try:
                    client = anthropic.Anthropic(
                        api_key=api_key,
                        http_client=httpx.Client(timeout=30.0)
                    )
                    msg = client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=1024,
                        messages=[{"role": "user", "content":
                            f"한국 주식 기술적 분석과 단기·중기 전망을 쉬운 한국어로 설명해줘:\n{summary}"}]
                    )
                    st.success(msg.content[0].text)
                except httpx.TimeoutException:
                    st.error("응답 시간 초과(30초). 잠시 후 다시 시도해주세요.")
                except Exception as e:
                    st.error(f"AI 분석 오류: {e}")
