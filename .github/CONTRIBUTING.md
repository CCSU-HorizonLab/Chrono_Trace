# 贡献指南

感谢你对 Chrono Trace 项目的关注! 我们欢迎任何形式的贡献。

## 🤝 如何贡献

### 报告问题

如果你发现了 bug 或有功能建议:

1. 检查 [Issues](../../issues) 是否已有相同问题
2. 如果没有,创建新 Issue
3. 清晰描述问题或建议
4. 提供复现步骤(对于 bug)

### 提交代码

1. **Fork 项目**
   ```bash
   # 点击右上角 Fork 按钮
   ```

2. **克隆到本地**
   ```bash
   git clone https://github.com/YOUR_USERNAME/Chrono-Trace.git
   cd Chrono-Trace
   ```

3. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   # 或
   git checkout -b fix/your-bug-fix
   ```

4. **开发与测试**
   - 遵循 [代码规范](../docs/DEVELOPMENT.md#-代码规范)
   - 添加必要的测试
   - 确保所有测试通过

5. **提交更改**
   ```bash
   git add .
   git commit -m "feat: add amazing feature"
   ```

   **Commit 格式**:
   - `feat`: 新功能
   - `fix`: Bug修复
   - `docs`: 文档更新
   - `refactor`: 代码重构
   - `test`: 测试相关
   - `chore`: 构建/工具相关

6. **推送到 GitHub**
   ```bash
   git push origin feature/your-feature-name
   ```

7. **创建 Pull Request**
   - 点击 "New Pull Request"
   - 填写 PR 描述
   - 等待审核

## 📝 开发规范

### Python 代码

- 遵循 PEP 8
- 使用类型注解
- 添加 docstring
- Debug 输出格式: `[DEBUG ClassName] message`

### TypeScript/Vue 代码

- 使用 ESLint
- 组件名 PascalCase
- 函数/变量 camelCase
- 添加类型定义

### 文档

- 使用 Markdown
- 保持简洁清晰
- 添加代码示例
- 更新目录索引

## 🧪 测试

运行测试确保代码质量:

```bash
# Python 测试
python test_decrypt_v2.py

# 前端测试
cd frontend
npm test
```

## 📚 参考资源

- [开发文档](../docs/DEVELOPMENT.md)
- [安装指南](../docs/SETUP.md)
- [更新日志](../CHANGELOG.md)

## ❓ 需要帮助?

- 查看 [文档中心](../docs/README.md)
- 提交 [Issue](../../issues)
- 发起 [Discussion](../../discussions)

---

再次感谢你的贡献! 🎉
