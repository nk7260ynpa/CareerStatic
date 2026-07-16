#!/usr/bin/env bash
#
# CareerStatic 主程式啟動腳本。
#
# 用法：
#   ./run.sh [serve]           啟動服務（每日排程 + 網頁儀表板）
#   ./run.sh crawl [參數...]   立即執行一次爬取（例：--max-pages 2 --detail-limit 10）
#   ./run.sh pytest [參數...]  於 container 內執行單元測試
#   ./run.sh logs              追蹤服務 log
#   ./run.sh stop              停止並移除服務
#   ./run.sh build             重新建置 Docker image
#   ./run.sh psql              進入 PostgreSQL 互動介面

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly COMPOSE_FILE="${SCRIPT_DIR}/docker/docker-compose.yaml"

#######################################
# 以專案 compose 檔執行 docker compose。
# Arguments:
#   docker compose 的子指令與參數。
#######################################
compose() {
  docker compose -f "${COMPOSE_FILE}" "$@"
}

main() {
  mkdir -p "${SCRIPT_DIR}/logs"

  local cmd="${1:-serve}"
  if [[ $# -gt 0 ]]; then
    shift
  fi

  case "${cmd}" in
    serve)
      compose up -d --build
      echo "儀表板網址：http://localhost:8000"
      ;;
    crawl)
      compose run --rm app python -m careerstatic.main crawl "$@"
      ;;
    pytest)
      # 掛載原始碼讓開發期改碼即測；強制 SQLite 並停用排程器
      compose run --rm --no-deps \
        -e ENABLE_SCHEDULER=false \
        -e RUN_ON_STARTUP=false \
        -e DATABASE_URL=sqlite+pysqlite:// \
        -v "${SCRIPT_DIR}:/app" \
        app pytest "$@"
      ;;
    logs)
      compose logs -f app
      ;;
    stop)
      compose down
      ;;
    build)
      "${SCRIPT_DIR}/docker/build.sh"
      ;;
    psql)
      compose exec db psql -U careerstatic careerstatic
      ;;
    *)
      compose run --rm app "$@"
      ;;
  esac
}

main "$@"
