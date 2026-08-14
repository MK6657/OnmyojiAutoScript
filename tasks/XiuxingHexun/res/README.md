# 修行合训资源

资源由 Coordinate Calibrator 从 MuMu 2301 的 `1280x720` Nemu IPC 画布采集，原始帧保存在 `captures/`，裁剪模板保存在本目录。

所有当前模板都经过人工核对并已写入 `assets.py`。模板只识别稳定页面锚点，不识别具体御灵或动态伤害数字。

## 标注约定

请在独立的“修行合训标注”工作区中使用以下语义名。`click` 使用点标注，`roiFront` 和 `roiBack` 使用矩形标注，票据数字和无票提示使用 `ocr` 矩形标注：

- `courtyard_access`, `activity_entry`, `activity_home_search`, `own_discovered_card`, `team_preset`, `preset_deploy`
- `start_challenge`, `prepare`, `continue`
- `courtyard`, `activity_hub`, `activity_home`, `own_discovered_badge`, `search_available`, `challenge_page`, `preset_page`, `battle_result`
- `ticket_count`, `preset_group`, `preset_team`, `result_continue`

流程先判断搜寻按钮是否可用。搜寻成功后会生成左侧卡片，只有带 `自己发现` 标记的第一张卡片才允许点击进入挑战。搜寻不可用时同样只恢复这张自己发现卡片；没有该标记的卡片视为队友发现，任务不会点击。票据只读活动主页左侧的免费数量 `56/55/...` 所在区域。右侧付费或任务票据，以及标注 08、09 的辅助区域，保留在标注工作区供后续人工复核，但任务代码不会读取或点击它们。

票数是辅助证据，不要求单调递减；击杀可能掉落额外票，OCR 也可能偶发误读。只有搜寻不可用、没有 `自己发现` 卡片，并且活动主页上的免费票连续三次读为 `0` 时，任务才会正常结束。零票复核期间读到非零、离开活动主页或读数不稳定，均不会被当作资源耗尽。

最后一张免费票时，搜寻按钮可能仍匹配到旧模板但点击不产生卡片。此时任务会重新确认活动主页和免费票；只有没有 `自己发现` 卡片且连续三次为 `0` 才走正常完成，付费票不会被自动切换或使用。

标注器保持 OAS 写回关闭；导出的 `oas_candidate` 只作为审核记录，最终资源由任务目录人工转换。旧的“坐标标注工作区”未删除或覆盖。
