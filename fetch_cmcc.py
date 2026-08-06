#!/usr/bin/env python3
"""
移动招标信息抓取 - 优化版
优化点：不切子分类，直接在大类页面深度翻页抓取
"""

import json
import os
import sys
import time
import random
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

def rand_sleep(lo=2, hi=5):
    time.sleep(random.uniform(lo, hi))

sys.stdout.reconfigure(line_buffering=True)

OUTPUT_FILE = "cmcc_bids.json"
KEYWORDS = ["数智化", "数据", "算力", "战略", "算网", "软件开发", "云智算", "DICT", "ICT", "业务支撑", "系统集成"]
BJT = timezone(timedelta(hours=8))
TODAY = os.environ.get("BIDDING_DATE") or datetime.now(BJT).strftime("%Y-%m-%d")

def scrape_table_deep(page, context, page_name, max_pages=50):
    """深度翻页抓取表格数据，不切子分类"""
    results = []
    page_num = 1
    today_count = 0
    seen_ids = set()  # 去重

    print(f"\n  开始深度抓取: {page_name} (最多{max_pages}页)")

    while page_num <= max_pages:
        print(f"    第{page_num}页...", end=" ")
        rand_sleep(3, 5)  # 增加等待时间

        # 等待表格加载完成（带重试）
        max_retries = 3
        rows = []
        for attempt in range(max_retries):
            rows = page.locator(".cmcc-table-row").all()
            if len(rows) > 0:
                break
            print(f"等待表格加载(重试{attempt+1})...", end=" ")
            rand_sleep(2, 3)
        
        if len(rows) == 0:
            # 最后一次检查是否真的没有数据
            page_content = page.content()
            if "暂无数据" in page_content or "cmcc-empty" in page_content:
                print("页面显示无数据")
            else:
                print("未找到表格数据（可能是JS未渲染）")
            break

        page_today = 0
        page_matched = 0
        
        for row in rows:
            try:
                cells = row.locator("td").all()
                if len(cells) < 4:
                    continue
                
                company = cells[0].inner_text().strip()
                bid_type = cells[1].inner_text().strip()
                title = cells[2].inner_text().strip()
                if title.startswith("NEW "):
                    title = title[4:]
                date_str = cells[3].inner_text().strip()

                # 只抓今天的
                if date_str != TODAY:
                    continue
                
                page_today += 1
                
                # 生成唯一ID去重
                row_id = f"{company}_{title[:30]}_{date_str}"
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)

                # 关键词过滤
                if KEYWORDS and not any(kw in title for kw in KEYWORDS):
                    continue
                
                page_matched += 1
                
                # 获取URL
                detail_url = ""
                try:
                    pages_before = len(context.pages)
                    row.click()
                    rand_sleep(2, 4)
                    if len(context.pages) > pages_before:
                        new_page = context.pages[-1]
                        detail_url = new_page.url
                        new_page.close()
                except:
                    pass

                results.append({
                    "platform": "移动",
                    "province": company,
                    "type": bid_type,
                    "company": company,
                    "title": title,
                    "url": detail_url or "https://b2b.10086.cn",
                    "date": date_str
                })
                
            except Exception as e:
                continue

        print(f"今日{page_today}条, 匹配{page_matched}条")
        today_count += page_today

        # 翻页
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            rand_sleep(2, 3)
            
            next_btn = page.locator(f".cmcc-page-item[title='{page_num + 1}']").first
            if next_btn.count() > 0:
                next_btn.click()
            else:
                next_arrow = page.locator(".cmcc-page-next").first
                if next_arrow.count() > 0 and "cmcc-page-disabled" not in (next_arrow.get_attribute("class") or ""):
                    next_arrow.click()
                else:
                    print(f"    已到最后一页")
                    break
            page_num += 1
        except Exception as e:
            print(f"翻页异常: {e}")
            break

    print(f"  {page_name} 完成: 今日{today_count}条, 匹配{len(results)}条 (翻了{page_num}页)")
    return results, today_count

def fetch_cmcc():
    print(f"=== 抓取移动招标 {datetime.now(BJT).strftime('%H:%M:%S')} ===")
    print(f"限定日期: {TODAY}")
    print(f"关键词: {' | '.join(KEYWORDS)}")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    ua = random.choice(UA_LIST)
    print(f"UA: {ua[:50]}...")
    context = browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=ua)
    page = context.new_page()

    all_results = []
    total_today_count = 0
    errors = []

    # ========== 第一个页面：招标采购公告（不切子分类，深度翻页） ==========
    print(f"\n{'='*60}")
    print("开始抓取: 招标采购公告")
    print(f"{'='*60}")

    try:
        page.goto("https://b2b.10086.cn/#/biddingProcurementBulletin", wait_until="networkidle", timeout=90000)
        rand_sleep(6, 10)  # 增加等待时间确保Vue渲染完成
        
        results, today_sub = scrape_table_deep(page, context, "招标采购公告", max_pages=50)
        all_results.extend(results)
        total_today_count += today_sub
        
    except Exception as e:
        print(f"  招标采购公告错误: {e}")
        errors.append(f"招标采购公告: {e}")

    # ========== 第二个页面：采购服务（不切子分类，深度翻页） ==========
    print(f"\n{'='*60}")
    print("开始抓取: 采购服务")
    print(f"{'='*60}")

    try:
        page.goto("https://b2b.10086.cn/#/procurementServices", wait_until="networkidle", timeout=90000)
        rand_sleep(6, 10)  # 增加等待时间确保Vue渲染完成
        
        results, today_sub = scrape_table_deep(page, context, "采购服务", max_pages=50)
        all_results.extend(results)
        total_today_count += today_sub
        
    except Exception as e:
        print(f"  采购服务错误: {e}")
        errors.append(f"采购服务: {e}")

    browser.close()
    playwright.stop()

    # 保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    with open("cmcc_status.json", 'w', encoding='utf-8') as f:
        json.dump({"errors": errors, "count": len(all_results)}, f, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"✅ 移动抓取完成: 今日{total_today_count}条, 匹配关键词{len(all_results)}条")
    print(f"{'='*60}")
    return len(all_results)

if __name__ == "__main__":
    fetch_cmcc()

