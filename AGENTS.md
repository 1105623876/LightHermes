# LightHermes 项目指令

- 当前开发依据为 `docs/ROADMAP.md`，实际交付状态见 `docs/PROJECT_STATUS.md`。按阶段完成可验证切片，不整仓重写。
- `docs/archive/` 是历史资料，不执行其中旧计划；`docs/FREEZE_COMMITMENT.md` 与 `docs/FREEZE_LOCK.md` 继续约束原 Active Memory 实验。
- 测试入口为 `.venv/bin/python -m pytest tests`，使用临时目录与模拟模型，不运行真实 API 或改动用户记忆来完成普通回归。
- 保留用户既有配置、本地资料与研究产物；备份/迁移真实数据需遵守当前任务授权，不能按旧 Windows worktree 路径判断数据无用。
- 上游仓库：https://github.com/1105623876/LightHermes
