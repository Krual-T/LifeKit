# 本机 RustFS 对象存储

这是可选的 Linux 单机单实例部署入口，固定使用 RustFS 1.0.3 和用户 systemd 服务 `lifekernel-rustfs.service`。已有 S3 兼容存储时可直接配置 [`object_store.py`](../object_store.py)，无需安装本机 RustFS。

## 安装与初始化

准备 Python 3.11+、uv 和可用的 systemd 用户会话。按[官方单盘安装说明](https://docs.rustfs.com/en/installation/linux/single-node-single-disk)选择适合主机架构的 [1.0.3 官方发布包](https://github.com/rustfs/rustfs/releases/tag/1.0.3)，自行下载包含 `rustfs` 可执行文件的 ZIP。

在私人实例仓库根目录运行：

```bash
python3 scripts/rustfs/setup_local.py /absolute/path/rustfs-linux-x86_64-gnu-v1.0.3.zip
systemctl --user daemon-reload
systemctl --user enable --now lifekernel-rustfs.service
uv run scripts/object_store.py init
```

安装器只部署二进制、生成首次配置并复制服务文件，不下载、不启动服务。已有二进制和配置保持原样，已有服务文件与随附版本不同则停止，先比较后再决定是否更新。启用服务会占用本机 9000、9001 端口；首次 `uv run` 会准备脚本声明的 boto3 依赖。

| 内容 | 默认位置 |
| --- | --- |
| S3 endpoint / bucket | `http://127.0.0.1:9000` / `lifekernel` |
| 控制台 | `http://127.0.0.1:9001/rustfs/console/` |
| 健康入口 | `http://127.0.0.1:9000/health` |
| 客户端配置 | `~/.config/lifekernel/object-storage.json` |
| 凭据与服务参数 | `~/.config/lifekernel/rustfs.env`，权限 600 |
| 持久卷 | `~/.local/share/lifekernel/rustfs/volumes/` |
| 服务文件 | `~/.config/systemd/user/lifekernel-rustfs.service` |

这些运行文件留在主机上；凭据和内部卷不得进入 Git。客户端配置含 `endpoint`、`region`、`bucket`、`credentials_file`，自定义位置通过 `object_store.py --config PATH` 指定。凭据文件沿用 `RUSTFS_ACCESS_KEY`、`RUSTFS_SECRET_KEY` 字段；不要将其内容复制到 Wiki、终端日志或报告。

若 SSH 会话没有继承用户 bus，使用当前用户的 `/run/user/<UID>` 和对应 `bus` 地址配置 `XDG_RUNTIME_DIR`、`DBUS_SESSION_BUS_ADDRESS`。需要退出登录后继续运行时，由主机管理员按实际需要配置 linger；安装器不会修改这一设置。

## 读取、归档与导出

对象 key 沿用 `data/...` 命名，与本地是否存在同名文件无关。Wiki 正文与 `sources[].resource` 引用同一 `s3://<bucket>/<key>`，固定历史版本时保留 `?versionId=...`。工具返回的 URI 已处理路径编码，可直接使用。

```bash
uv run scripts/object_store.py put /absolute/path/file data/wiki/topic/file
uv run scripts/object_store.py read 's3://lifekernel/data/wiki/topic/file?versionId=具体版本'
uv run scripts/object_store.py stat 's3://lifekernel/data/wiki/topic/file?versionId=具体版本'
uv run scripts/object_store.py get 's3://lifekernel/data/wiki/topic/file?versionId=具体版本' /absolute/path/exported
```

`read` 输出对象字节，默认不保存副本；需要本地文件或文档转换工具要求文件路径时使用 `get`。`get` 下载成功后替换目标，失败保留原文件。`--immutable` 上传只接受新对象或相同内容的重试。批量 `restore` 用于显式导出，日常读取按来源 URI 定点进行。

周期复盘及日证据归档入口将随复盘模块一起提供，当前公共候选仅包含通用对象存取。不要把上传命令返回成功直接视为可以删除全部本地目录；只有所属流程确认完成的原件才能释放。存储失败需如实报告，不作为空来源或重采历史的依据。

## 验收与运行维护

对象验收会在独立随机前缀下写入测试对象，检查历史版本、不可变上传和下载失败时的原文件保护，最后只删除本次生成的对象版本。桶需已启用版本控制。它默认不操作 systemd：

```bash
uv run scripts/rustfs/verify_local.py --config /absolute/path/object-storage.json
```

需要检验重启后的持久性时，先确认没有采集、上传或其他任务正在使用该服务，再显式执行：

```bash
uv run scripts/rustfs/verify_local.py --restart-local-service
```

重启选项只接受与当前用户安装的固定服务匹配的配置：HTTP loopback endpoint、匹配的监听地址及凭据文件、对应的正在运行的用户服务。外部 S3 配置会在对象验收前被拒绝，不能触发本机服务重启。

用 `systemctl --user status lifekernel-rustfs.service` 查看状态；暂停服务使用 `systemctl --user disable --now lifekernel-rustfs.service`，数据和凭据仍保留。不要通过移动或删除内部卷操作 S3 对象。Git 中的正文与清单不能替代原件备份；单盘部署需要另行安排独立设备备份。
