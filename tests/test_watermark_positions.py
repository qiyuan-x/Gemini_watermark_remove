import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from gemini_watermark_remover.app import WatermarkRemoverApp
from gemini_watermark_remover.config import ConfigStore
from gemini_watermark_remover.watermark import WatermarkMatch, WatermarkRemover


PROJECT_DIR = Path(__file__).resolve().parents[1]
TEST_IMAGE_DEFAULT = PROJECT_DIR / 'Test' / 'Gemini_Generated_Image_ (1).png'
TEST_IMAGE_MOVED = PROJECT_DIR / 'Test' / 'Gemini_Generated_Image_.png'


class WatermarkPositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.remover = WatermarkRemover()

    def _create_watermarked_image(self, width, height, x_start, y_start, size=48, template_size=48):
        image_array = np.full((height, width, 4), [130, 150, 170, 255], dtype=np.uint8)
        alpha_map = self.remover._alpha_map(size, template_size)
        region = image_array[y_start:y_start + size, x_start:x_start + size, :3].astype(np.float32)
        region = np.rint(region * (1.0 - alpha_map[:, :, np.newaxis]) + 255.0 * alpha_map[:, :, np.newaxis])
        image_array[y_start:y_start + size, x_start:x_start + size, :3] = region.astype(np.uint8)
        return Image.fromarray(image_array, 'RGBA')

    def test_default_position_uses_48_template(self):
        image = self._create_watermarked_image(300, 200, 220, 120)
        match = self.remover.find_default(image)

        self.assertIsNotNone(match)
        self.assertEqual((match.x, match.y, match.size, match.template_size), (220, 120, 48, 48))

    def test_large_default_position_uses_96_template(self):
        image = self._create_watermarked_image(1300, 1300, 1140, 1140, size=96, template_size=96)
        match = self.remover.find_default(image)

        self.assertIsNotNone(match)
        self.assertEqual((match.x, match.y, match.size, match.template_size), (1140, 1140, 96, 96))

    def test_clicked_position_can_be_reused(self):
        image = self._create_watermarked_image(320, 240, 100, 90)
        self.assertIsNone(self.remover.find_default(image))

        match = self.remover.find_near(image, 124, 114)
        self.assertIsNotNone(match)
        self.assertEqual((match.x, match.y, match.size), (100, 90, 48))

        position = {
            'x_ratio': match.x / image.width,
            'y_ratio': match.y / image.height,
            'size_ratio': match.size / min(image.size),
            'template_size': match.template_size,
            'aspect_ratio': image.width / image.height,
            'last_confirmed': '2026-06-24T00:00:00',
        }
        reused_match = self.remover.find_saved(image, [position])
        self.assertIsNotNone(reused_match)
        original_bytes = np.asarray(image.convert('RGBA')).tobytes()
        processed = self.remover.remove(image, reused_match)
        self.assertNotEqual(original_bytes, np.asarray(processed).tobytes())

    def test_confirmed_position_is_saved(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config = ConfigStore(Path(temporary_directory) / 'config.json')
            self.assertEqual(config.get('theme_mode'), 'system')
            match = WatermarkMatch(x=320, y=640, size=48, template_size=96, score=1.0)
            config.save_watermark_position(match, (800, 1330))
            loaded_config = ConfigStore(Path(temporary_directory) / 'config.json')
            positions = loaded_config.watermark_positions()

        self.assertEqual(len(positions), 1)
        self.assertAlmostEqual(positions[0]['x_ratio'], 0.4)
        self.assertAlmostEqual(positions[0]['y_ratio'], 640 / 1330)
        self.assertEqual(positions[0]['template_size'], 96)

    def test_config_ignores_invalid_saved_position(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / 'config.json'
            config = ConfigStore(config_path)
            config.set(
                'watermark_positions',
                [{'x_ratio': 'invalid'}, {'x_ratio': 0.5, 'y_ratio': 0.5, 'size_ratio': 0.1}],
            )
            loaded_config = ConfigStore(config_path)

        self.assertEqual(loaded_config.watermark_positions(), [])

    def test_output_path_cannot_replace_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / 'source.png'
            source_path.touch()

            with self.assertRaises(ValueError):
                WatermarkRemoverApp._ensure_output_does_not_replace_source(str(source_path), source_path)

    def test_match_requires_score_and_watermark_validation(self):
        low_score_match = WatermarkMatch(
            x=0,
            y=0,
            size=48,
            template_size=48,
            score=0.49,
            valid_ratio=1.0,
        )
        invalid_watermark_match = WatermarkMatch(
            x=0,
            y=0,
            size=48,
            template_size=48,
            score=0.70,
            valid_ratio=0.98,
        )
        valid_match = WatermarkMatch(
            x=0,
            y=0,
            size=48,
            template_size=48,
            score=0.50,
            valid_ratio=0.99,
        )

        self.assertFalse(self.remover.is_valid(low_score_match))
        self.assertFalse(self.remover.is_valid(invalid_watermark_match))
        self.assertTrue(self.remover.is_valid(valid_match))

    @unittest.skipUnless(TEST_IMAGE_DEFAULT.exists() and TEST_IMAGE_MOVED.exists(), '本地手工验证样图不存在')
    def test_local_manual_samples(self):
        with Image.open(TEST_IMAGE_DEFAULT) as image:
            default_match = self.remover.find_default(image)
        with Image.open(TEST_IMAGE_MOVED) as image:
            full_size_match = self.remover.find_near(image, 680, 1210, expected_size=48, template_size=48)

        self.assertIsNotNone(default_match)
        self.assertIsNotNone(full_size_match)
        self.assertEqual(full_size_match.size, 48)
        self.assertLessEqual(abs(full_size_match.x - 656), 2)
        self.assertLessEqual(abs(full_size_match.y - 1186), 2)

        detected_match = self.remover.find_best(image)
        self.assertIsNotNone(detected_match)
        self.assertLessEqual(abs(detected_match.x - 656), 2)
        self.assertLessEqual(abs(detected_match.y - 1186), 2)


if __name__ == '__main__':
    unittest.main()
