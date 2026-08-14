# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import monotonic, sleep
from cached_property import cached_property

from module.logger import logger
from module.base.timer import Timer
from module.exception import GameStuckError, TaskEnd

from tasks.Component.GeneralInvite.config_invite import InviteConfig, InviteNumber, FindMode
from tasks.Exploration.base import (
    BaseExploration,
    ExplorationBudgetExceeded,
    ExplorationExitReason,
    ExplorationSearchBudget,
    UpType,
    Scene,
)
from tasks.Exploration.config import ChooseRarity, AutoRotate, UserStatus
from tasks.GameUi.page import page_main


class SoloExploration(BaseExploration):
    INVITE_FLAG_OFF = (157, 109, 83)
    INVITE_FLAG_ON = (227, 193, 153)
    explore_init = False

    def _new_map_search_budget(self):
        return ExplorationSearchBudget(
            timeout_seconds=self.MAP_SEARCH_TIMEOUT,
            max_recognitions=self.MAP_SEARCH_MAX_RECOGNITIONS,
            max_swipes=self.MAP_SEARCH_MAX_SWIPES,
        )

    def _record_exploration_swipe_attempt(self, search_budget) -> None:
        """Charge the budget only when a swipe reached the device."""
        if getattr(self, '_exploration_last_swipe_failure', None) in (
            'skipped',
            'control_rejected',
        ):
            return
        search_budget.record_swipe()

    @cached_property
    def _invite_config(self) -> InviteConfig:
        return InviteConfig(
            invite_number=InviteNumber.ONE,
            friend_1=self._config.invite_config.friend_1,
            friend_2='',
            find_mode=self._config.invite_config.find_mode,
            wait_time=self._config.invite_config.wait_time,
            default_invite=False
        )

    def run_solo(self):
        logger.hr('solo')
        search_fail_cnt = 0
        unknown_scene_cnt = 0
        search_budget = self._new_map_search_budget()

        while 1:
            self.screenshot()
            scene = self.get_current_scene()
            if self._discovery_panel_layout_visible() and self._dismiss_discovery_panel():
                search_fail_cnt = 0
                continue
            if scene != Scene.UNKNOWN:
                unknown_scene_cnt = 0
            logger.info(f'[run_solo] Current scene: {scene.name}')  # TODO 2026.06.22 之后删掉这个刷屏的
            #
            if scene == Scene.WORLD:
                # 打开右边箭头
                if not self.wait_world_stable():
                    continue
                if self.appear(self.I_TREASURE_BOX_CLICK):
                    # 宝箱
                    logger.info('Treasure box appear, get it.')
                    self._require_click_workflow(
                        self.ui_click_until_disappear(
                            self.I_TREASURE_BOX_CLICK,
                            timeout=self.CLICK_WORKFLOW_TIMEOUT,
                            max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                        ),
                        'solo_collect_treasure_box',
                    )
                if self.check_exit():
                    break
                self.open_expect_level()
                continue
            #
            elif scene == Scene.ENTRANCE:
                if self.check_exit():
                    break
                self._require_click_workflow(
                    self.ui_click(
                        self.I_E_EXPLORATION_CLICK,
                        stop=self.I_E_SETTINGS_BUTTON,
                        timeout=self.CLICK_WORKFLOW_TIMEOUT,
                        max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                    ),
                    'solo_enter_chapter',
                )
                continue
            #
            elif scene == Scene.MAIN:
                if not self.explore_init:
                    if self._config.exploration_config.auto_rotate == AutoRotate.yes:
                        self.enter_settings_and_do_operations()
                    if not self._ensure_auto_rotate_on():
                        raise GameStuckError('Exploration: auto-rotate state not confirmed')
                    self.explore_init = True
                    continue
                search_budget.record_recognition()
                # 小纸人
                if self.appear(self.I_BATTLE_REWARD):
                    if self.ui_get_reward(
                        self.I_BATTLE_REWARD,
                        timeout=self.CLICK_WORKFLOW_TIMEOUT,
                        max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                    ):
                        continue
                # boss
                if self.appear(self.I_BOSS_BATTLE_BUTTON):
                    if self.fire(self.I_BOSS_BATTLE_BUTTON):
                        search_budget = self._new_map_search_budget()
                        search_fail_cnt = 0
                        logger.info(f'Boss battle, minions cnt {self.minions_cnt}')
                        if self.exit_after_battle_limit():
                            break
                    continue
                # 小怪
                fight_button = self.search_up_fight()
                if fight_button is not None:
                    search_fail_cnt = 0
                    if self.fire(fight_button):
                        search_budget = self._new_map_search_budget()
                        logger.info(f'Fight, minions cnt {self.minions_cnt}')
                        if self.exit_after_battle_limit():
                            break
                    continue
                # 向后拉,寻找怪
                if search_fail_cnt >= 4:
                    if self._confirm_exploration_endpoint():
                        self.quit_explore(reason=ExplorationExitReason.SEARCH_EXHAUSTED)
                        search_budget = self._new_map_search_budget()
                        search_fail_cnt = 0
                        continue
                    swipe_confirmed = self._execute_exploration_swipe(
                        self.S_SWIPE_BACKGROUND_RIGHT,
                        interval=3,
                    )
                    self._record_exploration_swipe_attempt(search_budget)
                    if swipe_confirmed:
                        search_fail_cnt = 0
                        continue
                    if getattr(self, '_exploration_last_swipe_failure', None) in (
                        'unconfirmed', 'control_rejected'
                    ):
                        logger.warning(
                            'Exploration swipe was not confirmed; return to search '
                            'state without treating it as an endpoint'
                        )
                        search_fail_cnt = 0
                        sleep(0.2)
                        continue
                    search_fail_cnt = 3
                else:
                    search_fail_cnt += 1
            #
            elif scene == Scene.BATTLE_PREPARE or scene == Scene.BATTLE_FIGHTING:
                self.check_take_over_battle(is_screenshot=False, config=self._config.general_battle_config)
            elif scene == Scene.UNKNOWN:
                unknown_scene_cnt = self._handle_unknown_scene('solo', unknown_scene_cnt)
                continue

    def run_leader(self):
        logger.hr('leader')
        search_fail_cnt = 0
        unknown_scene_cnt = 0
        friend_leave_timer = Timer(10)
        search_budget = self._new_map_search_budget()

        while 1:
            self.screenshot()
            scene = self.get_current_scene()
            if scene != Scene.UNKNOWN:
                unknown_scene_cnt = 0
            logger.info(f'[run_leader] Current scene: {scene.name}')  # TODO 2026.06.22 之后删掉这个刷屏的
            # 探索大世界
            if scene == Scene.WORLD:
                # 打开右边箭头
                if not self.wait_world_stable():
                    continue
                if self.appear(self.I_TREASURE_BOX_CLICK):
                    # 宝箱
                    logger.info('Treasure box appear, get it.')
                    self.wait_until_stable(self.I_UI_CANCEL, timer=Timer(0.6, 1))
                    reward_deadline = monotonic() + 15.0
                    reward_actions = 0
                    reward_max_actions = 8
                    while monotonic() < reward_deadline:
                        self.screenshot()
                        if self.appear(self.I_REWARD):
                            self._require_click_workflow(
                                self.ui_click_until_disappear(
                                    self.I_REWARD,
                                    timeout=min(
                                        self.CLICK_WORKFLOW_TIMEOUT,
                                        max(0.1, reward_deadline - monotonic()),
                                    ),
                                    max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                                ),
                                'leader_collect_reward',
                            )
                            logger.info('Get reward.')
                            break
                        if reward_actions >= reward_max_actions:
                            self._raise_exploration_click_boundary(
                                'leader_collect_reward',
                                reason='action_budget_exhausted',
                                actions=reward_actions,
                                timeout=15.0,
                                max_actions=reward_max_actions,
                            )
                        if self.ui_reward_appear_click():
                            reward_actions += 1
                            continue
                        if self.appear_then_click(self.I_UI_CANCEL, interval=0.8):
                            reward_actions += 1
                            continue
                        if self.appear_then_click(self.I_TREASURE_BOX_CLICK, interval=1):
                            reward_actions += 1
                            continue
                    else:
                        self._raise_exploration_click_boundary(
                            'leader_collect_reward',
                            reason='page_transition_timeout',
                            actions=reward_actions,
                            timeout=15.0,
                            max_actions=reward_max_actions,
                        )
                if self.check_exit():
                    self.wait_until_stable(self.I_UI_CANCEL, timer=Timer(0.6, 2))
                    if self.appear(self.I_UI_CANCEL):
                        self._require_click_workflow(
                            self.ui_click_until_disappear(
                                self.I_UI_CANCEL,
                                timeout=self.CLICK_WORKFLOW_TIMEOUT,
                                max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                            ),
                            'leader_close_exit_prompt',
                        )
                    break
                if self.appear(self.I_UI_CONFIRM):
                    self._require_click_workflow(
                        self.ui_click_until_disappear(
                            self.I_UI_CONFIRM,
                            timeout=self.CLICK_WORKFLOW_TIMEOUT,
                            max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                        ),
                        'leader_confirm_world_prompt',
                    )
                    # 可以加一下，清空第一次 explore_init
                    continue
                self.open_expect_level()
                # explore_init = False
                continue

            # 邀请好友, 非常有可能是后面邀请好友，然后直接跳到组队了
            elif scene == Scene.ENTRANCE:
                room_deadline = monotonic() + 20.0
                room_actions = 0
                room_max_actions = 8
                while monotonic() < room_deadline:
                    self.screenshot()
                    if self.is_in_room():
                        break
                    if room_actions >= room_max_actions:
                        self._raise_exploration_click_boundary(
                            'leader_create_team_room',
                            reason='action_budget_exhausted',
                            actions=room_actions,
                            timeout=20.0,
                            max_actions=room_max_actions,
                        )
                    if self.appear_then_click(self.I_ENSURE_PRIVATE_FALSE, interval=0.5):
                        room_actions += 1
                        continue
                    if self.appear_then_click(self.I_ENSURE_PRIVATE_FALSE_2, interval=0.5):
                        room_actions += 1
                        continue
                    if self.appear_then_click(self.I_EXP_CREATE_TEAM, interval=1):
                        room_actions += 1
                        continue
                    if self.appear_then_click(self.I_EXP_CREATE_ENSURE, interval=2):
                        room_actions += 1
                        continue
                else:
                    self._raise_exploration_click_boundary(
                        'leader_create_team_room',
                        reason='page_transition_timeout',
                        actions=room_actions,
                        timeout=20.0,
                        max_actions=room_max_actions,
                    )
            #
            elif scene == Scene.TEAM:
                self.wait_until_stable(self.I_ADD_2, timer=Timer(0.8, 1))
                if self.appear(self.I_FIRE, threshold=0.8) and not self.appear(self.I_ADD_2):
                    self._require_click_workflow(
                        self.ui_click_until_disappear(
                            self.I_FIRE,
                            interval=1,
                            timeout=self.CLICK_WORKFLOW_TIMEOUT,
                            max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                        ),
                        'leader_start_room_battle',
                    )
                    continue
                if self.appear(self.I_ADD_2) and self.run_invite(config=self._invite_config, is_first=True):
                    continue
                else:
                    logger.warning('Invite failed, quit')
                    exit_deadline = monotonic() + 20.0
                    exit_actions = 0
                    exit_max_actions = 8
                    while monotonic() < exit_deadline:
                        self.screenshot()
                        if self.is_exploration_world():
                            break
                        if exit_actions >= exit_max_actions:
                            self._raise_exploration_click_boundary(
                                'leader_exit_failed_invite',
                                reason='action_budget_exhausted',
                                actions=exit_actions,
                                timeout=20.0,
                                max_actions=exit_max_actions,
                            )
                        if self.appear_then_click(self.I_UI_CONFIRM, interval=0.5):
                            exit_actions += 1
                            continue
                        if self.appear_then_click(self.I_UI_BACK_RED, interval=0.7):
                            exit_actions += 1
                            continue
                        if self.appear_then_click(self.I_UI_BACK_YELLOW, interval=1):
                            exit_actions += 1
                            continue
                    else:
                        self._raise_exploration_click_boundary(
                            'leader_exit_failed_invite',
                            reason='page_transition_timeout',
                            actions=exit_actions,
                            timeout=20.0,
                            max_actions=exit_max_actions,
                        )
                    break
            ##
            elif scene == Scene.MAIN:
                if not self.explore_init:
                    if self._config.exploration_config.auto_rotate == AutoRotate.yes:
                        self.enter_settings_and_do_operations()
                    self._require_click_workflow(
                        self.ui_click(
                            self.I_E_AUTO_ROTATE_OFF,
                            stop=self.I_E_AUTO_ROTATE_ON,
                            timeout=self.CLICK_WORKFLOW_TIMEOUT,
                            max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                        ),
                        'leader_enable_auto_rotate',
                    )
                    friend_leave_timer = Timer(10)
                    self.explore_init = True
                    continue
                search_budget.record_recognition()
                # 小纸人
                if self.appear(self.I_BATTLE_REWARD):
                    if self.ui_get_reward(
                        self.I_BATTLE_REWARD,
                        timeout=self.CLICK_WORKFLOW_TIMEOUT,
                        max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                    ):
                        continue
                # 中途有人跑路
                if not self.appear(self.I_TEAM_EMOJI):
                    if not friend_leave_timer.started():
                        logger.warning('Mate leave, start timer')
                        friend_leave_timer = Timer(10)
                        friend_leave_timer.start()
                    elif friend_leave_timer.started() and friend_leave_timer.reached():
                        logger.warning('Mate leave timer reached')
                        logger.warning('Exit team')
                        self.quit_explore(reason=ExplorationExitReason.TEAM_MEMBER_LEFT)
                        continue
                else:
                    logger.warning('Team emoji appear again, clear friend_leave_timer')
                    friend_leave_timer = Timer(10)
                # boss
                if self.appear(self.I_BOSS_BATTLE_BUTTON):
                    if self.fire(self.I_BOSS_BATTLE_BUTTON):
                        search_budget = self._new_map_search_budget()
                        search_fail_cnt = 0
                        logger.info(f'Boss battle, minions cnt {self.minions_cnt}')
                        if self.exit_after_battle_limit():
                            break
                    continue
                # 小怪
                fight_button = self.search_up_fight()
                if fight_button is not None:
                    search_fail_cnt = 0
                    if self.fire(fight_button):
                        search_budget = self._new_map_search_budget()
                        logger.info(f'Fight, minions cnt {self.minions_cnt}')
                        if self.exit_after_battle_limit():
                            break
                    continue
                # 向后拉,寻找怪
                if search_fail_cnt >= 4:
                    if self._confirm_exploration_endpoint():
                        self.quit_explore(reason=ExplorationExitReason.SEARCH_EXHAUSTED)
                        search_budget = self._new_map_search_budget()
                        search_fail_cnt = 0
                        continue
                    swipe_confirmed = self._execute_exploration_swipe(
                        self.S_SWIPE_BACKGROUND_RIGHT,
                        interval=4.5,
                    )
                    self._record_exploration_swipe_attempt(search_budget)
                    if swipe_confirmed:
                        search_fail_cnt = 0
                        continue
                    if getattr(self, '_exploration_last_swipe_failure', None) in (
                        'unconfirmed', 'control_rejected'
                    ):
                        logger.warning(
                            'Exploration leader swipe was not confirmed; return to '
                            'search state without treating it as an endpoint'
                        )
                        search_fail_cnt = 0
                        sleep(0.2)
                        continue
                    search_fail_cnt = 3
                else:
                    search_fail_cnt += 1
            #
            elif scene == Scene.BATTLE_PREPARE or scene == Scene.BATTLE_FIGHTING:
                self.check_take_over_battle(is_screenshot=False, config=self._config.general_battle_config)
            elif scene == Scene.UNKNOWN:
                unknown_scene_cnt = self._handle_unknown_scene('leader', unknown_scene_cnt)
                continue

    def run_member(self):
        logger.hr('member')
        wait_timer = Timer(50)
        friend_leave_timer = Timer(10)
        unknown_scene_cnt = 0

        while 1:
            self.screenshot()
            scene = self.get_current_scene()
            if scene != Scene.UNKNOWN:
                unknown_scene_cnt = 0
            logger.info(f'[run_member] Current scene: {scene.name}')  # TODO 2026.06.12 之后删掉这个刷屏的
            #
            if scene == Scene.WORLD:
                # 打开右边箭头
                if not self.wait_world_stable():
                    continue
                if self.appear(self.I_TREASURE_BOX_CLICK):
                    # 宝箱
                    logger.info('Treasure box appear, get it.')
                    self._require_click_workflow(
                        self.ui_click_until_disappear(
                            self.I_TREASURE_BOX_CLICK,
                            timeout=self.CLICK_WORKFLOW_TIMEOUT,
                            max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                        ),
                        'member_collect_treasure_box',
                    )
                if self.check_exit():
                    break
                if self.check_then_accept():
                    pass
                if wait_timer.started() and wait_timer.reached():
                    logger.warning('Wait timer reached')
                    break

                continue
            #
            elif scene == Scene.ENTRANCE:
                self._require_click_workflow(
                    self.ui_click(
                        self.I_UI_BACK_YELLOW,
                        stop=self.I_CHECK_EXPLORATION,
                        timeout=self.CLICK_WORKFLOW_TIMEOUT,
                        max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                    ),
                    'member_return_to_exploration',
                )
            #
            elif scene == Scene.TEAM:
                continue
            #
            elif scene == Scene.MAIN:
                if not self.explore_init:
                    if self._config.exploration_config.auto_rotate == AutoRotate.yes:
                        self.enter_settings_and_do_operations()
                    self._require_click_workflow(
                        self.ui_click(
                            self.I_E_AUTO_ROTATE_OFF,
                            stop=self.I_E_AUTO_ROTATE_ON,
                            timeout=self.CLICK_WORKFLOW_TIMEOUT,
                            max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                        ),
                        'member_enable_auto_rotate',
                    )
                    self.explore_init = True
                    continue
                # 小纸人
                if self.appear(self.I_BATTLE_REWARD):
                    if self.ui_get_reward(
                        self.I_BATTLE_REWARD,
                        timeout=self.CLICK_WORKFLOW_TIMEOUT,
                        max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                    ):
                        continue
                #
                if not self.appear(self.I_TEAM_EMOJI):
                    logger.warning('Team emoji not appear')
                    if not friend_leave_timer.started():
                        logger.warning('Mate leave, start timer')
                        friend_leave_timer = Timer(10)
                        friend_leave_timer.start()
                    elif friend_leave_timer.started() and friend_leave_timer.reached():
                        logger.warning('Mate leave timer reached')
                        logger.warning('Exit team')
                        self.quit_explore(reason=ExplorationExitReason.TEAM_MEMBER_LEFT)
                        wait_timer = Timer(50)
                        wait_timer.start()
                        continue
                else:
                    logger.warning('Team emoji appear again, clear friend_leave_timer')
                    friend_leave_timer = Timer(10)
            #
            elif scene == Scene.BATTLE_PREPARE or scene == Scene.BATTLE_FIGHTING:
                logger.info('[run_member] Handling scene: BATTLE')
                self.check_take_over_battle(is_screenshot=False, config=self._config.general_battle_config)
            elif scene == Scene.UNKNOWN:
                unknown_scene_cnt = self._handle_unknown_scene('member', unknown_scene_cnt)
                continue

    def invite_friend(self, name: str = None, find_mode: FindMode = FindMode.AUTO_FIND) -> bool:
        logger.info('Click add to invite friend')
        # 点击＋号
        open_deadline = monotonic() + 15.0
        open_actions = 0
        open_max_actions = 6
        while monotonic() < open_deadline:
            self.screenshot()
            if self.appear(self.I_LOAD_FRIEND):
                break
            if self.appear(self.I_INVITE_ENSURE):
                break
            if open_actions >= open_max_actions:
                self._raise_exploration_click_boundary(
                    'invite_open_panel',
                    reason='action_budget_exhausted',
                    actions=open_actions,
                    timeout=15.0,
                    max_actions=open_max_actions,
                )
            if self.appear_then_click(self.I_ADD_2, interval=1):
                open_actions += 1
                continue
            if self.appear_then_click(self.I_ADD_5_4, interval=1):
                open_actions += 1
                continue
        else:
            self._raise_exploration_click_boundary(
                'invite_open_panel',
                reason='page_transition_timeout',
                actions=open_actions,
                timeout=15.0,
                max_actions=open_max_actions,
            )

        friend_class = []
        class_ocr = [self.O_F_LIST_1, self.O_F_LIST_2, self.O_F_LIST_3, self.O_F_LIST_4]
        class_index = 0
        list_1 = self.O_F_LIST_1.ocr(self.device.image)
        list_2 = self.O_F_LIST_2.ocr(self.device.image)
        list_3 = self.O_F_LIST_3.ocr(self.device.image)
        list_4 = self.O_F_LIST_4.ocr(self.device.image)
        list_1 = list_1.replace(' ', '').replace('、', '')
        list_2 = list_2.replace(' ', '').replace('、', '')
        list_3 = list_3.replace(' ', '').replace('、', '')
        if list_1 is not None and list_1 != '' and list_1 in self.friend_class:
            friend_class.append(list_1)
        if list_2 is not None and list_2 != '' and list_2 in self.friend_class:
            friend_class.append(list_2)
        if list_3 is not None and list_3 != '' and list_3 in self.friend_class:
            friend_class.append(list_3)
        if list_4 is not None and list_4 != '' and list_4 in self.friend_class:
            friend_class.append(list_4)
        for i in range(len(friend_class)):
            if friend_class[i] == '蔡友':
                friend_class[i] = '寮友'
            elif friend_class[i] == '路区':
                friend_class[i] = '跨区'
            elif friend_class[i] == '察友':
                friend_class[i] = '寮友'
            elif friend_class[i] == '区':
                friend_class[i] = '跨区'
        logger.info(f'Friend class: {friend_class}')

        is_select: bool = False  # 是否选中了好友
        if find_mode == FindMode.RECENT_FRIEND:
            logger.info('Find recent friend')
            # 获取’最近‘在friend_class中的index
            if '最近' not in friend_class:
                logger.warning('No recent friend')
                return False
            recent_index = friend_class.index('最近')
            if recent_index == 1:
                recent_deadline = monotonic() + 8.0
                recent_actions = 0
                recent_max_actions = 4
                while monotonic() < recent_deadline:
                    self.screenshot()
                    if self.appear(self.I_FLAG_2_ON):
                        break
                    if recent_actions >= recent_max_actions:
                        self._raise_exploration_click_boundary(
                            'invite_select_recent',
                            reason='action_budget_exhausted',
                            actions=recent_actions,
                            timeout=8.0,
                            max_actions=recent_max_actions,
                        )
                    if self.appear_then_click(self.I_FLAG_2_OFF, interval=1):
                        recent_actions += 1
                        continue
                else:
                    self._raise_exploration_click_boundary(
                        'invite_select_recent',
                        reason='page_transition_timeout',
                        actions=recent_actions,
                        timeout=8.0,
                        max_actions=recent_max_actions,
                    )

            logger.info(f'Now find friend in ”最近“')
            sleep(1)
            if not is_select:
                if self.detect_select(name):
                    is_select = True
            sleep(1)
            if not is_select:
                if self.detect_select(name):
                    is_select = True

        for index in range(len(friend_class)):
            # 如果不是自动寻找，就跳过
            if find_mode != FindMode.AUTO_FIND:
                continue
            # 如果已经选中了好友，就不需要再选中了
            if is_select:
                continue
            # 首先切换到不同的好友列表
            flags = (
                (self.I_FLAG_1_ON, self.I_FLAG_1_OFF),
                (self.I_FLAG_2_ON, self.I_FLAG_2_OFF),
                (self.I_FLAG_3_ON, self.I_FLAG_3_OFF),
                (self.I_FLAG_4_ON, self.I_FLAG_4_OFF),
            )
            flag_on, flag_off = flags[index]
            flag_deadline = monotonic() + 8.0
            flag_actions = 0
            flag_max_actions = 4
            while monotonic() < flag_deadline:
                self.screenshot()
                if flag_on.match_mean_color(self.device.image, self.INVITE_FLAG_ON, 10):
                    break
                if flag_actions >= flag_max_actions:
                    self._raise_exploration_click_boundary(
                        'invite_select_category',
                        reason='action_budget_exhausted',
                        actions=flag_actions,
                        timeout=8.0,
                        max_actions=flag_max_actions,
                        detail=f'index={index}',
                    )
                if self.click(flag_off, interval=1):
                    flag_actions += 1
                    continue
            else:
                self._raise_exploration_click_boundary(
                    'invite_select_category',
                    reason='page_transition_timeout',
                    actions=flag_actions,
                    timeout=8.0,
                    max_actions=flag_max_actions,
                    detail=f'index={index}',
                )

            # 选中好友， 在这里游戏获取在线的好友并不是很快，根据不同的设备会有不同的时间，而且没有什么元素提供我们来判断
            # 所以这里就直接等待一段时间
            logger.info(f'Now find friend in {friend_class[index]}')
            sleep(1)
            if not is_select:
                if self.detect_select(name):
                    is_select = True
            sleep(1)
            if not is_select:
                if self.detect_select(name):
                    is_select = True

        # 点击确定
        logger.info('Click invite ensure')
        if not self.appear(self.I_INVITE_ENSURE):
            logger.warning('No appear invite ensure while invite friend')
        ensure_deadline = monotonic() + 8.0
        ensure_actions = 0
        ensure_max_actions = 4
        while monotonic() < ensure_deadline:
            self.screenshot()
            if not self.appear(self.I_INVITE_ENSURE):
                break
            if ensure_actions >= ensure_max_actions:
                self._raise_exploration_click_boundary(
                    'invite_confirm',
                    reason='action_budget_exhausted',
                    actions=ensure_actions,
                    timeout=8.0,
                    max_actions=ensure_max_actions,
                )
            if self.appear_then_click(self.I_INVITE_ENSURE):
                ensure_actions += 1
                continue
        else:
            self._raise_exploration_click_boundary(
                'invite_confirm',
                reason='page_transition_timeout',
                actions=ensure_actions,
                timeout=8.0,
                max_actions=ensure_max_actions,
            )
        # 哪怕没有找到好友也有点击 确认 以退出好友列表
        if not is_select:
            logger.warning('No find friend')
            # 这个时候任务运行失败
            logger.info('Task failed')
            return False

        return True


class ScriptTask(SoloExploration):
    def _prepare_startup(self):
        startup_deadline = monotonic() + 30.0
        startup_actions = 0
        startup_max_actions = 4
        self.screenshot()
        if self._click_exploration_exit_confirmation():
            startup_actions += 1
            logger.info('Recovered pending exploration exit confirmation before scene detection')
        startup_unknown_cnt = 0
        while monotonic() < startup_deadline:
            self.screenshot()
            if self._candidate_panel_visible():
                if startup_actions >= startup_max_actions:
                    BaseExploration._raise_exploration_click_boundary(
                        self,
                        'prepare_startup',
                        reason='action_budget_exhausted',
                        actions=startup_actions,
                        timeout=30.0,
                        max_actions=startup_max_actions,
                        target='candidate_panel',
                    )
                logger.warning(
                    'EXPLORATION_START_SCENE recognized=candidate_panel '
                    'action=confirm_and_resume'
                )
                self._confirm_candidate_panel()
                startup_actions += 1
                startup_unknown_cnt = 0
                continue
            scene = self.get_current_scene()
            if scene != Scene.UNKNOWN:
                return
            if self._home_scene_visible():
                logger.info(
                    'EXPLORATION_START_SCENE recognized=home_or_protection '
                    'action=pre_process'
                )
                self.pre_process()
                return
            startup_unknown_cnt += 1
            logger.warning(
                'EXPLORATION_START_SCENE unknown '
                f'consecutive={startup_unknown_cnt}/{self.UNKNOWN_SCENE_LIMIT} '
                'action=wait_no_click'
            )
            if startup_unknown_cnt >= self.UNKNOWN_SCENE_LIMIT:
                self._abort_unknown_scene('startup', startup_unknown_cnt)
            sleep(self.UNKNOWN_SCENE_RETRY_DELAY)
        BaseExploration._raise_exploration_click_boundary(
            self,
            'prepare_startup',
            reason='page_transition_timeout',
            actions=startup_actions,
            timeout=30.0,
            max_actions=startup_max_actions,
        )

    def run(self):
        logger.hr('exploration')
        try:
            self._prepare_startup()

            match self._config.exploration_config.user_status:
                case UserStatus.ALONE:
                    self.run_solo()
                case UserStatus.LEADER:
                    self.run_leader()
                case UserStatus.MEMBER:
                    self.run_member()
                case _:
                    self.run_solo()

            self.post_process()
        except ExplorationBudgetExceeded as error:
            try:
                self.quit_explore(reason=ExplorationExitReason.SEARCH_BUDGET_EXHAUSTED)
            except Exception as exit_error:  # noqa: BLE001
                logger.warning(f'Exploration budget exit failed: {exit_error}')
            self._restore_buffs_after_error()
            decision = self.set_next_run(
                task='Exploration',
                success=False,
                finish=False,
                reason=f'exploration budget exhausted: {error.reason}',
            )
            raise TaskEnd.aborted(
                str(error),
                statistics={
                    'reason': error.reason,
                    'recognitions': error.recognitions,
                    'swipes': error.swipes,
                    'elapsed': error.elapsed,
                    'minions_cnt': getattr(self, 'minions_cnt', 0),
                },
                next_run=getattr(decision, 'when', None),
            )
        except Exception:
            self._restore_buffs_after_error()
            raise

    def _restore_buffs_after_error(self):
        if getattr(self, '_exploration_buff_snapshot', None) is not None:
            logger.warning(
                'Exploration aborted with a pending buff snapshot; '
                'attempting best-effort restoration'
            )
            try:
                self.ui_get_current_page()
                if self.ui_goto(page_main):
                    self._restore_exploration_buff_states()
            except Exception as restore_error:  # noqa: BLE001
                logger.warning(f'Exploration buff restore after error failed: {restore_error}')


if __name__ == "__main__":
    from module.config.config import Config
    from module.device.device import Device

    config = Config('oas1')
    device = Device(config)
    t = ScriptTask(config, device)
    t.run()
