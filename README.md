# Medical Equipment Rental System

医疗设备租赁管理系统后端 API，基于 FastAPI + SQLAlchemy + Alembic 构建。

## 目录

- [快速开始](#快速开始)
- [数据库工程化流程](#数据库工程化流程)
- [环境变量说明](#环境变量说明)
- [常用命令](#常用命令)
- [测试](#测试)
- [故障排查](#故障排查)
- [架构说明](#架构说明)

---

## 快速开始

### 前置要求

- Python 3.9+
- SQLite（默认，零配置）或 PostgreSQL（生产环境）

### 一键启动（新机器）

```bash
# 1. 克隆项目后，进入目录
cd xzwl-4

# 2. 安装依赖并初始化配置
make install
# 或手动执行：
#   cp .env.example .env
#   pip install -r requirements.txt

# 3. 初始化数据库（运行迁移 + 填充种子数据）
make init
# 或手动执行：
#   python init_db.py

# 4. 启动开发服务器
make run
# 或手动执行：
#   python -m uvicorn app.main:app --reload --port 8000
```

启动后访问：
- API 文档（Swagger UI）: http://localhost:8000/docs
- API 文档（ReDoc）: http://localhost:8000/redoc
- 健康检查: http://localhost:8000/health

### 默认测试账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 员工 | staff | staff123 |
| 客户 | customer | customer123 |

---

## 数据库工程化流程

### 职责边界说明

| 组件 | 职责 | 使用场景 |
|------|------|----------|
| **Alembic Migrations** | 数据库 schema 版本管理、表结构变更 | 所有表创建、字段增删改、索引变更 |
| `Base.metadata.create_all()` | 仅用于测试环境内存数据库初始化 | `tests/conftest.py` 中使用 |
| `init_db.py` | 种子数据填充（用户、分类、示例数据等） | 首次部署或重置后执行 |
| `ensure_database_compatibility()` | **已移除**，由 Alembic 替代 | - |

> **重要**：生产环境禁止使用 `Base.metadata.create_all()`，所有 schema 变更必须通过 Alembic 迁移。

### 标准开发流程

#### 1. 首次设置

```bash
# 安装依赖
pip install -r requirements.txt

# 复制环境配置
cp .env.example .env

# 运行所有迁移
make migrate
# 或：python -m alembic upgrade head

# 填充种子数据
make seed
# 或：python init_db.py --seed-only
```

#### 2. 修改模型后生成新迁移

```bash
# 1. 修改 app/models/ 下的模型文件

# 2. 生成迁移脚本（自动对比模型与数据库差异）
make new-migration
# 或：python -m alembic revision --autogenerate -m "add_field_to_device"

# 3. 检查生成的迁移文件（alembic/versions/）
#    SQLite 注意：ALTER COLUMN 等操作会自动转为 batch 模式

# 4. 应用迁移
make migrate
```

#### 3. 迁移管理命令

```bash
# 查看当前数据库版本
make db-status
# 或：python -m alembic current

# 查看迁移历史
make db-history
# 或：python -m alembic history --verbose

# 回滚到上一个版本
python -m alembic downgrade -1

# 回滚到初始状态（慎用！）
python -m alembic downgrade base

# 重置数据库（删除所有表 + 重新迁移 + 种子数据）
make reset
# 或：python init_db.py --reset
```

### SQLite vs PostgreSQL 兼容性

本项目同时支持两种数据库，Alembic 配置已自动处理兼容性：

| 特性 | SQLite | PostgreSQL |
|------|--------|------------|
| 默认配置 | ✅ `DATABASE_URL=sqlite:///./medical_rental.db` | ❌ 需要手动配置 |
| 外键约束 | 自动启用 | 原生支持 |
| ALTER TABLE | 通过 `render_as_batch=True` 自动处理 | 原生支持 |
| 枚举类型 | 映射为 VARCHAR | 原生 ENUM 类型 |

**切换到 PostgreSQL**：

1. 编辑 `.env`：
```env
DATABASE_URL=postgresql://user:password@localhost:5432/medical_rental
```

2. 运行迁移：
```bash
make migrate
```

---

## 环境变量说明

完整配置请参考 [.env.example](.env.example)

### 数据库配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `sqlite:///./medical_rental.db` | 数据库连接字符串。<br>SQLite: `sqlite:///./path/to/file.db`<br>PostgreSQL: `postgresql://user:pass@host:port/dbname` |

### JWT 认证配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `JWT_SECRET_KEY` | `your-super-secret-key-change-in-production` | JWT 签名密钥。**生产环境必须修改！**<br>生成命令：`python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_ALGORITHM` | `HS256` | 签名算法 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token 过期时间（分钟），默认 24 小时 |

### 应用配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_NAME` | `Medical Equipment Rental System` | 应用名称 |
| `APP_ENV` | `development` | 运行环境：<br>- `development`: 自动运行迁移，开启 debug<br>- `production`: 禁止自动迁移，关闭 debug |
| `APP_DEBUG` | `true` | 是否开启 debug 模式 |

### 业务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OVERDUE_DAILY_RATE` | `50.0` | 单台设备每日逾期费用 |
| `OVERDUE_GRACE_PERIOD_DAYS` | `1` | 逾期宽限期（天） |
| `DEVICE_LOCK_TIMEOUT_MINUTES` | `30` | 设备锁定超时时间（分钟） |

---

## 常用命令

使用 `make` 命令简化操作（无 make 可参考 Makefile 手动执行）：

```bash
make help              # 显示所有可用命令
make install           # 安装依赖 + 创建 .env
make run               # 启动开发服务器（自动重载）
make migrate           # 运行数据库迁移
make seed              # 填充种子数据
make init              # 初始化：迁移 + 种子数据
make reset             # 重置数据库（确认后执行）
make db-status         # 查看迁移状态
make db-history        # 查看迁移历史
make new-migration     # 生成新迁移
make test              # 运行测试
make clean             # 清理临时文件和数据库
```

---

## 测试

测试使用独立的内存 SQLite 数据库，每次测试后自动清理。

```bash
# 运行所有测试
make test
# 或：python -m pytest tests/ -v

# 运行测试并显示 print 输出
make test-verbose
# 或：python -m pytest tests/ -v -s

# 运行单个测试文件
python -m pytest tests/test_device_import_validation.py -v

# 生成覆盖率报告
python -m pytest tests/ --cov=app --cov-report=html
```

测试数据库在 `tests/conftest.py` 中配置，使用 `Base.metadata.create_all()` 直接建表，不经过 Alembic 迁移流程，确保测试快速且隔离。

---

## 故障排查

### 数据库迁移相关

**问题：迁移失败，显示 "table already exists"**
```
原因：数据库中已存在表但迁移表中无记录
解决：
  1. 若是新数据库：删除 .db 文件后重新 make init
  2. 若是已有数据库：标记当前状态为最新
     python -m alembic stamp head
```

**问题：SQLite 迁移失败，"No support for ALTER of constraints in SQLite dialect"**
```
原因：SQLite 不支持部分 DDL 操作
解决：Alembic 已配置 render_as_batch=True，确保生成的迁移使用 batch_alter_table
```

**问题：自动生成的迁移为空**
```
原因：模型没有导入到 Alembic env.py 中
解决：确保新模型在 app/models/__init__.py 中导出
```

### 启动相关

**问题：启动后 404，路由不存在**
```
原因：APP_ENV 不是 development，未自动运行迁移
解决：
  make migrate  # 手动运行迁移
  或设置 APP_ENV=development
```

**问题：数据库连接错误**
```
SQLite：确保目录有写权限
PostgreSQL：确保服务运行、认证信息正确、数据库已创建
```

---

## 架构说明

### 目录结构

```
xzwl-4/
├── app/
│   ├── core/           # 业务核心逻辑（安全、审计、库存等）
│   ├── models/         # SQLAlchemy ORM 模型
│   ├── routers/        # FastAPI 路由
│   ├── schemas/        # Pydantic 请求/响应模型
│   ├── config.py       # 配置管理（pydantic-settings）
│   ├── database.py     # 数据库连接、Session 管理
│   └── main.py         # 应用入口
├── alembic/            # 数据库迁移
│   ├── versions/       # 迁移脚本（按时间排序）
│   ├── env.py          # 迁移环境配置
│   └── script.py.mako  # 迁移模板
├── tests/              # 测试用例
├── init_db.py          # 种子数据初始化
├── alembic.ini         # Alembic 配置
├── requirements.txt    # Python 依赖
├── .env.example        # 环境变量示例
├── Makefile            # 命令快捷方式
└── README.md           # 本文档
```

### 迁移工作流

```
修改 app/models/xxx.py
       ↓
python -m alembic revision --autogenerate -m "message"
       ↓
检查 alembic/versions/xxx.py 生成的脚本
       ↓
python -m alembic upgrade head  # 应用到本地
       ↓
提交迁移文件到版本控制
       ↓
部署时自动/手动运行 alembic upgrade head
```

### 生产部署建议

1. **设置 `APP_ENV=production`** - 禁用自动迁移
2. **部署流程中显式运行迁移**：
   ```bash
   python -m alembic upgrade head
   ```
3. **使用 PostgreSQL** - SQLite 不适合生产多并发场景
4. **修改 `JWT_SECRET_KEY`** - 使用强随机密钥
5. **禁用 `APP_DEBUG`** - 避免泄露敏感信息

---

## 开发规范

### 新增模型

1. 在 `app/models/` 下创建模型文件
2. 在 `app/models/__init__.py` 中导出
3. 生成迁移：`make new-migration`
4. 验证迁移：`make migrate`
5. 在 `app/schemas/` 创建对应 Pydantic 模型
6. 在 `app/routers/` 创建路由

### 数据库变更原则

- **禁止直接修改生产数据库** - 所有变更必须通过迁移
- **迁移脚本可重复执行** - 使用 `IF NOT EXISTS` 等安全语句
- **向下兼容** - 新增字段必须有默认值或可空
- **破坏性变更单独处理** - 删除字段/表需要先部署兼容版本

---

## License

Internal use only.
