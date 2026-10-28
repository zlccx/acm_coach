# ACM Coach workspace

此仓库同时存放算法学习 Skill 与用户训练数据。

- 训练、题单、算法教学请求读取 `.agents/skills/acm-coach/SKILL.md`；继续编号任务先用其 `resume` 命令，不全量读取 data。
- 修改实现时运行 `python -m unittest discover -s tests -v`。测试使用临时目录，不能把虚假训练或测试 AC 写入真实 data。
- 教学保留在独立交互会话，不能委派 subagent。资源研究可按需委派。
- 不把模型推测写成用户思路，不擅自修改用户目标，不覆盖人工知识笔记。
- 只用标准库；未知数据版本不自动迁移，真实数据修改经持久化脚本。
