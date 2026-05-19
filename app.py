import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import anthropic

st.set_page_config(page_title="한국 주식 분석기", page_icon="📈", layout="wide")
st.title("📈 한국 주식 차트 분석기")

# 사이드바: 설정
with st.sidebar:
    st.header("⚙️ 설정")
    ticker_input = st.text_input("종목코드", "005930", help="예: 005930(삼성전자), 035720(카카오), 000660(SK하이닉스)")
    market = st.radio("시장 선택", ["KOSPI (코스피)", "KOSDAQ (코스닥)"])
    period = st.select_slider("조회 기간", ["1mo", "3mo", "6mo", "1y", "2y"], value="3mo",
                               format_func=lambda x: {"1mo":"1개월","3mo":"3개월","6mo":"6개월","1y":"1년","2y":"2년"}[x])
    api_key = st.text_input("Anthropic API 키 (AI 전망용)", type="password",
                             help="https://console.anthropic.com 에서 발급")
    analyze_btn = st.button("🔍 분석 시작", type="primary", use_container_width=True)

# 인기 종목 바로가기
st.caption("💡 인기 종목: 005930(삼성전자) · 000660(SK하이닉스) · 035720(카카오) · 005380(현대차) · 035420(NAVER)")

if analyze_btn:
    suffix = ".KS" if "KOSPI" in market else ".KQ"
    ticker = ticker_input.strip() + suffix

    with st.spinner("📡 데이터 불러오는 중..."):
        raw = yf.download(ticker, period=period, progress=False)

    if raw.empty:
        st.error("❌ 데이터를 찾을 수 없습니다. 종목코드와 시장 구분을 확인해주세요.")
        st.stop()

    # MultiIndex 컬럼 처리 (yfinance 버전 대응)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw[["Open","High","Low","Close","Volume"]].copy()

    # 지표 계산
    df["MA5"]  = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()

    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))

    # ── 차트 그리기 ──────────────────────────────────────────
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.03,
        subplot_titles=["캔들 차트 + 이동평균선", "거래량", "RSI (과매수/과매도)"]
    )

    # 캔들
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        increasing_line_color="red", decreasing_line_color="blue", name="주가"
    ), row=1, col=1)

    # 이동평균선
    for col, color, name in [("MA5","orange","5일"), ("MA20","green","20일"), ("MA60","purple","60일")]:
        fig.add_trace(go.Scatter(x=df.index, y=df[col], name=f"MA{name}",
                                  line=dict(color=color, width=1.2)), row=1, col=1)

    # 거래량
    bar_colors = ["red" if c >= o else "blue" for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=bar_colors,
                          name="거래량", showlegend=False), row=2, col=1)

    # RSI
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                              line=dict(color="darkorange", width=1.5)), row=3, col=1)
    fig.add_hrect(y0=70, y1=100, fillcolor="red",   opacity=0.05, row=3, col=1)
    fig.add_hrect(y0=0,  y1=30,  fillcolor="blue",  opacity=0.05, row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red",  line_width=1, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="blue", line_width=1, row=3, col=1)

    fig.update_layout(height=680, xaxis_rangeslider_visible=False,
                       legend=dict(orientation="h", y=1.02),
                       margin=dict(t=60, b=20))
    st.plotly_chart(fig, use_container_width=True)

    # ── 핵심 지표 요약 ──────────────────────────────────────
    latest = df.iloc[-1]
    prev   = df.iloc[-2]
    change_pct = float((latest["Close"] - prev["Close"]) / prev["Close"] * 100)
    rsi_val    = float(latest["RSI"])
    rsi_label  = "🔴 과매수" if rsi_val > 70 else "🔵 과매도" if rsi_val < 30 else "⚪ 중립"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("현재가",    f"{float(latest['Close']):,.0f}원",  f"{change_pct:+.2f}%")
    c2.metric("RSI",      f"{rsi_val:.1f}",                    rsi_label)
    c3.metric("5일 평균",  f"{float(latest['MA5']):,.0f}원")
    c4.metric("52주 고가", f"{float(df['High'].max()):,.0f}원")
    c5.metric("52주 저가", f"{float(df['Low'].min()):,.0f}원")

    # ── 자동 전망 분석 ─────────────────────────────────────
    st.divider()
    st.subheader("자동 차트 분석 및 전망")

    def auto_analyze(df, latest, rsi_val, change_pct):
        close = float(latest["Close"])
        ma5   = float(latest["MA5"])
        ma20  = float(latest["MA20"])
        ma60  = float(latest["MA60"])
        high52 = float(df["High"].max())
        low52  = float(df["Low"].min())
        pos52  = (close - low52) / (high52 - low52) * 100 if high52 != low52 else 50

        lines = []

        # 추세 분석
        if ma5 > ma20 > ma60:
            lines.append("이동평균선이 단기>중기>장기 순으로 정렬되어 있어 **상승 추세**가 확인됩니다.")
        elif ma5 < ma20 < ma60:
            lines.append("이동평균선이 단기<중기<장기 순으로 정렬되어 있어 **하락 추세**가 지속되고 있습니다.")
        else:
            lines.append("이동평균선이 혼조세로, 뚜렷한 방향성 없이 **횡보 중**입니다.")

        # 골든/데드 크로스
        if ma5 > ma20 and df["MA5"].iloc[-5] < df["MA20"].iloc[-5]:
            lines.append("최근 5일 이동평균이 20일 이동평균을 위로 돌파했습니다 — **골든크로스** 발생으로 단기 매수 신호입니다.")
        elif ma5 < ma20 and df["MA5"].iloc[-5] > df["MA20"].iloc[-5]:
            lines.append("최근 5일 이동평균이 20일 이동평균을 아래로 이탈했습니다 — **데드크로스** 발생으로 단기 주의가 필요합니다.")

        # RSI 분석
        if rsi_val >= 80:
            lines.append(f"RSI가 {rsi_val:.1f}로 **심한 과매수** 구간입니다. 단기 조정 가능성이 높으니 신규 매수는 자제하세요.")
        elif rsi_val >= 70:
            lines.append(f"RSI가 {rsi_val:.1f}로 **과매수** 구간입니다. 단기 차익 실현 매물이 나올 수 있습니다.")
        elif rsi_val <= 20:
            lines.append(f"RSI가 {rsi_val:.1f}로 **심한 과매도** 구간입니다. 기술적 반등 가능성이 있습니다.")
        elif rsi_val <= 30:
            lines.append(f"RSI가 {rsi_val:.1f}로 **과매도** 구간입니다. 저점 매수 기회를 고려해볼 수 있습니다.")
        else:
            lines.append(f"RSI가 {rsi_val:.1f}로 **중립** 구간입니다. 과열도 침체도 아닌 안정적인 상태입니다.")

        # 52주 위치
        if pos52 >= 90:
            lines.append(f"현재 주가는 52주 고가 대비 **{pos52:.0f}% 위치**로 신고가 근처입니다. 강한 상승 모멘텀이나 고점 리스크에 주의하세요.")
        elif pos52 <= 10:
            lines.append(f"현재 주가는 52주 저가 근처 **{pos52:.0f}% 위치**입니다. 저점 구간이나 추가 하락 가능성도 열려 있습니다.")
        else:
            lines.append(f"현재 주가는 52주 범위의 **{pos52:.0f}% 위치**에 있습니다.")

        # 전일 대비
        if change_pct >= 5:
            lines.append(f"전일 대비 **+{change_pct:.2f}%** 급등했습니다. 거래량과 함께 확인이 필요합니다.")
        elif change_pct <= -5:
            lines.append(f"전일 대비 **{change_pct:.2f}%** 급락했습니다. 원인 파악 후 대응하세요.")

        # 종합 의견
        score = 0
        if ma5 > ma20: score += 1
        if ma20 > ma60: score += 1
        if rsi_val < 60: score += 1
        if rsi_val > 40: score += 1
        if change_pct > 0: score += 1

        lines.append("---")
        if score >= 4:
            lines.append("**종합 의견:** 여러 지표가 긍정적입니다. 단기 상승 흐름이 이어질 가능성이 있으나, 과매수 여부를 꼭 확인하세요.")
        elif score >= 3:
            lines.append("**종합 의견:** 지표가 혼조세입니다. 뚜렷한 방향성이 나올 때까지 관망이 무난합니다.")
        else:
            lines.append("**종합 의견:** 하락 압력이 우세합니다. 추가 하락 가능성에 대비하고 손절 기준을 명확히 하세요.")

        lines.append("*※ 이 분석은 기술적 지표 기반 자동 분석으로, 투자 조언이 아닙니다. 투자 결정은 본인 판단 하에 하세요.*")
        return "\n\n".join(lines)

    result = auto_analyze(df, latest, rsi_val, change_pct)
    st.info(result)

    # ── Claude API 분석 (선택) ──────────────────────────────
    with st.expander("Claude AI 심층 분석 (API 키 필요)"):
        if not api_key:
            st.caption("왼쪽 사이드바에 Anthropic API 키를 입력하면 더 상세한 AI 분석을 받을 수 있어요.")
        else:
            if st.button("Claude AI로 심층 분석하기"):
                summary = f"종목: {ticker}, 현재가: {float(latest['Close']):,.0f}원 ({change_pct:+.2f}%), RSI: {rsi_val:.1f}, MA5: {float(latest['MA5']):,.0f}, MA20: {float(latest['MA20']):,.0f}, MA60: {float(latest['MA60']):,.0f}, 52주고가: {float(df['High'].max()):,.0f}, 52주저가: {float(df['Low'].min()):,.0f}"
                with st.spinner("분석 중... (최대 30초)"):
                    try:
                        import httpx
                        client = anthropic.Anthropic(
                            api_key=api_key,
                            http_client=httpx.Client(timeout=30.0)
                        )
                        msg = client.messages.create(
                            model="claude-haiku-4-5-20251001",
                            max_tokens=1024,
                            messages=[{"role": "user", "content": f"한국 주식 기술적 분석과 단기·중기 전망을 쉬운 한국어로 설명해줘:\n{summary}"}]
                        )
                        st.success(msg.content[0].text)
                    except httpx.TimeoutException:
                        st.error("⏱️ 응답 시간 초과(30초). 잠시 후 다시 시도해주세요.")
                    except Exception as e:
                        st.error(f"AI 분석 오류: {e}")
