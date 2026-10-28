# 浏览器与 web search 保底路径

不依赖账号 cookie 复制、隐藏 API 或自动绕过风控。脚本返回失败、未命中、范围太窄或页面结构变化时，保留实际错误，并继续以下路径。浏览器本身不可用再用 web search；均不可用时明确待验证，不编造资源。

## 获取查询入口

`coach resource-fallback <site> <关键词>` 只生成计划，verification=fallback_plan_only；不是执行了浏览器搜索。

- 洛谷：`https://www.luogu.com.cn/problem/list` 的“算法、标题或题目编号”框。题单入口 `/training/list`。文章 `/article`；日报 `/article/collection/1` 的“搜索文章”框。填好后 Enter，等待 URL/DOM 更新。已验证的 URL 参数为 `keyword=...`、`page=...`，题目另有 `type=all`。
- 洛谷日报必须来自合集 1 或文章元数据 collection.id=1；普通博客不能只因内容好就标日报。
- AcWing：主页的全站搜索入口，以及 `/file_system/search_engine/web_all/result/index/?search_type=web_entry_all&search_content=...`。该入口在 Chrome 中实际验证过。脚本课程目录找不到文章时，用浏览器全站搜索或 `site:acwing.com 关键词`。
- OI Wiki：主页目录和页面搜索 UI；或 `site:oi-wiki.org 点分治`。导航标题和正文可能名称不同，搜索“分治”可找到“树分治”。当前 `/search/search_index.json` 实测404，不反复盲试该接口。
- NOI：已有本地索引时直接查询；需精确引用或 OCR 异常时打开源 PDF 的对应物理页核对。无字面命中可尝试较宽关键词，不能推断某知识点不在大纲。

## 浏览器提取脚本

`scripts/browser_extract.js` 是自包含函数，运行于已经打开的目标页。适用 Chrome DevTools 的 `evaluate_script`（其他浏览器工具仅在明确允许同类 DOM 操作时用）；先列出页面并确认 pageId，再读文件全文作为 `function` 参数，`waitForStableDom=false`。函数默认 research；严格题面传 `args: ["strict"]`。不是粘贴到网页输入框，不是 shell 中执行 JS。

输出限定在公开资源白名单：

- 洛谷单题：题面、样例和限制，不含标签、推荐题解、lastCode、bestRecord 或个人 AC。
- 洛谷题单：title/source_url/items/ordering=original，可保存 resource 字段后显式导入。文章：公开 content 与 content_complete 标记。列表：当前 main 的真实资源链接。
- AcWing：仅 `/activity/` 课程目录或 `/activity/content/introduction/数字/` 公开简介；其他路径返回错误，不从已登录受限页提正文。
- OI Wiki：当前 article 的标题与可见正文。

浏览器提取标 `browser_dom_verified`，不冒充公开 HTTP 请求成功。UI 可能通过 SPA 更新 DOM 而初始 JSON 仍旧；单篇/题单校验 ID，不匹配时必须重新导航到确切 URL 后再提取。列表只读当前 DOM 链接。遇登录/验证码/403，不能更改脚本绕过；可让用户正常完成网站交互后读取公开内容，或换公开来源。

## Web search

使用当前可用的搜索工具执行 fallback 中的 `web_search_query`。摘要只是 search_snippet；真正打开候选内容后才 page_verified。核对作者、题号、课程名、题单顺序和是否能访问正文。既保留最初脚本错误，也注明最终验证路径。不要把 web search 提供的缓存片段称为当前网站全文。
