import unittest
from types import SimpleNamespace

from tasks.base_task import BaseTask


class OcrCacheDevice:
    def __init__(self):
        self.image = object()
        self.frame_id = 1
        self.cache = {}

    def recognition_cache_get(self, key):
        if key in self.cache:
            return True, self.cache[key]
        return False, None

    def recognition_cache_set(self, key, value):
        self.cache[key] = value


class OcrTarget:
    name = 'cache_target'
    roi = [10, 20, 30, 40]
    area = [10, 20, 30, 40]
    mode = 'Single'
    method = 'Default'
    keyword = '自动'

    def __init__(self):
        self.calls = 0

    @staticmethod
    def pre_process(image):
        return image

    def ocr(self, _image, **_kwargs):
        self.calls += 1
        return self.keyword

    def ocr_single(self, _image):
        self.calls += 1
        return self.keyword
        return '自动'


class OcrCacheTest(unittest.TestCase):
    def test_same_frame_and_same_rule_hit_cache(self):
        task = object.__new__(BaseTask)
        task.device = OcrCacheDevice()
        target = OcrTarget()

        self.assertEqual(task._ocr_cached(target), '自动')
        self.assertEqual(task._ocr_cached(target), '自动')
        self.assertEqual(target.calls, 1)

    def test_new_frame_and_roi_do_not_reuse_old_result(self):
        task = object.__new__(BaseTask)
        task.device = OcrCacheDevice()
        target = OcrTarget()

        task._ocr_cached(target)
        task.device.frame_id = 2
        task._ocr_cached(target)
        target.roi = [11, 20, 30, 40]
        task._ocr_cached(target)

        self.assertEqual(target.calls, 3)

    def test_rule_contract_fields_do_not_share_results(self):
        task = object.__new__(BaseTask)
        task.device = OcrCacheDevice()
        target = OcrTarget()

        task._ocr_cached(
            target,
            keyword='first',
            score=0.8,
            preprocess_mode='default',
        )
        task._ocr_cached(
            target,
            keyword='second',
            score=0.8,
            preprocess_mode='default',
        )
        task._ocr_cached(
            target,
            keyword='first',
            score=0.9,
            preprocess_mode='default',
        )
        task._ocr_cached(
            target,
            keyword='first',
            score=0.8,
            preprocess_mode='alternate',
        )

        target.mode = 'DigitCounter'
        task._ocr_cached(
            target,
            keyword='first',
            score=0.8,
            preprocess_mode='default',
        )

        self.assertEqual(target.calls, 5)

    def test_single_ocr_entry_points_share_one_backend_call(self):
        task = object.__new__(BaseTask)
        task.device = OcrCacheDevice()
        target = OcrTarget()

        task._ocr_cached(target, operation='ocr_single')
        task._ocr_cached(target, operation='ocr')

        self.assertEqual(target.calls, 1)

    def test_full_ocr_area_mutation_does_not_break_same_frame_cache(self):
        task = object.__new__(BaseTask)
        task.device = OcrCacheDevice()
        target = OcrTarget()

        task._ocr_cached(target)
        target.area = [700, 500, 20, 20]
        task._ocr_cached(target)

        self.assertEqual(target.calls, 1)


if __name__ == '__main__':
    unittest.main()
