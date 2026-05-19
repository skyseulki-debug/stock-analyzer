import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import anthropic
import httpx
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

st.set_page_config(page_title="한국 주식 분석기", page_icon="📈", layout="wide")
st.title("📈 한국 주식 차트 분석기")

# 세션 상태 초기화
for key in ["df", "ticker", "last_updated"]:
    if key not in st.session_state:
        st.session_state[key] = None

period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730}

# 사이드바
with st.sidebar:
    st.header("설정")
    ticker_input = st.text_input("종목코드", "005930",
                                  help="예: 005930(삼성전자), 035720(카카오), 000660(SK하이닉스)")
    period = st.select_slider("조회 기간", list(period_days.keys()), value="3mo",
                               format_func=lambda x: {"1mo":"1개월","3mo":"3개월","6mo":"6개월","1y":"1년","2y":"2년"}[x])
    api_key = st.text_input("Anthropic API 키 (AI 전망용)", type="password")
    analyze_btn = st.button("분석 시작", type="primary", use_container_width=True)
    refresh_btn = st.button("새로고침", use_container_width=True)
    if st.session_state.last_updated:
        st.caption(f"마지막 업데이트: {st.session_state.last_updated}")

st.caption("인기 종목: 005930(삼성전자) · 000660(SK하이닉스) · 035720(카카오) · 005380(현대차) · 035420(NAVER)")

# ── 데이터 로드 ─────────────────────────────────────────────
def load_data(ticker_code, period):
    start = (datetime.now() - timedelta(days=period_days[period])).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker_code.strip(), start)
    if df.empty:
        return None
    df = df[["Open","High","Low","Close","Volume"]].copy()
    # 이동평균
    df["MA5"]  = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()
    # RSI
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))
    # MACD (모멘텀)
    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    df["MACD"]      = ema12 - ema26
    df["MACD_sig"]  = df["MACD"].ewm(span=9).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_sig"]
    # 볼린저 밴드
    df["BB_mid"]   = df["Close"].rolling(20).mean()
    df["BB_std"]   = df["Close"].rolling(20).std()
    df["BB_upper"] = df["BB_mid"] + 2 * df["BB_std"]
    df["BB_lower"] = df["BB_mid"] - 2 * df["BB_std"]
    # 20일 등락률 (모멘텀)
    df["ROC20"] = df["Close"].pct_change(20) * 100
    return df

# ── 네이버 금융 뉴스 ────────────────────────────────────────
def get_news(ticker_code):
    try:
        url = f"https://finance.naver.com/item/news_news.nhn?code={ticker_code}&page=1"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        items = []
        for row in soup.select("table.type5 tr"):
            title = row.select_one(".title")
            date  = row.select_one(".date")
            if title and date:
                items.append(f"· {title.get_text(strip=True)} ({date.get_text(strip=True)})")
            if len(items) >= 5:
                break
        return "\n".join(items) if items else "뉴스 없음"
    except:
        return "뉴스를 불러올 수 없습니다."

# ── pykrx 재무제표 ──────────────────────────────────────────
def get_fundamentals(ticker_code):
    try:
        from pykrx import stock
        today    = datetime.now().strftime("%Y%m%d")
        week_ago = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
        df = stock.get_market_fundamental(week_ago, today, ticker_code)
        if df.empty:
            return "재무 데이터 없음"
        r = df.iloc[-1]
        return (f"PER: {r.get('PER', 'N/A'):.1f}배 | "
                f"PBR: {r.get('PBR', 'N/A'):.2f}배 | "
                f"EPS: {r.get('EPS', 0):,.0f}원 | "
                f"배당수익률: {r.get('DIV', 'N/A'):.2f}%")
    except:
        return "재무 데이터를 불러올 수 없습니다."

# ── 분석 시작 ───────────────────────────────────────────────
if analyze_btn or refresh_btn:
    with st.spinner("데이터 불러오는 중..."):
        df = load_data(ticker_input, period)
    if df is None:
        st.error("데이터를 찾을 수 없습니다. 종목코드를 확인해주세요.")
        st.stop()
    st.session_state.df           = df
    st.session_state.ticker       = ticker_input.strip()
    st.session_state.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── 차트 및 분석 표시 ────────────────────────────────────────
if st.session_state.df is not None:
    df     = st.session_state.df
    ticker = st.session_state.ticker

    # 차트 (캔들 + MA + 볼린저밴드 / 거래량 / RSI / MACD)
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
                        row_heights=[0.5, 0.15, 0.15, 0.2], vertical_spacing=0.02,
                        subplot_titles=["캔들 차트 + 이동평균 + 볼린저밴드", "거래량", "RSI", "MACD (모멘텀)"])

    # 캔들
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                                  low=df["Low"], close=df["Close"],
                                  increasing_line_color="red", decreasing_line_color="blue",
                                  name="주가"), row=1, col=1)
    # 이동평균선
    for col, color, lname in [("MA5","orange","MA5"), ("MA20","green","MA20"), ("MA60","purple","MA60")]:
        fig.add_trace(go.Scatter(x=df.index, y=df[col], name=lname,
                                  line=dict(color=color, width=1.2)), row=1, col=1)
    # 볼린저밴드
    fig.add_trace(go.Scatter(x=df.index, y=df["BB_upper"], name="BB상단",
                              line=dict(color="gray", width=1, dash="dot"), showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["BB_lower"], name="BB하단",
                              line=dict(color="gray", width=1, dash="dot"),
                              fill="tonexty", fillcolor="rgba(128,128,128,0.1)", showlegend=False), row=1, col=1)
    # 거래량
    bar_colors = ["red" if c >= o else "blue" for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=bar_colors, showlegend=False), row=2, col=1)
    # RSI
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                              line=dict(color="darkorange", width=1.5)), row=3, col=1)
    fig.add_hrect(y0=70, y1=100, fillcolor="red",  opacity=0.05, row=3, col=1)
    fig.add_hrect(y0=0,  y1=30,  fillcolor="blue", opacity=0.05, row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red",  line_width=1, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="blue", line_width=1, row=3, col=1)
    # MACD
    colors_macd = ["red" if v >= 0 else "blue" for v in df["MACD_hist"]]
    fig.add_trace(go.Bar(x=df.index, y=df["MACD_hist"], marker_color=colors_macd,
                          name="MACD 히스토그램", showlegend=False), row=4, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"],     name="MACD",
                              line=dict(color="blue",   width=1.2)), row=4, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD_sig"], name="Signal",
                              line=dict(color="orange", width=1.2)), row=4, col=1)

    fig.update_layout(height=800, xaxis_rangeslider_visible=False,
                       legend=dict(orientation="h", y=1.02), margin=dict(t=60, b=20))
    st.plotly_chart(fig, use_container_width=True)

    # 핵심 지표
    latest     = df.iloc[-1]
    prev       = df.iloc[-2]
    change_pct = float((latest["Close"] - prev["Close"]) / prev["Close"] * 100)
    rsi_val    = float(latest["RSI"])
    macd_val   = float(latest["MACD"])
    macd_sig   = float(latest["MACD_sig"])
    roc20      = float(latest["ROC20"]) if not pd.isna(latest["ROC20"]) else 0
    rsi_label  = "과매수" if rsi_val > 70 else "과매도" if rsi_val < 30 else "중립"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("현재가",    f"{float(latest['Close']):,.0f}원", f"{change_pct:+.2f}%")
    c2.metric("RSI",      f"{rsi_val:.1f}", rsi_label)
    c3.metric("MACD",     f"{macd_val:.1f}", "상승" if macd_val > macd_sig else "하락")
    c4.metric("20일 모멘텀", f"{roc20:+.1f}%")
    c5.metric("52주 고가", f"{float(df['High'].max()):,.0f}원")

    st.divider()

    # 자동 차트 분석
    st.subheader("자동 차트 분석 및 전망")

    def auto_analyze(df, latest, rsi_val, change_pct):
        ma5    = float(latest["MA5"])
        ma20   = float(latest["MA20"])
        ma60   = float(latest["MA60"])
        close  = float(latest["Close"])
        high52 = float(df["High"].max())
        low52  = float(df["Low"].min())
        pos52  = (close - low52) / (high52 - low52) * 100 if high52 != low52 else 50
        lines  = []

        if ma5 > ma20 > ma60:
            lines.append("이동평균선이 단기>중기>장기 순으로 정렬 — **상승 추세**가 확인됩니다.")
        elif ma5 < ma20 < ma60:
            lines.append("이동평균선이 단기<중기<장기 순으로 정렬 — **하락 추세**가 지속되고 있습니다.")
        else:
            lines.append("이동평균선이 혼조세 — 뚜렷한 방향성 없이 **횡보 중**입니다.")

        if ma5 > ma20 and df["MA5"].iloc[-5] < df["MA20"].iloc[-5]:
            lines.append("**골든크로스** 발생 — 단기 매수 신호입니다.")
        elif ma5 < ma20 and df["MA5"].iloc[-5] > df["MA20"].iloc[-5]:
            lines.append("**데드크로스** 발생 — 단기 주의가 필요합니다.")

        if rsi_val >= 80:
            lines.append(f"RSI {rsi_val:.1f} — **심한 과매수**. 신규 매수 자제하세요.")
        elif rsi_val >= 70:
            lines.append(f"RSI {rsi_val:.1f} — **과매수**. 단기 차익 실현 매물 주의.")
        elif rsi_val <= 20:
            lines.append(f"RSI {rsi_val:.1f} — **심한 과매도**. 기술적 반등 가능성.")
        elif rsi_val <= 30:
            lines.append(f"RSI {rsi_val:.1f} — **과매도**. 저점 매수 기회 고려.")
        else:
            lines.append(f"RSI {rsi_val:.1f} — **중립** 구간.")

        macd_v = float(latest["MACD"])
        macd_s = float(latest["MACD_sig"])
        if macd_v > macd_s:
            lines.append("MACD가 시그널선 위 — **상승 모멘텀** 유지 중입니다.")
        else:
            lines.append("MACD가 시그널선 아래 — **하락 모멘텀** 진행 중입니다.")

        bb_upper = float(latest["BB_upper"])
        bb_lower = float(latest["BB_lower"])
        if close >= bb_upper:
            lines.append("볼린저밴드 **상단 돌파** — 강한 상승이나 과열 신호입니다.")
        elif close <= bb_lower:
            lines.append("볼린저밴드 **하단 이탈** — 강한 하락이나 반등 신호입니다.")
        else:
            lines.append(f"볼린저밴드 내 **{pos52:.0f}% 위치** — 정상 범위 내 거래 중입니다.")

        score = sum([ma5 > ma20, ma20 > ma60, rsi_val < 60, rsi_val > 40,
                     change_pct > 0, macd_v > macd_s])
        lines.append("---")
        if score >= 5:
            lines.append("**종합 의견:** 대부분의 지표가 긍정적입니다. 단기 상승 흐름 가능성이 높으나 과매수 여부를 확인하세요.")
        elif score >= 3:
            lines.append("**종합 의견:** 지표가 혼조세입니다. 방향성이 나올 때까지 관망이 무난합니다.")
        else:
            lines.append("**종합 의견:** 하락 압력이 우세합니다. 추가 하락에 대비하세요.")

        lines.append("*※ 기술적 지표 기반 자동 분석입니다. 투자 결정은 본인 판단 하에 하세요.*")
        return "\n\n".join(lines)

    st.info(auto_analyze(df, latest, rsi_val, change_pct))

    # Claude AI 심층 분석
    st.divider()
    st.subheader("Claude AI 종합 심층 분석")
    if not api_key:
        st.caption("왼쪽 사이드바에 API 키를 입력하면 뉴스·재무·모멘텀을 포함한 AI 심층 분석을 받을 수 있어요.")
    else:
        if st.button("Claude AI 종합 분석 시작", type="secondary"):
            with st.spinner("뉴스 · 재무제표 · 모멘텀 데이터 수집 중..."):
                news  = get_news(ticker)
                funds = get_fundamentals(ticker)

            close  = float(latest["Close"])
            high52 = float(df["High"].max())
            low52  = float(df["Low"].min())
            pos52  = (close - low52) / (high52 - low52) * 100 if high52 != low52 else 50

            full_summary = f"""
=== 종목 정보 ===
종목코드: {ticker}
현재가: {close:,.0f}원 (전일대비 {change_pct:+.2f}%)
52주 고가: {high52:,.0f}원 | 52주 저가: {low52:,.0f}원 | 현재 위치: {pos52:.0f}%

=== 기술적 지표 (차트 분석) ===
RSI(14): {rsi_val:.1f} ({'과매수' if rsi_val>70 else '과매도' if rsi_val<30 else '중립'})
MACD: {float(latest['MACD']):.2f} / Signal: {float(latest['MACD_sig']):.2f} ({'상승모멘텀' if float(latest['MACD']) > float(latest['MACD_sig']) else '하락모멘텀'})
20일 모멘텀(ROC): {roc20:+.2f}%
5일 이동평균: {float(latest['MA5']):,.0f}원
20일 이동평균: {float(latest['MA20']):,.0f}원
60일 이동평균: {float(latest['MA60']):,.0f}원
볼린저밴드 상단: {float(latest['BB_upper']):,.0f}원 | 하단: {float(latest['BB_lower']):,.0f}원

=== 재무제표 (기본지표) ===
{funds}

=== 최신 뉴스 (네이버 금융) ===
{news}
"""
            with st.spinner("Claude AI 종합 분석 중... (최대 30초)"):
                try:
                    client = anthropic.Anthropic(
                        api_key=api_key,
                        http_client=httpx.Client(timeout=30.0)
                    )
                    msg = client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=2048,
                        messages=[{"role": "user", "content":
                            f"""다음 한국 주식 데이터를 바탕으로 아래 4가지 항목을 각각 쉬운 한국어로 분석해줘:

1. 차트 기술적 분석 (이동평균, RSI, MACD, 볼린저밴드 종합)
2. 모멘텀 분석 (현재 상승/하락 힘이 얼마나 강한지)
3. 재무 상태 평가 (PER, PBR 등 지표가 고평가/저평가인지)
4. 뉴스 기반 이슈 요약 및 주가 영향 전망
5. 종합 투자 의견 (단기/중기 전망, 리스크 포함)

데이터:
{full_summary}"""}]
                    )
                    st.success(msg.content[0].text)
                except httpx.TimeoutException:
                    st.error("응답 시간 초과(30초). 잠시 후 다시 시도해주세요.")
                except Exception as e:
                    st.error(f"AI 분석 오류: {e}")
