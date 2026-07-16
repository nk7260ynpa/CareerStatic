"""技術關鍵字字典與比對。

正則守則：
1. 英文詞一律以 \\b 包夾並用 IGNORECASE 比對。
2. 含 +、# 等符號的詞（\\b 在符號旁失效）改用 lookaround。
3. 中文詞不加 \\b（中文字元間無字邊界可言），直接子字串比對。
4. 複合詞容忍空白與連字號差異：[\\s\\-]?。
5. 高誤判縮寫（Go、R、CV、JS）逐條處理：Go 只認 Golang／Go 語言，
   R 只認 R 語言，電腦視覺不收 CV（與履歷縮寫衝突）。
"""

import functools
import re

# (正規名稱, regex pattern)；依領域分組，方便日後增修
TECH_KEYWORDS: tuple[tuple[str, str], ...] = (
    # === 程式語言 ===
    ("Python", r"\bpython\b"),
    ("Java", r"\bjava\b(?!\s*script)"),
    ("JavaScript", r"\bjavascript\b|\bnode\.?js\b"),
    ("TypeScript", r"\btypescript\b"),
    ("C++", r"(?<![a-z0-9_+])c\+\+"),
    ("C#", r"(?<![a-z0-9_])c#"),
    ("Go", r"\bgolang\b|go\s*語言"),
    ("R", r"\br\s*語言"),
    ("Scala", r"\bscala\b"),
    ("SQL", r"\bsql\b"),
    ("Shell/Bash", r"\bbash\b|\bshell\b"),
    # === 機器學習 / 深度學習框架 ===
    ("PyTorch", r"\bpytorch\b|\btorch\b"),
    ("TensorFlow", r"\btensorflow\b"),
    ("Keras", r"\bkeras\b"),
    ("scikit-learn", r"scikit[\s\-]?learn|\bsklearn\b"),
    ("XGBoost", r"\bxgboost\b|\blightgbm\b"),
    ("Pandas", r"\bpandas\b"),
    ("NumPy", r"\bnumpy\b"),
    ("OpenCV", r"\bopencv\b"),
    ("CUDA/GPU", r"\bcuda\b|\bgpu\b"),
    ("ONNX", r"\bonnx\b"),
    ("TensorRT", r"\btensorrt\b"),
    ("Transformer", r"\btransformers?\b"),
    ("Hugging Face", r"hugging\s*face|\bhuggingface\b"),
    # === LLM 生態 ===
    ("LLM", r"\bllms?\b|大型?語言模型"),
    ("生成式 AI", r"生成式\s*ai|generative\s*ai|\bgenai\b|\baigc\b"),
    ("RAG", r"\brag\b|檢索增強"),
    ("LangChain", r"lang\s*chain"),
    ("LlamaIndex", r"llama[\s\-]?index"),
    ("Prompt Engineering", r"prompt\s*engineering|提示工程|提示詞"),
    ("Fine-tuning", r"fine[\s\-]?tun(?:e|ing|ed)|微調"),
    ("OpenAI/GPT", r"\bopenai\b|\bchatgpt\b|\bgpt\b|\bgpt[-\s]?\d"),
    ("Claude", r"\bclaude\b|\banthropic\b"),
    ("Gemini", r"\bgemini\b"),
    ("Stable Diffusion", r"stable\s*diffusion|\bsdxl\b"),
    ("ComfyUI", r"comfy\s*ui"),
    ("vLLM", r"\bvllm\b|\bollama\b"),
    ("n8n", r"(?<![a-z0-9])n8n\b"),
    ("AI Agent", r"ai\s*agents?|\bagentic\b|智慧代理|智能代理"),
    ("向量資料庫", r"向量資料庫|vector\s*(?:database|db|store)|\bmilvus\b|\bpinecone\b|\bqdrant\b|\bfaiss\b|\bchroma\b"),
    # === 領域能力 ===
    ("機器學習", r"機器學習|machine[\s\-]?learning|\bml\b"),
    ("深度學習", r"深度學習|deep[\s\-]?learning"),
    ("NLP", r"\bnlp\b|自然語言"),
    ("電腦視覺", r"電腦視覺|計算機視覺|computer\s*vision|影像辨識|影像處理"),
    ("語音辨識", r"語音辨識|speech\s*recognition|\basr\b|\btts\b"),
    ("強化學習", r"強化學習|reinforcement\s*learning"),
    ("推薦系統", r"推薦系統|recommend(?:ation|er)\s*system"),
    ("時間序列", r"時間序列|time[\s\-]?series"),
    ("MLOps", r"\bmlops\b"),
    ("模型部署", r"模型部署|model\s*(?:deployment|serving)|\btriton\b"),
    ("資料探勘", r"資料探勘|數據挖掘|data\s*mining"),
    ("資料分析", r"資料分析|數據分析|data\s*analy(?:sis|tics)"),
    ("資料視覺化", r"資料視覺化|數據視覺化|data\s*visualization"),
    ("大數據", r"大數據|big\s*data"),
    ("統計", r"統計分析|statistics|統計模型"),
    ("A/B 測試", r"a/?b\s*(?:test(?:ing)?|測試)"),
    ("OCR", r"\bocr\b|文字辨識"),
    ("網路爬蟲", r"爬蟲|web\s*(?:crawl|scrap)(?:ing|er)?"),
    # === 資料工程 ===
    ("Spark", r"\bspark\b"),
    ("Hadoop", r"\bhadoop\b"),
    ("Kafka", r"\bkafka\b"),
    ("Airflow", r"\bairflow\b"),
    ("ETL", r"\betl\b|\belt\b"),
    ("資料倉儲", r"資料倉儲|數據倉儲|data\s*warehouse"),
    ("Databricks", r"\bdatabricks\b"),
    ("Snowflake", r"\bsnowflake\b"),
    ("BigQuery", r"big\s*query"),
    ("Elasticsearch", r"elastic\s*search|\belk\b"),
    ("Redis", r"\bredis\b"),
    ("MongoDB", r"\bmongodb\b|\bmongo\b"),
    ("PostgreSQL", r"\bpostgresql\b|\bpostgres\b"),
    ("MySQL", r"\bmysql\b"),
    ("NoSQL", r"\bnosql\b"),
    # === 雲端 / 部署 ===
    ("AWS", r"\baws\b|amazon\s*web\s*services"),
    ("GCP", r"\bgcp\b|google\s*cloud"),
    ("Azure", r"\bazure\b"),
    ("Docker", r"\bdocker\b|容器化"),
    ("Kubernetes", r"\bkubernetes\b|\bk8s\b"),
    ("CI/CD", r"ci\s*/\s*cd|\bcicd\b|\bjenkins\b|github\s*actions|gitlab\s*ci"),
    ("Git", r"\bgit\b(?!hub|lab)"),
    ("Linux", r"\blinux\b|\bubuntu\b|\bcentos\b"),
    ("FastAPI", r"fast\s*api"),
    ("Flask", r"\bflask\b"),
    ("Django", r"\bdjango\b"),
    ("REST API", r"rest(?:ful)?\s*api"),
    ("gRPC", r"\bgrpc\b"),
    ("微服務", r"微服務|microservices?"),
    # === BI / 視覺化工具 ===
    ("Tableau", r"\btableau\b"),
    ("Power BI", r"power\s*bi\b"),
    ("Looker", r"\blooker\b"),
    ("Grafana", r"\bgrafana\b"),
    # === 開發方法 ===
    ("Agile/Scrum", r"\bagile\b|\bscrum\b|敏捷"),
)


@functools.lru_cache(maxsize=1)
def compiled_patterns() -> tuple[tuple[str, re.Pattern], ...]:
    """預編譯全部關鍵字 regex（IGNORECASE）。"""
    return tuple(
        (name, re.compile(pattern, re.IGNORECASE))
        for name, pattern in TECH_KEYWORDS
    )


def match_keywords(text: str) -> set[str]:
    """比對文字中出現的技術關鍵字（回傳正規名稱集合，已去重）。

    Args:
        text: 待比對文字（通常為職稱 + 職缺描述 + 其他條件）。

    Returns:
        命中的正規名稱集合；輸入為空時回傳空集合。
    """
    if not text:
        return set()
    return {name for name, pattern in compiled_patterns() if pattern.search(text)}
