"""Reviewed coordinate and recognition assets for 修行合训.

The source screenshots are kept under ``res/captures`` for later re-review.
The small templates below are deliberately tied to stable labels and controls;
dynamic ticket counts and enemy artwork are not used as page identity.
"""

from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr


class XiuxingHexunAssets:
    # Page anchors.
    I_COURTYARD = RuleImage(
        roi_front=(290, 339, 100, 115),
        roi_back=(150, 250, 400, 300),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/courtyard_wu_entry_latest.png",
    )
    I_COURTYARD_ALT = RuleImage(
        roi_front=(425, 415, 100, 115),
        roi_back=(350, 330, 260, 260),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/courtyard_wu_entry.png",
    )
    I_ACTIVITY_HUB = RuleImage(
        roi_front=(145, 0, 180, 62),
        roi_back=(95, 0, 360, 120),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/courtyard_wudao_title.png",
    )
    I_ACTIVITY_ENTRY = RuleImage(
        roi_front=(1090, 250, 100, 180),
        roi_back=(1000, 190, 220, 320),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/activity_entry.png",
    )
    I_ACTIVITY_HOME = RuleImage(
        roi_front=(145, 0, 190, 65),
        roi_back=(100, 0, 330, 110),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/activity_home_title.png",
    )

    # The first left card is actionable only when it carries the explicit
    # "自己发现" ribbon.  A plain card may belong to a teammate and must not
    # be opened by this task.
    I_OWN_DISCOVERED_BADGE = RuleImage(
        roi_front=(205, 58, 83, 67),
        roi_back=(150, 20, 180, 180),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/own_discovered_badge.png",
    )
    I_SEARCH_AVAILABLE = RuleImage(
        roi_front=(1108, 582, 104, 92),
        roi_back=(1060, 545, 180, 150),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/search_button.png",
    )

    # After 搜寻 the client opens 收服御灵 directly.  The result-card state
    # is retained as an alias for compatibility with the original task plan.
    I_CHALLENGE_PAGE = RuleImage(
        roi_front=(535, 50, 200, 75),
        roi_back=(430, 20, 400, 180),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/challenge_page_title.png",
    )
    I_SEARCH_RESULT = I_CHALLENGE_PAGE
    I_BATTLE_ENTRY = I_CHALLENGE_PAGE

    # The monthly group label is stable even when the selected enemy changes.
    I_PRESET_PAGE = RuleImage(
        # The 2301 client opens the preset panel at the right-center of the
        # daily-training page.  Keep the search ROI around the actual
        # 每月活动 tab; the previous y=360 crop started below the tab and
        # could never confirm that the panel was open on this layout.
        roi_front=(535, 319, 125, 75),
        roi_back=(500, 280, 220, 170),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/preset_group_monthly.png",
    )
    I_PRESET_TEAM = RuleImage(
        # The monthly group can show another preset card in the first row;
        # the configured 修行合训 card is currently rendered in the second
        # row on MuMu 2301.  Keep the fast crop on that row and let the
        # fallback search cover the whole two-row panel for layout variants.
        roi_front=(700, 285, 280, 80),
        roi_back=(650, 150, 450, 270),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/preset_team_hexun.png",
    )
    I_PREPARE = RuleImage(
        roi_front=(1110, 520, 160, 160),
        roi_back=(1050, 450, 230, 250),
        threshold=0.75,
        method="Template matching",
        file=(
            "./tasks/XiuxingHexun/res/battle_prepare_button.png|"
            "./tasks/XiuxingHexun/res/battle_prepare_button_latest.png"
        ),
    )
    I_RESULT = RuleImage(
        roi_front=(660, 70, 360, 220),
        roi_back=(550, 20, 600, 330),
        threshold=0.8,
        method="Template matching",
        file="./tasks/XiuxingHexun/res/battle_result_victory_title.png",
    )

    # Ticket policy: read only the free ticket number on the left.  The paid
    # resource on the right and the 08/09 annotation areas are never read or
    # clicked by the task.
    O_TICKET_COUNT = RuleOcr(
        roi=(970, 5, 55, 42),
        area=(970, 5, 55, 42),
        mode="Digit",
        method="Default",
        keyword="",
        name="xiuxing_free_ticket_count",
    )
    O_NO_TICKET = O_TICKET_COUNT
    O_PRESET_GROUP = RuleOcr(
        roi=(535, 319, 125, 75),
        area=(535, 319, 125, 75),
        mode="Single",
        method="Default",
        keyword="每月活动",
        name="xiuxing_preset_group",
    )
    O_PRESET_TEAM = RuleOcr(
        # Both visible team rows belong to the selected group.  Keep one
        # bounded ROI so a caller can verify either row (爬塔222 is on the
        # first row; 【修行合训】顶配 is on the second row in 2301).
        roi=(660, 145, 420, 205),
        area=(660, 145, 420, 205),
        mode="Single",
        method="Default",
        keyword="修行合训",
        name="xiuxing_preset_team",
    )
    O_RESULT_CONTINUE = RuleOcr(
        roi=(540, 670, 220, 45),
        area=(540, 670, 220, 45),
        mode="Single",
        method="Default",
        keyword="点击屏幕继续",
        name="xiuxing_result_continue",
    )

    # Click areas are intentionally broad enough for animation, but remain
    # inside the reviewed control rather than using full-screen random clicks.
    C_COURTYARD_ACCESS = RuleClick(
        roi_front=(290, 339, 100, 115),
        roi_back=(290, 339, 100, 115),
        name="XIUXING_COURTYARD_WU",
    )
    C_COURTYARD_ACCESS_ALT = RuleClick(
        # The recognition crop also contains the character and the stool.
        # Sample only the circular 武 control so a random click cannot land
        # on the surrounding courtyard scene.
        roi_front=(447, 418, 42, 42),
        roi_back=(447, 418, 42, 42),
        name="XIUXING_COURTYARD_WU_ALT",
    )
    C_ACTIVITY_ENTRY = RuleClick(
        roi_front=(1095, 270, 75, 170),
        roi_back=(1095, 270, 75, 170),
        name="XIUXING_ACTIVITY_ENTRY",
    )
    C_SEARCH = RuleClick(
        # The left and right arrow decorations do not trigger 搜寻.  Sample
        # only the center label area of the wooden search button.
        roi_front=(1110, 585, 100, 85),
        roi_back=(1110, 585, 100, 85),
        name="XIUXING_SEARCH",
    )
    C_OWN_CARD = RuleClick(
        # Click inside the top-left card body, never on a teammate card below
        # it.  The card is accepted only after I_OWN_DISCOVERED_BADGE matches.
        roi_front=(20, 95, 245, 90),
        roi_back=(20, 95, 245, 90),
        name="XIUXING_OWN_DISCOVERED_CARD",
    )
    C_TEAM_PRESET = RuleClick(
        # Keep the sampled point on the 队伍预设 icon, away from 协战 and
        # the label row below it.  The previous 48x52 ROI reached the label
        # baseline; random sampling could land at y=633 and miss the icon.
        roi_front=(910, 590, 30, 30),
        roi_back=(910, 590, 30, 30),
        name="XIUXING_TEAM_PRESET",
    )
    C_PRESET_GROUP_MONTHLY = RuleClick(
        # Activity preset panels remember the last selected group.
        roi_front=(545, 322, 105, 48),
        roi_back=(545, 322, 105, 48),
        name="XIUXING_PRESET_GROUP_MONTHLY",
    )
    C_PRESET_DEPLOY = RuleClick(
        # Keep every sampled point inside the orange 出战 button.  The
        # surrounding panel accepts no click, so a broad ROI can look like
        # a successful action while leaving the preset page open.
        roi_front=(800, 477, 115, 40),
        roi_back=(800, 477, 115, 40),
        name="XIUXING_PRESET_DEPLOY",
    )
    C_PRESET_TEAM_TOP = RuleClick(
        # First team card in 每月活动 (currently 爬塔222).  Do not sample
        # the card's upper/right controls: those open the preset detail
        # dialog instead of selecting the card for deployment.
        roi_front=(680, 195, 220, 35),
        roi_back=(680, 195, 220, 35),
        name="XIUXING_PRESET_TEAM_TOP",
    )
    C_PRESET_TEAM_BOTTOM = RuleClick(
        # Second team card in 每月活动 (currently 【修行合训】顶配), with
        # the same safe body-only click area.
        roi_front=(680, 295, 220, 35),
        roi_back=(680, 295, 220, 35),
        name="XIUXING_PRESET_TEAM_BOTTOM",
    )
    C_START_CHALLENGE = RuleClick(
        roi_front=(1070, 520, 145, 150),
        roi_back=(1070, 520, 145, 150),
        name="XIUXING_START_CHALLENGE",
    )
    C_CONTINUE = RuleClick(
        roi_front=(540, 650, 230, 70),
        roi_back=(540, 650, 230, 70),
        name="XIUXING_CONTINUE",
    )
