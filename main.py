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
RECIPIENTS = os.environ["RECIPIENTS"].split(",")
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
        print(f"  [{section}] 가져오기 실패")
        return []

    soup = BeautifulSoup(res.text, "html.parser")

    # 방법 1: Next.js __NEXT_DATA__ JSON에서 파싱
    next_script = soup.find("script", id="__NEXT_DATA__")
    if next_script:
        try:
            data = json.loads(next_script.string)
            page_props = data.get("props", {}).get("pageProps", {})

            # 여러 가능한 키 시도
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

            # JSON 구조 디버그용 출력
            print(f"  [{section}] JSON 키 목록: {list(page_props.keys())}")

        except Exception as e:
            print(f"  [{section}] JSON 파싱 실패: {e}")

    # 방법 2: utm_source=tldr 링크 기반 파싱 (폴백)
    articles = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if (href.startswith("http")
                and "utm_source=tldr" in href
                and len(title) > 20
                and title not in seen):
            seen.add(title)
            # 가장 가까운 p 태그에서 요약 추출
            summary = ""
            for sib in a.parents:
                next_p = sib.find_next_sibling("p")
                if next_p:
                    summary = next_p.get_text(strip=True)
                    break
            articles.append({"title": title, "link": href, "summary": summary})

    print(f"  [{section}] {len(articles)}개 파싱됨 (링크 기반)")
    return articles[:10]


def translate_with_claude(articles: list[dict], section: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    articles_text = "\n\n".join(
        f"제목: {a['title']}\n링크: {a['link']}\n요약: {a['summary']}"
        for a in articles
    )
    prompt = f"""아래는 TLDR {section.upper()} 뉴스레터의 오늘 기사들입니다.
각 기사를 한국어로 번역하고, 핵심 내용을 2~3줄로 자연스럽게 요약해주세요.

출력 형식 (HTML만 출력, 다른 텍스트 없이):
<div class="article">
  <h3><a href="링크">제목 (한국어)</a></h3>
  <p>요약 내용 (한국어)</p>
</div>

기사 목록:
{articles_text}"""
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def build_email_html(sections_content: dict) -> str:
    today_str = date.today().strftime("%Y년 %m월 %d일")
    section_labels = {"tech": "🔧 테크", "ai": "🤖 AI", "dev": "💻 개발"}
    sections_html = ""
    for section, content in sections_content.items():
        label = section_labels.get(section, section.upper())
        sections_html += f"""
        <div class="section">
            <h2>{label}</h2>
            {content}
        </div><hr>"""
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<style>
  body {{ font-family: 'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
          max-width:680px;margin:0 auto;padding:20px;background:#f9f9f9;color:#333 }}
  .header {{ background:#1a1a2e;color:white;padding:24px;border-radius:8px;
             margin-bottom:24px;text-align:center }}
  .header h1 {{ margin:0;font-size:24px }}
  .header p {{ margin:6px 0 0;opacity:.7;font-size:14px }}
  .section {{ background:white;padding:20px 24px;border-radius:8px;
              margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08) }}
  .section h2 {{ margin:0 0 16px;font-size:18px;border-bottom:2px solid #eee;padding-bottom:8px }}
  .article {{ margin-bottom:20px }}
  .article h3 {{ margin:0 0 6px;font-size:15px }}
  .article h3 a {{ color:#1a73e8;text-decoration:none }}
  .article p {{ margin:0;font-size:14px;line-height:1.6;color:#555 }}
  .footer {{ text-align:center;font-size:12px;color:#999;margin-top:24px }}
  hr {{ border:none;border-top:1px solid #eee;margin:16px 0 }}
</style></head>
<body>
  <div class="header">
    <h1>📰 TLDR 한국어판</h1>
    <p>{today_str} · 오늘의 테크 뉴스 요약</p>
  </div>
  {sections_html}
  <div class="footer"><p>원문 보기: <a href="https://tldr.tech">tldr.tech</a></p></div>
</body></html>"""


def send_email(html_body: str):
    today_str = date.today().strftime("%m/%d")
    subject = f"[TLDR 한국어] {today_str} 오늘의 테크 뉴스"
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
    sections_content = {}
    for section in SECTIONS:
        articles = fetch_tldr(section)
        if not articles:
            print(f"  [{section}] 기사 없음, 건너뜀")
            continue
        print(f"  [{section}] Claude 번역 중...")
        translated = translate_with_claude(articles, section)
        sections_content[section] = translated
    if not sections_content:
        print("❌ 수집된 기사가 없습니다.")
        return
    print("📧 이메일 발송 중...")
    html = build_email_html(sections_content)
    send_email(html)


if __name__ == "__main__":
    main()
