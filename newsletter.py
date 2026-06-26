#!/usr/bin/env python3
"""
AI 뉴스레터 자동 발송 스크립트
매일 아침 5시에 최신 AI 뉴스를 수집하고 이메일로 발송합니다.
"""

import argparse
import mimetypes
import os
import smtplib
import json
import re
import sys
import textwrap
from io import BytesIO
from datetime import datetime, timezone, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape as html_escape
from urllib.parse import quote, unquote, urlparse

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageOps

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
SECTION_IMAGE_MAX_WIDTH = int(normalize_env_value("SECTION_IMAGE_MAX_WIDTH", "960"))
SECTION_IMAGE_JPEG_QUALITY = int(normalize_env_value("SECTION_IMAGE_JPEG_QUALITY", "78"))
EMAIL_INLINE_IMAGE_MAX_WIDTH = int(normalize_env_value("EMAIL_INLINE_IMAGE_MAX_WIDTH", "960"))
EMAIL_INLINE_IMAGE_JPEG_QUALITY = int(normalize_env_value("EMAIL_INLINE_IMAGE_JPEG_QUALITY", "78"))

KST = timezone(timedelta(hours=9))


def public_asset_relative_path(local_path: str) -> str:
    """public/ 안의 로컬 파일 경로를 배포 기준 상대 경로로 바꿉니다."""
    base_dir = os.path.dirname(__file__)
    public_dir = os.path.abspath(os.path.join(base_dir, "public"))
    abs_path = os.path.abspath(local_path)
    try:
        if os.path.commonpath([public_dir, abs_path]) != public_dir:
            return ""
    except ValueError:
        return ""
    return os.path.relpath(abs_path, public_dir).replace(os.sep, "/")


def public_asset_url(local_path: str) -> str:
    """public/ 안의 로컬 파일 경로를 배포 사이트 URL로 바꿉니다."""
    rel_path = public_asset_relative_path(local_path)
    if not rel_path:
        return ""
    return f"{SITE_URL.rstrip('/')}/{quote(rel_path, safe='/-_.~')}"


def local_path_from_public_url(src: str) -> str:
    """SITE_URL 아래의 공개 이미지 URL을 로컬 public/ 파일 경로로 바꿉니다."""
    if not isinstance(src, str):
        return ""

    parsed_src = urlparse(src.strip())
    parsed_site = urlparse(SITE_URL.rstrip("/"))
    if parsed_src.scheme not in ("http", "https"):
        return ""
    if parsed_src.scheme != parsed_site.scheme or parsed_src.netloc != parsed_site.netloc:
        return ""

    rel_path = unquote(parsed_src.path.lstrip("/"))
    if not rel_path:
        return ""

    public_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "public"))
    local_path = os.path.abspath(os.path.join(public_dir, rel_path.replace("/", os.sep)))
    try:
        if os.path.commonpath([public_dir, local_path]) != public_dir:
            return ""
    except ValueError:
        return ""
    return local_path if os.path.exists(local_path) else ""


def local_path_from_image_src(src: str) -> str:
    """이미지 src가 로컬 public 파일이면 파일 경로를 돌려줍니다."""
    if not isinstance(src, str):
        return ""
    src = src.strip()
    if not src or src.startswith(("https://", "http://", "data:", "cid:")):
        return ""

    if src.startswith("file:///"):
        return src[len("file:///") :].replace("/", os.sep)
    elif src.startswith("file://"):
        return src[len("file://") :].replace("/", os.sep)
    elif src.startswith(("/public/", "\\public\\")):
        return os.path.join(os.path.dirname(__file__), src.lstrip("/\\"))
    elif src.startswith(("public/", "public\\")):
        return os.path.join(os.path.dirname(__file__), src)
    elif os.path.isabs(src):
        return src

    return ""


def optimize_section_image_src(src: str, issue_number: int, section_index: int) -> str:
    """섹션 이미지를 웹/메일용 JPEG로 압축하고 공개 URL을 반환합니다."""
    local_path = local_path_from_image_src(src)
    if not local_path:
        local_path = local_path_from_public_url(src)
    if not local_path:
        return normalize_image_src(src)

    if not public_asset_relative_path(local_path) or not os.path.exists(local_path):
        return normalize_image_src(src)

    images_dir = os.path.join(os.path.dirname(__file__), "public", "issues", "images")
    os.makedirs(images_dir, exist_ok=True)
    output_path = os.path.join(images_dir, f"{issue_number:03d}-{section_index:02d}.jpg")

    with Image.open(local_path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            background = Image.new("RGB", img.size, "white")
            if img.mode in ("RGBA", "LA"):
                background.paste(img, mask=img.getchannel("A"))
            else:
                background.paste(img.convert("RGB"))
            img = background
        else:
            img = img.convert("RGB")

        if img.width > SECTION_IMAGE_MAX_WIDTH:
            new_height = round(img.height * SECTION_IMAGE_MAX_WIDTH / img.width)
            img = img.resize((SECTION_IMAGE_MAX_WIDTH, new_height), Image.Resampling.LANCZOS)

        save_path = output_path
        replace_original = os.path.abspath(local_path) == os.path.abspath(output_path)
        if replace_original:
            save_path = f"{output_path}.tmp"

        img.save(
            save_path,
            "JPEG",
            quality=SECTION_IMAGE_JPEG_QUALITY,
            optimize=True,
            progressive=True,
        )

    if os.path.abspath(local_path) == os.path.abspath(output_path):
        os.replace(save_path, output_path)

    return public_asset_url(output_path)


def image_path_from_html_src(src: str) -> str:
    """HTML img src에서 inline 첨부 가능한 로컬 이미지 경로를 찾습니다."""
    if not isinstance(src, str):
        return ""
    src = src.strip()
    if not src or src.startswith(("data:", "cid:")):
        return ""

    local_path = local_path_from_public_url(src)
    if local_path:
        return local_path

    local_path = local_path_from_image_src(src)
    if local_path and os.path.exists(local_path):
        return local_path
    return ""


def build_inline_image_part(path: str) -> MIMEBase:
    """로컬 이미지를 메일용 Content-ID MIME 파트로 만듭니다."""
    content_type, _ = mimetypes.guess_type(path)
    maintype, subtype = (content_type or "application/octet-stream").split("/", 1)

    if maintype == "image":
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                background = Image.new("RGB", img.size, "white")
                if img.mode in ("RGBA", "LA"):
                    background.paste(img, mask=img.getchannel("A"))
                else:
                    background.paste(img.convert("RGB"))
                img = background
            else:
                img = img.convert("RGB")

            if img.width > EMAIL_INLINE_IMAGE_MAX_WIDTH:
                new_height = round(img.height * EMAIL_INLINE_IMAGE_MAX_WIDTH / img.width)
                img = img.resize((EMAIL_INLINE_IMAGE_MAX_WIDTH, new_height), Image.Resampling.LANCZOS)

            buffer = BytesIO()
            img.save(
                buffer,
                "JPEG",
                quality=EMAIL_INLINE_IMAGE_JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
        part = MIMEImage(buffer.getvalue(), _subtype="jpeg")
    else:
        with open(path, "rb") as f:
            payload = f.read()
        part = MIMEBase(maintype, subtype)
        part.set_payload(payload)
        encoders.encode_base64(part)
    return part


def prepare_html_with_inline_images(html: str) -> tuple[str, list[tuple[str, str]]]:
    """공개 이미지 URL을 cid로 바꾸고 첨부할 이미지 목록을 반환합니다."""
    cid_by_path: dict[str, str] = {}
    inline_images: list[tuple[str, str]] = []

    def replace_src(match: re.Match) -> str:
        prefix, src, suffix = match.groups()
        local_path = image_path_from_html_src(src)
        if not local_path:
            return match.group(0)

        abs_path = os.path.abspath(local_path)
        cid = cid_by_path.get(abs_path)
        if not cid:
            cid = f"newsletter-image-{len(cid_by_path) + 1}"
            cid_by_path[abs_path] = cid
            inline_images.append((cid, abs_path))
        return f'{prefix}cid:{cid}{suffix}'

    inlined_html = re.sub(r'(src=["\'])([^"\']+)(["\'])', replace_src, html)
    return inlined_html, inline_images


def normalize_image_src(src: str) -> str:
    """이메일/웹에서 접근 가능한 이미지 URL로 정규화합니다."""
    if not isinstance(src, str):
        return ""
    src = src.strip()
    if not src:
        return ""
    if src.startswith(("https://", "http://", "data:", "cid:")):
        return src

    local_path = local_path_from_image_src(src)

    if local_path:
        url = public_asset_url(local_path)
        if url:
            return url

    return src


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


def build_section_image_data_uri(section: dict, index: int) -> str:
    """섹션별 라이트 에디토리얼 스타일 SVG 이미지를 만듭니다."""
    palettes = [
        ("#ecfbff", "#d6eef7", "#1570ef", "#0f766e", "#d9b85c"),
        ("#f3fbff", "#dbe8ff", "#2563eb", "#0f766e", "#e4c46a"),
        ("#f6fbf8", "#d9f1e5", "#0f766e", "#1570ef", "#d9b85c"),
        ("#fffaf0", "#f4e6bf", "#c4861a", "#1570ef", "#0f766e"),
    ]
    bg, border, accent, accent_2, gold = palettes[index % len(palettes)]
    category = html_escape(section.get("category", "AI News"))
    title = section.get("title", "")
    title_lines = textwrap.wrap(title, width=18)[:3]
    emoji = html_escape(section.get("emoji", "📰"))

    title_svg = ""
    y = 185
    for line in title_lines:
        title_svg += f'<text x="56" y="{y}" font-size="36" font-weight="700" fill="#172033">{html_escape(line)}</text>'
        y += 52

    svg = f"""
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720">
  <rect width="1200" height="720" rx="36" fill="{bg}"/>
  <rect x="22" y="22" width="1156" height="676" rx="30" fill="#ffffff" stroke="{border}" stroke-width="2"/>
  <rect x="56" y="56" width="210" height="44" rx="22" fill="#ffffff" stroke="{border}" stroke-width="2"/>
  <text x="84" y="84" font-size="22" font-weight="700" fill="{accent}" letter-spacing="1.5">{category.upper()}</text>
  <circle cx="1030" cy="126" r="72" fill="#ffffff" stroke="{border}" stroke-width="2"/>
  <text x="990" y="145" font-size="64">{emoji}</text>
  <circle cx="930" cy="560" r="120" fill="{gold}" fill-opacity="0.18"/>
  <circle cx="1080" cy="540" r="88" fill="{accent}" fill-opacity="0.10"/>
  <path d="M820 190 C900 120 1010 110 1100 170" stroke="{accent}" stroke-width="6" fill="none" stroke-linecap="round"/>
  <path d="M790 250 C885 205 1000 215 1095 275" stroke="{accent_2}" stroke-width="4" fill="none" stroke-linecap="round"/>
  <rect x="56" y="126" width="112" height="6" rx="3" fill="{gold}"/>
  {title_svg}
  <rect x="56" y="538" width="360" height="96" rx="24" fill="#ffffff" stroke="{border}" stroke-width="2"/>
  <text x="84" y="582" font-size="24" font-weight="700" fill="{accent_2}">SECTION {index + 1:02d}</text>
  <text x="84" y="618" font-size="20" fill="#5f7695">Creative AI editorial brief</text>
</svg>
"""
    return f"data:image/svg+xml;utf8,{quote(svg)}"


def attach_section_images(data: dict) -> None:
    """각 섹션에 기본 이미지를 붙입니다."""
    for index, sec in enumerate(data.get("sections", [])):
        if sec.get("image_src") or sec.get("image_url") or sec.get("image_data_uri"):
            continue
        sec["image_data_uri"] = build_section_image_data_uri(sec, index)


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
    attach_section_images(data)
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
  <tr><td style="background:#ffffff; padding:0 28px 0;">
    <div style="background:#ffffff; border:1px solid #dfe9f2; border-radius:28px; padding:32px 28px; box-shadow:0 18px 40px rgba(16, 40, 72, 0.06);">
      <div style="display:inline-block; font-size:11px; color:#0f766e; font-weight:800; letter-spacing:1.6px; text-transform:uppercase; padding:8px 12px; background:#ebfffb; border:1px solid #c9f3ed; border-radius:999px; margin-bottom:16px;">이번 호 트렌드 분석</div>
      <h2 style="margin:0 0 10px; font-size:30px; font-weight:800; color:#172033; line-height:1.28;">{art_title}</h2>
      <p style="margin:0 0 24px; font-size:16px; color:#5f7695; line-height:1.7;">{art_subtitle}</p>
      <div style="height:1px; background:#e7eef5; margin:0 0 24px;"></div>
      <p style="margin:0 0 18px; color:#172033; font-size:17px; line-height:1.95; font-weight:500;">{art_intro}</p>
      <p style="margin:0 0 18px; color:#43536b; font-size:15px; line-height:1.95;">{art_body}</p>
      {'<p style="margin:0 0 24px; color:#43536b; font-size:15px; line-height:1.95;">' + art_body_para2 + '</p>' if art_body_para2 else ''}
      <div style="background:#f3fbff; border:1px solid #d7edf8; border-radius:22px; padding:20px 22px;">
        <div style="font-size:12px; color:#1570ef; font-weight:800; letter-spacing:1.2px; text-transform:uppercase; margin-bottom:8px;">Practical Take</div>
        <p style="margin:0; color:#1e2b3f; font-size:15px; line-height:1.85;">{art_impact}</p>
      </div>
    </div>
  </td></tr>
  <tr><td style="background:#f7f9fc; padding:18px 28px 0;">
    <div style="height:1px; background:#e3ebf3;"></div>
  </td></tr>
"""

    sections_html = ""
    for i, sec in enumerate(sections, 1):
        emoji = sec.get("emoji", "📰")
        category = sec.get("category", "")
        title = sec.get("title", "")
        body = sec.get("body", "")
        comment = clean_comment(sec.get("comment", ""))
        image_src = sec.get("image_src") or sec.get("image_url") or sec.get("image_data_uri", "")
        image_src = optimize_section_image_src(image_src, issue_number, i)

        sections_html += f"""
        <div style="margin-bottom:26px; padding:28px; background:#ffffff; border:1px solid #dfe9f2; border-radius:28px; box-shadow:0 14px 32px rgba(20, 33, 61, 0.05);">
            {'<div style="margin:0 0 22px;"><img src="' + image_src + '" alt="' + html_escape(title) + '" style="display:block; width:100%; height:auto; border-radius:24px; border:1px solid #dfe9f2;"></div>' if image_src else ''}
            <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
              <tr>
                <td style="vertical-align:top;">
                  <div style="font-size:11px; color:#1570ef; font-weight:800; letter-spacing:1.4px; text-transform:uppercase; margin-bottom:10px;">
                    {category}
                  </div>
                </td>
                <td align="right" style="vertical-align:top;">
                  <div style="display:inline-block; min-width:42px; height:42px; line-height:42px; text-align:center; border-radius:50%; background:#eef9ff; border:1px solid #d6eef7; font-size:20px;">
                    {emoji}
                  </div>
                </td>
              </tr>
            </table>
            <h3 style="margin:8px 0 14px; font-size:28px; color:#172033; line-height:1.34; letter-spacing:-0.02em;">
                {title}
            </h3>
            <p style="margin:0 0 18px; color:#5f7695; line-height:1.9; font-size:15px;">
                {body}
            </p>
            <div style="background:#f4f7fb; border:1px solid #e4ebf2; border-radius:22px; padding:18px 20px;">
                <div style="font-size:12px; color:#0f766e; font-weight:800; letter-spacing:1.2px; text-transform:uppercase; margin-bottom:8px;">{COMMENT_AUTHOR_NAME} Note</div>
                <div style="font-size:15px; color:#243247; line-height:1.8;">{comment}</div>
            </div>
        </div>
"""

    highlights_html = ""
    for h in highlights:
        highlights_html += f"""
        <tr>
          <td style="padding:0 0 14px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
              <tr>
                <td style="width:28px; vertical-align:top; padding-top:2px;">
                  <div style="width:18px; height:18px; border-radius:50%; background:#d9b85c;"></div>
                </td>
                <td style="color:#243247; font-size:15px; line-height:1.75;">{h}</td>
              </tr>
            </table>
          </td>
        </tr>"""

    og_title = f"{NEWSLETTER_NAME} #{issue_number:03d} — {tagline}"
    og_description = summary.replace("\"", "&quot;")
    og_image = f"{SITE_URL}/issues/og/{issue_number:03d}.png"
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
<meta property="og:url" content="{web_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_description}">
<meta name="twitter:image" content="{og_image}">
</head>
<body style="margin:0; padding:0; background:#f7f9fc; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#172033;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f7f9fc;">
<tr><td align="center" style="padding:36px 16px 48px;">
<table width="760" cellpadding="0" cellspacing="0" style="max-width:760px; width:100%;">

  <!-- 웹에서 보기 -->
  <tr><td style="padding:0 12px 16px; text-align:center;">
    <p style="margin:0; font-size:12px; color:#8da0b8;">
      이메일이 제대로 보이지 않나요?
      <a href="{web_url}" style="color:#1570ef; text-decoration:underline;">웹에서 보기</a>
    </p>
  </td></tr>

  <!-- 헤더 -->
  <tr><td style="padding:0 12px 18px;">
    <div style="background:#ffffff; border:1px solid #dfe9f2; border-radius:34px; padding:34px 34px 30px; box-shadow:0 22px 50px rgba(16, 40, 72, 0.07);">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr>
          <td style="vertical-align:top;">
            <div style="display:inline-block; padding:9px 14px; border-radius:999px; background:#eef9ff; border:1px solid #d6eef7; font-size:11px; color:#1570ef; font-weight:800; letter-spacing:1.5px; text-transform:uppercase; margin-bottom:18px;">
              Issue #{issue_number:03d}
            </div>
            <div style="font-size:13px; color:#667a95; font-weight:700; letter-spacing:1.5px; margin-bottom:14px;">
              {NEWSLETTER_NAME} · {date_str}
            </div>
            <div style="font-size:38px; font-weight:800; color:#172033; line-height:1.18; letter-spacing:-0.03em; margin-bottom:14px;">
              {tagline}
            </div>
            <div style="font-size:16px; color:#5f7695; line-height:1.75; max-width:560px;">
              모델 발표 그 자체보다, AI가 실제 산업과 일상 속으로 어떻게 스며드는지를 읽는 뉴스레터.
            </div>
          </td>
        </tr>
      </table>
      <div style="margin-top:28px; background:linear-gradient(135deg,#ecfbff 0%,#f9fbff 58%,#fff8e9 100%); border:1px solid #dfeef7; border-radius:28px; padding:20px 22px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
          <tr>
            <td style="width:34%; vertical-align:top; padding-right:12px;">
              <div style="font-size:11px; color:#0f766e; font-weight:800; letter-spacing:1.3px; text-transform:uppercase; margin-bottom:8px;">Signal</div>
              <div style="font-size:18px; color:#172033; font-weight:700; line-height:1.45;">AI가 제품, 보안, 광고, 공급망으로 확장되는 흐름</div>
            </td>
            <td style="width:33%; vertical-align:top; padding:0 12px;">
              <div style="font-size:11px; color:#1570ef; font-weight:800; letter-spacing:1.3px; text-transform:uppercase; margin-bottom:8px;">Palette</div>
              <div style="font-size:15px; color:#4a5d77; line-height:1.65;">밝은 매거진형 레이아웃 위에 청록과 골드로 브랜드 포인트를 얹었습니다.</div>
            </td>
            <td style="width:33%; vertical-align:top; padding-left:12px;">
              <div style="font-size:11px; color:#c4861a; font-weight:800; letter-spacing:1.3px; text-transform:uppercase; margin-bottom:8px;">Format</div>
              <div style="font-size:15px; color:#4a5d77; line-height:1.65;">카카오 공유용 썸네일과 웹 아카이브에 모두 맞는 카드형 편집 구조입니다.</div>
            </td>
          </tr>
        </table>
      </div>
    </div>
  </td></tr>

  <!-- 편집장 노트 -->
  <tr><td style="padding:0 12px 18px;">
    <div style="background:#ffffff; border:1px solid #dfe9f2; border-radius:28px; padding:24px 26px; box-shadow:0 16px 38px rgba(16, 40, 72, 0.05);">
      <div style="font-size:11px; color:#1570ef; font-weight:800; letter-spacing:1.5px; text-transform:uppercase; margin-bottom:10px;">Editor's Note</div>
      <p style="margin:0; color:#243247; font-size:16px; line-height:1.9;">{summary}</p>
    </div>
  </td></tr>

  {trend_html}

  <!-- 뉴스 섹션 헤더 -->
  <tr><td style="padding:10px 28px 12px;">
    <div style="font-size:12px; color:#6f83a0; font-weight:800; letter-spacing:1.7px; text-transform:uppercase;">This Week's Key Stories</div>
  </td></tr>

  <!-- 섹션들 -->
  <tr><td style="padding:0 28px;">
    {sections_html}
  </td></tr>

  <!-- 핵심 인사이트 -->
  <tr><td style="padding:8px 28px 0;">
    <div style="background:linear-gradient(135deg,#ffffff 0%,#f7fbff 62%,#fffaf0 100%); border:1px solid #dfe9f2; border-radius:28px; padding:28px; box-shadow:0 16px 36px rgba(16, 40, 72, 0.05);">
      <div style="font-size:12px; color:#c4861a; font-weight:800; letter-spacing:1.5px; text-transform:uppercase; margin-bottom:14px;">Key Insights</div>
      <div style="font-size:28px; color:#172033; font-weight:800; line-height:1.3; margin-bottom:16px;">이번 호에서 꼭 읽어야 할 세 가지</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        {highlights_html}
      </table>
    </div>
  </td></tr>

  <!-- 푸터 -->
  <tr><td style="padding:24px 28px 0; text-align:center;">
    <p style="margin:0 0 10px; font-size:13px; color:#5f7695;">
      🌐 <a href="https://cri-ai-tive.com" style="color:#1570ef; text-decoration:none;">cri-ai-tive.com</a>
      &nbsp;&nbsp;·&nbsp;&nbsp;
      <a href="https://aitive.me" style="color:#1570ef; text-decoration:none;">aitive.me</a>
      &nbsp;&nbsp;&nbsp;
      📺 <a href="https://youtube.com/@cri-ai-tive" style="color:#1570ef; text-decoration:none;">youtube.com/@cri-ai-tive</a>
    </p>
    <p style="margin:0; font-size:11px; color:#94a3b8;">
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
    email_html = html or build_html_email(data)
    email_html, inline_images = prepare_html_with_inline_images(email_html)

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL

    alternative_part = MIMEMultipart("alternative")
    text_part = MIMEText(build_text_email(data), "plain", "utf-8")
    html_part = MIMEText(email_html, "html", "utf-8")

    alternative_part.attach(text_part)
    alternative_part.attach(html_part)
    msg.attach(alternative_part)

    for cid, image_path in inline_images:
        image_part = build_inline_image_part(image_path)
        image_part.add_header("Content-ID", f"<{cid}>")
        image_part.add_header("Content-Disposition", "inline")
        image_part.add_header("Content-Location", os.path.basename(image_path))
        msg.attach(image_part)

    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("❌ GMAIL_USER 또는 GMAIL_APP_PASSWORD 환경 변수가 비어 있습니다.")
        return False
    if not RECIPIENT_EMAIL:
        print("❌ RECIPIENT_EMAIL 환경 변수가 비어 있습니다.")
        return False

    print(f"[DEBUG] 발신: {GMAIL_USER} → 수신: {RECIPIENT_EMAIL}")
    print(f"[DEBUG] App Password 길이: {len(GMAIL_APP_PASSWORD)}자")
    print(f"[DEBUG] inline 이미지 첨부: {len(inline_images)}개")

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
    issues_og_dir = os.path.join(public_dir, "issues", "og")
    os.makedirs(issues_og_dir, exist_ok=True)

    img = Image.new("RGB", (1200, 630), color="#f7f9fc")
    draw = ImageDraw.Draw(img)

    # Outer frame
    draw.rounded_rectangle([24, 24, 1176, 606], radius=34, fill="#ffffff", outline="#dfe9f2", width=2)

    # Accent ribbon
    draw.rounded_rectangle([72, 64, 220, 112], radius=24, fill="#eef9ff", outline="#d6eef7", width=2)
    draw.text((96, 80), f"ISSUE #{issue_number:03d}", fill="#1570ef")

    # Brand line
    draw.text((72, 140), NEWSLETTER_NAME, fill="#5f7695")

    # Main title
    title_line_1 = tagline[:20]
    title_line_2 = tagline[20:40]
    title_line_3 = tagline[40:58]
    draw.text((72, 205), title_line_1, fill="#172033")
    if title_line_2:
        draw.text((72, 265), title_line_2, fill="#172033")
    if title_line_3:
        draw.text((72, 325), title_line_3, fill="#172033")

    # Soft editorial panel
    draw.rounded_rectangle([72, 420, 1128, 542], radius=28, fill="#f4f8fc", outline="#e4ebf2", width=2)
    draw.text((100, 455), "AI competition is shifting from model launches", fill="#0f766e")
    draw.text((100, 492), "to product integration, security, and infrastructure.", fill="#4a5d77")

    # Gold signal mark
    draw.ellipse([1010, 78, 1088, 156], fill="#fff7df", outline="#e6cf85", width=3)
    draw.text((1033, 101), "AI", fill="#c4861a")

    # Decorative lines
    draw.line([920, 104, 1000, 104], fill="#8fdbe5", width=3)
    draw.line([920, 128, 980, 128], fill="#cfeef3", width=3)

    # Footer URL
    draw.text((72, 570), SITE_URL.replace("https://", ""), fill="#94a3b8")

    latest_og_path = os.path.join(public_dir, "og-image.png")
    issue_og_path = os.path.join(issues_og_dir, f"{issue_number:03d}.png")
    img.save(latest_og_path)
    img.save(issue_og_path)
    print(f"🖼️  OG 이미지 생성 완료: public/og-image.png, public/issues/og/{issue_number:03d}.png")


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
