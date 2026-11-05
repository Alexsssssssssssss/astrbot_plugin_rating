# 雀魂 / 天凤 Rating 查询

基于仓库原有 AstrBot 插件模板，适用于 **AstrBot + OneBot v11 + NapCat**。收到牌谱链接后，按初始东、南、西、北四个座位串行提交 Mortal，返回每人的 Rating、一致率、匹配决策数和报告链接。

## 安装

将完整插件目录放在 AstrBot 的 `data/plugins/astrbot_plugin_rating` 中，`main.py`、`metadata.yaml`、`_conf_schema.json` 和 `mortal/` 必须保留在一起。

在 **AstrBot 实际使用的 Python 环境或容器内**安装依赖和浏览器：

```bash
python -m pip install -r data/plugins/astrbot_plugin_rating/requirements.txt
python -m playwright install chromium
```

Linux 缺少浏览器系统库时，按 Playwright 官方方式使用 `python -m playwright install --with-deps chromium`（需要系统安装权限）。已有系统 Chromium 的环境无需重复下载，插件会自动查找 `chromium` 或 `google-chrome`，也可通过 `CHROMIUM_PATH` 指定路径。

在 AstrBot 中配置 OneBot v11 适配器，让 NapCat 的 WebSocket 客户端连接面板提供的反向 WebSocket 地址，保持双方 access token 一致。先确认普通消息能够收发，再重载插件。插件不直接登录 QQ，不需要在插件配置里填写 QQ 密码。

## 使用

```text
/rating https://game.maj-soul.com/1/?paipu=实际牌谱ID
/rating https://tenhou.net/0/?log=实际牌谱ID
```

默认也识别直接发送、以链接开头的消息。只接受一个 HTTPS 牌谱链接，不支持短链接或 QQ 卡片内未展开的链接。支持雀魂国服、日服/国际服的常见牌谱域名和 `tenhou.net`。天凤链接中的 `tw` 仅代表观看座位，不影响逐座位分析。

群聊完成后会 @ 发起查询的人，私聊直接返回结果。是否需要先 @ 机器人唤醒，由 AstrBot 自身的会话设置决定。

返回形式（以下数值仅作格式示例）：

```text
牌谱分析结果
引擎: mortal
模型: 4.1b
玩家昵称: Rating: 74.35 一致率: 64.9 (48/74)
报告：
网站实际返回的报告链接
```

昵称取自报告中播放器的四人牌谱数据或明确的玩家名称字段；无法读取时显示东家、南家、西家、北家。Rating 来自 Mortal 的实际评分，不能由一致率推算。网站没有独立报告链接时明确标注，不拼接虚假的 JSON 地址。网站不支持的规则、三麻或无效牌谱不能保证分析成功。

## 插件设置

| 设置 | 默认值 | 作用 |
| --- | --- | --- |
| `auto_detect` | `true` | 自动识别直接发送的链接；关闭后使用 `/rating` |
| `cooldown_seconds` | `60` | 每名用户的提交间隔 |
| `max_pending` | `3` | 运行中与排队任务总数，实际限制为 1–20 |

同一插件实例只运行一组分析，避免同时打开大量浏览器。用户冷却跨群聊和私聊生效。遇到验证、限流或报告错误时停止后续座位并保留已成功结果。任务与冷却记录保存在内存中；重启不恢复未完成任务，卸载时取消任务并关闭浏览器。

可通过 **AstrBot 进程环境变量**设置浏览器适配参数：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `CHROMIUM_PATH` | 自动查找 | Chromium 可执行文件 |
| `MORTAL_MODEL_TAG` | `4.1b` | 官网支持的模型版本 |
| `MORTAL_INTERVAL` | `15` | 两次实际提交的最小间隔（秒） |
| `MORTAL_TIMEOUT` | `300` | 单座位提交后的报告等待时间（秒） |
| `MORTAL_VERIFICATION_TIMEOUT` | `15` | 等待网站正常验证回调的时间（秒） |
| `MORTAL_HEADLESS` | `1` | 无头运行；有桌面时可设为 `0` |
| `RATING_DATA_DIR` | `.data` | 报告归属异常时的本地诊断目录 |

模型版本按网站实际返回值显示。插件不自动加载 `.env`。默认不接入付费验证码服务，不绕过网站验证，也不关闭 TLS 校验。

## 网络和验证限制

需要能访问 `mjai.ekyu.moe`；其验证组件使用 `challenges.cloudflare.com`。用户提供的牌谱由 Mortal 网站获取，本插件不通过牌谱屋查询，因此不需要牌谱屋访问 token，也不需要 Mortal 模型权重。

Mortal 网站的人机验证可能阻止自动提交。插件会返回实际错误；在其他浏览器中通过验证不保证当前自动化浏览器会话也被放行。若网站限制自动访问，应遵守站方要求。本地模拟测试通过不代表已经取得真实线上评分。

## 开发验证

在插件目录执行：

```bash
python -m pip install -r requirements.txt
python -m pip install pytest==8.3.5 pytest-asyncio==0.26.0
python -m pytest -q
```

测试覆盖 URL 校验、报告身份、指标计算、四座位输出、排队限制、任务取消、AstrBot 消息接口和 Chromium 表单提交。外部网站响应与 AstrBot 消息接口使用测试替身；真实 QQ 收发和线上评分需要在你的 AstrBot/NapCat 环境联调。

入口为 `main.py`；`mortal/service.py` 组织分析与输出，`mortal/browser.py` 对接网站，`mortal/reports.py` 解析并校验报告。插件没有复制 mjai-reviewer 源代码，报告字段依据其公开模板核对。
