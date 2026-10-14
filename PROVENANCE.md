# 来源与备份范围

- 上游：https://github.com/cd233ljx/wechat-dot-bridge
- 固定提交：`67c726e15ae2de8b60d293d6f5e81107bd0b6ebc`
- 来源：已交付的源码与容器部署包；本仓库不是 NAS 当前运行目录的镜像，不声称包含交付之后的现场修改。
- `source/` 保留上游源码、测试、文档、MIT 许可及第三方声明；不移植原仓库 Git 历史。
- `container/`、集成测试与部署模板来自交付包。公开版移除了专用 NAS 目录，改由操作者填写绝对路径。
- 新增中文总教程及联网准备依赖脚本；镜像仍使用固定的基础镜像和哈希锁定的 Python 依赖。
- 不包含运行密钥、微信绑定、SQLite 数据库、聊天记录、二维码、运行状态、原部署日志、预构建镜像或第三方二进制。
- Tunnel 固定 v0.0.16 / linux-amd64，下载后核对 SHA256。构建出的镜像须由操作者本地保存，本仓库不托管镜像。
- 上游历史验收文档仅表示上游当时的结果，不能作为本仓库新部署的微信真人验收结论。

## 许可

上游源码遵循 MIT，作者版权见 [LICENSE](LICENSE)，完整声明见 [source/NOTICE.txt](source/NOTICE.txt) 与 [source/licenses](source/licenses)。Tunnel 与其捆绑组件使用各自许可，准备依赖时保留下载包中的许可文件。
