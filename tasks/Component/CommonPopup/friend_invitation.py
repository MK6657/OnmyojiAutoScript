from __future__ import annotations

import hashlib
from datetime import datetime

import numpy as np

from module.exception import ScriptError
from module.logger import logger
from tasks.Component.CommonPopup.models import (
    PopupActionKind,
    PopupActionResult,
    PopupDetection,
)
from tasks.GlobalGame.config_emergency import FriendInvitation


class FriendInvitationPopupHandler:
    popup_id = 'friend_invitation'
    priority = 800
    max_actions = 2
    verify_absent_frames = 2
    # DeepSeek-14 O14-5: restored. A synchronous capture backend cannot be
    # preempted by the deadline budget, so this handler only runs when capture
    # is deadline-bounded (nemu_ipc). Long-term: cancellable capture backend or
    # process-level isolation (OAS-POPUP-DEADLINE-001, P3).
    required_deadline_capabilities = ('capture',)
    IDENTITY_ROI = (480, 120, 320, 220)

    @classmethod
    def _stable_content_fingerprint(cls, context) -> str:
        task = context._task
        identity_provider = getattr(task, 'friend_invitation_identity', None)
        if callable(identity_provider):
            identity = identity_provider(context)
            if identity:
                return 'identity:' + str(identity)

        image = context.image
        if not isinstance(image, np.ndarray) or image.ndim < 2:
            return 'content:unavailable'
        x, y, width, height = cls.IDENTITY_ROI
        crop = image[y:y + height, x:x + width]
        if crop.size == 0:
            return 'content:empty'
        if crop.ndim == 3:
            crop = crop[..., :3].mean(axis=2)
        ys = np.linspace(0, crop.shape[0] - 1, 16, dtype=np.intp)
        xs = np.linspace(0, crop.shape[1] - 1, 16, dtype=np.intp)
        sample = crop[np.ix_(ys, xs)]
        quantized = np.clip(sample // 16, 0, 15).astype(np.uint8)
        digest = hashlib.sha256(quantized.tobytes()).hexdigest()[:16]
        return 'content:' + digest

    @staticmethod
    def _decision(context) -> tuple[str, str, dict]:
        task = context._task
        raw_invite_type = task.config.global_game.emergency.friend_invitation
        try:
            invite_type = FriendInvitation(raw_invite_type)
        except (TypeError, ValueError) as exc:
            raise ScriptError(
                f'Unknown friend invitation type: {raw_invite_type}'
            ) from exc
        evidence = {'policy': str(getattr(invite_type, 'value', invite_type))}
        if invite_type == FriendInvitation.ACCEPT:
            return 'I_G_ACCEPT', 'accept', evidence
        if invite_type == FriendInvitation.REJECT:
            return 'I_G_REJECT', 'reject', evidence
        if invite_type == FriendInvitation.IGNORE:
            return 'I_G_IGNORE', 'ignore', evidence

        jade = context.appear(task.I_G_JADE)
        cat_food = context.appear(task.I_G_CAT_FOOD)
        dog_food = context.appear(task.I_G_DOG_FOOD)
        evidence.update({
            'jade': jade,
            'cat_food': cat_food,
            'dog_food': dog_food,
        })
        if invite_type == FriendInvitation.ONLY_JADE:
            accepted = jade
        elif invite_type == FriendInvitation.JADE_AND_FOOD:
            accepted = jade or cat_food or dog_food
        else:
            raise ScriptError(f'Unknown friend invitation type: {invite_type}')
        return (
            ('I_G_ACCEPT', 'accept', evidence)
            if accepted
            else ('I_G_IGNORE', 'ignore', evidence)
        )

    def detect(self, context) -> PopupDetection | None:
        task = context._task
        if not context.appear(task.I_G_ACCEPT):
            return None
        control_attr, decision, evidence = self._decision(context)
        evidence = {**evidence, 'decision': decision, 'control_attr': control_attr}
        content_fingerprint = self._stable_content_fingerprint(context)
        evidence['content_fingerprint'] = content_fingerprint
        reward_identity = '|'.join(
            name for name, present in (
                ('jade', bool(evidence.get('jade'))),
                ('cat_food', bool(evidence.get('cat_food'))),
                ('dog_food', bool(evidence.get('dog_food'))),
            )
            if present
        ) or 'unspecified'
        evidence['reward_identity'] = reward_identity
        key_parts = [
            evidence.get('policy', ''),
            decision,
            reward_identity,
            content_fingerprint,
        ]
        return PopupDetection(
            popup_id=self.popup_id,
            priority=self.priority,
            frame_id=context.frame_id,
            instance_key=':'.join(key_parts),
            pixel_sha256=context.pixel_sha256(),
            evidence=evidence,
        )

    def act(self, context, detection, attempt: int) -> PopupActionResult:
        task = context._task
        control_attr = str(detection.evidence['control_attr'])
        target = getattr(task, control_attr)
        if not context.appear(target):
            return PopupActionResult(
                kind=PopupActionKind.FAILED,
                control_name=getattr(target, 'name', control_attr),
                attempt=attempt,
                reason='decision_control_not_visible',
            )
        x, y = target.coord()
        detect_record = getattr(task.device, 'detect_record', None)
        try:
            context.click(x, y, control_name=getattr(target, 'name', control_attr))
        finally:
            if detect_record is not None:
                task.device.detect_record = detect_record
        logger.info(
            'FRIEND_INVITATION action=' + str(detection.evidence['decision'])
            + f' attempt={attempt} click=({x},{y})'
        )
        return PopupActionResult(
            kind=PopupActionKind.CLICKED,
            control_name=getattr(target, 'name', control_attr),
            click_point=(int(x), int(y)),
            attempt=attempt,
            reason=str(detection.evidence['decision']),
        )

    @staticmethod
    def on_resolved(task, detection, action) -> None:
        if detection.evidence.get('decision') != 'accept':
            return
        task.set_next_run(
            task='WantedQuests',
            target=datetime.now().replace(microsecond=0),
        )

    @staticmethod
    def on_abort(task, detection, reason: str) -> None:
        logger.warning(
            f'FRIEND_INVITATION status=aborted reason={reason} '
            f'instance={detection.instance_key}'
        )
