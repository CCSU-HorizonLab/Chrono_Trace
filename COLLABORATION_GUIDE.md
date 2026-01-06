# 🤝 两人协作开发指南

## 📋 当前状态

- **远程仓库**: origin/master (主分支)
- **开发人员**: 2人
- **问题**: 直接推送到 master 会导致代码冲突和覆盖

---

## 🚫 错误的工作流程

```bash
# ❌ 不要这样做
# 你：本地开发 → 直接推送到 master
git add .
git commit -m "修复深色模式"
git push origin master

# 他：本地开发 → 也直接推送到 master
git add .
git commit -m "添加新功能"
git push origin master  # 会覆盖你的修改！
```

**问题**：
1. 你们的修改会互相覆盖
2. 无法进行代码审查
3. 难以追溯谁做了什么修改
4. 冲突解决困难

---

## ✅ 推荐的工作流程

### 方案1：功能分支工作流（简单）

#### 你这边的工作流程

```bash
# 1. 开始新功能前，先拉取最新代码
git checkout master
git pull origin master

# 2. 创建功能分支
git checkout -b feature/deep-mode-fix

# 3. 开发功能
git add .
git commit -m "修复深色模式问题"

# 4. 开发完成后，切换回 master
git checkout master

# 5. 拉取最新的 master（可能有对方的修改）
git pull origin master

# 6. 合并你的功能分支
git merge feature/deep-mode-fix

# 7. 如果有冲突，解决冲突
# 编辑冲突文件，然后：
git add .
git commit -m "合并深色模式修复"

# 8. 推送到远程
git push origin master

# 9. 删除本地功能分支
git branch -d feature/deep-mode-fix
```

#### 他那边的工作流程

```bash
# 同样的流程
git checkout master
git pull origin master
git checkout -b feature/other-function
# ... 开发 ...
git checkout master
git pull origin master
git merge feature/other-function
git push origin master
git branch -d feature/other-function
```

### 方案2：远程功能分支 + Pull Request（推荐）

这个方案更安全，可以进行代码审查。

#### 你这边的工作流程

```bash
# 1. 拉取最新代码
git checkout master
git pull origin master

# 2. 创建功能分支
git checkout -b feature/deep-mode-fix

# 3. 开发功能
git add .
git commit -m "修复深色模式问题"

# 4. 推送功能分支到远程
git push -u origin feature/deep-mode-fix

# 5. 在GitHub/GitLab上创建Pull Request
# - 标题：修复深色模式问题
# - 描述：修复了深色模式下的白色背景问题...

# 6. 等待对方review并合并

# 7. 合并后，拉取最新master并删除本地分支
git checkout master
git pull origin master
git branch -d feature/deep-mode-fix
```

#### 他那边的工作流程

```bash
# 1. 在GitHub上review你的Pull Request
# 2. 如果没问题，点击"Merge Pull Request"
# 3. 拉取最新代码
git checkout master
git pull origin master

# 4. 他开始新功能时，同样的流程
git checkout -b feature/other-function
# ...
```

---

## 📝 分支命名规范

```bash
# 功能开发
feature/xxx
feature-deep-mode-fix
feature-user-auth

# Bug修复
fix/bug-xxx
fix-login-error

# 紧急修复
hotfix/critical-bug
```

---

## 🔄 日常协作步骤

### 每天开始工作前

```bash
# 1. 切换到 master
git checkout master

# 2. 拉取最新代码
git pull origin master

# 3. 查看对方做了什么
git log --oneline --graph --all -10
```

### 开发过程中

```bash
# 1. 在功能分支上开发
git checkout feature-xxx

# 2. 定期合并 master 的最新修改
git checkout master
git pull origin master
git checkout feature-xxx
git merge master

# 3. 继续开发
git add .
git commit -m "..."
```

### 提交前检查

```bash
# 1. 确保在正确的分支
git branch  # 应该显示 * feature-xxx

# 2. 查看修改的文件
git status

# 3. 查看具体的修改内容
git diff

# 4. 提交修改
git add .
git commit -m "清晰的提交信息"

# 5. 如果使用方案2，推送到远程
git push -u origin feature-xxx
```

---

## ⚠️ 冲突解决

### 当合并时出现冲突

```bash
# 1. Git会提示冲突
git merge feature-xxx
# Auto-merging file.vue
# CONFLICT (content): Merge conflict in file.vue

# 2. 查看冲突文件
git status

# 3. 编辑冲突文件，查找冲突标记
# <<<<<<< HEAD
# 对方的修改
# =======
# 你的修改
# >>>>>>> feature-xxx

# 4. 手动解决冲突，保留正确的代码

# 5. 标记冲突已解决
git add file.vue

# 6. 完成合并
git commit -m "解决合并冲突"
```

---

## 📌 重要规则

### ✅ 应该做的

1. **每天开始工作前先 `git pull`**
2. **在功能分支上开发，不要在 master 上直接开发**
3. **写清晰的 commit 信息**
4. **推送前先拉取最新代码**
5. **定期沟通，避免修改同一个文件**

### ❌ 不应该做的

1. ❌ **不要在 master 分支上直接开发**
2. ❌ **不要强制推送到 master** (`git push -f`)
3. ❌ **不要推送到对方的分支**
4. ❌ **不要不沟通就修改同一个文件**

---

## 🎯 推荐配置

### 在 `.git/config` 中设置别名

```bash
git config --global alias.co checkout
git config --global alias.br branch
git config --global alias.ci commit
git config --global alias.st status
git config --global alias.unstage 'reset HEAD --'
git config --global alias.last 'log -1 HEAD'
git config --global alias.visual 'log --graph --oneline --all'
```

使用：
```bash
git co master        # git checkout master
git br               # git branch
git st               # git status
```

---

## 📞 沟通建议

### 每天工作开始时

- 告诉对方："我今天要做XXX功能"
- 确认对方："你今天要做什么？"

### 修改重要文件前

- 在群里说："我要修改 App.vue"
- 等对方回复后再开始

### 遇到冲突时

- 先沟通："我们在同一个文件有冲突，怎么解决？"
- 不要强制覆盖对方的代码

---

## 🔧 实用命令

```bash
# 查看分支图
git log --graph --oneline --all --decorate

# 查看远程分支
git branch -r

# 查看最近5次提交
git log -5 --oneline

# 撤销最后一次提交（保留修改）
git reset --soft HEAD~1

# 查看某个分支的提交
git log feature-xxx --oneline

# 比较两个分支的差异
git diff master feature-xxx

# 查看哪个分支合并到了当前分支
git branch --merged
```

---

## 📚 快速参考

### 标准开发流程

```bash
# 开发新功能
git checkout master
git pull origin master
git checkout -b feature-xxx
# ... 开发 ...
git add .
git commit -m "完成功能"
git checkout master
git pull origin master
git merge feature-xxx
git push origin master
git branch -d feature-xxx
```

### 紧急Bug修复

```bash
git checkout master
git pull origin master
git checkout -b hotfix/critical-bug
# ... 修复 ...
git add .
git commit -m "修复紧急bug"
git checkout master
git merge hotfix/critical-bug
git push origin master
git branch -d hotfix/critical-bug
```

---

**最后更新**: 2026-01-06
**维护者**: 开发团队
