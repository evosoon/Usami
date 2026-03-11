---
name: commit
description: 自动化 git 提交流程：检查状态、运行测试、add、commit、push
allowed-tools: Bash, Read, Grep
---

# Git 提交流程

执行以下步骤完成代码提交：

## 1. 检查 Git 状态
- 运行 `git status` 查看变更文件
- 运行 `git diff --stat` 查看变更摘要
- 运行 `git log --oneline -3` 查看最近提交风格

## 2. 运行测试
如果项目中存在测试，先运行测试确保代码质量：
- Python 项目: `python -m pytest tests/ -v --tb=short`
- 如果测试失败，停止提交并报告错误

## 3. 暂存文件
使用 `git add` 暂存相关文件，排除以下内容：
- `outputs/`, `__pycache__/`, `.env`, `*.log`, `node_modules/`
- 不要提交敏感信息（API keys, credentials 等）

## 4. 生成 Commit Message
根据变更内容生成符合规范的 commit message：
- `feat:` 新功能
- `fix:` 修复 bug
- `docs:` 文档更新
- `refactor:` 重构
- `test:` 测试
- `chore:` 杂项

Commit message 格式：
```
<type>: <简短描述>

<详细说明（如有多个变更）>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

## 5. 提交并推送
- 执行 `git commit -m "<message>"`
- 执行 `git push origin <current-branch>`

## 6. 输出结果
- 显示 commit hash
- 显示推送状态

## 参数
如果用户提供了 `$ARGUMENTS`，将其作为 commit message 的描述参考。

示例：
- `/commit` - 自动分析变更并生成 message
- `/commit 添加用户认证功能` - 使用指定描述
