### 🌱 v0.3.0
**发布日期**：2025-04-03

*   **核心重构与优化：** 本次更新对 Milvus 数据库的控制逻辑进行了重写，并同步优化了长期记忆的存储机制。
    *   **重要提示：** 由于涉及底层重构，新实现的稳定性尚未经过充分验证，建议您在评估风险后谨慎使用。
*   **连接性扩展：** 扩展了 Milvus 数据库的连接选项，在设计上增加了对通过代理地址进行连接的支持。
    *   **注意：** 该代理连接功能目前仅停留在设计阶段，尚未经过实际测试或验证。

---

### 🚀 v0.2.0
**发布日期**：2025-02-23
- **完全重构**:重构项目代码，提高代码的可拓展性
- **资源管理**:对Milvus数据库连接进行合理的管理，但目前方案不是最优

1. **基于人格ID和会话ID的记忆区分**
    - 现在支持根据 **人格ID** 和 **会话ID** 对记忆进行区分。
    - **人格ID** 的区分是可选的（可通过配置启用或禁用）。
    - **会话ID** 的隔离是绝对的，确保不同会话之间的记忆完全独立。

2. **长期记忆切换**
    - 目前暂时不支持在单一会话中动态切换长期记忆（我们会在后续版本中评估这一功能的需求和实现方案）。

3. **对话轮次阈值更新机制**
    - 我们改进了记忆逻辑，现在采用 **对话轮次阈值** 的方式触发记忆更新：
    - 当对话轮次达到指定阈值后，系统会立即对历史对话内容进行总结并存储为长期记忆。
    - 这一机制可以有效减少冗余记忆，同时提升总结的准确性和效率。

4. **兼容性问题**
    - 新版本与旧版本的Milvus数据库不兼容，在更新版本后需要修改`collection_name`参数，使用新的集合

#### ⚠️ 升级注意
1. **不向下兼容**：由于架构重构，Milvus数据库中格式会发生改变，建议使用配置中的`collection_name`切换新的数据库，暂时无法实现长期记忆的迁移
2. **指令更改**：由于代码重构，指令也有变化，具体请使用/memory 查询使用

### 🌱 v0.1.0
**发布日期**：2025-02-19
- 实现基础记忆存储/检索功能  
- 支持Milvus向量数据库基础操作
- 构建对话总结核心算法框架
