# 本地 NOI 大纲查询

仓库根目录 PDF 的文字提取结果保存于 `resources/noi-syllabus-2025.index.json`，不写入训练 data。

```powershell
python .agents/skills/acm-coach/scripts/noi_adapter.py build
python .agents/skills/acm-coach/scripts/noi_adapter.py search 点分治
python .agents/skills/acm-coach/scripts/noi_adapter.py search 分治 --limit 3
```

Python 接口：`build_index(pdf_path=DEFAULT_PDF, index_path=None)`；`search(query, pdf_path=None, limit=10, index_path=None)`。查询返回匹配页面完整原文、物理页码（从 1 开始）、提取方法、PDF 绝对路径、SHA256 和版次原文证据。仅做忽略空白和大小写的字面匹配；无命中不能推出该知识点不属于某级别，也不自动把同义概念归类。

搜索仅需 Python 标准库及现有索引。查询时核对源 PDF 路径和 SHA256；文件改变、源文件不存在、索引版本未知都会报错，必须显式重建。版次仅来自页面文字，不从文件名推断。首次构建优先使用 PATH 中 `pdftotext`；若不存在，调用已有 Python 的 `pypdf`。缺少文本层的页面调用 `pypdfium2` 渲染，再用本地 glm-ocr 脚本经 Ollama 提取文字。扫描/轮廓字 PDF 的 OCR 可能误字、漏字、打乱表格；需要精确引用时应对照对应 PDF 页面。

公开包不附带源 PDF 或全文索引；请自行准备有权使用的源文件。

可用 `NOI_PDF_PYTHON` 指定已装 pypdf/pypdfium2 的 Python，`NOI_OCR_SCRIPT` 指定本地 glm-ocr 脚本。Ollama 不可用时构建失败，已有索引保持不变。不会联网下载包、调用远程 OCR 或自动安装依赖。

版次证据是 PDF 封面的“竞赛大纲（2025年修订版）”。物理页码与页脚印刷页码可能不同。保留每页完整 OCR 结果，不把模型扩写内容混入原文。

## 可选：使用当前模型自身的读图能力 OCR

需要对扫描版 PDF 做 OCR 时，Agent 必须先询问用户并等待明确选择，例如：“这份 PDF 需要 OCR。你希望用本地 GLM-OCR，还是用当前模型自身的读图能力？后者会将页面图像交给当前模型处理。”已有针对本文件的明确选择可直接沿用；沉默、失败重试或本地工具缺失都不算同意。不要为了执行此方法擅自安装依赖。

用户选择模型读图后：

1. 记录源 PDF 的 SHA256（可用 Python hashlib），用可用的 PDF 工具读取真实物理页数并逐页渲染为清晰图片。PDF 渲染按客户端可用工具/相关 PDF skill 操作；本方法不需要本地 GLM-OCR 或 Ollama，但仍需要 PDF 渲染能力。没有可用工具时说明缺少什么，不伪造页数或识别结果。
2. 当前模型亲自查看每页图片，按页完整转录原文，保留标题、编号、公式与表格关系。不能凭文件名、上下文或算法常识补字；无法辨认处标记 `[无法辨认]`，空白页写 `[空白页]`，必要时重新查看局部放大图。逐页核对，不能仅看封面就声称处理完成。若部分页面无法完成，保留暂存文件并明确报告，不能导入完整索引。
3. 将结果保存到 `tmp/noi-model-ocr.json`，格式如下。`page_count` 必须是真实总页数，`pages` 按物理页码从 1 开始包含全部页面，不能用示例代替实际内容：

```json
{
  "schema_version": 1,
  "sha256": "实际源 PDF 的 SHA256",
  "page_count": 2,
  "pages": [
    {"page": 1, "text": "第一页实际转录文字"},
    {"page": 2, "text": "第二页实际转录文字"}
  ]
}
```

4. 仅在用户已明确同意且全部页面核对完毕后运行：

```powershell
python .agents/skills/acm-coach/scripts/noi_adapter.py import-model-ocr --transcript tmp/noi-model-ocr.json --user-approved
```

CLI 只负责校验并导入，不能自己调用当前聊天模型看图。它检查同意标志、PDF 哈希和所声明页数的连续完整性；真实总页数、转录准确性及用户是否同意仍由 Agent 核实，不能把参数当作自行批准。校验失败保留旧索引；成功索引注明 model vision OCR，并沿用查询命令。OCR 可能误识别，精确引用仍需核对 PDF 原页。临时转录文件、PDF 与索引均不应提交公开仓库。
