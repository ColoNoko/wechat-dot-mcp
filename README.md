# wechat-dot-mcp：微信接入 dot（中文使用教程）

把本人微信私聊连接到已有的 OpenAI dot：微信来信 → 本地桥接 → MCP Events → 原 dot 读取并回复 → 同一微信会话。

这是**公开的脱敏源码备份与部署模板**，不是微信官方产品，也不是模型 API 网关。只支持本人绑定的私聊；不把群聊、任意联系人主动群发或旧聊天记录迁移当作已有能力。

## 备份版本和限制

- 上游：[cd233ljx/wechat-dot-bridge](https://github.com/cd233ljx/wechat-dot-bridge)，固定提交 `67c726e15ae2de8b60d293d6f5e81107bd0b6ebc`。
- 本备份取自已交付源码包，不代表 NAS 当前运行目录，不能确认包含交付后的现场修改。详情见 [来源与许可](PROVENANCE.md)。
- 容器模板：Linux x86-64 / amd64、Python 3.11、官方 Tunnel v0.0.16。ARM 机器不要直接照搬。
- 本仓库只上传源码、锁文件、模板和测试；没有上传 Docker 镜像、运行密钥、微信绑定、聊天、状态库或私人日志。
- 原交付包曾进行容器与模拟测试。本公开版修改了路径与依赖准备方式；新的本地构建与真实微信闭环仍须按文末验收。上游文档中的历史验收不等于你的部署已验收。
- 代码和教程开源不等于整个链路免费；dot / ChatGPT 的正常用量、账号功能与服务限制仍适用。本桥接没有新增模型 API 调用。

## 0. 开始前准备

1. 已有可用的 dot，以及允许安装自定义 MCP 插件并使用 MCP Events 的账号/工作区。普通聊天不一定具备这些能力。
2. 自己的 OpenAI Platform 组织和对应权限；需要创建 Tunnel 时具有 Tunnels Read + Manage，使用 Tunnel 时具有 Read + Use。
3. Linux amd64 主机或 NAS，Docker Engine、Docker Compose v2；用于准备依赖的主机需 Git、Python 3.11 和 pip，可联网访问官方 GitHub、PyPI 和 Docker Hub。
4. 使用已有普通用户部署，知道其 UID/GID；不要为了教程新建特权用户或把状态目录设为 777。
5. 主机能通过出站 HTTPS 访问 OpenAI、微信服务及经核验的事件回调服务。不需要公网 IP、域名、端口映射或开放 MCP 入站端口。
6. 停止同一微信绑定的其他接收端，例如旧桥接、OpenClaw、cc-connect。一个绑定仅保留一个消费者。

## 1. 从零创建或申请 Tunnel

以下入口和权限依据 [OpenAI Secure MCP Tunnel 官方指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)、[官方 onboarding](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/onboarding.md) 与 [权限说明](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/permissions.md)。核对日期：2026-10-14。当前浏览器未登录 Platform，未代你创建 Tunnel 或密钥；页面按钮名称以你账号实际界面为准。

1. 登录 [Platform Tunnel 设置](https://platform.openai.com/settings/organization/tunnels)，先切换到实际要使用的 Platform 组织。个人使用选择属于自己账号的个人组织。
2. 如果显示无访问权限或没有创建入口，请组织所有者/RBAC 管理员在组织角色、组配置里授予 Tunnels Read + Manage；运行者另需 Read + Use。该权限是**组织级**，不是随便换一个项目就能解决。新角色可能需要最多 30 分钟传播。
3. 在 Tunnel 管理页点击 **Create tunnel**，按弹窗填写名称和说明，给 Tunnel 起一个自己能识别的名字，例如 `wechat-dot`；已有合适 Tunnel 时直接复用，避免无故重复创建。
4. 在关联组织/工作区配置中确认所属 Platform 组织，并关联**实际使用 dot 的 ChatGPT 上下文/工作区**。仅关联个人 Platform 组织不会自动让企业/教育工作区看到它。企业映射无法自动核验时请管理员联系 OpenAI，不要伪造组织 ID。
5. 创建后复制页面提供的真实 Tunnel ID，格式为 `tunnel_` 加 32 位小写十六进制字符。它不是 URL、API 密钥或微信 token。
6. 保持仅必要本人/工作区可用。公开本源码仓库不代表要公开你的 Tunnel 或私人微信插件。

若你的账号没有该功能或权限，先由管理员解决；不存在一个通用“免费申请 API”按钮能绕过账号限制。

## 2. 申请 Tunnel 运行 API Key

这里的 API 是 **Tunnel 运行密钥**，用于 `tunnel-client` 向 OpenAI Tunnel 服务认证。不要把它误认为需要另外购买、填写模型名称的聊天模型 API 配置；也不要把管理员密钥用于常驻服务。

1. 打开同一组织的 [Runtime API Keys 页面](https://platform.openai.com/settings/organization/api-keys)。使用页面提供的 **Create new secret key**（创建新密钥）入口，为本桥接单独创建一个有明确用途的密钥。
2. 如果页面提供权限模式，选择 Restricted/受限，并赋予 Tunnel 所需的 **Tunnels Read + Use**。密钥所属主体本身也必须有对应组织权限。不要为了排错改成无限制权限。
3. 密钥创建完成后，由你本人通过安全输入保存到下文的 `secrets/tunnel-runtime-key`。不要贴到聊天、GitHub、命令行参数、截图、README 或 `.env`。完整密钥通常只在创建时显示；遗失时按官方界面撤销并重新生成，不要猜测。
4. [Admin Keys](https://platform.openai.com/settings/organization/admin-keys) 面向管理操作，例如创建、列举、编辑、删除 Tunnel。本教程使用管理网页，不要求生成管理员密钥；常驻客户端用 Runtime Key。
5. 后续轮换：先停止桥接，按官方页面撤销/替换密钥，再由本人安全更新本地密钥文件，保持 `0600` 和正确所有者，重启并重新验收。

## 3. 获取源码、准备依赖与构建镜像

```bash
git clone https://github.com/ColoNoko/wechat-dot-mcp.git
cd wechat-dot-mcp
# 请在 Linux amd64 + Python 3.11 环境执行：
python3.11 --version
sh prepare-vendor.sh
docker pull python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d
sh build.sh
```

`prepare-vendor.sh` 从锁文件下载带哈希校验的 Python wheels，并从 OpenAI 官方 GitHub 下载 Tunnel v0.0.16，核对固定 SHA256 后解压。二进制放入被 Git 忽略的 `vendor/`。构建步骤使用 `--network none`，不会临时重新解析依赖。

本模板不包含 Node/SILK/FFmpeg 可选编解码器；任意音频转换不保证可用。上游源码保留完整相关功能，详见 `source/docs/`。

准备你的**新部署目录**，例如 `/srv/wechat-dot-mcp`。这个路径只是公开示例，应替换成自己 NAS 的实际绝对目录，并确保当前已有普通用户可读写。你可以把克隆仓库直接放到该目录。以下命令均在该仓库根目录执行。

```bash
id -u
id -g
pwd
```

如果 UID 是 0，先切换已有普通用户。目录已存在 `config/`、`state/`、`secrets/` 或 `.env` 时不要重新初始化。容器通过 stdio 与桥接通信，不提供独立 HTTP MCP 端口。

## 4. 手动填写 Tunnel ID 和运行密钥

在你自己的 OpenAI 界面确认已经有仅供本人使用的 Tunnel，正确关联个人 ChatGPT 上下文，并具备 Tunnel 和开发者插件/Events 权限。把下面占位符换成控制台实际给出的 `tunnel_` 加 32 位十六进制 ID。该命令只创建本地私有目录和配置，不创建 Tunnel、不启用接收：

```bash
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  -v "$PWD:/setup" --entrypoint python \
  wechat-dot-bridge:67c726e-tunnel0.0.16-amd64 \
  /opt/container/init_config.py '替换为你的实际Tunnel_ID'
```

生成 `.env`、`config/bridge.json`、`config/tunnel.yaml`、`state/`、`secrets/`。**必须编辑 `.env`，把 `WDB_ROOT=REPLACE_WITH_ABSOLUTE_DEPLOYMENT_DIRECTORY` 替换为当前部署目录的真实绝对路径（与 `pwd` 一致）。**检查 `.env` 中 `PUID` / `PGID` 是该现有用户的数字 UID/GID。容器不创建用户，不以 root 运行。`tunnel.yaml` 使用合法的 JSON 形式 YAML，保持这种格式；除了 Tunnel ID 不需要修改它。配置模板的精确结构由启动器校验。

通过以下交互隐藏输入，将你自己的 Tunnel **运行密钥**写入文件；不要把密钥放进聊天、命令参数、环境变量、截图或 `.env`：

```bash
docker run --rm -it --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  -v "$PWD/secrets:/secrets" --entrypoint python \
  wechat-dot-bridge:67c726e-tunnel0.0.16-amd64 \
  /opt/bridge/scripts/save_runtime_key.py --path /secrets/tunnel-runtime-key
```

密钥文件由上游工具创建为 `0600`，目录为 `0700`，不覆盖已有文件。正式服务只读挂载 `secrets/`，密钥通过 `file:/run/secrets/tunnel-runtime-key` 读取，不嵌入镜像。配置文件也必须为当前 UID 所有且为 `0600`；`state/` 必须为该 UID 所有且为 `0700`。不要使用符号链接、硬链接或 `chmod 777` 处理权限错误。

## 5. 在暂停状态扫码绑定

**先停止所有旧收信程序**，包括其他机器上的 OpenClaw、cc-connect 或旧桥接。同一微信绑定只能有一个消费者。以下步骤先不启动常驻服务：

```bash
docker compose run --rm --no-deps bridge bridge status
docker compose run --rm --no-deps bridge bridge login-start
docker compose run --rm --no-deps bridge qr
```

第一条命令预期 `bound:false`、`enabled:false`。二维码生成到宿主 `state/weixin-login-qr.png`。仅通过可信的 NAS 文件访问或 SSH 查看，用微信扫码确认；不要公开分享 PNG 或 `state/`。然后：

```bash
docker compose run --rm --no-deps bridge bridge login-poll
```

如返回需要手机验证码，运行交互版本：

```bash
docker compose run --rm --no-deps bridge bridge login-poll --verification-code
```

等待时可再次 `login-poll`。二维码过期时重新 `login-start`；确认旧 PNG 不再使用后删除旧 PNG，再运行 `qr`。确认成功后凭据写入 `state/bridge.sqlite3`，**接收仍暂停**。新扫码可能对应新的微信机器人/会话，不能保证保留旧入口。

## 6. 启动私人 Tunnel、接入同一个 dot

```bash
docker compose config --quiet
docker compose up -d
docker compose exec bridge python /opt/container/entrypoint.py check
```

检查 `key_ready`、`tunnel_healthy`、`tunnel_ready`。首次连接前，`ready:false` 不应通过扩大权限或开放端口来修复。`healthy` 只表示进程健康，不能代表微信闭环成功；健康检查也不会自动重启不健康容器。

打开 [ChatGPT Plugins](https://chatgpt.com/plugins)，使用当前账号提供的自定义 MCP/开发者插件创建入口；旧版客户端可能在设置的 Connectors/连接器中。创建仅自己使用的开发者插件，Connection 选择真实的 Tunnel，按上游说明使用私人 Tunnel 访问控制及 No authentication。不要分享或发布插件。检查插件显示的权限/风险提示后完成 **Create as a plugin**（创建为插件），把它添加到**原来的同一个 dot**；应发现 11 个工具及 `weixin.message`。

`callback_hosts` 初始为空。先在该 dot 请求订阅 `weixin.message`，第一次订阅会被拒绝。调用 `get_weixin_status` 查看 `events.observed_callback_host`，通过 OpenAI 可信界面/官方来源独立核验该**精确主机名**。确认后：

```bash
docker compose stop
```

在 NAS 上编辑 `config/bridge.json`，保留 `state_dir` 与 `lock_dir`，仅把 `callback_hosts` 改为 1–3 个已核验的小写 hostname。不能填写通配符、URL、路径、端口或 IP；不能直接信任聊天里给出的回调主机。保存后保持 `0600`，再：

```bash
docker compose up -d
```

回到**同一个原 dot**重新订阅 `weixin.message`，由平台提供 callback URL 和签名 secret，并完成 challenge。不要手写或在聊天索取订阅 secret。确认 `active_subscriptions:1`；避免在第二个聊天里订阅。需要长期订阅时由原 dot 显式请求 `ttlMs:null` 并确认 `refreshBefore:null`，同时确认平台任务仍启用。

给 dot 的工作要求：收到事件后先 `read_weixin_message(message_id)`，再向该来信 `reply_weixin_message`，最后 `get_weixin_send_status`。同一次发送使用稳定 `reply_key`；`uncertain` 时先人工核对微信，不自动重发。

## 7. 确认唯一消费者后恢复

只有在旧服务全部停止、仅有原 dot 的一个订阅、本人绑定确认无误后，才执行：

```bash
docker compose stop
docker compose run --rm --no-deps bridge bridge resume --confirm-single-consumer
docker compose up -d
```

最后从本人微信私聊发送一条唯一标记的短文字，确认原 dot 收到事件、读取同一消息并回复，再在**同一个微信对话**确认仅收到一次。`accepted` 仅表示 API 接受，并不等于实际投递或已读。云端模拟测试不能替代这一步真人验收。

## 日常操作与恢复

安全状态：`docker compose exec bridge python /opt/container/entrypoint.py bridge status`。日志默认抑制 Tunnel 运行日志，启动校验只输出固定错误类别。错误例：`config_missing`、`key_missing`、`unsafe_key_file`、`tunnel_id_invalid`。不要通过打印完整密钥、SQLite、回调 URL 来诊断。

暂停收发：先 `docker compose stop`，再 `docker compose run --rm --no-deps bridge bridge pause`。取消 dot 订阅只停止事件通知；要停止微信收发还需暂停桥接。正式服务的停止命令为 `docker compose stop`，有 45 秒宽限期；不要使用 `kill -9` 作常规停止。

备份：停止服务后，完整备份 `config/`、`secrets/` 和 `state/`，保留权限和所有者；这些目录包含私有登录状态与消息，不要放进公共备份或源码包。恢复时保持唯一消费者，不同时运行旧实例。发送状态 `uncertain` 必须人工核对，程序不会自动重发。

默认限制为 1 CPU、768 MiB 内存、128 PID、64 MiB 临时空间；容器根只读、移除全部 capabilities、禁止新增权限，`unless-stopped` 重启策略。NAS 重启后 Docker 自行恢复服务；手动停止的容器保持停止。`state/` 的磁盘占用不受内存限制，需要自行留意 NAS 剩余空间。

本容器模板未装可选 Node 24 / SILK / FFmpeg。普通文字已测试；Markdown 使用上游降级路径，任意音频转换未验收。已有图片/文件相关上游 Python 依赖随锁文件安装，但此公开备份没有进行新的真实微信媒体验收，不承诺媒体转换完整可用。

## 8. 发给原 dot 的订阅指令

在添加私人插件的**原 dot**中发送：

> 请订阅我添加的私人微信插件的 `weixin.message` 事件。收到事件后，用 `read_weixin_message` 读取相同 message_id，理解后用 `reply_weixin_message` 回复同一来信，并用 `get_weixin_send_status` 检查结果。进度回复用 final:false，完成回复用 final:true；同一次发送使用稳定 reply_key。uncertain 时不要自动重发，先请我核对微信。不要新建助手，不处理群聊，不发送没有原来信的主动消息。需要长期订阅时显式请求 ttlMs:null，并确认 refreshBefore:null；不要创建第二份订阅。

首次 callback 白名单拒绝是安全设计，按第 6 节核验精确 hostname 后再订阅。callback URL 与签名 secret 由平台自动提供，不需要你“申请 webhook API”或手写 secret。平台任务是否启用、任务期限，与桥接侧订阅期限是不同事项。

## 9. 测试与验收清单

### 本地回归

```bash
# 从仓库根目录运行；仅使用合成数据：
sh run-tests.sh
# 上游完整回归（需已安装 uv，首次可能下载依赖）：
cd source
uv sync --locked --no-dev --all-extras
uv run --locked --no-dev --all-extras python -m unittest discover -s tests -v
```

测试产生的 `test-work/` 与 `evidence/` 不应上传到公开仓库。不要将测试状态复制到生产目录。

### 真人闭环

- Tunnel 客户端健康且 ready，保持后台运行。
- 插件发现 11 个工具和 `weixin.message`，状态查询成功。
- 原 dot 中只有一个有效订阅，callback challenge 已通过。
- 绑定正确、唯一消费者确认后恢复接收。
- 本人微信私聊发一条独特短文字；原 dot 读到相同 ID 并回复。
- `accepted` 只表示 API 接受；由本人在微信同一对话确认实际只出现一次回复。
- 图片、小文件、语音、视频逐项单独测试；没有读取成功的内容不能声称已理解。

以上任何阶段失败，都不能用“Tunnel 已启动”代替完整验收。

## 10. 常见问题排查

| 现象 | 检查与处理 |
| --- | --- |
| 没有 Tunnel 创建入口 | 确认组织与组织级 Read + Manage 权限；请管理员处理，等待权限传播 |
| ChatGPT 找不到 Tunnel | 关联目标 ChatGPT 工作区；核验操作者 Read + Use 和自定义插件权限 |
| 401/403、运行不就绪 | 核验 Runtime Key 所属组织、Read + Use、是否撤销；不要换成 Admin Key 或公开密钥 |
| `config_missing` / `key_missing` | 核验 WDB_ROOT 绝对目录、配置和密钥文件存在、挂载正确 |
| `unsafe_key_file` | 检查普通用户 UID/GID、密钥 0600、目录 0700；拒绝符号/硬链接，不用 chmod 777 |
| `tunnel_id_invalid` | 使用控制台真实 ID，不使用 URL；格式 tunnel_ + 32 位小写十六进制 |
| 二维码过期 | 停止旧接收端，重新 login-start；安全处理旧 PNG 后重新 qr；不要公开二维码 |
| 已登录却没来信 | 确认 resume、唯一消费者、当前微信绑定、原 dot 有效订阅及回调状态 |
| callback 被拒绝 | 只独立核验并批准精确 hostname；不填 URL/IP/通配符，不关闭 TLS 校验 |
| 有工具无自动事件 | 客户端/工作区需支持 MCP Events；协议 2026-07-28；在原 dot 明确订阅 |
| 订阅一小时后停止 | 省略 ttlMs 使用默认有限期限；明确 ttlMs:null 后确认 refreshBefore:null，也检查平台任务 |
| 回复 `queued` | 查询相同 reply_id 的发送状态，不靠重复提交等待 |
| 回复 `uncertain` | 人工核对微信；不要自动重试可能已发送的那一次 |
| 插件显示新工具、原 dot 仍旧 | 先刷新工具定义和客户端状态，必要时重启客户端；保留原 dot 和唯一订阅 |
| 构建依赖下载失败 | 检查 Python 3.11、amd64、网络及锁文件哈希；不要关闭哈希/TLS 或换不明镜像 |
| NAS 上只有旧镜像 | 本仓库不上传预构建镜像，须按第 3 节本地构建并确认标签 |

更详细的能力、操作与安全边界见 [上游安装指南](source/docs/INSTALL.md)、[dot 接入](source/docs/DOT_SETUP.md)、[运维](source/docs/OPERATIONS.md)、[安全](source/docs/SECURITY.md)。

## 官方参考

- [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Tunnel v0.0.16 下载](https://github.com/openai/tunnel-client/releases/tag/v0.0.16)
- [Tunnel v0.0.16 onboarding](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/onboarding.md)
- [Tunnel v0.0.16 权限](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/permissions.md)
- [MCP Events](https://developers.openai.com/plugins/build/mcp-events)

请勿在 Issue 上传密钥、二维码、微信账号标识、聊天正文、SQLite 数据库、完整 callback URL、私人目录或未经审查的日志。
