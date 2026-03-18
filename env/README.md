# 环境配置

- **dev**：开发环境，使用 `env/dev.env`
- **prod**：生产环境，使用 `env/prod.env`

## 使用方式

通过环境变量 `APP_ENV` 指定当前环境（默认 `dev`）：

```bash
# 开发环境（默认）
uv run python start.py
# 或
APP_ENV=dev make run

# 生产环境
APP_ENV=prod make run
```

## 数据库配置

在对应 env 文件中配置，或通过系统环境变量覆盖：

| 变量 | 说明 | 默认 |
|------|------|------|
| DB_HOST | 数据库主机 | 192.168.2.101 |
| DB_PORT | 端口 | 3306 |
| DB_USER | 用户名 | root |
| DB_PASSWORD | 密码 | 123456 |
| DB_NAME | 数据库名 | media_operator |

首次部署可复制 `dev.env.example` → `dev.env`、`prod.env.example` → `prod.env` 后修改（实际含密码的 `dev.env`/`prod.env` 已加入 .gitignore，不会提交）。
