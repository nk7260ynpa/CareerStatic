# CareerStatic 應用程式映像。
#
# 內含爬蟲、每日排程與網頁儀表板；預設啟動 serve 模式
# （APScheduler 每日排程 + FastAPI 儀表板）。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Taipei

WORKDIR /app

# 先安裝相依套件以利用 Docker layer 快取
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "careerstatic.main", "serve"]
