import os
import json
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from datetime import date
import anthropic

# ── 설정 ───────────────────────────────────────────────
RECIPIENTS = [r.strip() for r in os.environ["RECIPIENTS"].split(",") if r.strip()]
NAVER_USER = os.environ["NAVER_USER"]
NAVER_PASSWORD = os.environ["NAVER_PASSWORD"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

SECTIONS = ["tech", "ai", "dev"]
# ────────────────────────────────────────────────────────


def fetch_tldr(section: str) -> list[dict]:
    today = date.today().strftime("%Y-%m-%d")
    urls = [
        f"https://tldr.tech/{section}/{today}",
        f"https://tldr.tech/api/latest/{section}",
    ]
    res = None
    for url in urls:
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                res = r
                print(f"  [{section}] URL 성공: {url}")
                break
        except Exception as e:
            print(f"  [{section}] 요청 실패: {e}")

    if not res:
        return []

    soup = BeautifulSoup(res.text, "html.parser")

    # Next.js __NEXT_DATA__ 시도
    next_script = soup.find("script", id="__NEXT_DATA__")
    if next_script:
        try:
            data = json.loads(next_script.string)
            page_props = data.get("props", {}).get("pageProps", {})
            raw_articles = (
                page_props.get("newsletter", {}).get("articles")
                or page_props.get("articles")
                or page_props.get("stories")
                or []
            )
            articles = []
            for item in raw_articles:
                title = item.get("title") or item.get("headline", "")
                link = item.get("url") or item.get("link") or item.get("href", "")
                summary = item.get("description") or item.get("summary") or item.get("excerpt", "")
                if title and link and len(title) > 10:
                    articles.append({"title": title, "link": link, "summary": summary})
            if articles:
                print(f"  [{section}] {len(articles)}개 파싱됨 (JSON)")
                return articles[:10]
        except Exception as e:
            print(f"  [{section}] JSON 파싱 실패: {e}")

    # 폴백: utm_source=tldr 링크 기반
    articles = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if href.startswith("http") and "utm_source=tldr" in href and len(title) > 20 and title not in seen:
            seen.add(title)
            summary = ""
            for sib in a.parents:
                next_p = sib.find_next_sibling("p")
                if next_p:
                    summary = next_p.get_text(strip=True)
                    break
            articles.append({"title": title, "link": href, "summary": summary})

    print(f"  [{section}] {len(articles)}개 파싱됨 (링크 기반)")
    return articles[:10]


def translate_with_claude(articles: list[dict], section: str) -> list[dict]:
    """기사들을 한국어로 번역하고 구조화된 리스트로 반환"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    articles_text = "\n\n".join(
        f"[{i+1}] 제목: {a['title']}\n링크: {a['link']}\n요약: {a['summary']}"
        for i, a in enumerate(articles)
    )
    prompt = f"""아래 TLDR {section.upper()} 기사들을 한국어로 번역하고 JSON으로만 응답하세요. 다른 텍스트 없이 JSON만.

형식:
[
  {{"title": "한국어 제목", "link": "원본링크", "summary": "한 줄 핵심 요약 (30자 이내)"}}
]

기사:
{articles_text}"""
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    # JSON 파싱
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def make_subject(all_articles: list[dict]) -> str:
    """전체 기사 중 가장 핫한 것들로 이메일 제목 생성"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    titles = "\n".join(f"- {a['title']}" for a in all_articles[:15])
    prompt = f"""아래 오늘 테크 뉴스 제목들 중 가장 핫한 것 2~3개를 골라서
이메일 제목용 키워드로 만들어주세요.
형식: 키워드1 · 키워드2 · 키워드3
예시: Tesla 신모델 · Meta AI 출시 · GitHub 장애
다른 텍스트 없이 키워드만 응답.

{titles}"""
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def build_email_html(sections_data: dict) -> str:
    today_str = date.today().strftime("%Y년 %m월 %d일")
    section_labels = {"tech": "🔧 테크", "ai": "🤖 AI", "dev": "💻 개발"}
    section_colors = {"tech": "#4f46e5", "ai": "#0ea5e9", "dev": "#10b981"}

    sections_html = ""
    for section, articles in sections_data.items():
        label = section_labels.get(section, section.upper())
        color = section_colors.get(section, "#666")
        cards = ""
        for i, a in enumerate(articles):
            cards += f"""
            <tr><td style="padding:0 0 10px 0">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:white;border-radius:8px;border:1px solid #e5e7eb">
                <tr><td style="padding:14px 16px">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td width="24" valign="top" style="padding-top:1px">
                        <span style="display:inline-block;width:20px;height:20px;background:{color};border-radius:50%;color:white;font-size:11px;font-weight:700;text-align:center;line-height:20px">{i+1}</span>
                      </td>
                      <td style="padding-left:10px">
                        <a href="{a["link"]}" style="color:#111;text-decoration:none;font-size:14px;font-weight:600;line-height:1.4">{a["title"]}</a>
                        <p style="margin:5px 0 0;color:#6b7280;font-size:13px;line-height:1.5">{a["summary"]}</p>
                      </td>
                    </tr>
                  </table>
                </td></tr>
              </table>
            </td></tr>"""

        sections_html += f"""
        <tr><td style="padding:0 0 24px 0">
          <p style="margin:0 0 10px;font-size:13px;font-weight:700;color:{color};letter-spacing:.5px">{label}</p>
          <table width="100%" cellpadding="0" cellspacing="0">{cards}</table>
        </td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0">
    <tr><td align="center">
      <table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%">
        <tr><td style="padding:0 0 20px 0">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;border-radius:10px">
            <tr><td style="padding:24px;text-align:center">
              <p style="margin:0;font-size:22px;font-weight:700;color:white">📰 TLDR 한국어</p>
              <p style="margin:6px 0 0;font-size:13px;color:#94a3b8">{today_str} · 오늘의 테크 뉴스</p>
            </td></tr>
          </table>
        </td></tr>
        {sections_html}
        <tr><td style="text-align:center;padding:8px 0 24px">
          <p style="margin:0;font-size:12px;color:#9ca3af">원문: <a href="https://tldr.tech" style="color:#9ca3af">tldr.tech</a></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def send_email(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = NAVER_USER
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.naver.com", 465) as server:
        server.login(NAVER_USER, NAVER_PASSWORD)
        server.sendmail(NAVER_USER, RECIPIENTS, msg.as_string())
    print(f"✅ 발송 완료 → {RECIPIENTS}")


def main():
    print("📥 TLDR 뉴스 수집 중...")
    sections_data = {}
    all_articles = []

    for section in SECTIONS:
        raw = fetch_tldr(section)
        if not raw:
            print(f"  [{section}] 기사 없음, 건너뜀")
            continue
        print(f"  [{section}] Claude 번역 중...")
        translated = translate_with_claude(raw, section)
        sections_data[section] = translated
        all_articles.extend(translated)

    if not sections_data:
        print("❌ 수집된 기사가 없습니다.")
        return

    print("✍️  이메일 제목 생성 중...")
    today_str = date.today().strftime("%m/%d")
    keywords = make_subject(all_articles)
    subject = f"[TLDR] {today_str} {keywords}"

    print(f"  제목: {subject}")
    print("📧 이메일 발송 중...")
    html = build_email_html(sections_data)
    send_email(subject, html)


if __name__ == "__main__":
    main()
