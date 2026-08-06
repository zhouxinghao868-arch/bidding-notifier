#!/usr/bin/env python3
"""
电信招标信息抓取 - 双模式（API拦截优先 + DOM降级）
模式1: 拦截queryListNew API响应获取结构化数据（白天稳定）
模式2: 直接读取页面DOM表格（API失败时降级）
"""

import json
import os
import sys
import time
import random
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True)

OUTPUT_FILE = "telecom_bids.json"
KEYWORDS = ["数智化", "数据", "算力", "战略", "算网", "软件开发", "云智算", "DICT", "ICT", "业务支撑", "系统集成"]
BJT = timezone(timedelta(hours=8))
TODAY = os.environ.get("BIDDING_DATE") or datetime.now(BJT).strftime("%Y-%m-%d")

BASE_URL = "https://caigou.chinatelecom.com.cn"
SEARCH_URL = f"{BASE_URL}/search"

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

DOC_TYPE_MAP = {
    "TenderAnnouncement": "1", "PurchaseAnnounceBasic": "2",
    "PurchaseAnnounc": "2", "CompareSelect": "3",
    "NegotiationSelect": "5", "Prequalfication": "6",
    "ResultAnnounc": "7", "TerminationAnnounc": "15",
    "AuctionAnnounce": "19", "SingleSource": "2",
}


def construct_api_url(record):
    """用API数据中的docId构造详情URL"""
    doc_id = str(record.get('docId', record.get('id', '')))
    dtc = record.get('docTypeCode', '')
    svc = record.get('securityViewCode', '')
    typ = DOC_TYPE_MAP.get(dtc, '7')
    return f"{BASE_URL}/DeclareDetails?id={doc_id}&type={typ}&docTypeCode={dtc}&securityViewCode={svc}"


def construct_dom_url(context, title):
    """用新页面点击搜索结果获取真实详情URL"""
    detail_page = context.new_page()
    try:
        detail_page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)

        # 关闭弹窗（智慧客服等遮挡元素）
        detail_page.evaluate('''() => {
            document.querySelectorAll(".el-dialog__wrapper, .el-dialog, .chat-widget, .service-popup").forEach(el => {
                el.style.display = "none";
                el.style.visibility = "hidden";
            });
        }''')
        time.sleep(1)

        # 搜索框输入标题关键词
        search_input = detail_page.query_selector('input[placeholder="请输入关键字"]')
        if search_input:
            search_input.fill(title[:40])
            time.sleep(1)
            search_input.press("Enter")
            time.sleep(4)

            # 再次关闭弹窗
            detail_page.evaluate('''() => {
                document.querySelectorAll(".el-dialog__wrapper, .el-dialog").forEach(el => {
                    el.style.display = "none";
                });
            }''')
            time.sleep(1)

        # 点击第一条结果（force=True绕过残留遮挡）
        first_row = detail_page.query_selector('.el-table__row')
        if first_row:
            first_row.click(force=True)
            time.sleep(3)
            url = detail_page.url
            if 'DeclareDetails' in url or url != SEARCH_URL:
                print(f"      → 详情URL: {url[:80]}...")
                return url

    except Exception as e:
        print(f"      → 获取详情URL失败: {e}")
    finally:
        detail_page.close()

    return SEARCH_URL


def mode_api(page, context):
    """模式1: API拦截抓取（带重试）"""
    api_data = []
    seen_ids = set()
    results = []
    today_count = 0

    def on_response(response):
        try:
            if "queryListNew" in response.url and response.status == 200:
                body = response.json()
                records = (body.get("data") or {}).get("pageInfo", {}).get("list", [])
                if records:
                    api_data.extend(records)
                    tc = sum(1 for r in records if (r.get("createDate", "") or "")[:10] == TODAY)
                    print(f"    拦截到 {len(records)} 条 (今天{tc}条, 累计{len(api_data)}条)")
        except:
            pass

    page.on("response", on_response)

    # 首页加载触发API（带重试）
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"  尝试加载页面 (第{attempt+1}/{max_retries}次)...")
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=90000)
            time.sleep(8)
            if len(api_data) > 0:
                break
            print(f"  未拦截到数据，等待2秒后重试...")
            time.sleep(2)
        except Exception as e:
            print(f"  页面加载异常: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                page.remove_listener("response", on_response)
                return None

    print(f"  首页拦截: {len(api_data)} 条")

    if len(api_data) == 0:
        page.remove_listener("response", on_response)
        return None  # API失败，触发降级

    # 翻页
    empty_streak = 0
    for pg in range(2, 30):
        last_batch = api_data[-20:] if len(api_data) >= 20 else api_data
        today_in_batch = sum(1 for r in last_batch if (r.get("createDate", "") or "")[:10] == TODAY)
        if today_in_batch == 0:
            empty_streak += 1
            if empty_streak >= 3:
                print(f"  连续{empty_streak}页无今天数据，停止翻页")
                break
        else:
            empty_streak = 0

        try:
            next_btn = page.query_selector('button.btn-next:not([disabled])')
            if not next_btn:
                break
            next_btn.click()
            time.sleep(3)
        except:
            break

    page.remove_listener("response", on_response)
    print(f"  API模式共拦截 {len(api_data)} 条")

    # 过滤
    for record in api_data:
        rid = str(record.get('id', ''))
        if rid in seen_ids:
            continue
        seen_ids.add(rid)

        create_date = (record.get('createDate', '') or '')[:10]
        if create_date != TODAY:
            continue
        today_count += 1

        title = record.get('docTitle', '')

        # 关键词过滤
        if KEYWORDS and not any(kw in title for kw in KEYWORDS):
            continue
        
        results.append({
            "platform": "电信",
            "province": record.get('provinceName', '') or '总部',
            "type": record.get('docType', '公告'),
            "company": "中国电信",
            "title": title,
            "url": construct_api_url(record),
            "date": create_date
        })

    return {"results": results, "today_count": today_count, "mode": "API"}


def mode_dom(page, context):
    """模式2: 从el-table的Vue数据中直接获取完整字段，构造详情URL"""
    results = []
    seen_ids = set()
    today_count = 0

    try:
        if "search" not in page.url:
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=90000)
            time.sleep(8)
    except:
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=90000)
        time.sleep(8)

    # 关闭弹窗
    page.evaluate('document.querySelectorAll(".el-dialog__wrapper").forEach(el => el.remove())')

    empty_streak = 0

    for pg in range(1, 30):
        # 直接从Vue el-table组件获取底层数据
        records = page.evaluate('''() => {
            const tables = document.querySelectorAll('.el-table');
            for (const t of tables) {
                const vm = t.__vue__;
                if (vm && vm.store && vm.store.states && vm.store.states.data) {
                    return vm.store.states.data.map(r => ({
                        id: r.id, docId: r.docId, docTitle: r.docTitle,
                        docTypeCode: r.docTypeCode, securityViewCode: r.securityViewCode,
                        docType: r.docType, createDate: r.createDate, provinceName: r.provinceName
                    }));
                }
            }
            return [];
        }''')

        if not records:
            print(f"  第{pg}页: 无数据，停止")
            break

        page_today = 0
        for record in records:
            rid = str(record.get('id', ''))
            if rid in seen_ids:
                continue
            seen_ids.add(rid)

            create_date = (record.get('createDate', '') or '')[:10]
            if create_date != TODAY:
                continue
            page_today += 1
            today_count += 1

            title = record.get('docTitle', '')

            # 关键词过滤
            if KEYWORDS and not any(kw in title for kw in KEYWORDS):
                continue

            url = construct_api_url(record)
            province = record.get('provinceName', '') or '总部'
            doc_type = record.get('docType', '公告')

            print(f"  [✓] {province} | {title[:50]}...")
            print(f"      URL: {url[:80]}")

            results.append({
                "platform": "电信",
                "province": province,
                "type": doc_type,
                "company": "中国电信",
                "title": title,
                "url": url,
                "date": create_date
            })

        print(f"  第{pg}页: {len(records)}条, 今日{page_today}条")

        if page_today == 0:
            empty_streak += 1
            if empty_streak >= 3:
                print(f"  连续{empty_streak}页无今天数据，停止翻页")
                break
        else:
            empty_streak = 0

        # 翻页
        try:
            next_btn = page.query_selector('button.btn-next:not([disabled])')
            if next_btn:
                next_btn.click()
            else:
                active = page.query_selector('.el-pager .active')
                if active:
                    current_num = int(active.inner_text().strip())
                    next_num = page.query_selector(f'.el-pager li.number:text-is("{current_num + 1}")')
                    if next_num:
                        next_num.click()
                    else:
                        break
                else:
                    break
            time.sleep(3)
        except:
            break

    return {"results": results, "today_count": today_count, "mode": "DOM"}


def fetch_telecom():
    print(f"=== 抓取电信招标 {datetime.now(BJT).strftime('%H:%M:%S')} ===")
    print(f"限定日期: {TODAY}")
    print(f"关键词: {' | '.join(KEYWORDS)}")

    errors = []
    ua = random.choice(UA_LIST)
    print(f"UA: {ua[:50]}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=ua,
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        data = None

        # 模式1: API拦截
        try:
            print("\n[模式1] API拦截抓取...")
            data = mode_api(page, context)
            if data is None:
                print("  API未拦截到数据，降级到DOM模式")
        except Exception as e:
            print(f"  API模式异常: {e}")
            errors.append(f"API: {e}")

        # 模式2: DOM降级
        if data is None:
            try:
                print("\n[模式2] DOM页面抓取...")
                data = mode_dom(page, context)
            except Exception as e:
                print(f"  DOM模式异常: {e}")
                errors.append(f"DOM: {e}")
                data = {"results": [], "today_count": 0, "mode": "失败"}

        browser.close()

    results = data["results"]
    today_count = data["today_count"]
    mode = data["mode"]

    # 保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    with open("telecom_status.json", 'w', encoding='utf-8') as f:
        json.dump({"errors": errors, "count": len(results), "mode": mode}, f, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"[{mode}模式] 今天共 {today_count} 条记录，{len(results)} 条匹配")
    print(f"✅ 电信抓取完成: {len(results)} 条")
    for i, r in enumerate(results):
        print(f"  [{i+1}] 【{r['province']}】{r['title'][:50]}...")
    print(f"{'='*60}")
    return len(results)


if __name__ == "__main__":
    fetch_telecom()

