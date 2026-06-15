#!/usr/bin/env python3
"""
AI 뉴스레터 자동 발송 스크립트
매일 아침 5시에 최신 AI 뉴스를 수집하고 이메일로 발송합니다.
"""

import argparse
import os
import smtplib
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()

# 환경 변수 정규화

def normalize_env_value(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    if not isinstance(value, str):
        return default
    stripped = value.strip()
    if not stripped or "???" in stripped:
        return default
    return stripped


def normalize_app_password(value: str) -> str:
    return "".join(value.split())


GEMINI_API_KEY = normalize_env_value("GEMINI_API_KEY")
GMAIL_USER = normalize_env_value("GMAIL_USER")
GMAIL_APP_PASSWORD = normalize_app_password(os.getenv("GMAIL_APP_PASSWORD") or "")
RECIPIENT_EMAIL = normalize_env_value("RECIPIENT_EMAIL")
NEWSLETTER_NAME = normalize_env_value("NEWSLETTER_NAME", "크리AI티브 AI Design Letter")
AUTHOR_NAME = normalize_env_value("AUTHOR_NAME", "제시카AI")
COMMENT_AUTHOR_NAME = "크리AI티브"
SITE_URL = normalize_env_value("SITE_URL", "https://aiinfor.netlify.app")

KST = timezone(timedelta(hours=9))


def clean_comment(comment: str) -> str:
    """생성 모델이 덧붙인 중복 '한마디' 라벨을 제거합니다."""
    if not isinstance(comment, str):
        return ""
    cleaned = comment.strip()
    prefixes = [
        rf"{re.escape(COMMENT_AUTHOR_NAME)}(?:\s*AI)?의\s*한마디\s*[:：]\s*",
        r"(?:아이티브|제시카AI|AI)의\s*한마디\s*[:：]\s*",
    ]
    for pattern in prefixes:
        cleaned = re.sub(rf"^([\W_]*\s*)?{pattern}", r"\1", cleaned)
    return cleaned.strip()


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
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    # 화요일/금요일 발송 기준 — 3일 이내 뉴스만 다룸
    start_date = (now - timedelta(days=3)).strftime("%Y-%m-%d")

    prompt = f"""당신은 AI 업계 전문 뉴스레터 에디터이자 트렌드 분석가입니다.
독자는 디자이너, 기획자, 개발자 등 AI를 실무에 활용하는 한국의 크리에이티브 전문가입니다.
이들은 전문 용어보다 '이게 내 일에 어떤 영향을 미치나'를 먼저 궁금해 합니다.

Google 검색으로 {start_date} ~ {today} 사이에 발표된 최신 AI 뉴스를 수집하고 분석해주세요.

⚠️ 반드시 지켜야 할 규칙:
1. {start_date} 이전에 발표된 뉴스는 절대 포함하지 마세요.
2. 각 섹션은 서로 다른 뉴스여야 합니다. 같은 회사/제품/주제를 2개 이상 다루지 마세요.
3. 검색 결과에서 날짜를 반드시 확인하고, 날짜가 불명확한 오래된 기사는 제외하세요.

검색 키워드 (날짜 범위 {start_date}~{today} 명시하여 검색):
"AI news {today}", "AI model release {today}", "generative AI {today}",
"LLM update {today}", "ComfyUI update {today}", "vibe coding {today}",
"AI design tools {today}", "AI workflow {today}", "AI news this week"

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.
단어 사이 공백을 반드시 지켜주세요 (예: "바이브 코딩", "전체 애플리케이션"):

{{
  "tagline": "이번 호 핵심을 한 문장으로 (날카롭고 기억에 남는 문장)",
  "summary": "편집장 노트: 이번 주 AI 흐름의 핵심 맥락 (2-3문장, 트렌드 변화의 의미 중심)",
  "trend_article": {{
    "title": "이번 호 여러 뉴스를 관통하는 하나의 주제. 독자가 미처 몰랐던 시각이나 역설적 통찰을 담은 제목.",
    "subtitle": "이 주제가 왜 지금 이 시점에 중요한지 한 문장으로.",
    "intro": "이번 {start_date}~{today} 뉴스에서 발견한 흥미로운 패턴이나 역설로 시작하세요. '어, 그러네?' 하고 고개 끄덕이게 만드는 구체적 사실이나 수치로 열어도 좋습니다. 2-3문장.",
    "body": "이 패턴의 구조적 배경을 분석하세요. 단순히 뉴스를 나열하지 말고, 이번 주 여러 사건들이 왜 같은 방향을 가리키는지, 업계의 이면에서 무슨 일이 일어나고 있는지를 전문가 시각으로 설명하세요. 4-5문장.",
    "body_para2": "반론 또는 주의점. '하지만', '그럼에도 불구하고', '많은 사람들이 놓치는 것은' 등으로 자연스럽게 시작하세요. 낙관론과 현실적 시각의 균형을 맞추세요. 2-3문장.",
    "impact": "구체적 행동 권고. '~를 시작해보세요', '~에 주목하세요', '~를 준비할 때입니다' 같은 실질적 제안으로 마무리. 디자이너·기획자·개발자 각자에게 의미 있는 내용으로. 2-3문장."
  }},
  "sections": [
    {{
      "emoji": "섹션 이모지",
      "category": "카테고리명",
      "title": "뉴스 제목 (단어 간 공백 필수)",
      "body": "뉴스 분석 (3-4문장): 사실 + 맥락 + 의미. 단어 간 공백을 반드시 지켜주세요.",
      "comment": "실무자 관점의 날카로운 통찰 (이모지 1개로 시작, 'AI의 한마디:' 같은 라벨은 절대 쓰지 않음)"
    }}
  ],
  "highlights": [
    "이번 호 핵심 인사이트 1 (실무 관점으로)",
    "이번 호 핵심 인사이트 2",
    "이번 호 핵심 인사이트 3"
  ]
}}

섹션은 최소 5개, 최대 8개.
카테고리: 영상 생성 AI, 이미지 생성 AI, 언어 모델, 오픈소스·커뮤니티,
음성·음악 AI, 크리에이터 경제, AI 규제·정책, 기업·투자, 중국 AI 동향,
ComfyUI·워크플로우, 바이브코딩·AI개발도구, 인테리어·건축 AI.
comment에는 "{COMMENT_AUTHOR_NAME}의 한마디:", "AI의 한마디:" 같은 라벨을 넣지 말고 통찰 문장만 작성.
ComfyUI·워크플로우 / 바이브코딩·AI개발도구 / 인테리어·건축 AI 섹션은 관련 뉴스가 있으면 반드시 포함."""

    # Gemini REST API + Google 검색 그라운딩 (gemini-2.0-flash)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }
    resp = requests.post(url, json=payload, timeout=120)
    print(f"[DEBUG] Gemini API 상태코드: {resp.status_code}")
    if resp.status_code != 200:
        print(f"[DEBUG] 오류 응답: {resp.text[:500]}")
    resp.raise_for_status()
    parts = resp.json()["candidates"][0]["content"]["parts"]
    full_text = "".join(p["text"] for p in parts if "text" in p)

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
    trend_article = data.get("trend_article", {})
    sections = data.get("sections", [])
    highlights = data.get("highlights", [])

    # 트렌드 아티클 섹션
    trend_html = ""
    if trend_article:
        art_title = trend_article.get("title", "")
        art_subtitle = trend_article.get("subtitle", "")
        art_intro = trend_article.get("intro", "")
        art_body = trend_article.get("body", "")
        art_body_para2 = trend_article.get("body_para2", "")
        art_impact = trend_article.get("impact", "")
        trend_html = f"""
  <!-- 트렌드 아티클 -->
  <tr><td style="background:#fff; padding:32px 40px 0;">
    <div style="border-left:4px solid #6366f1; padding-left:16px; margin-bottom:8px;">
      <span style="font-size:11px; color:#6366f1; font-weight:800; letter-spacing:2px; text-transform:uppercase;">이번 호 트렌드 분석</span>
    </div>
    <h2 style="margin:0 0 6px; font-size:22px; font-weight:800; color:#1a1a2e; line-height:1.35;">{art_title}</h2>
    <p style="margin:0 0 24px; font-size:14px; color:#8b5cf6; font-weight:600;">{art_subtitle}</p>
    <p style="margin:0 0 18px; color:#222; font-size:16px; line-height:1.9; font-weight:500;">{art_intro}</p>
    <p style="margin:0 0 18px; color:#444; font-size:15px; line-height:1.9;">{art_body}</p>
    {'<p style="margin:0 0 24px; color:#444; font-size:15px; line-height:1.9;">' + art_body_para2 + '</p>' if art_body_para2 else ''}
    <div style="background:#f0f7ff; border-radius:10px; padding:18px 22px; border-left:3px solid #6366f1;">
      <span style="font-size:12px; color:#6366f1; font-weight:700;">💡 실무 시사점</span>
      <p style="margin:10px 0 0; color:#333; font-size:15px; line-height:1.8;">{art_impact}</p>
    </div>
  </td></tr>
  <tr><td style="background:#fff; padding:16px 40px 0;">
    <hr style="border:none; border-top:2px solid #f0f0f0;">
  </td></tr>
"""

    sections_html = ""
    for i, sec in enumerate(sections, 1):
        emoji = sec.get("emoji", "📰")
        category = sec.get("category", "")
        title = sec.get("title", "")
        body = sec.get("body", "")
        comment = clean_comment(sec.get("comment", ""))

        sections_html += f"""
        <div style="margin-bottom:32px; padding:24px; background:#fff; border-radius:12px; border-left:4px solid #6366f1;">
            <div style="font-size:12px; color:#6366f1; font-weight:700; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px;">
                {emoji} {category}
            </div>
            <h3 style="margin:0 0 12px; font-size:17px; color:#1a1a2e; line-height:1.4;">
                {title}
            </h3>
            <p style="margin:0 0 16px; color:#444; line-height:1.85; font-size:15px;">
                {body}
            </p>
            <div style="background:#f8f7ff; border-radius:8px; padding:12px 16px; border-left:3px solid #a78bfa;">
                <span style="font-size:13px; color:#6366f1; font-weight:600;">☞ {COMMENT_AUTHOR_NAME}의 한마디:</span>
                <span style="font-size:14px; color:#555; margin-left:6px;">{comment}</span>
            </div>
        </div>
        <hr style="border:none; border-top:1px solid #f0f0f0; margin:0 0 32px;">
"""

    highlights_html = ""
    for h in highlights:
        highlights_html += f'<li style="margin-bottom:10px; color:#e8e8e8; font-size:15px; line-height:1.6;">{h}</li>'

    og_title = f"{NEWSLETTER_NAME} #{issue_number:03d} — {tagline}"
    og_description = summary.replace("\"", "&quot;")
    og_image = f"{SITE_URL}/og-image.png"
    web_url = f"{SITE_URL}/issues/{issue_number:03d}.html"

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{og_title}</title>
<meta name="description" content="{og_description}">
<meta property="og:type" content="article">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_description}">
<meta property="og:image" content="{og_image}">
<meta property="og:url" content="{SITE_URL}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_description}">
<meta name="twitter:image" content="{og_image}">
</head>
<body style="margin:0; padding:0; background:#f5f5f7; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f7;">
<tr><td align="center" style="padding:32px 16px;">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px; width:100%;">

  <!-- 웹에서 보기 -->
  <tr><td style="padding:0 0 12px; text-align:center;">
    <p style="margin:0; font-size:12px; color:#999;">
      이메일이 제대로 보이지 않나요?
      <a href="{web_url}" style="color:#6366f1; text-decoration:underline;">웹에서 보기</a>
    </p>
  </td></tr>

  <!-- 헤더 -->
  <tr><td style="background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%); border-radius:16px 16px 0 0; padding:36px 40px;">
    <div style="font-size:12px; color:rgba(255,255,255,0.7); font-weight:600; letter-spacing:2px; margin-bottom:8px;">
      {NEWSLETTER_NAME} _ {date_str}
    </div>
    <div style="font-size:26px; font-weight:800; color:#fff; line-height:1.3;">
      "{tagline}"
    </div>
  </td></tr>

  <!-- 편집장 노트 -->
  <tr><td style="background:#fff; padding:24px 40px 0;">
    <div style="background:#f0f0ff; border-radius:10px; padding:16px 20px;">
      <span style="font-size:13px; color:#6366f1; font-weight:700;">💬 편집장 노트</span>
      <p style="margin:8px 0 0; color:#333; font-size:15px; line-height:1.75;">{summary}</p>
    </div>
  </td></tr>

  {trend_html}

  <!-- 뉴스 섹션 헤더 -->
  <tr><td style="background:#fff; padding:24px 40px 8px;">
    <div style="font-size:11px; color:#999; font-weight:700; letter-spacing:2px; text-transform:uppercase;">이번 주 주요 뉴스</div>
  </td></tr>

  <!-- 섹션들 -->
  <tr><td style="background:#f8f8fc; padding:24px 40px;">
    {sections_html}
  </td></tr>

  <!-- 핵심 인사이트 -->
  <tr><td style="background:#fff; padding:32px 40px;">
    <div style="background:#1a1a2e; border-radius:12px; padding:24px 28px;">
      <div style="font-size:14px; color:#a78bfa; font-weight:700; margin-bottom:16px;">
        이번 호 핵심 인사이트 ✅
      </div>
      <ul style="margin:0; padding-left:20px; color:#ccc;">
        {highlights_html}
      </ul>
    </div>
  </td></tr>

  <!-- 푸터 -->
  <tr><td style="background:#f5f5f7; border-radius:0 0 16px 16px; padding:28px 40px; text-align:center;">
    <p style="margin:0 0 10px; font-size:13px; color:#555;">
      🌐 <a href="https://cri-ai-tive.com" style="color:#6366f1; text-decoration:none;">cri-ai-tive.com</a>
      &nbsp;&nbsp;·&nbsp;&nbsp;
      <a href="https://aitive.me" style="color:#6366f1; text-decoration:none;">aitive.me</a>
      &nbsp;&nbsp;&nbsp;
      📺 <a href="https://youtube.com/@cri-ai-tive" style="color:#6366f1; text-decoration:none;">youtube.com/@cri-ai-tive</a>
    </p>
    <p style="margin:0; font-size:11px; color:#aaa;">
      {NEWSLETTER_NAME} · 매주 화요일·금요일 오전 5시 50분 발송 · 구독 취소를 원하시면 회신해주세요.
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
        comment = clean_comment(sec.get("comment", ""))

        lines += [
            f"{i}. {emoji} {category}",
            "",
            title,
            "",
            body,
            "",
            f"☞ {COMMENT_AUTHOR_NAME}의 한마디: {comment}",
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


def send_email(data: dict, html: str = None) -> bool:
    """Gmail SMTP를 통해 이메일을 발송합니다."""
    issue_number = data["issue_number"]
    date_str = data["date_str"]
    tagline = data.get("tagline", "오늘의 AI 뉴스")

    subject = f"[{NEWSLETTER_NAME}] {date_str} — \"{tagline}\""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL

    text_part = MIMEText(build_text_email(data), "plain", "utf-8")
    html_part = MIMEText(html or build_html_email(data), "html", "utf-8")

    msg.attach(text_part)
    msg.attach(html_part)

    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("❌ GMAIL_USER 또는 GMAIL_APP_PASSWORD 환경 변수가 비어 있습니다.")
        return False
    if not RECIPIENT_EMAIL:
        print("❌ RECIPIENT_EMAIL 환경 변수가 비어 있습니다.")
        return False

    print(f"[DEBUG] 발신: {GMAIL_USER} → 수신: {RECIPIENT_EMAIL}")
    print(f"[DEBUG] App Password 길이: {len(GMAIL_APP_PASSWORD)}자")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.set_debuglevel(0)
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        print(f"✅ 이메일 발송 완료: {RECIPIENT_EMAIL}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Gmail 인증 실패: {e}")
        print("   → GitHub Secret GMAIL_APP_PASSWORD가 Google 앱 비밀번호(16자리)인지 확인하세요.")
        print("   → Google 계정 → 보안 → 2단계 인증 ON → 앱 비밀번호 생성")
        return False
    except smtplib.SMTPRecipientsRefused as e:
        print(f"❌ 수신 주소 거부됨: {e}")
        return False
    except Exception as e:
        print(f"❌ 이메일 발송 실패 ({type(e).__name__}): {e}")
        return False




def generate_og_image(data: dict, public_dir: str) -> None:
    """OG 썸네일 이미지를 생성합니다."""
    tagline = data.get("tagline", NEWSLETTER_NAME)
    issue_number = data["issue_number"]

    img = Image.new("RGB", (1200, 630), color="#1a1a2e")
    draw = ImageDraw.Draw(img)

    # 왼쪽 보라색 강조선
    draw.rectangle([0, 0, 8, 630], fill="#6366f1")

    # 상단 배지
    draw.rounded_rectangle([60, 55, 60 + len(NEWSLETTER_NAME) * 13 + 40, 105], radius=20, fill="#6366f1")
    draw.text((80, 68), NEWSLETTER_NAME, fill="white")

    # 이슈 번호
    draw.text((60, 130), f"#{issue_number:03d}", fill="#a78bfa")

    # 태그라인 (긴 텍스트 줄바꿈)
    words = tagline
    draw.text((60, 200), words[:28], fill="#ffffff")
    if len(words) > 28:
        draw.text((60, 255), words[28:56], fill="#ffffff")

    # 구분선
    draw.rectangle([60, 360, 1140, 362], fill="#2d2d4e")

    # 하단 카테고리 태그
    tags = ["언어모델", "ComfyUI", "바이브코딩", "인테리어AI", "영상AI"]
    x = 60
    for tag in tags:
        w = len(tag) * 14 + 30
        draw.rounded_rectangle([x, 400, x + w, 440], radius=12, fill="#2d2d4e")
        draw.text((x + 15, 410), tag, fill="#a78bfa")
        x += w + 15

    # URL
    draw.text((60, 560), SITE_URL.replace("https://", ""), fill="#6366f1")

    img.save(os.path.join(public_dir, "og-image.png"))
    print("🖼️  OG 이미지 생성 완료: public/og-image.png")


def save_html_files(data: dict, html: str) -> None:
    """뉴스레터 HTML을 public/ 폴더에 저장합니다."""
    base_dir = os.path.dirname(__file__)
    public_dir = os.path.join(base_dir, "public")
    issues_dir = os.path.join(public_dir, "issues")
    os.makedirs(issues_dir, exist_ok=True)

    issue_number = data["issue_number"]

    # OG 썸네일 이미지 생성
    generate_og_image(data, public_dir)

    # 최신호: public/index.html
    with open(os.path.join(public_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # 아카이브: public/issues/001.html
    with open(os.path.join(issues_dir, f"{issue_number:03d}.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"💾 HTML 저장 완료: public/index.html, public/issues/{issue_number:03d}.html")


def parse_args():
    parser = argparse.ArgumentParser(description="AI 뉴스레터 자동 생성 및 발송")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="메일 발송 없이 HTML/OG 이미지 생성 및 저장만 수행합니다.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # 환경 변수 확인
    required_vars = {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "GMAIL_USER": GMAIL_USER,
        "GMAIL_APP_PASSWORD": GMAIL_APP_PASSWORD,
        "RECIPIENT_EMAIL": RECIPIENT_EMAIL,
    }
    missing = [name for name, value in required_vars.items() if not value]
    if missing:
        print(f"❌ 필수 환경 변수가 없습니다: {', '.join(missing)}")
        print("   .env 파일을 설정하세요. (.env.example 참고)")
        return 1

    now = datetime.now(KST)
    date_str = get_korean_date(now)
    issue_number = get_issue_number()

    print(f"📰 {NEWSLETTER_NAME} #{issue_number:03d} 생성 중... ({date_str})")

    # 뉴스 수집 및 뉴스레터 생성
    print("🔍 최신 AI 뉴스 검색 중...")
    data = collect_and_generate_newsletter(issue_number, date_str)

    print(f"✍️  뉴스레터 작성 완료: \"{data.get('tagline')}\"")

    # HTML 생성
    html = build_html_email(data)
    save_html_files(data, html)

    if args.dry_run:
        print("🛑 dry run 모드: 이메일 발송 없이 종료합니다.")
    else:
        # 이메일 발송
        print("📧 이메일 발송 중...")
        if not send_email(data, html):
            return 1

    # 공유 링크 출력
    print(f"\n🔗 공유 링크: {SITE_URL}/issues/{issue_number:03d}.html")
    print("   💡 웹에서 보기 링크가 404가 나올 경우, public/ 내용을 Vercel에 다시 배포해야 합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
