#!/usr/bin/env python3
"""
AI 뉴스레터 자동 발송 스크립트
매일 아침 5시에 최신 AI 뉴스를 수집하고 이메일로 발송합니다.
"""

import os
import smtplib
import json
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# 환경 변수
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")
NEWSLETTER_NAME = os.getenv("NEWSLETTER_NAME", "Design Letter")
AUTHOR_NAME = os.getenv("AUTHOR_NAME", "제시카AI")

KST = timezone(timedelta(hours=9))


def get_issue_number() -> int:
    """발행 번호를 파일에서 읽거나 1로 초기화합니다."""
    counter_file = os.path.join(os.path.dirname(__file__), ".issue_counter")
    try:
        with open(counter_file, "r") as f:
            num = int(f.read().strip()) + 1
    except (FileNotFoundError, ValueError):
        num = 1
    with open(counter_file, "w") as f:
        f.write(str(num))
    return num


def get_korean_date(dt: datetime) -> str:
    """한국어 날짜 형식으로 변환합니다."""
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays[dt.weekday()]
    return f"{dt.year}년 {dt.month}월 {dt.day}일 ({weekday})"


def collect_and_generate_newsletter(issue_number: int, date_str: str) -> dict:
    """Gemini API를 사용해 AI 뉴스를 수집하고 뉴스레터를 생성합니다."""
    genai.configure(api_key=GEMINI_API_KEY)

    today = datetime.now(KST).strftime("%Y-%m-%d")

    prompt = f"""당신은 AI 업계 전문 뉴스레터 에디터입니다. 한국어로 작성하며,
독자가 AI 트렌드를 빠르게 파악할 수 있도록 명확하고 통찰력 있는 분석을 제공합니다.

오늘({today}) 기준 최신 AI 뉴스를 Google 검색으로 수집하고 분석해주세요.
검색 키워드: "AI news {today}", "generative AI 2026", "LLM release 2026", "AI model update"

검색 결과를 바탕으로 오늘의 가장 중요한 AI 뉴스 5-7개를 선정하고,
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요:

{{
  "tagline": "오늘의 핵심을 한 문장으로 (예: 'Seedance가 할리우드를 건드렸다')",
  "summary": "오늘의 한 줄 총평 (이모지 포함, 2문장 이내)",
  "sections": [
    {{
      "emoji": "섹션 이모지",
      "category": "카테고리명",
      "title": "뉴스 제목",
      "body": "뉴스 내용 (3-4문장, 핵심 사실 중심)",
      "comment": "{AUTHOR_NAME}의 한마디 (이모지 포함, 날카로운 통찰)"
    }}
  ],
  "highlights": [
    "핵심 요약 1",
    "핵심 요약 2",
    "핵심 요약 3"
  ]
}}

섹션은 최소 5개, 최대 7개. 카테고리: 영상 생성 AI, 이미지 생성 AI, 언어 모델,
오픈소스·커뮤니티, 음성·음악 AI, 크리에이터 경제, AI 규제·정책, 기업·투자, 중국 AI 동향"""

    # Google 검색 그라운딩 사용
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        tools="google_search_retrieval",
    )
    response = model.generate_content(prompt)
    full_text = response.text

    # JSON 파싱
    try:
        # JSON 블록 추출
        text = full_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        data = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        # JSON 파싱 실패시 기본 구조 반환
        data = {
            "tagline": "오늘의 AI 뉴스",
            "summary": "오늘의 주요 AI 뉴스를 정리했습니다.",
            "sections": [
                {
                    "emoji": "🤖",
                    "category": "AI 일반",
                    "title": "뉴스레터 생성 오류",
                    "body": f"뉴스 수집 중 오류가 발생했습니다. 원본 응답: {full_text[:500]}",
                    "comment": "시스템 점검이 필요합니다.",
                }
            ],
            "highlights": ["뉴스레터 생성에 문제가 발생했습니다."],
        }

    data["issue_number"] = issue_number
    data["date_str"] = date_str
    return data


def build_html_email(data: dict) -> str:
    """HTML 이메일 본문을 생성합니다."""
    issue_number = data["issue_number"]
    date_str = data["date_str"]
    tagline = data.get("tagline", "오늘의 AI 뉴스")
    summary = data.get("summary", "")
    sections = data.get("sections", [])
    highlights = data.get("highlights", [])

    sections_html = ""
    for i, sec in enumerate(sections, 1):
        emoji = sec.get("emoji", "📰")
        category = sec.get("category", "")
        title = sec.get("title", "")
        body = sec.get("body", "")
        comment = sec.get("comment", "")

        sections_html += f"""
        <div style="margin-bottom:32px; padding:24px; background:#fff; border-radius:12px; border-left:4px solid #6366f1;">
            <div style="font-size:12px; color:#6366f1; font-weight:700; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px;">
                {emoji} {category}
            </div>
            <h2 style="margin:0 0 12px; font-size:18px; color:#1a1a2e; line-height:1.4;">
                ① {emoji} {title}
            </h2>
            <p style="margin:0 0 16px; color:#444; line-height:1.8; font-size:15px;">
                {body}
            </p>
            <div style="background:#f8f7ff; border-radius:8px; padding:12px 16px; border-left:3px solid #a78bfa;">
                <span style="font-size:13px; color:#6366f1; font-weight:600;">☞ {AUTHOR_NAME}의 한마디:</span>
                <span style="font-size:14px; color:#555; margin-left:6px;">{comment}</span>
            </div>
        </div>
        <hr style="border:none; border-top:1px solid #f0f0f0; margin:0 0 32px;">
"""

    highlights_html = ""
    for h in highlights:
        highlights_html += f'<li style="margin-bottom:8px; color:#444; font-size:15px;">{h}</li>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{NEWSLETTER_NAME} #{issue_number:03d}</title>
</head>
<body style="margin:0; padding:0; background:#f5f5f7; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f7;">
<tr><td align="center" style="padding:32px 16px;">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px; width:100%;">

  <!-- 헤더 -->
  <tr><td style="background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%); border-radius:16px 16px 0 0; padding:36px 40px;">
    <div style="font-size:12px; color:rgba(255,255,255,0.7); font-weight:600; letter-spacing:2px; margin-bottom:8px;">
      {NEWSLETTER_NAME} #{issue_number:03d} _ {date_str}
    </div>
    <div style="font-size:26px; font-weight:800; color:#fff; line-height:1.3;">
      "{tagline}"
    </div>
  </td></tr>

  <!-- 오늘의 총평 -->
  <tr><td style="background:#fff; padding:24px 40px 0;">
    <div style="background:#f0f0ff; border-radius:10px; padding:16px 20px;">
      <span style="font-size:13px; color:#6366f1; font-weight:700;">💬 오늘의 한 줄 총평</span>
      <p style="margin:8px 0 0; color:#333; font-size:15px; line-height:1.7;">{summary}</p>
    </div>
  </td></tr>

  <!-- 구분선 -->
  <tr><td style="background:#fff; padding:24px 40px 0;">
    <hr style="border:none; border-top:2px solid #f0f0f0;">
  </td></tr>

  <!-- 섹션들 -->
  <tr><td style="background:#f8f8fc; padding:32px 40px;">
    {sections_html}
  </td></tr>

  <!-- 핵심 요약 -->
  <tr><td style="background:#fff; padding:32px 40px;">
    <div style="background:#1a1a2e; border-radius:12px; padding:24px 28px;">
      <div style="font-size:14px; color:#a78bfa; font-weight:700; margin-bottom:16px;">
        {NEWSLETTER_NAME} #{issue_number:03d} 완료 ✅
      </div>
      <div style="font-size:13px; color:#fff; font-weight:600; margin-bottom:12px;">오늘의 핵심 3줄:</div>
      <ul style="margin:0; padding-left:20px; color:#ccc;">
        {highlights_html}
      </ul>
    </div>
  </td></tr>

  <!-- 푸터 -->
  <tr><td style="background:#f5f5f7; border-radius:0 0 16px 16px; padding:24px 40px; text-align:center;">
    <p style="margin:0; font-size:12px; color:#999;">
      {NEWSLETTER_NAME} · 매주 금요일 오전 5시 50분 발송<br>
      구독 취소를 원하시면 회신해주세요.
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    return html


def build_text_email(data: dict) -> str:
    """텍스트 이메일 본문을 생성합니다."""
    issue_number = data["issue_number"]
    date_str = data["date_str"]
    tagline = data.get("tagline", "오늘의 AI 뉴스")
    summary = data.get("summary", "")
    sections = data.get("sections", [])
    highlights = data.get("highlights", [])

    lines = [
        f"{NEWSLETTER_NAME} #{issue_number:03d} _ {date_str}",
        f'"{tagline}"',
        "",
        f"💬 오늘의 한 줄 총평",
        summary,
        "",
        "=" * 50,
        "",
    ]

    for i, sec in enumerate(sections, 1):
        emoji = sec.get("emoji", "📰")
        category = sec.get("category", "")
        title = sec.get("title", "")
        body = sec.get("body", "")
        comment = sec.get("comment", "")

        lines += [
            f"{i}. {emoji} {category}",
            "",
            title,
            "",
            body,
            "",
            f"☞ {AUTHOR_NAME}의 한마디: {comment}",
            "",
            "-" * 50,
            "",
        ]

    lines += [
        f"{NEWSLETTER_NAME} #{issue_number:03d} 완료 ✅",
        "",
        "오늘의 핵심 3줄:",
    ]
    for h in highlights:
        lines.append(f"• {h}")

    return "\n".join(lines)


def send_email(data: dict) -> bool:
    """Gmail SMTP를 통해 이메일을 발송합니다."""
    issue_number = data["issue_number"]
    date_str = data["date_str"]
    tagline = data.get("tagline", "오늘의 AI 뉴스")

    subject = f"[{NEWSLETTER_NAME} #{issue_number:03d}] {date_str} — \"{tagline}\""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL

    text_part = MIMEText(build_text_email(data), "plain", "utf-8")
    html_part = MIMEText(build_html_email(data), "html", "utf-8")

    msg.attach(text_part)
    msg.attach(html_part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        print(f"✅ 이메일 발송 완료: {RECIPIENT_EMAIL}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("❌ Gmail 인증 실패. GMAIL_APP_PASSWORD를 확인하세요.")
        return False
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")
        return False


def main():
    # 환경 변수 확인
    required_vars = ["GEMINI_API_KEY", "GMAIL_USER", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"❌ 필수 환경 변수가 없습니다: {', '.join(missing)}")
        print("   .env 파일을 설정하세요. (.env.example 참고)")
        return

    now = datetime.now(KST)
    date_str = get_korean_date(now)
    issue_number = get_issue_number()

    print(f"📰 {NEWSLETTER_NAME} #{issue_number:03d} 생성 중... ({date_str})")

    # 뉴스 수집 및 뉴스레터 생성
    print("🔍 최신 AI 뉴스 검색 중...")
    data = collect_and_generate_newsletter(issue_number, date_str)

    print(f"✍️  뉴스레터 작성 완료: \"{data.get('tagline')}\"")

    # 이메일 발송
    print("📧 이메일 발송 중...")
    send_email(data)


if __name__ == "__main__":
    main()
