"""Reviewed 日常训练 coordinates for the temporary 修行合训爬塔 task."""

from module.atom.click import RuleClick
from module.atom.ocr import RuleOcr

from tasks.XiuxingHexun.assets import XiuxingHexunAssets


class XiuxingHexunClimbAssets(XiuxingHexunAssets):
    """Reuse courtyard/battle assets and add only the daily-training controls."""

    # The title is stable while the reward artwork and stamina amount are not.
    I_DAILY_HOME = RuleOcr(
        roi=(120, 0, 280, 70),
        area=(120, 0, 280, 70),
        # Full mode checks that the keyword occurs anywhere in the title crop,
        # which is more tolerant of decorative spacing than exact Single OCR.
        mode="Full",
        method="Default",
        keyword="日常训练",
        name="xiuxing_climb_daily_home",
    )
    I_DAILY_ENTRY = RuleOcr(
        # Vertical 日常训练 tab on the left side of 武道大会.
        roi=(155, 185, 105, 190),
        area=(155, 185, 105, 190),
        mode="Single",
        method="Default",
        keyword="日常训练",
        name="xiuxing_climb_daily_entry",
    )

    # Only the right-side ticket count is read.  The orange stamina amount on
    # the left is intentionally outside this ROI.
    O_DAILY_TICKET_COUNT = RuleOcr(
        roi=(1135, 0, 105, 58),
        area=(1135, 0, 105, 58),
        mode="Digit",
        method="Default",
        keyword="",
        name="xiuxing_climb_daily_ticket_count",
    )

    # 日常训练 uses a reward modal that can omit the generic victory title
    # and render the bottom "点击屏幕继续" prompt too faintly for OCR.  The
    # centered 获得奖励 title is stable across reward artwork variants and
    # is used only as a positive guard before the bounded bottom tap.
    I_DAILY_REWARD = RuleOcr(
        # Keep the crop on the centered 获得奖励 title.  Full-mode OCR would
        # treat any text in the broad modal crop as a match (for example the
        # 玉藻前 description on the 日常训练 home page).
        roi=(450, 130, 380, 110),
        area=(450, 130, 380, 110),
        mode="Single",
        method="Default",
        keyword="获得奖励",
        name="xiuxing_climb_daily_reward",
    )

    C_DAILY_ENTRY = RuleClick(
        roi_front=(165, 215, 65, 115),
        roi_back=(165, 215, 65, 115),
        name="XIUXING_CLIMB_DAILY_ENTRY",
    )
    C_DAILY_CHALLENGE = RuleClick(
        # Only sample the solid center of the large bottom-right 挑战 button;
        # the upper part of its visual ROI is transparent background and a
        # random click there leaves 日常训练 unchanged.
        roi_front=(1150, 585, 80, 70),
        roi_back=(1150, 585, 80, 70),
        name="XIUXING_CLIMB_DAILY_CHALLENGE",
    )
