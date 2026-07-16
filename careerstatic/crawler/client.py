"""104 人力銀行 API 客戶端。

104 全站有 Cloudflare 防護，必須使用 curl_cffi 的
impersonate="chrome"（瀏覽器 TLS 指紋）才能取得 JSON 回應；
切勿自訂 User-Agent，以免與 TLS 指紋不一致而遭識破。
"""

import logging
import random
import time
from collections.abc import Iterator

from curl_cffi import requests as cffi_requests

logger = logging.getLogger(__name__)

LIST_URL = "https://www.104.com.tw/jobs/search/api/jobs"
DETAIL_URL = "https://www.104.com.tw/job/ajax/content/{code}"
LIST_REFERER = "https://www.104.com.tw/jobs/search/"
DETAIL_REFERER = "https://www.104.com.tw/job/{code}"

# 重試等待基準秒數（指數退避：5 → 15 → 45）
_BACKOFF_BASE = 5.0
_BACKOFF_FACTOR = 3.0
_BACKOFF_JITTER = 5.0
_RETRY_AFTER_CAP = 120


class CrawlError(Exception):
    """單一請求重試耗盡或收到不可重試的錯誤。"""


class CrawlBlockedError(Exception):
    """連續多筆請求失敗，疑似遭到封鎖，應中止本輪爬取。"""


class Client104:
    """104 API 客戶端：統一節流、重試與 JSON 解析。

    Attributes:
        min_delay: 每次請求前隨機延遲的下限秒數。
        max_delay: 每次請求前隨機延遲的上限秒數。
    """

    def __init__(
        self,
        min_delay: float = 1.2,
        max_delay: float = 2.8,
        max_retries: int = 3,
        timeout: float = 20.0,
    ) -> None:
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._max_retries = max_retries
        self._timeout = timeout
        # session 全程重用以保留 cookie；impersonate 由 curl_cffi
        # 提供與 Chrome 一致的 TLS 指紋與標頭
        self._session = cffi_requests.Session(impersonate="chrome")

    def _throttle(self) -> None:
        """請求前的禮貌性延遲。"""
        time.sleep(random.uniform(self._min_delay, self._max_delay))

    def _request(self, url: str, params: dict | None, referer: str) -> dict:
        """發出 GET 請求並解析 JSON，內含節流與指數退避重試。

        Args:
            url: 目標網址。
            params: query string 參數。
            referer: 必要的 Referer 標頭。

        Returns:
            解析後的 JSON dict。

        Raises:
            CrawlError: 重試耗盡或收到不可重試的狀態碼。
        """
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt:
                backoff = _BACKOFF_BASE * (_BACKOFF_FACTOR ** (attempt - 1))
                backoff += random.uniform(0, _BACKOFF_JITTER)
                logger.warning(
                    "第 %d 次重試 %s（等待 %.1f 秒）", attempt, url, backoff
                )
                time.sleep(backoff)
            self._throttle()

            try:
                resp = self._session.get(
                    url,
                    params=params,
                    headers={"Referer": referer, "Accept": "application/json"},
                    timeout=self._timeout,
                )
            except Exception as exc:  # noqa: BLE001 - 網路層例外一律重試
                last_error = exc
                logger.warning("請求 %s 發生網路錯誤：%s", url, exc)
                continue

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    last_error = exc
                    logger.warning("回應非 JSON（%s），重試", url)
                    continue

            if resp.status_code == 429:
                retry_after = str(resp.headers.get("Retry-After", ""))
                if retry_after.isdigit():
                    wait = min(int(retry_after), _RETRY_AFTER_CAP)
                    logger.warning("收到 429，依 Retry-After 等待 %d 秒", wait)
                    time.sleep(wait)

            if resp.status_code in (403, 429) or resp.status_code >= 500:
                last_error = CrawlError(f"HTTP {resp.status_code}")
                logger.warning("請求 %s 收到 HTTP %d", url, resp.status_code)
                continue

            # 其他 4xx（如 404）視為不可重試
            raise CrawlError(f"HTTP {resp.status_code}：{url}")

        raise CrawlError(f"重試耗盡：{url}") from last_error

    def search_jobs(self, keyword: str, page: int) -> dict:
        """搜尋單一頁職缺列表。"""
        params = {
            "jobsource": "index_s",
            "keyword": keyword,
            "mode": "s",
            "order": "15",
            "page": str(page),
            "pagesize": "20",
        }
        return self._request(LIST_URL, params, LIST_REFERER)

    def iter_search(
        self, keyword: str, max_pages: int
    ) -> Iterator[tuple[list[dict], dict]]:
        """逐頁搜尋職缺，產出 (items, pagination)。

        停止條件：超過 API 回報的 lastPage、該頁無資料、或達 max_pages。
        """
        page = 1
        while page <= max_pages:
            payload = self.search_jobs(keyword, page)
            items = payload.get("data") or []
            pagination = (payload.get("metadata") or {}).get("pagination") or {}
            if not items:
                break
            yield items, pagination
            last_page = int(pagination.get("lastPage") or 0)
            if last_page and page >= last_page:
                break
            page += 1

    def fetch_job_detail(self, job_code: str) -> dict:
        """抓取單一職缺的詳細內容。"""
        return self._request(
            DETAIL_URL.format(code=job_code),
            None,
            DETAIL_REFERER.format(code=job_code),
        )
