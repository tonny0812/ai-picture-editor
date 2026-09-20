# LLM 接口页面化配置 · 技术设计方案

> 状态：批次①已实施并验证（2026-09-20）· 前置决策已定：**全局默认 + 用户级覆盖**两层结构
> 关联：`OPTIMIZATION-ROADMAP.md`（A7 密钥守卫）、教程扩展点 7「API 开放」

## 1. 目标与现状差距

| 现状 | 目标 |
|---|---|
| LLM 配置只存在于 `.env`，改一次要重启容器 | 页面上改，**热生效**（无需重启） |
| 全系统共用一把 key（`sk-image-123`） | 管理员配全局默认；用户可自带 key 覆盖 |
| `users` 表无角色字段，只有 `current_user` 依赖 | 增加 `admin` 角色，配置入口按角色隔离 |
| key 明文躺在 `.env`（不入库但磁盘可见） | 入库**加密存储**，接口返回**打码** |

## 2. 角色设计（本方案的地基）

### 2.1 模型变更

```python
# app/models/user.py 增加一个字段
class User(UUIDBase):
    ...
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | admin
```

迁移：`users` 加列 `role`，默认 `user`。

### 2.2 管理员引导（第一个 admin 怎么来）

页面注册无法自证身份，**不能用"第一个注册用户自动成为 admin"**（公网部署时任何人抢注即得管理员）。采用双通道：

- **CLI 提升（主通道）**：`./dev.sh promote <用户名>` → 容器内执行 `python -m app.cli promote xxx`。部署文档写明。
- **ENV 白名单（可选）**：`.env` 里 `ADMIN_USERNAMES=guodongqing`，注册时命中即 `admin`。方便自用场景，默认留空。

### 2.3 权限矩阵（核心约束）

| 能力 | 匿名 | user | admin |
|---|---|---|---|
| 查看自己生效的配置（key 打码） | ❌ | ✅ | ✅ |
| 设置/修改**自己的** key 覆盖 | ❌ | ✅ | ✅ |
| 查看/修改**全局**配置 | ❌ | ❌ | ✅ |
| 全局/个人配置「测试连接」 | ❌ | 仅自己的 | ✅ 任意 |
| 查看配置变更审计 | ❌ | 仅自己的 | ✅ 全部 |
| 修改他人角色 | ❌ | ❌ | ✅（且不能改自己，防自锁） |

角色变更入口只给 admin 且**禁止操作自己**——避免最后一个 admin 把自己降级后系统失去管理员。

### 2.4 新增鉴权依赖

```python
# app/deps.py 新增（与现有 current_user 同风格）
async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
AdminUser = Annotated[User, Depends(require_admin)]
```

前端路由守卫同步：`/admin/*` 路由校验 `user.role === 'admin'`（后端 403 是真闸门，前端守卫只是体验）。

## 3. 数据模型

**单表两域**（不建两张表——全局和用户覆盖结构完全一致，用 scope 区分，查询逻辑可复用）：

```python
class LlmConfig(UUIDBase):
    __tablename__ = "llm_configs"

    scope: Mapped[str] = mapped_column(String(8))          # global | user
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    # —— 对话规划（对应 config.py 的 planner_*）——
    planner_base_url: Mapped[str | None]
    planner_api_key_enc: Mapped[str | None]                # Fernet 加密密文
    planner_model: Mapped[str | None]
    planner_timeout: Mapped[int | None]
    planner_max_retries: Mapped[int | None]

    # —— 图像模型（对应 images_*）——
    images_base_url: Mapped[str | None]
    images_api_key_enc: Mapped[str | None]
    images_model: Mapped[str | None]
    images_sizes: Mapped[str | None]

    # —— provider 总开关 ——
    image_provider: Mapped[str | None]                     # mock | dashscope | openai
    lock_image_provider: Mapped[bool] = mapped_column(default=False)  # 仅全局行有意义：禁止用户覆盖 provider

    updated_by: Mapped[UUID | None]
    updated_at: Mapped[datetime]
```

约束：
- `scope='global'` 全表最多一行（partial unique index）
- `scope='user'` 则 `user_id` 必填，每人最多一行（partial unique index）
- **NULL = 不覆盖，回落到下一层**（见 §4 解析顺序），这样用户覆盖只需填自己想改的字段

### 密钥加密

- 新增配置 `SETTINGS_ENCRYPTION_KEY`（Fernet key，32 字节 base64）。
- 未配置时**启动时自动从 `JWT_SECRET` 派生**并打 WARN 日志（自用可接受，部署文档建议独立 key）——这同时落地路线图 A7 的生产密钥守卫。
- 数据库只存密文；`get_decrypted()` 只在两个地方调用：构建 planner / 构建 provider。**永远不出现在 API 响应、日志、队列载荷里**。

## 4. 配置解析顺序（最关键的一处逻辑）

```
用户发起编辑任务
   │
   ▼
resolve_llm_config(user)          # services/llm_config.py，带 60s TTL 缓存
   ├─ 1. 用户覆盖行（llm_configs, scope=user）  ← 非空字段生效
   ├─ 2. 全局行（scope=global）
   └─ 3. .env / Settings 默认值                 ← 现有 config.py 兜底，保底可跑
   │
   ▼
┌────────────────┬──────────────────────────┐
│ 对话链路        │ planner() 改为 get_planner(config)，
│                │ 按 config 实例化 ChatOpenAI（小 LRU 缓存，key=配置指纹）
├────────────────┼──────────────────────────┤
│ 生图链路        │ get_image_provider(config) 同理；
│                │ ★ ARQ 任务载荷只带 {user_id}，worker 执行时
│                │   自行 resolve——载荷里没有 key 明文
└────────────────┴──────────────────────────┘
```

现有代码的三个改动点：
1. `app/agent/llm.py`：`planner()` 从 `@lru_cache` 无参函数改为 `get_planner(config)`（缓存键 = 配置指纹哈希，配置变更自动失效）
2. `app/providers/__init__.py`：`get_image_provider()` 增加 `config` 参数
3. `app/worker.py` + `services/tools.py`：任务执行入口先 `resolve_llm_config(user)` 再取 provider

> ⚠️ 为什么 worker 必须按 user 解析：队列是全局共享的，A 用户的换背景任务绝不能落到 B 用户（或全局）的 key 上——**这是用户级覆盖方案里最容易做错的一处**。

## 5. 接口设计

```
# 任何登录用户
GET    /api/me/llm-config          自己的覆盖 + 生效合并视图（key 全打码）
PUT    /api/me/llm-config          设置自己的覆盖（key 只写不读，传空串=清除该字段）
DELETE /api/me/llm-config          清空覆盖，回到全局默认
POST   /api/me/llm-config/test     测试自己的配置（body 可带未保存的草稿值）

# 仅 admin
GET    /api/admin/llm-config       全局配置（key 打码）
PUT    /api/admin/llm-config       更新全局配置
POST   /api/admin/llm-config/test  测试全局配置
GET    /api/admin/llm-config/audit 配置变更审计（最近 100 条）
PATCH  /api/admin/users/{id}/role  调整他人角色（不可操作自己）
```

打码规则：`sk-image-123` → `sk-i***23`；只回前后各 2~4 字符或纯 `••••`，**编辑表单永远是只写框**（不回填明文，留空=不变）。

### SSRF 防护（用户级 base_url 是攻击面）

用户可以填任意 `base_url`，服务端会拿它发请求——等于给了内网探测能力（`http://postgres:5432`、云元数据 `169.254.169.254`）。分级处理：

- **admin 配全局**：不限（管理员本来可控整个部署）
- **user 配个人**：只允许 `http/https` + 解析后拒绝私网/环回/链路本地地址（`ipaddress` 标准库一行判断）；「测试连接」接口加 **1 次/分钟** 限流（防止被当端口扫描器）

## 6. 审计

新表 `llm_config_audit`：`id, actor_id, scope, target_user_id, action(update/clear/test), diff(仅字段名+非密钥值，密钥只记"已变更"), created_at`。

够回答两个问题就够了：「谁在什么时候改了全局 key」「谁的覆盖导致行为变化」——不上来做完整审计系统。

## 7. 前端

```
新增页面：
/settings            普通用户：个人覆盖表单 + 当前生效配置只读视图 + 测试按钮
/admin/llm-config    管理员：全局表单 + 审计列表 + 用户角色管理入口
路由守卫：admin 路由按 user.role 拦截 → 跳 403 页
复用：TanStack Query 管理加载态；表单沿用现有 Tailwind design token
组件：MaskedSecretInput（只写、显示 ••••、可点"更换"）、TestConnectionButton
```

交互细节：保存成功后 toast 提示「配置已热生效，无需重启」；测试连接显示耗时与模型名。

## 8. 实施步骤（预估 4 批）

| 批 | 内容 | 验收 |
|---|---|---|
| ① 地基 | role 字段 + 迁移 + require_admin + promote CLI + 7 个权限单测 | 非管理员访问 admin 接口 403 |
| ② 配置层 | llm_configs 表 + 加密 + resolve 服务 + planner/provider 改造 + SSRF 守卫 | 改全局配置后**不重启**，新任务用新 key（看 worker 日志） |
| ③ 接口 | §5 全部端点 + 打码 + 审计 + 限流 | 单测覆盖越权矩阵每格 |
| ④ 前端 | 两个页面 + 守卫 + 组件 | 手工冒烟：user 改 key→立即生效；admin 改全局→user 无感回落 |

每批结束跑 `./dev.sh test` + `./dev.sh smoke`（现有 167 单测 / 23 冒烟是回归底线）。

## 9. 已确认决策（2026-09-20）

1. **角色管理**：本期只做 CLI（`./dev.sh promote <用户名>`），管理界面放后续批次。
2. **`ADMIN_USERNAMES` 白名单**：要做。命中即注册为 admin，默认留空；部署文档注明公网场景建议不用。
3. **用户级覆盖允许自选 `image_provider`**：允许。
4. **`lock_image_provider` 强制锁**：保留字段，**默认关闭**。

### 强制锁的语义（补充说明）

全局配置新增布尔字段 `lock_image_provider`（默认 `false`）。开启后：

- 用户个人设置页的 `image_provider` 字段置灰只读；
- 后端校验同样拒绝用户覆盖该字段（返回 422），**不只依赖前端拦截**；
- 其余字段（`base_url` / `api_key` / `model` / `sizes`）不受影响，照常可覆盖。

解决的问题：防止用户把真实模型降级成 `mock` 后，看到占位图却误判为「提示词没写好」或「系统坏了」。典型场景是演示环境与开放试用。

