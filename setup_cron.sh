#!/bin/bash
# ========================================
# 매일 아침 5시 뉴스레터 자동 발송 설정
# 실행: bash setup_cron.sh
# ========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$(which python3)"
LOG_FILE="$SCRIPT_DIR/newsletter.log"

# .env 파일 확인
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "❌ .env 파일이 없습니다."
    echo "   cp .env.example .env 후 값을 입력하세요."
    exit 1
fi

# 의존성 설치
echo "📦 패키지 설치 중..."
pip3 install -r "$SCRIPT_DIR/requirements.txt" -q

# 크론 작업 등록
CRON_JOB="0 5 * * * $PYTHON_BIN $SCRIPT_DIR/newsletter.py >> $LOG_FILE 2>&1"

# 기존 등록된 크론 제거 후 새로 등록
( crontab -l 2>/dev/null | grep -v "newsletter.py" ; echo "$CRON_JOB" ) | crontab -

echo ""
echo "✅ 크론 설정 완료!"
echo ""
echo "   스케줄: 매일 오전 5시 (KST)"
echo "   스크립트: $SCRIPT_DIR/newsletter.py"
echo "   로그: $LOG_FILE"
echo ""
echo "현재 크론 목록:"
crontab -l | grep newsletter.py
echo ""
echo "지금 바로 테스트하려면:"
echo "   python3 $SCRIPT_DIR/newsletter.py"
echo ""
echo "크론을 제거하려면:"
echo "   crontab -l | grep -v newsletter.py | crontab -"
