# 安全与公开发布说明

更新时间：2026-10-10

本文定义 CustomSystem 可以提交到 GitHub 的内容，以及必须保留在本机或通过安全渠道迁移的内容。

## 不得提交的内容

- `.env` 及其他真实环境配置；
- DeepSeek API Key、数据库密码和管理令牌；
- `pgdata/` PostgreSQL 数据目录及数据库导出；
- `workspace/` 中的会话、日志、Trace、评测运行结果和 Qdrant 索引；
- `migration/` 中的迁移导出；
- `models/` 中的大模型权重；
- PEM、PFX、P12、SSH 私钥、凭据 JSON 和压缩备份。

这些路径已经写入 `.gitignore`。`.env.example` 只能保留占位符，不得填入真实值。

## 已公开的数据

`data/` 中的数据是演示数据。订单手机号使用 `138****5678` 形式的掩码，商品、FAQ、订单号和物流信息均用于本地演示。新增数据前仍需确认不含真实姓名、完整手机号、地址、邮箱、身份证号、支付信息或真实订单。

## 管理接口

服务端不再提供固定的默认管理令牌。未设置 `ADMIN_TOKEN` 时，`/api/admin/*` 数据接口保持禁用。管理页面要求用户输入令牌，并只在当前浏览器标签页的 `sessionStorage` 中保存。

管理后台适合本地演示，不应直接暴露到公网。公网部署应增加正式身份认证、HTTPS、来源限制、速率限制和审计日志。

## 本地模型

`models/bge-base-zh-v1.5/pytorch_model.bin` 约 390 MB，超过普通 GitHub 文件限制，因此不提交仓库。使用者可以：

1. 从可信模型源单独下载 `BAAI/bge-base-zh-v1.5`；
2. 将模型放到 `models/bge-base-zh-v1.5`；
3. 或通过 `.env` 的 `BGE_MODEL_PATH` 指向其他本地目录。

## 提交前检查

```powershell
git status --short
git check-ignore -v .env pgdata workspace models
git grep -n -I -E "sk-[A-Za-z0-9_-]{12,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"
```

最后一条命令应无输出。若密钥曾经进入 Git 历史，仅删除当前文件不够；应立即吊销并轮换密钥，再使用历史清理工具删除仓库历史中的凭据。

## 换机与备份

公开 GitHub 仓库只保存可共享源码。真实 `.env`、本地模型和数据库备份应使用密码管理器或加密存储单独迁移，不应放入公开仓库、聊天记录或普通压缩包。
