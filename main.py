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

    sections_html = ""
    for section, articles in sections_data.items():
        label = section_labels.get(section, section.upper())
        rows = ""
        for a in articles:
            rows += f"""
            <tr>
              <td><a href="{a['link']}" style="color:#1a73e8;text-decoration:none;font-weight:500">{a['title']}</a></td>
              <td style="color:#555">{a['summary']}</td>
            </tr>"""
        sections_html += f"""
        <div class="section">
          <h2>{label}</h2>
          <table>
            <thead><tr><th>제목</th><th>요약</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<style>
  body {{ font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
          max-width:700px;margin:0 auto;padding:20px;background:#f5f5f5;color:#333 }}
  .header {{ background:#1a1a2e;color:white;padding:20px 24px;border-radius:8px;margin-bottom:20px;text-align:center }}
  .header h1 {{ margin:0;font-size:22px }}
  .header p {{ margin:4px 0 0;opacity:.7;font-size:13px }}
  .section {{ background:white;border-radius:8px;margin-bottom:16px;
              overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08) }}
  .section h2 {{ margin:0;padding:14px 20px;font-size:15px;background:#f8f8f8;
                 border-bottom:1px solid #eee }}
  table {{ width:100%;border-collapse:collapse }}
  th {{ padding:10px 16px;background:#fafafa;font-size:12px;color:#888;
        text-align:left;border-bottom:1px solid #eee;font-weight:600 }}
  td {{ padding:12px 16px;font-size:13px;border-bottom:1px solid #f0f0f0;
        vertical-align:top;line-height:1.5 }}
  tr:last-child td {{ border-bottom:none }}
  tr:hover td {{ background:#fafeff }}
  .footer {{ text-align:center;font-size:12px;color:#aaa;margin-top:16px }}
</style></head>
<body>
  <div class="header">
    <h1>📰 TLDR 한국어판</h1>
    <p>{today_str}</p>
  </div>
  {sections_html}
  <div class="footer"><p>원문: <a href="https://tldr.tech" style="color:#aaa">tldr.tech</a></p></div>
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
