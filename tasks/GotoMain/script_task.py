# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

import time

from module.atom.ocr import RuleOcr
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_battle, page_main
from module.exception import TaskEnd
from module.logger import logger


class ScriptTask(GameUi):

    # 日常训练结算页在低帧率下常常只保留中间的“获得奖励”标题，底部
    # “点击屏幕继续”会短暂漏掉 OCR。这个标题只作为 page_battle 下的
    # 正向证据，绝不会在普通活动页盲点。
    O_DAILY_REWARD_TITLE = RuleOcr(
        roi=(450, 130, 380, 110),
        area=(450, 130, 380, 110),
        mode="Single",
        method="Default",
        keyword="获得奖励",
        name="goto_main_daily_reward_title",
    )

    def _consume_result_overlay(self, max_clicks: int = 3) -> bool:
        """Dismiss only an explicitly recognized result continuation page."""
        ocr_visible = getattr(self, "ocr_appear", None)
        ocr_click = getattr(self, "ocr_appear_click", None)
        device = getattr(self, "device", None)
        screenshot = getattr(self, "screenshot", None)
        if not callable(ocr_visible) or device is None:
            return False

        clicks = 0
        for _ in range(max(1, int(max_clicks))):
            if callable(screenshot):
                screenshot()
            clicked = False
            try:
                prompt_visible = bool(
                    ocr_visible(GeneralBattleAssets.O_BATTLE_RESULT_CONTINUE)
                )
            except Exception:
                prompt_visible = False
            if prompt_visible and callable(ocr_click):
                try:
                    clicked = bool(
                        ocr_click(
                            GeneralBattleAssets.O_BATTLE_RESULT_CONTINUE,
                            interval=0.5,
                        )
                    )
                except Exception:
                    clicked = False

            # The reward title is a second, task-independent guard for the
            # faint-prompt frame. Tap the known bottom strip only after that
            # title was recognized; never use a blind random click here.
            if not clicked and not prompt_visible:
                try:
                    reward_visible = bool(ocr_visible(self.O_DAILY_REWARD_TITLE))
                except Exception:
                    reward_visible = False
                if reward_visible:
                    device.click(
                        x=640,
                        y=675,
                        control_name="GOTOMAIN_RESULT_CONTINUE_BOTTOM",
                    )
                    clicked = True

            if not clicked:
                break
            clicks += 1
            time.sleep(0.35)

        if clicks:
            logger.info(
                f"GotoMain consumed battle result continuation clicks={clicks}"
            )
        return clicks > 0

    def run(self) -> None:
        current_page = self.ui_get_current_page()
        if current_page == page_battle:
            consume_overlay = getattr(self, "_consume_result_overlay", None)
            if callable(consume_overlay) and consume_overlay():
                # The activity page is intentionally left where the task put
                # it. A blind ui_goto(page_main) would treat the unregistered
                # 日常训练 page as unknown and start the same loop again.
                raise TaskEnd.completed(
                    "Battle result overlay dismissed; left current activity page",
                )
            logger.warning(
                'GotoMain skipped: current page is page_battle; '
                'leave the active battle/result page untouched'
            )
            raise TaskEnd.aborted(
                'Goto main skipped on active battle page',
                outcome='active_unconfirmed',
            )
        self.ui_goto(page_main)
        raise TaskEnd.completed('Goto main end')
