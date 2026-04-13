import os
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from datetime import date
import anthropic

# ── 설정 ───────────────────────────────────────────────
RECIPIENTS = os.environ["RECIPIENTS"].split(",")   # 이메일 주소들 (쉼표 구분)
NAVER_USER = os.environ["NAVER_USER"]         # 네이버 아이디@naver.com
NAVER_PASSWORD = os.environ["NAVER_PASSWORD"] # 네이버 비밀번호
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

SECTIONS = ["tech", "ai", "dev"]   # 원하는 섹션 추가/제거 가능
# ────────────────────────────────────────────────────────


def fetch_tldr(section: str) -> list[dict]:
    """TLDR 뉴스레터에서 기사 목록을 가져옵니다."""
    today = date.today().strftime("%Y-%m-%d")
    url = f"https://tldr.tech/{section}/{today}"
    res = requests.get(url, timeout=15)
    if res.status_code != 200:
        # 오늘자가 없으면 최신호 시도
        url = f"https://tldr.tech/api/latest/{section}"
        res = requests.get(url, timeout=15)
        if res.status_code != 200:
            print(f"[{section}] 가져오기 실패: {res.status_code}")
            return []

    soup = BeautifulSoup(res.text, "html.parser")
    articles = []

    for article in soup.select("article, .story, h3"):
        a_tag = article.find("a") if article.name != "a" else article
        if not a_tag:
            continue
        title = a_tag.get_text(strip=True)
        link = a_tag.get("href", "")
        # 본문 요약 (제목 다음 p 태그)
        summary_tag = article.find_next("p")
        summary = summary_tag.get_text(strip=True) if summary_tag else ""

        if title and len(title) > 10:
            articles.append({"title": title, "link": link, "summary": summary})

    return articles[:10]  # 섹션당 최대 10개


def translate_with_claude(articles: list[dict], section: str) -> str:
    """Claude API로 기사들을 한국어로 번역·요약합니다."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    articles_text = "\n\n".join(
        f"제목: {a['title']}\n링크: {a['link']}\n요약: {a['summary']}"
        for a in articles
    )

    prompt = f"""아래는 TLDR {section.upper()} 뉴스레터의 오늘 기사들입니다.
각 기사를 한국어로 번역하고, 핵심 내용을 2~3줄로 자연스럽게 요약해주세요.
개발자/테크 종사자가 읽기 좋은 톤으로 작성해주세요.

출력 형식 (HTML):
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


def build_email_html(sections_content: dict[str, str]) -> str:
    """HTML 이메일 본문을 만듭니다."""
    today_str = date.today().strftime("%Y년 %m월 %d일")

    section_labels = {"tech": "🔧 테크", "ai": "🤖 AI", "dev": "💻 개발"}

    sections_html = ""
    for section, content in sections_content.items():
        label = section_labels.get(section, section.upper())
        sections_html += f"""
        <div class="section">
            <h2>{label}</h2>
            {content}
        </div>
        <hr>
        """

    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
          max-width: 680px; margin: 0 auto; padding: 20px;
          background: #f9f9f9; color: #333; }}
  .header {{ background: #1a1a2e; color: white; padding: 24px;
             border-radius: 8px; margin-bottom: 24px; text-align: center; }}
  .header h1 {{ margin: 0; font-size: 24px; }}
  .header p {{ margin: 6px 0 0; opacity: 0.7; font-size: 14px; }}
  .section {{ background: white; padding: 20px 24px; border-radius: 8px;
              margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .section h2 {{ margin: 0 0 16px; font-size: 18px; border-bottom: 2px solid #eee;
                 padding-bottom: 8px; }}
  .article {{ margin-bottom: 20px; }}
  .article h3 {{ margin: 0 0 6px; font-size: 15px; }}
  .article h3 a {{ color: #1a73e8; text-decoration: none; }}
  .article h3 a:hover {{ text-decoration: underline; }}
  .article p {{ margin: 0; font-size: 14px; line-height: 1.6; color: #555; }}
  .footer {{ text-align: center; font-size: 12px; color: #999; margin-top: 24px; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 16px 0; }}
</style>
</head>
<body>
  <div class="header">
    <h1>📰 TLDR 한국어판</h1>
    <p>{today_str} · 오늘의 테크 뉴스 요약</p>
  </div>

  {sections_html}

  <div class="footer">
    <p>원문 보기: <a href="https://tldr.tech">tldr.tech</a></p>
  </div>
</body>
</html>
"""


def send_email(html_body: str):
    """Gmail SMTP로 이메일을 발송합니다."""
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
        print(f"  [{section}] {len(articles)}개 수집 → Claude 번역 중...")
        translated = translate_with_claude(articles, section)
        sections_content[section] = translated

    if not sections_content:
        print("❌ 수집된 기사가 없습니다.")
        return

    print("📧 이메일 생성 및 발송 중...")
    html = build_email_html(sections_content)
    send_email(html)


if __name__ == "__main__":
    main()
