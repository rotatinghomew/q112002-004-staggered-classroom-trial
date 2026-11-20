# 提示时点轮换试行资料

`week` 表示轮次，`day` 是内部统一日历。每个区组各有两个班，两者中一个分派先独立，另一个是比较班；不同区组独立抽签。`assignment` 中是已经公布的结果。未公布轮次的几份排课方案均来自同一份尚待抽签的名单，不把名单本身当分派。
`contacts` 记可能令其他班接触试行流程的联合教学事件；跨班老师与共同活动是排期风险。对学生的实际流程交付有单独的 `delivery` 回执；学生可在发生的当周换课，原分派仍按抽签里的首班。
`observations` 测验分值 0–10，关闭日含当日；取消首场后，补开窗口取登记中最后发布的有效关闭日。下一轮候选方案包含未公布班级、区组、老师和计划讨论搭档；每班人数是符合随访资格的首班学生数。

## 资料格式

资料是匿名合成登记，不包含真实学生、真实成绩或外部访问地址。UTF-8 JSON，每张表是对象数组；`null` 表示该字段无已知值。`records/catalog.json` 记录每张表的字段。

- `assignment`：锁定随机分派。 字段：`week`、`block`、`room`、`assigned`、`published`。
- `enrollment`：轮次首班名册。 字段：`student`、`room`、`cohort`。
- `contacts`：实际发生的跨班接触；计划校务安排在候选表。 字段：`week`、`day`、`room`、`other`、`kind`。
- `moves`：实际转班及到达日。 字段：`student`、`to_room`、`day`。
- `delivery`：学生的实际交付，仅存在于收到记录的人。 字段：`student`、`day`、`independent_first`。
- `windows`：补开上报前取消的窗口不具备有效结果。 字段：`room`、`day`、`open_day`、`close_day`、`state`。
- `observations`：统一无辅助测验记录。 字段：`student`、`day`、`score`。
- `proposals`：候选下一轮名单，partner 为空表示无联合讨论。 字段：`proposal`、`room`、`block`、`teacher`、`partner`、`eligible`。

## 本地查看

使用 Python 3.11 标准库，无需安装包。用 `python3 record_reader.py` 检查并列出收到的表行数；也可传入同格式资料目录。用 `python3 -m unittest discover -s tests -v` 检查资料契约。读取入口不会计算分析结果。

分析入口是 `trial_analysis.py`：`python3 -I trial_analysis.py` 打印按锁定分派的区组估计、缺测边界、
接触审计、下一轮名单分级与功效；`--json` 输出机器可读结果。口径与结论见 `SUMMARY.md`。
