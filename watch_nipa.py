import os, re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from notion_client import Client

# ===== 설정 =====
KEYWORD = "AI"  # 찾을 단어(대소문자 그대로 포함 검색)
NIPA_URL = "https://www.nipa.kr/home/bsnsAll/0/nttList?bbsNo=4&tab=2"  # 사업공고 리스트

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DB_ID = os.getenv("NOTION_DB_ID", "")

# ===== 도우미 =====
def norm(txt: str) -> str:
    return re.sub(r"\s+", " ", txt or "").strip()

def already_in_notion(notion: Client, url: str) -> bool:
    if not url: return False
    res = notion.databases.query(
        database_id=NOTION_DB_ID,
        filter={"property": "URL", "url": {"equals": url}}
    )
    return len(res.get("results", [])) > 0

def upsert_notion(notion: Client, item: dict) -> bool:
    if already_in_notion(notion, item["url"]):
        return False
    props = {
        "Name": {"title":[{"text":{"content": item["title"][:200]}}]},
        "Source": {"select":{"name":"NIPA"}},
        "URL": {"url": item["url"]},
        "기관": {"rich_text":[{"text":{"content":"정보통신산업진흥원"}}]},
    }
    if item.get("posted_at"):
        props["공고일"] = {"date":{"start": item["posted_at"]}}
    if item.get("due_at"):
        props["마감일"] = {"date":{"start": item["due_at"]}}
    props["매칭키워드"] = {"multi_select":[{"name": KEYWORD}]}

    notion.pages.create(parent={"database_id": NOTION_DB_ID}, properties=props)
    return True

# ===== 크롤러 =====
def fetch_nipa_list(limit=50):
    r = requests.get(NIPA_URL, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    rows = []
    # 사이트가 표 형태인 경우가 많음: tr 안의 a, td들을 이용
    for tr in soup.select("table tbody tr")[:limit]:
        a = tr.select_one("a")
        if not a: 
            continue
        title = norm(a.get_text())
        href  = a.get("href") or ""
        url   = "https://www.nipa.kr" + href if href.startswith("/") else href
        tds   = [norm(td.get_text()) for td in tr.select("td")]
        # 기간(마감일) 대략 추정: yyyy-mm-dd 포맷을 찾아 가장 마지막을 마감일로
        period_text = " ".join(tds)
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", period_text)
        due_at = dates[-1] if dates else None

        rows.append({
            "title": title,
            "url": url,
            "posted_at": None,
            "due_at": due_at,
            "raw": period_text
        })
    return rows

def run():
    if not (NOTION_TOKEN and NOTION_DB_ID):
        print("환경변수(NOTION_TOKEN/NOTION_DB_ID)가 필요합니다.")
        return

    notion = Client(auth=NOTION_TOKEN)

    items = fetch_nipa_list()
    new_count = 0
    for it in items:
        text_blob = (it["title"] + " " + (it.get("raw") or "")).lower()
        if KEYWORD.lower() not in text_blob:
            continue
        if upsert_notion(notion, it):
            new_count += 1

    print(f"[NIPA-AI] scanned={len(items)} new_saved={new_count}")

if __name__ == "__main__":
    run()
