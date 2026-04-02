#!/usr/bin/env python3
"""
整合推送脚本
读取 cmcc_bids.json 和 unicom_bids.json，合并推送到飞书
"""

import json
import os
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List

import requests

# 北京时间
BJT = timezone(timedelta(hours=8))

def now_bjt():
    return datetime.now(BJT)

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/3f57d6e3-20d7-4511-bb85-695352fbd651")
PUSHED_RECORDS_FILE = "pushed_bids_combined.json"
KEYWORDS = ["数智化", "数据", "算力", "战略"]


def load_pushed_records() -> Dict:
    if os.path.exists(PUSHED_RECORDS_FILE):
        try:
            with open(PUSHED_RECORDS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"hashes": [], "urls": []}


def save_pushed_records(records: Dict):
    with open(PUSHED_RECORDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False)


def get_bid_hash(title: str) -> str:
    return hashlib.md5(title.strip()[:50].encode('utf-8')).hexdigest()


def is_bid_pushed(title: str, url: str, records: Dict) -> bool:
    bid_hash = get_bid_hash(title)
    if bid_hash in records.get("hashes", []):
        return True
    if url in records.get("urls", []):
        return True
    return False


def mark_bid_pushed(title: str, url: str, records: Dict):
    bid_hash = get_bid_hash(title)
    if "hashes" not in records:
        records["hashes"] = []
    if "urls" not in records:
        records["urls"] = []
    if bid_hash not in records["hashes"]:
        records["hashes"].append(bid_hash)
    if url not in records["urls"]:
        records["urls"].append(url)


def load_bids():
    """加载三个抓取结果文件"""
    cmcc_bids = []
    unicom_bids = []
    telecom_bids = []
    
    try:
        with open("cmcc_bids.json", 'r', encoding='utf-8') as f:
            cmcc_bids = json.load(f)
    except:
        print("⚠️ 未找到移动招标数据")
    
    try:
        with open("unicom_bids.json", 'r', encoding='utf-8') as f:
            unicom_bids = json.load(f)
    except:
        print("⚠️ 未找到联通招标数据")
    
    try:
        with open("telecom_bids.json", 'r', encoding='utf-8') as f:
            telecom_bids = json.load(f)
    except:
        print("⚠️ 未找到电信招标数据")
    
    return cmcc_bids, unicom_bids, telecom_bids


def send_combined_message(cmcc_bids: List[Dict], unicom_bids: List[Dict], telecom_bids: List[Dict]) -> bool:
    """发送整合消息到飞书"""
    
    # 去重过滤
    records = load_pushed_records()
    
    cmcc_new = [b for b in cmcc_bids if not is_bid_pushed(b["title"], b["url"], records)]
    unicom_new = [b for b in unicom_bids if not is_bid_pushed(b["title"], b["url"], records)]
    telecom_new = [b for b in telecom_bids if not is_bid_pushed(b["title"], b["url"], records)]
    
    total = len(cmcc_new) + len(unicom_new) + len(telecom_new)
    
    if total == 0:
        print("\n没有新消息需要推送")
        return True
    
    # 使用飞书富文本格式（post），确保URL作为超链接完整传递
    content_lines = []  # 飞书post格式的content数组
    
    # 标题统计行
    content_lines.append([{"tag": "text", "text": f"📅 {now_bjt().strftime('%Y-%m-%d %H:%M')}\n📊 共 {total} 条新公告（移动{len(cmcc_new)} | 联通{len(unicom_new)} | 电信{len(telecom_new)}）"}])
    content_lines.append([{"tag": "text", "text": ""}])
    
    def add_section(bids, emoji, platform_name):
        if not bids:
            return
        content_lines.append([{"tag": "text", "text": f"{'─'*18}\n{emoji} {platform_name}招标信息\n{'─'*18}"}])
        content_lines.append([{"tag": "text", "text": ""}])
        for i, bid in enumerate(bids, 1):
            content_lines.append([{"tag": "text", "text": f"【{bid['province']}-{bid['type']}-{i}】\n日期：{bid['date']}\n标题：{bid['title']}"}])
            content_lines.append([{"tag": "text", "text": "链接："}, {"tag": "a", "text": "点击查看详情", "href": bid['url']}])
            content_lines.append([{"tag": "text", "text": ""}])
    
    add_section(cmcc_new, "📱", "中国移动")
    add_section(unicom_new, "🌐", "中国联通")
    add_section(telecom_new, "📞", "中国电信")
    
    content_lines.append([{"tag": "text", "text": f"{'─'*18}\n来源: 移动·联通·电信采购网 | 更新: {now_bjt().strftime('%H:%M')}"}])
    
    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"📢 运营商招标信息汇总（{total}条）",
                    "content": content_lines
                }
            }
        }
    }
    
    try:
        response = requests.post(
            FEISHU_WEBHOOK,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        result = response.json()
        if result.get("code") == 0:
            print(f"\n✅ 成功推送 {total} 条消息到飞书")
            # 更新推送记录
            for bid in cmcc_new + unicom_new + telecom_new:
                mark_bid_pushed(bid["title"], bid["url"], records)
            save_pushed_records(records)
            return True
        else:
            print(f"\n❌ 推送失败: {result}")
            return False
    except Exception as e:
        print(f"\n❌ 推送异常: {e}")
        return False


def is_workday():
    """判断今天是否是工作日（周一到周五）"""
    return now_bjt().weekday() < 5  # 0=周一, 4=周五


def send_alert(problems: list):
    """工作日抓取异常时推送告警到飞书"""
    now = now_bjt()
    content_lines = [
        [{"tag": "text", "text": f"⏰ {now.strftime('%Y-%m-%d %H:%M')} ({['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]})"}],
        [{"tag": "text", "text": ""}],
    ]
    for p in problems:
        content_lines.append([{"tag": "text", "text": f"❌ {p}"}])
    content_lines.append([{"tag": "text", "text": ""}])
    content_lines.append([{"tag": "text", "text": "请检查对应抓取脚本或目标网站是否有变化。\n如连续多次告警，可能需要排查反爬或接口变更。"}])

    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"⚠️ 商机抓取异常告警（{len(problems)}项）",
                    "content": content_lines
                }
            }
        }
    }
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=payload,
                             headers={"Content-Type": "application/json"}, timeout=30)
        result = resp.json()
        if result.get("code") == 0:
            print(f"⚠️ 告警已推送（{len(problems)}项问题）")
        else:
            print(f"⚠️ 告警推送失败: {result}")
    except Exception as e:
        print(f"⚠️ 告警推送异常: {e}")


def main():
    print(f"=== 整合推送开始 {now_bjt().strftime('%Y-%m-%d %H:%M:%S')} ===")
    
    cmcc_bids, unicom_bids, telecom_bids = load_bids()
    print(f"\n加载数据:")
    print(f"  移动: {len(cmcc_bids)} 条")
    print(f"  联通: {len(unicom_bids)} 条")
    print(f"  电信: {len(telecom_bids)} 条")
    
    # 检查抓取错误（读取各脚本的状态文件）
    problems = []
    for name, label in [("cmcc", "移动"), ("unicom", "联通"), ("telecom", "电信")]:
        status_file = f"{name}_status.json"
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
                for err in status.get("errors", []):
                    problems.append(f"{label}: {err}")
        except FileNotFoundError:
            problems.append(f"{label}: 状态文件缺失（脚本可能未运行或崩溃）")
        except Exception as e:
            problems.append(f"{label}: 状态文件读取异常 ({e})")
    
    if problems:
        print(f"\n⚠️ 检测到 {len(problems)} 项错误")
        send_alert(problems)
    
    send_combined_message(cmcc_bids, unicom_bids, telecom_bids)
    
    print(f"\n=== 整合推送完成 {now_bjt().strftime('%Y-%m-%d %H:%M:%S')} ===")


if __name__ == "__main__":
    main()
