# 运营商招标信息监控

自动抓取中国移动、中国联通、中国电信的招标公告，筛选关键词后推送到飞书。

## 功能特点

- **三大运营商全覆盖**：移动、联通、电信招标信息一网打尽
- **智能关键词过滤**：数智化、数据、算力、战略等核心关键词
- **去重推送**：基于标题哈希和URL双重去重，避免重复推送
- **双模式抓取**：API拦截优先 + DOM降级，确保抓取稳定性
- **异常告警**：抓取失败时自动推送告警到飞书
- **云端部署**：GitHub Actions 定时运行，无需本地维护

## 运行时间

- **工作日**：8:30 - 17:30，每30分钟运行一次
- **手动触发**：支持通过 GitHub Actions 手动运行

## 项目结构

```
.
├── .github/workflows/bidding-monitor.yml  # GitHub Actions 配置
├── fetch_cmcc.py                          # 中国移动招标抓取
├── fetch_unicom.py                        # 中国联通招标抓取
├── fetch_telecom.py                       # 中国电信招标抓取
├── push_combined.py                       # 整合推送脚本
├── requirements.txt                       # Python 依赖
└── README.md                              # 项目说明
```

## 配置说明

### 1. 飞书 Webhook 配置

在 GitHub 仓库的 **Settings > Secrets and variables > Actions** 中添加：

| Secret 名称 | 说明 |
|------------|------|
| `FEISHU_WEBHOOK` | 飞书机器人的 Webhook URL |

获取方式：飞书群设置 → 添加机器人 → 自定义机器人 → 复制 Webhook 地址

### 2. 关键词配置

如需修改关键词，编辑各 `fetch_*.py` 文件中的 `KEYWORDS` 列表：

```python
KEYWORDS = ["数智化", "数据", "算力", "战略", "算网", "软件开发", "云智算", "DICT", "ICT", "业务支撑", "系统集成"]
```

### 3. 定时频率调整

编辑 `.github/workflows/bidding-monitor.yml` 中的 `schedule` 部分：

```yaml
schedule:
  - cron: '30 0-9 * * 1-5'  # 工作日每30分钟
```

Cron 格式说明：
- `30` 分钟（UTC时间，北京时间需减8小时）
- `0-9` 小时（UTC 0-9点 = 北京 8-17点）
- `1-5` 星期（周一到周五）

## 本地测试

```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium

# 运行单个抓取脚本
python fetch_cmcc.py
python fetch_unicom.py
python fetch_telecom.py

# 运行推送（需设置环境变量）
export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/..."
python push_combined.py
```

## 数据源

| 运营商 | 数据源 URL |
|-------|-----------|
| 中国移动 | https://b2b.10086.cn |
| 中国联通 | https://www.chinaunicombidding.cn |
| 中国电信 | https://caigou.chinatelecom.com.cn |

## 技术实现

### 抓取策略

1. **API 拦截模式**：监听页面网络请求，直接获取结构化数据
2. **DOM 降级模式**：API 失败时，通过浏览器自动化读取页面内容
3. **Vue 数据提取**：电信网站直接从 Vue 组件状态中提取底层数据

### 去重机制

- **标题哈希**：MD5(title[:50]) 作为主键
- **URL 去重**：已推送的 URL 不再推送
- **持久化存储**：`pushed_bids_combined.json` 保存在仓库中

### 错误处理

- 单运营商抓取失败不影响其他运营商
- 推送脚本检查各运营商状态文件，异常时发送告警
- 所有错误记录到 `*_status.json` 文件

## License

MIT

