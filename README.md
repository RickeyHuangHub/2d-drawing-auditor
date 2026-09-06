# Drawing Audit Expert（2D图纸审核高手）

一个本地运行的网页工具，对标豆包工作的对话式界面，用于批量审核 2D 工程图纸（PDF）。

## 核心特性

- **🤖 AI 智能审核**：调用视觉大模型，逐张审核工程图纸
- **🔍 智能分块**：全局缩略图 + 标题栏高保真切片 + 高密度标注区局部切片，解决大图纸分辨率瓶颈
- **📐 Baseline V1.0 规则引擎**：28 条结构化审核规则（图纸完整性/尺寸/公差/GD&T/材料工艺/DFM/版本控制），AI 逐条执行、强制给证据、禁止乱猜
- **⚙️ 规则前置检查**：PDF 矢量文本提取 + 正则校验，标题栏信息（图号/版本/材料/签名）零误差，映射到 Baseline 规则 ID（DOC-001/REV-001/DOC-003/TOL-001）
- **🧮 确定性规则计算**：DFM-001 孔边距 E/D、DFM-002 深孔 L/D、GDT-001 基准引用校验，由程序精确计算，不靠 AI 估算
- **🏷️ finding_type 六类分类**：图纸错误 / 信息歧义 / 可制造性风险 / 成本风险 / 检验风险 / 文件控制，报告不再混淆"图纸错误"与"建议优化"
- **🏢 企业扩展机制**：Baseline Rule → Override → Custom Rule 三层，企业不改 28 条基线即可覆盖参数或新增自定义规则
- **📊 汇总看板**：健康度环、缺陷统计、通过率，批量审核一目了然
- **📂 逐张下钻**：双栏对比面板（左原图 + 右审核建议），点击问题直接定位
- **💾 报告回写**：每张图纸生成 `.md` + `.json` 报告，保存到原文件夹；批量生成汇总报告
- **🏷️ 三级严重度**：阻断级（Block）/ 警告级（Warning）/ 建议级（Info）

## 快速开始

### 1. 环境要求

- Python 3.9+
- Windows / macOS / Linux

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 AI API Key

支持 OpenAI 兼容接口（豆包 / GPT / Claude 等），通过环境变量配置：

**Windows (cmd)**:
```cmd
set AI_API_KEY=your_api_key
set AI_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
set AI_MODEL=doubao-vision-pro-32k
```

**Windows (PowerShell)**:
```powershell
$env:AI_API_KEY="your_api_key"
$env:AI_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
$env:AI_MODEL="doubao-vision-pro-32k"
```

**推荐模型**：
- 豆包视觉：`doubao-vision-pro-32k`（国内直连，中文图纸识别强，成本低）
- GPT-4o：`gpt-4o`（需配置对应 base_url）
- 备用模型：设置 `AI_FALLBACK_API_KEY` / `AI_FALLBACK_BASE_URL` / `AI_FALLBACK_MODEL`

### 4. 启动

**方式一：双击启动（Windows）**
```
双击 2d-audit-start.bat
```

**方式二：命令行启动**
```bash
python main.py
```

启动后浏览器自动打开 `http://127.0.0.1:8080`（端口可用环境变量 `PORT` 修改；默认 8080）

### 5. 安全与资源限制（可选，默认已开启防护）

以下限制已内置，无需配置即可生效：

| 项目 | 限制 |
| --- | --- |
| 上传单文件大小 | ≤ 50 MB（超限返回 413） |
| 上传文件数量 | 每次 ≤ 10 张 |
| 上传内容校验 | 写入后校验 PDF 文件头（`%PDF-`），伪装文件会被拒绝 |
| PDF 页数 | ≤ 30 页 |
| PDF 页面尺寸 / 渲染像素 | 页面边长 ≤ 8000pt；渲染像素总量有上限（超限自动降 DPI 或停止分块） |
| 损坏 / 加密 / 空 PDF | 单独分类报错，不影响其它文件 |
| 审计日志 | 所有写操作（POST/PUT/DELETE）写入 `data/audit.log` |

**可选鉴权**（默认关闭，不影响本地使用）：给 `/api/*` 接口增加 Bearer Token 校验，防止服务暴露在局域网/公网时被未授权访问：

```powershell
# PowerShell 启动前设置
$env:AUTH_TOKEN="你的自定义口令"
python main.py
```

设置后访问接口需带 `Authorization: Bearer <口令>`（或 URL 参数 `?token=<口令>`）；`/api/config` 豁免，供前端读取配置。

### 提交图纸的三种方式

1. **粘贴文件夹路径**：在输入框粘贴图纸所在文件夹完整路径（如 `D:\图纸\项目A`），回车或点发送。
   > 输入框支持混入说明文字，系统会自动提取路径部分。例如输入 `D:\AI_Vault\Output\DrawingTest\Test2 请审核图纸`，会提取出路径 `D:\AI_Vault\Output\DrawingTest\Test2` 进行审核。
2. **拖拽图纸**：把 PDF 图纸直接拖入页面任意位置，松开即自动上传并开始审核（支持一次多张）。
3. **点击上传按钮**：点输入框右侧的「上传」按钮，在文件选择框中选中一张或多张 PDF。

> 上传的图纸保存在 `data\uploads\<任务号>\` 目录，审核报告同样自动保存到该目录。
> 若提示"文件夹不存在"，请检查路径是否含不可见字符（如复制粘贴带入的空格/零宽字符），系统已自动清理常见此类字符。

### 端口配置（与其它程序冲突时）

默认端口 **8080**。若该端口被其它程序占用，两种方式更换：

- **方式一（推荐，无需改代码）**：编辑项目根目录 `端口配置.txt`，把里面的数字改成你想要的端口（如 `8688`），保存后重新运行 `2d-audit-start.bat`。
- **方式二**：启动前设置环境变量 `PORT`：
  ```powershell
  $env:PORT="8688"
  python main.py
  ```

> 若指定端口被占用，程序会自动顺延到下一个可用端口（8080→8081→8082…）并在控制台提示实际访问地址。访问地址 = `http://127.0.0.1:<端口>`。

## 使用方法

1. 在底部输入框中粘贴图纸文件夹的完整路径（如 `D:\图纸\项目A\`）
2. 点击「审核标准」选择需要的检查项，展开 **Baseline 规则库 V1.0** 可查看 28 条规则清单（规则 ID / 严重度 / 执行方式 / 企业自定义标记）
3. 点击发送按钮开始审核
4. 实时查看逐张审核进度
5. 审核完成后查看汇总看板
6. 点击任意图纸行，展开双栏详情面板（原图 + 问题清单，含规则 ID / 类型 / 证据 / 计算 / 工程风险）
7. 报告已自动保存到原图纸文件夹

## 审核规则体系（Baseline V1.0）

### 全局审核原则

每条审核任务都注入以下约束，AI 必须逐条执行：

- 只审核图纸中可见或可可靠提取的信息，绝不臆造尺寸/公差/材料/基准/工艺/标准/版本
- 每条 CRITICAL / WARNING 结论必须包含可验证的图纸证据；证据不足 → 返回 `NEEDS_REVIEW`，禁止乱猜
- 区分"图纸错误"与"可制造性风险"，不做无谓误报
- 关联视图/剖视/局部放大/标注/公差/GD&T/材料工艺综合判断
- 规则优先级：**Project > Customer > Company > Baseline**
- 允许结果：`PASS` / `WARNING` / `CRITICAL` / `NEEDS_REVIEW` / `NOT_APPLICABLE`
- 证据策略：**No Evidence → No Finding**

### 28 条规则（7 大类）

| 类别 | 规则 | 严重度 | 执行方式 |
|---|---|---|---|
| DOC 图纸完整性 | DOC-001 图号/零件号缺失 | CRITICAL | Deterministic |
| | DOC-002 标题栏关键信息缺失 | WARNING | Hybrid |
| | DOC-003 材料规格缺失 | CRITICAL | Hybrid |
| | DOC-004 制造特征定义不完整 | CRITICAL | AI |
| DIM 尺寸 | DIM-001 特征尺寸不完整 | CRITICAL | Hybrid |
| | DIM-002 特征位置未完全定义 | CRITICAL | Hybrid |
| | DIM-003 重复/封闭尺寸链 | WARNING | Hybrid |
| | DIM-004 跨视图尺寸/特征冲突 | CRITICAL | Hybrid |
| | DIM-005 尺寸与几何不匹配 | CRITICAL | AI |
| TOL 公差 | TOL-001 未注公差未定义 | WARNING | Hybrid |
| | TOL-002 功能尺寸公差疑似过松 | WARNING | AI |
| | TOL-003 公差过严/成本风险 | WARNING | Hybrid |
| | TOL-004 公差要求冲突 | CRITICAL | Hybrid |
| GDT 形位公差 | GDT-001 被引用基准不存在 | CRITICAL | Deterministic |
| | GDT-002 基准定义歧义 | CRITICAL | Hybrid |
| | GDT-003 特征控制框无效/不完整 | CRITICAL | Hybrid |
| | GDT-004 GD&T/基本尺寸/基准体系不一致 | CRITICAL | Hybrid |
| MAT 材料/工艺 | MAT-001 材料规格歧义 | CRITICAL | Hybrid |
| | MAT-002 材料与表面处理不兼容 | CRITICAL | Hybrid |
| | MAT-003 材料/热处理/硬度冲突 | CRITICAL | Hybrid |
| | MAT-004 表面处理区域歧义 | WARNING | AI |
| DFM 可制造性 | DFM-001 孔边距风险（E/D < 1.0） | WARNING | Deterministic |
| | DFM-002 深孔风险（L/D > 5.0） | WARNING | Deterministic |
| | DFM-003 内角/刀具可达性风险 | WARNING | Hybrid |
| | DFM-004 薄壁/窄槽/微小特征风险 | WARNING | Hybrid |
| | DFM-005 综合制造风险 | WARNING | AI |
| REV 版本控制 | REV-001 版本号缺失/无效 | CRITICAL | Deterministic |
| | REV-002 修订表与当前版本冲突 | CRITICAL | Hybrid |

> **执行方式说明**：`Deterministic` = 程序计算（不靠 AI 估算，可复现）；`Hybrid` = 文本提取 + AI 审核交叉验证；`AI` = 由 AI 跨区域/跨视图综合判断（如 DIM-004 / TOL-004 / GDT-004 / MAT-003 / DFM-005）。

### finding_type 六类分类

每条发现必须归类，报告据此区分"图纸错误"与"优化建议"：

- `DRAWING_ERROR` 图纸错误
- `AMBIGUITY` 信息歧义
- `MANUFACTURING_RISK` 可制造性风险
- `COST_RISK` 成本风险（如 TOL-003 强制为此类）
- `INSPECTION_RISK` 检验风险
- `DOCUMENT_CONTROL` 文件控制

### 企业扩展：Override / Custom Rule

企业不直接修改 28 条 Baseline，采用三层扩展：

```
Baseline Rule → Override（覆盖参数/严重度） → Custom Rule（新增企业规则）
```

编辑 `custom_rules.py`：

```python
# 覆盖 Baseline 参数/严重度
CUSTOM_OVERRIDES = [
    {
        "rule_id": "DFM-002",
        "parameter": "maximum_hole_depth_ratio",
        "new_value": 4.0,
        "severity": "WARNING",
        "reason": "ABC internal machining standard",
        "standard_source": "ABC Drawing Standard DS-001 Rev.C",
    },
]

# 新增企业自定义规则
CUSTOM_BASELINE_RULES = [
    {
        "id": "ABC-DIM-001",
        "name": "Mounting Hole Minimum Edge Distance",
        "name_zh": "安装孔最小边距",
        "category": "DIM",
        "severity": "CRITICAL",
        "execution": "Deterministic",
        "finding_type": "MANUFACTURING_RISK",
        "condition": "安装孔边距 < 8 mm",
        "standard_source": "ABC Drawing Standard DS-001 Rev.C",
    },
]
```

### 统一 AI 输出格式

AI 每条发现强制返回结构化 JSON：

```json
{
  "audit_standard": "Baseline V1.0",
  "rule_id": "DFM-002",
  "rule_name": "Deep Hole Risk",
  "category": "DFM",
  "result": "WARNING",
  "finding_type": "MANUFACTURING_RISK",
  "confidence": 0.97,
  "location": {"page": 2, "view": "SECTION A-A", "feature": "Hole H3"},
  "evidence": ["Hole diameter = 3 mm", "Hole depth = 22 mm"],
  "parameters": {"maximum_hole_depth_ratio": 5.0},
  "calculation": {"formula": "L / D", "value": 7.33},
  "finding": "Hole depth-to-diameter ratio exceeds configured baseline.",
  "engineering_risk": "Deep-hole drilling and chip evacuation risk.",
  "recommendation": "Review whether the depth is functionally required.",
  "standard_source": "BASELINE",
  "requires_human_review": true
}
```

### 审核流水线（10 步运行逻辑）

```
① 读取图纸 → ② 提取结构化工程信息 → ③ 加载 28 条 Baseline → ④ 加载企业 Override/Custom
→ ⑤ Deterministic 先算（RuleEngine）→ ⑥ Hybrid 审核（AI 分块）→ ⑦ AI 综合审核（跨视图）
→ ⑧ Evidence 验证（无证据 → NEEDS_REVIEW 降级）→ ⑨ 去重/冲突处理 → ⑩ 生成 Audit Report
```

## 审核检查项

| ID | 检查项 | 说明 |
|---|---|---|
| title_block | 图框与标题栏 | 图名、图号、版本、日期、签名、材料、比例、单位 |
| dimension | 尺寸标注 | 缺尺寸、重复尺寸、封闭尺寸链、标注清晰 |
| tolerance | 公差与粗糙度 | 尺寸公差、形位公差、表面粗糙度 |
| views | 视图表达 | 主/俯/侧视图、剖视图、局部放大图 |
| features | 工艺特征 | 螺纹、孔、倒角、圆角、拔模角 |
| tech_req | 技术要求 | 热处理、表面处理、未注公差 |
| drafting | 制图规范 | 图层/线型/线宽、字体字号、符号标准 |
| assembly | 装配图专项 | 序号/明细表(BOM)、配合代号、焊接符号 |
| revision | 版本与变更 | 版本号、变更记录 |

> 勾选检查项后，系统自动启用映射的 Baseline 规则；`/api/rules` 返回完整规则库（含规则 ID/严重度/执行方式/finding_type/Override 标记/企业自定义规则）。

## 输出文件结构

```
图纸文件夹/
├── 零件A.pdf
├── 零件A_审核报告.md          # 单张详细报告（含启用规则清单/确定性计算结果/结构化问题）
├── 零件A_audit_result.json    # 单张结构化数据
├── 装配图.pdf
├── 装配图_审核报告.md
├── 装配图_audit_result.json
├── _审核汇总_20260830_143022.md   # 批量汇总
└── _audit_batch_20260830_143022.json
```

## 项目结构

```
2d-drawing-auditor/
├── main.py                  # FastAPI 主入口（含 GET /api/rules 规则库接口）
├── config.py                # 全局配置（Baseline + Override + Custom 规则加载/生效）
├── baseline_rules.py        # Baseline V1.0：28 条规则 + 全局审核原则 + finding_type 枚举
├── custom_rules.py          # 企业扩展：CUSTOM_OVERRIDES + CUSTOM_BASELINE_RULES
├── requirements.txt         # Python 依赖
├── 2d-audit-start.bat       # Windows 一键启动
├── README.md
├── frontend/
│   └── index.html           # 单文件前端应用（含规则库面板）
├── backend/
│   ├── __init__.py
│   ├── models.py            # 数据模型（IssueItem 结构化字段 + FindingType 枚举）
│   ├── pdf_processor.py     # PDF 处理（文本提取 + 分块渲染）
│   ├── rule_checker.py      # 规则前置检查（正则校验，映射 Baseline ID）
│   ├── rule_engine.py       # 确定性规则引擎（DFM-001/002、GDT-001）
│   ├── ai_auditor.py        # AI 审核引擎（两轮：分块 Hybrid + 跨视图综合）
│   ├── report_writer.py     # 报告生成（MD + JSON）
│   └── task_manager.py      # 任务管理（10 步流水线 + SQLite）
└── data/
    └── audit_history.db     # 审核历史数据库
```

## 技术架构

```
浏览器 (前端 HTML/JS)
    │  HTTP + WebSocket
    ▼
FastAPI 后端 (Python)
    ├── PDF 处理 (PyMuPDF)
    │   ├── 矢量文本提取
    │   └── 智能分块渲染
    ├── 规则体系 (Baseline V1.0)
    │   ├── baseline_rules.py    # 28 条规则定义
    │   ├── custom_rules.py      # 企业 Override/Custom
    │   ├── config.py            # 规则加载/优先级/生效
    │   ├── rule_engine.py       # ⑤ 确定性计算
    │   ├── rule_checker.py      # 正则前置检查
    │   └── ai_auditor.py        # ⑥⑦ Hybrid + AI 综合审核
    ├── 报告生成 (Markdown + JSON)
    └── 任务管理 (asyncio + SQLite)
```

## 常见问题

**Q: 提示"未配置 AI_API_KEY"怎么办？**
A: 请先设置环境变量 `AI_API_KEY`，然后重启服务。没有 API Key 时进入演示模式，AI 返回模拟数据，可用于测试完整流程。

**Q: 支持哪些 PDF？**
A: 支持矢量 PDF（CAD 导出）和扫描件 PDF。矢量 PDF 会先提取文本做规则检查（含 DFM 深孔/边距等确定性计算），扫描件完全依赖 AI 视觉识别。

**Q: 如何启用企业自定义规则？**
A: 编辑 `custom_rules.py` 中的 `CUSTOM_OVERRIDES`（覆盖 Baseline 参数/严重度）和 `CUSTOM_BASELINE_RULES`（新增企业规则），保存后重启服务。规则优先级：Project > Customer > Company > Baseline。

**Q: 审核一张图纸需要多久？**
A: 取决于图纸复杂度和切片数量，通常 10-30 秒/张。可通过 `AUDIT_CONFIG.max_concurrent_files` 调整并发数。

**Q: 报告保存在哪里？**
A: 每张图纸的报告保存在该 PDF 同目录下，文件名格式为 `<原名>_审核报告.md`。批量汇总保存在文件夹根目录。

## License

MIT

