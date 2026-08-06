#!/usr/bin/env python3
"""
联通招标信息抓取 - 双模式（API拦截优先 + DOM降级）
优化点：增强重试机制、指数退避、更长超时、多种等待策略
"""

import json
import os
import sys
import time
import random
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True)

OUTPUT_FILE = "unicom_bids.json"
KEYWORDS = ["数智化", "数据", "算力", "战略", "算网", "软件开发", "云智算", "DICT", "ICT", "业务支撑", "系统集成"]
BJT = timezone(timedelta(hours=8))
TODAY = os.environ.get("BIDDING_DATE") or datetime.now(BJT).strftime("%Y-%m-%d")

UNICOM_URL = "https://www.chinaunicombidding.cn/bidInformation"

# 增强配置
MAX_PAGE_RETRIES = 5          # 页面加载重试次数（从3增加到5）
PAGE_TIMEOUT = 90000          # 页面超时时间（从60秒增加到90秒）
API_WAIT_TIME = 10            # API拦截等待时间（从8秒增加到10秒）
BACKOFF_BASE = 3              # 指数退避基数（重试间隔：3, 6, 12, 24, 48秒）

def rand_sleep(lo=2, hi=5):
    """随机延迟，避免固定模式"""
    time.sleep(random.uniform(lo, hi))

def construct_unicom_url(record):
    """用API/DOM数据构造联通真实详情URL"""
    rid = str(record.get('id', ''))
    if not rid or rid == 'None':
        return UNICOM_URL
    return f"{UNICOM_URL}/detail?id={rid}"


def wait_for_page_stable(page, timeout_ms=10000):
    """等待页面网络稳定（避免还在加载时被误判为失败）"""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
        return True
    except:
        return False


def load_page_with_retry(page, url, wait_strategy="networkidle"):
    """
    带增强重试的页面加载
    - 指数退避重试
    - 多种等待策略
    - 网络稳定检测
    """
    last_error = None
    
    for attempt in range(MAX_PAGE_RETRIES):
        try:
            print(f"  尝试加载页面 (第{attempt+1}/{MAX_PAGE_RETRIES}次)...")
            
            # 使用不同的等待策略
            if attempt == 0:
                wait_state = wait_strategy
            elif attempt == 1:
                wait_state = "domcontentloaded"  # 第二次尝试更快返回
            else:
                wait_state = "load"  # 后续尝试标准加载
            
            page.goto(url, wait_until=wait_state, timeout=PAGE_TIMEOUT)
            
            # 额外等待网络稳定
            if wait_for_page_stable(page, 5000):
                print(f"  页面加载成功（网络稳定）")
            else:
                print(f"  页面加载成功（继续执行）")
            
            return True
            
        except Exception as e:
            last_error = str(e)
            print(f"  页面加载异常: {e}")
            
            if attempt < MAX_PAGE_RETRIES - 1:
                # 指数退避：3, 6, 12, 24, 48秒
                sleep_time = BACKOFF_BASE * (2 ** attempt)
                sleep_time += random.uniform(0, 2)  # 添加随机抖动
                print(f"  等待{sleep_time:.1f}秒后重试...")
                time.sleep(sleep_time)
    
    print(f"  页面加载失败（已重试{MAX_PAGE_RETRIES}次）: {last_error}")
    return False


def mode_api(page):
    """模式1: API拦截抓取（增强版）"""
    api_data = []
    all_records = []
    seen_ids = set()
    results = []
    today_count = 0

    def on_response(resp):
        if 'getAnnoList' in resp.url:
            try:
                body = resp.json()
                if body.get('success') and body.get('data', {}).get('records'):
                    api_data.append(body['data'])
            except:
                pass

    page.on("response", on_response)

    # 增强页面加载
    if not load_page_with_retry(page, UNICOM_URL, "networkidle"):
        page.remove_listener("response", on_response)
        return None

    # 等待API数据（带重试）
    api_wait_attempts = 3
    for attempt in range(api_wait_attempts):
        time.sleep(API_WAIT_TIME if attempt == 0 else 5)
        if api_data:
            break
        print(f"  未拦截到数据，额外等待...")

    if not api_data:
        page.remove_listener("response", on_response)
        return None

    # 首页数据
    data = api_data[-1]
    total = data.get('total', 0)
    pages = data.get('pages', 0)
    records = data.get('records', [])
    all_records.extend(records)
    print(f"  总记录: {total}, 总页数: {pages}")
    print(f"  第1页: {len(records)} 条")

    # 翻页
    max_pages = min(50, pages)
    no_today_streak = 0
    print(f"  将翻页检查: 最多{max_pages}页 (总页数{pages})")

    for p in range(2, max_pages + 1):
        api_data.clear()
        try:
            next_btn = page.locator(f".ant-pagination-item[title='{p}']").first
            if next_btn.count() > 0:
                next_btn.click()
                rand_sleep(3, 5)  # 随机延迟
                if api_data:
                    records = api_data[-1].get('records', [])
                    all_records.extend(records)
                    print(f"  第{p}页: {len(records)} 条")
                    has_today = any(r.get('createDate', '')[:10] == TODAY for r in records)
                    if has_today:
                        no_today_streak = 0
                    else:
                        no_today_streak += 1
                        if no_today_streak >= 2:
                            print(f"  连续{no_today_streak}页无今日数据，停止翻页")
                            break
            else:
                break
        except Exception as e:
            print(f"  翻页异常: {e}")
            break

    page.remove_listener("response", on_response)
    print(f"  共获取 {len(all_records)} 条记录")

    # 过滤
    for record in all_records:
        rid = str(record.get('id', ''))
        if rid in seen_ids:
            continue
        seen_ids.add(rid)

        title = record.get('annoName', '')
        province = record.get('provinceName', '')
        anno_type = record.get('annoType', '')
        create_date = record.get('createDate', '')[:10]
        bid_company = record.get('bidCompany', '')

        if create_date and create_date != TODAY:
            continue
        today_count += 1

        if KEYWORDS and not any(kw in title for kw in KEYWORDS):
            continue
        
        detail_url = construct_unicom_url(record)
        print(f"  [✓] {province} | {anno_type} | {title[:50]}...")

        results.append({
            "platform": "联通",
            "province": province or "全国",
            "type": anno_type,
            "company": bid_company or "中国联通",
            "title": title,
            "url": detail_url,
            "date": create_date or TODAY
        })

    return {"results": results, "today_count": today_count, "mode": "API"}


def mode_dom(page, context):
    """模式2: DOM模式——在浏览器JS环境中直接fetch调用API获取数据"""
    results = []
    seen_ids = set()
    today_count = 0
    page_no = 1
    max_pages = 10

    # 增强页面加载
    if not load_page_with_retry(page, UNICOM_URL, "networkidle"):
        return {"results": [], "today_count": 0, "mode": "DOM-失败"}

    print("  [模式2] 使用JS fetch调用API获取数据...")

    # 翻页获取所有今天的记录
    while page_no <= max_pages:
        # 在浏览器JS环境中调用API
        api_data = page.evaluate(f'''async () => {{
            try {{
                const resp = await fetch('/api/v1/bizAnno/getAnnoList', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        pageNo: {page_no},
                        pageSize: 50,
                        modeNo: 'BizAnnoVoMtable'
                    }})
                }});
                const data = await resp.json();
                if (data.success && data.data && data.data.records) {{
                    return {{
                        success: true,
                        total: data.data.total,
                        pages: data.data.pages,
                        records: data.data.records.map(r => ({{
                            id: r.id,
                            annoName: r.annoName,
                            provinceName: r.provinceName,
                            annoType: r.annoType,
                            createDate: r.createDate,
                            bidCompany: r.bidCompany
                        }}))
                    }};
                }}
                return {{ success: false, error: 'no data', keys: Object.keys(data) }};
            }} catch(e) {{
                return {{ success: false, error: e.message }};
            }}
        }}''')

        if not api_data.get('success'):
            print(f"  第{page_no}页API调用失败: {api_data.get('error', 'unknown')}")
            break

        records = api_data.get('records', [])
        if not records:
            break

        page_today = 0
        for record in records:
            rid = str(record.get('id', ''))
            if rid in seen_ids or not rid:
                continue
            seen_ids.add(rid)

            create_date = (record.get('createDate', '') or '')[:10]
            if create_date != TODAY:
                continue
            page_today += 1
            today_count += 1

            title = record.get('annoName', '')
            
            if KEYWORDS and not any(kw in title for kw in KEYWORDS):
                continue

            province = record.get('provinceName', '') or '全国'
            anno_type = record.get('annoType', '') or '公告'
            bid_company = record.get('bidCompany', '') or '中国联通'

            detail_url = construct_unicom_url(record)

            print(f"  [✓] {province} | {anno_type} | {title[:50]}...")

            results.append({
                "platform": "联通",
                "province": province,
                "type": anno_type,
                "company": bid_company,
                "title": title,
                "url": detail_url,
                "date": create_date
            })

        print(f"  第{page_no}页: {len(records)}条API记录, 今日{page_today}条匹配")

        if page_today == 0 and page_no > 3:
            break

        total_pages = api_data.get('pages', 1)
        if page_no >= total_pages:
            break

        page_no += 1
        rand_sleep(1, 3)  # 随机延迟

    return {"results": results, "today_count": today_count, "mode": "JS-API"}


def fetch_unicom():
    print(f"=== 抓取联通招标 {datetime.now(BJT).strftime('%H:%M:%S')} ===")
    print(f"限定日期: {TODAY}")
    print(f"关键词: {' | '.join(KEYWORDS)}")
    print(f"配置: 重试{MAX_PAGE_RETRIES}次, 超时{PAGE_TIMEOUT/1000:.0f}秒")

    errors = []

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    data = None

    # 模式1: API拦截
    try:
        print("\n[模式1] API拦截抓取...")
        data = mode_api(page)
        if data is None:
            print("  API未拦截到数据，降级到DOM模式")
    except Exception as e:
        print(f"  API模式异常: {e}")
        errors.append(f"API: {e}")

    # 模式2: DOM降级
    if data is None:
        try:
            print("\n[模式2] DOM页面抓取...")
            # 关闭旧页面，新建页面避免状态问题
            page.close()
            page = context.new_page()
            data = mode_dom(page, context)
        except Exception as e:
            print(f"  DOM模式异常: {e}")
            errors.append(f"DOM: {e}")
            data = {"results": [], "today_count": 0, "mode": "失败"}

    page.close()
    browser.close()
    playwright.stop()

    results = data["results"]
    today_count = data["today_count"]
    mode = data["mode"]

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    with open("unicom_status.json", 'w', encoding='utf-8') as f:
        json.dump({"errors": errors, "count": len(results), "mode": mode}, f, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"[{mode}模式] ✅ 联通抓取完成: 今日{today_count}条, {len(results)}条匹配关键词")
    for i, r in enumerate(results):
        print(f"  [{i+1}] 【{r['province']}-{r['type']}】{r['title'][:50]}...")
    print(f"{'='*60}")

    return len(results)


if __name__ == "__main__":
    fetch_unicom()

