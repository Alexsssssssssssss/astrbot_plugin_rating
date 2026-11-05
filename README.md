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
| `captcha_provider` | `manual` | 改成 `2captcha` 后启用付费 Turnstile 求解 |
| `twocaptcha_api_key` | 空 | 2Captcha API Key，仅在管理面板填写 |
| `twocaptcha_proxy` | 空 | 可选 HTTP 代理，例如 `http://127.0.0.1:7890` |
| `twocaptcha_request_timeout` | `30` | 单次网络请求超时秒数，范围 5–120 |
| `twocaptcha_timeout` | `180` | 验证任务等待秒数，范围 10–600 |
| `twocaptcha_max_tasks` | `4` | 每份牌谱最多创建的付费任务，范围 1–4 |

同一插件实例只运行一组分析，避免同时打开大量浏览器。用户冷却跨群聊和私聊生效，同一用户不能重复排入正在进行的查询。遇到验证、限流或报告错误时停止后续座位并保留已成功结果。任务与冷却记录保存在内存中；重启不恢复未完成任务，卸载时取消任务并关闭浏览器。

## 进度与取消（v1.2.0）

插件会发送当前座位、打开网站、2Captcha 创建/等待/返回结果、提交分析及等待报告等阶段。每个座位完成后立即发送该座位评分，最后再汇总。阶段没有变化时默认每 30 秒发送当前阶段和已用时间，避免长时间没有反馈。

- `/rating_cancel`：取消自己当前的查询，停止继续分析和创建验证任务；已经创建的 2Captcha 任务仍可能计费。
- `progress_interval`：等待时的进度间隔，默认 30 秒（范围 10–120）。
- `seat_timeout`：单座位总等待上限，默认 360 秒，包括验证码与报告等待。
- `analysis_timeout`：整份牌谱等待上限，默认 900 秒，包括排队时间；超时会保留已完成结果，随后清理浏览器。

收到“2Captcha 已创建任务，正在等待求解”表示创建 API 已成功；收到“接收分析报告”表示程序已点击提交并开始等待 Mortal 报告，尚不等于分析成功。若长时间卡在同一阶段，将该条进度或最终错误交给管理员排查，不要重复发送牌谱。

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

模型版本按网站实际返回值显示。插件不自动加载 `.env`。默认不调用付费验证服务，TLS 校验始终开启。

## 2Captcha 接入（v1.1.0）

1. 更新插件到 v1.1.0，在 AstrBot 插件设置中将 `captcha_provider` 选为 `2captcha`。
2. 在 `twocaptcha_api_key` 中填写自己的 2Captcha API Key，保存并重载插件。不要把密钥发到群聊。也可设置 AstrBot 进程环境变量 `TWOCAPTCHA_API_KEY`，环境变量优先。
3. 确认账户有余额、AstrBot 能通过 HTTPS 访问 `api.2captcha.com`，再发送 `/rating 牌谱链接`。

只有 Mortal 的提交按钮仍被验证禁用时才调用 2Captcha。插件读取当前页面实际的 Turnstile sitekey、action、cData/chlPageData，提交 `TurnstileTaskProxyless` 任务，并将返回 token 交给网站原有回调；网站启用提交按钮后才继续提交牌谱。不会硬改按钮状态来假装验证成功。

每个座位最多求解一次，每份牌谱默认最多四次；创建任务失败或响应不明时不会自动重复创建。账户余额不足、超时、缺少回调或网站不接受结果时，停止后续座位并返回原因。取消或超时不会保证退费，已创建的任务仍可能产生费用。`twocaptcha_max_tasks=1` 可将每份牌谱的付费任务上限降为一次，但后续座位如再次要求验证会停止。

已通过模拟 API 与真实 Chromium 的回调提交流程测试；未使用真实 API Key 进行付费线上验证，不能保证站点接受每次求解结果。

### 请求失败排查（v1.1.1）

v1.1.1 会区分创建任务失败与查询结果失败，显示连接超时、读取超时、代理故障、HTTP 状态、无效 JSON 或 TLS 证书校验错误，不输出 API Key、代理密码或接口响应正文。

若 AstrBot 所在网络需要代理，在插件设置的“2Captcha HTTP 代理”填写实际 HTTP 代理地址。插件无法自动读取另一个应用或 AstrBot 面板中的代理设置；留空时沿用进程的 `HTTP_PROXY`/`HTTPS_PROXY` 等标准环境设置。`http://127.0.0.1:7890` 只是格式示例，应改成你实际的 HTTP 代理端口，且本机地址指 AstrBot 所在的电脑/容器。单次请求较慢时可将“2Captcha 单次网络请求超时”调为 `60`，这与验证码求解等待时间不同。

如果返回 `ERROR_KEY_DOES_NOT_EXIST` 或 `ERROR_ZERO_BALANCE` 等服务错误，按对应账户问题处理；出现连接失败不等于密钥或余额有问题。先查看 2Captcha 账户任务记录，避免对可能已创建的任务重复付费。

## 网络和验证限制

需要能访问 `mjai.ekyu.moe`；其验证组件使用 `challenges.cloudflare.com`。用户提供的牌谱由 Mortal 网站获取，本插件不通过牌谱屋查询，因此不需要牌谱屋访问 token，也不需要 Mortal 模型权重。

Mortal 网站的人机验证可能阻止自动提交。可按上节配置 2Captcha，插件会返回实际错误；在其他浏览器中通过验证不保证当前自动化浏览器会话也被放行。若网站限制自动访问，应遵守站方要求。本地模拟测试通过不代表已经取得真实线上评分。

## 开发验证

在插件目录执行：

```bash
python -m pip install -r requirements.txt
python -m pip install pytest==8.3.5 pytest-asyncio==0.26.0
python -m pytest -q
```

测试覆盖 URL 校验、报告身份、指标计算、四座位输出、排队限制、任务取消、AstrBot 消息接口和 Chromium 表单提交。外部网站响应与 AstrBot 消息接口使用测试替身；真实 QQ 收发和线上评分需要在你的 AstrBot/NapCat 环境联调。

入口为 `main.py`；`mortal/service.py` 组织分析与输出，`mortal/browser.py` 对接网站，`mortal/reports.py` 解析并校验报告。插件没有复制 mjai-reviewer 源代码，报告字段依据其公开模板核对。
