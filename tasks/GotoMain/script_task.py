# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_battle, page_main
from module.exception import TaskEnd
from module.logger import logger


class ScriptTask(GameUi):

    def run(self) -> None:
        current_page = self.ui_get_current_page()
        if current_page == page_battle:
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
