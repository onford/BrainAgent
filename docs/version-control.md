# 版本管理

源码仓库跟踪代码、Schema、报告模板、测试和维护文档。每完成一版可用修改即提交；删除的实现及修改说明通过 `git log`、`git show`、`git diff` 查阅，不以 `_old`、`_backup`、`v2` 旁路目录保留在当前产品中。Schema 的版本字段用于格式校验，属于正式契约。

报告和记录采用唯一正式路径，例如 `survey/local-inspection.json`、`survey/local-events.tsv`、`survey/reports/data-information.html`。报告展示数据来源、检查时间和科学限制；不包含代码修补说明。重新生成时同步检查引用、清单哈希和下载包。

## 跟踪范围

| 内容 | 保存位置 |
| --- | --- |
| 代码、Schema、模板、测试、配置样例 | 源码 Git 仓库 |
| `.env` 及本地密钥配置 | 本地文件，Git 忽略；`.env.example` 等样例保留跟踪 |
| 原始数据、工作流输出、数据库、日志 | `data/`、`workspace/` 等运行目录，源码 Git 忽略 |
| 依赖、工具、构建和测试缓存 | 本地目录，Git 忽略 |
| 已发布运行中需要修订的记录、报告、清单和交付包 | 修订前后提交到独立本地 Git 历史，Git 元数据放在 `.local/artifact-history/<运行ID>.git`，工作目录仍为该运行目录 |

本地产物历史没有远程地址。只跟踪需要修订及还原的文件，不重复纳入原始 EEG 和未修改的中间信号数组；这些文件由运行清单中的输入与输出哈希定位。修订完成后，工作目录只保留当前正式产物，Git 历史保留此前内容。

查看某次运行的本地历史（从项目根目录执行）：

```powershell
git --git-dir=.local/artifact-history/<运行ID>.git log --oneline
git --git-dir=.local/artifact-history/<运行ID>.git show <提交>:survey/local-inspection.json
git --git-dir=.local/artifact-history/<运行ID>.git diff <旧提交> <新提交> -- survey/
```

`.gitignore` 排除依赖、数据、运行状态、缓存和编辑器/合并残留，不笼统忽略 JSON、TSV、HTML 或图片等可能属于源码、测试或模板的文件。`.gitattributes` 统一文本换行，并标记常见数据二进制格式。检查忽略规则使用 `git check-ignore -v <路径>`；已跟踪文件不会被新增的 ignore 规则自动移出 Git。
