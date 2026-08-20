# 修行合训爬塔（临时）

此目录是活动期间在「武道大会 → 日常训练」页面使用的临时任务。

- 只读取右上角票数；左侧体力不参与判断。
- `max_challenges` 默认 1，设为 0 才会一直挑战到票数稳定为 0。
- 战斗、队伍预设和低帧率自动模式均复用现有通用组件。

活动结束后下架：删除本目录，并移除 `ConfigModel`、`ConfigMenu`、
`ConfigManual`、中文标签、Bridge 标签和 `config/template.json` 中的注册项。
