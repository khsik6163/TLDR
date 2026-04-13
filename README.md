# 📰 TLDR 한국어 뉴스레터

TLDR Tech 뉴스를 매일 아침 한국어로 번역해서 이메일로 받아보는 개인용 도구입니다.

## 설치 방법

### 1. 이 저장소를 GitHub에 올리기
```bash
git init
git add .
git commit -m "init"
# GitHub에서 새 저장소 만들고 push
```

### 2. GitHub Secrets 설정
저장소 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 값 |
|------|----|
| `ANTHROPIC_API_KEY` | Anthropic API 키 (https://console.anthropic.com) |
| `GMAIL_USER` | 발송할 Gmail 주소 (예: yourname@gmail.com) |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 (아래 참고) |
| `RECIPIENTS` | 받을 이메일 주소들, 쉼표로 구분 (예: me@gmail.com,gf@gmail.com) |

### 3. Gmail 앱 비밀번호 발급
1. Google 계정 → 보안 → 2단계 인증 활성화
2. 보안 → 앱 비밀번호 → 앱 선택: 메일 → 기기: 기타(직접 입력) → "TLDR"
3. 생성된 16자리 비밀번호를 `GMAIL_APP_PASSWORD`에 입력

### 4. 수동 테스트
GitHub → Actions → "TLDR 한국어 일일 발송" → Run workflow

## 발송 시간
평일 매일 오전 7시 (한국 시간)  
`daily.yml`의 cron 값을 수정하면 시간 변경 가능.

## 섹션 설정
`main.py` 상단의 `SECTIONS` 리스트에서 원하는 섹션을 추가/제거하세요.
- `tech` · `ai` · `dev` · `devops` · `infosec` · `design` · `founders`
