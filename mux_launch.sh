#!/bin/sh
# HELP: Đọc tin tức từ các báo chính thống (VnExpress, TTXVN, Nhân Dân, Tuổi Trẻ...)
# ICON: tintuc
# GRID: Tin Tức

. /opt/muos/script/var/func.sh

APP_BIN="python3"

# muOS Jacaranda/Andromeda: thiết lập governor, SDL, HOME... cho app
if command -v SETUP_APP >/dev/null 2>&1; then
	SETUP_APP "$APP_BIN" ""
fi

# ------------------------------------------------------------------
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR" || exit 1

PY="$(command -v python3 || echo /usr/bin/python3)"

# Tránh lỗi bộ đệm khi ghi log
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

"$PY" "$APP_DIR/tintuc.py" >"$APP_DIR/stdout.log" 2>&1
