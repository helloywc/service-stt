.PHONY: dev run run-web run-dev run-prod install sync clean help
.DEFAULT_GOAL := help

dev run:
	START_OPEN_WEB=0 uv run python start.py

run-web:
	START_OPEN_WEB=1 uv run python start.py

run-dev:
	APP_ENV=dev uv run python start.py

run-prod:
	APP_ENV=prod uv run python start.py

install sync:
	uv sync

clean:
	rm -rf .venv build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  dev       - 启动服务 (不自动打开浏览器，等价于 run)"
	@echo "  run       - 同 dev"
	@echo "  run-web   - 启动服务并自动打开浏览器"
	@echo "  run-dev   - 开发环境启动 (APP_ENV=dev)"
	@echo "  run-prod  - 生产环境启动 (APP_ENV=prod)"
	@echo "  install   - 安装/同步依赖 (uv sync)"
	@echo "  sync    - 同 install"
	@echo "  clean   - 清理 .venv、build、__pycache__ 等"
	@echo "  help    - 显示此帮助"
