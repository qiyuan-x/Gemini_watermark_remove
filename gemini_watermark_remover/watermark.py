from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

import cv2
import numpy as np
from PIL import Image

from .paths import resource_path


@dataclass(frozen=True)
class WatermarkMatch:
    x: int
    y: int
    size: int
    template_size: int
    score: float
    valid_ratio: float = 0.0
    alpha_strength: float = 1.0


@dataclass(frozen=True)
class DetectionContext:
    rgb_image: np.ndarray
    gray_image: np.ndarray


class WatermarkRemover:
    MIN_WATERMARK_SIZE = 16
    MAX_WATERMARK_SIZE = 512
    MATCH_THRESHOLD = 0.50
    MIN_VALID_RATIO = 0.99

    def __init__(self) -> None:
        self.watermark_images = {
            48: Image.open(resource_path('bg_48.png')).convert('RGBA'),
            96: Image.open(resource_path('bg_96.png')).convert('RGBA'),
        }
        self.alpha_maps: dict[tuple[int, int], np.ndarray] = {}
        self.detection_templates: dict[tuple[int, int], np.ndarray] = {}

    def create_detection_context(self, image: Image.Image) -> DetectionContext:
        rgb_image = np.asarray(image.convert('RGB'))
        gray_image = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2GRAY)
        return DetectionContext(rgb_image=rgb_image, gray_image=gray_image)

    def preferred_size(self, image: Image.Image) -> int:
        return self.default_rule(image.size)['size']

    def default_rule(self, image_size: tuple[int, int]) -> dict[str, int]:
        image_width, image_height = image_size
        if image_width > 1024 and image_height > 1024:
            return {'size': 96, 'right_margin': 64, 'bottom_margin': 64}
        return {'size': 48, 'right_margin': 32, 'bottom_margin': 32}

    def default_position(self, image_size: tuple[int, int]) -> WatermarkMatch:
        image_width, image_height = image_size
        rule = self.default_rule(image_size)
        size = rule['size']
        return WatermarkMatch(
            x=image_width - rule['right_margin'] - size,
            y=image_height - rule['bottom_margin'] - size,
            size=size,
            template_size=size,
            score=0.0,
        )

    def _source_template_size(self, size: int, requested_size: int | None = None) -> int:
        if requested_size in self.watermark_images:
            return requested_size
        return min(self.watermark_images, key=lambda available: abs(np.log(size / available)))

    def _watermark_image(self, size: int, template_size: int | None = None) -> Image.Image:
        source_size = self._source_template_size(size, template_size)
        return self.watermark_images[source_size]

    def _alpha_map(self, size: int, template_size: int | None = None) -> np.ndarray:
        source_size = self._source_template_size(size, template_size)
        cache_key = (size, source_size)
        cached = self.alpha_maps.get(cache_key)
        if cached is not None:
            return cached

        watermark = self._watermark_image(size, source_size)
        if watermark.size != (size, size):
            watermark = watermark.resize((size, size), Image.Resampling.LANCZOS)
        rgba = np.asarray(watermark, dtype=np.float32)
        alpha_map = rgba[:, :, :3].max(axis=2) / 255.0
        self.alpha_maps[cache_key] = alpha_map
        return alpha_map

    def _detection_template(self, size: int, template_size: int | None = None) -> np.ndarray:
        source_size = self._source_template_size(size, template_size)
        cache_key = (size, source_size)
        cached = self.detection_templates.get(cache_key)
        if cached is not None:
            return cached

        watermark = self._watermark_image(size, source_size).convert('L')
        if watermark.size != (size, size):
            watermark = watermark.resize((size, size), Image.Resampling.LANCZOS)
        template = np.asarray(watermark)
        self.detection_templates[cache_key] = template
        return template

    def _detection_sizes(self, image_size: tuple[int, int]) -> list[int]:
        image_width, image_height = image_size
        max_size = min(
            self.MAX_WATERMARK_SIZE,
            max(self.MIN_WATERMARK_SIZE, int(min(image_width, image_height) * 0.25)),
        )
        sizes = {self.MIN_WATERMARK_SIZE, max_size, *self.watermark_images.keys()}
        current_size = float(self.MIN_WATERMARK_SIZE)
        while current_size < max_size:
            sizes.add(round(current_size))
            current_size *= 1.15
        return sorted(size for size in sizes if self.MIN_WATERMARK_SIZE <= size <= max_size)

    def _find_best_match(
        self,
        gray_image: np.ndarray,
        sizes: Iterable[int],
        bounds: tuple[int, int, int, int] | None = None,
        template_size: int | None = None,
    ) -> WatermarkMatch | None:
        image_height, image_width = gray_image.shape
        if bounds is None:
            left, top, right, bottom = 0, 0, image_width, image_height
        else:
            left, top, right, bottom = bounds

        search_image = gray_image[top:bottom, left:right]
        best_match: WatermarkMatch | None = None
        for size in sizes:
            if size >= search_image.shape[0] or size >= search_image.shape[1]:
                continue

            source_size = self._source_template_size(size, template_size)
            template = self._detection_template(size, source_size)
            result = cv2.matchTemplate(search_image, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            candidate = WatermarkMatch(
                x=left + location[0],
                y=top + location[1],
                size=size,
                template_size=source_size,
                score=float(score),
            )
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate
        return best_match

    def _find_top_matches(
        self,
        gray_image: np.ndarray,
        size: int,
        template_size: int,
        maximum_candidates: int = 64,
    ) -> list[WatermarkMatch]:
        """Return separated high-score candidates for one original template."""
        image_height, image_width = gray_image.shape
        if size >= image_height or size >= image_width:
            return []

        template = self._detection_template(size, template_size)
        result = cv2.matchTemplate(gray_image, template, cv2.TM_CCOEFF_NORMED)
        candidate_count = min(maximum_candidates, result.size)
        if candidate_count == 0:
            return []

        flattened = result.ravel()
        top_indexes = np.argpartition(flattened, -candidate_count)[-candidate_count:]
        ordered_indexes = top_indexes[np.argsort(flattened[top_indexes])[::-1]]
        candidates: list[WatermarkMatch] = []
        minimum_distance = max(8, size // 3)
        for flat_index in ordered_indexes:
            y, x = np.unravel_index(int(flat_index), result.shape)
            if any(abs(x - item.x) < minimum_distance and abs(y - item.y) < minimum_distance for item in candidates):
                continue
            candidates.append(
                WatermarkMatch(
                    x=int(x),
                    y=int(y),
                    size=size,
                    template_size=template_size,
                    score=float(result[y, x]),
                )
            )
        return candidates

    def _with_metrics(self, rgb_image: np.ndarray, match: WatermarkMatch | None) -> WatermarkMatch | None:
        if match is None:
            return None
        valid_ratio = self._valid_ratio(rgb_image, match)
        if match.score < self.MATCH_THRESHOLD or valid_ratio < self.MIN_VALID_RATIO:
            return replace(match, valid_ratio=valid_ratio)
        alpha_strength = self._estimate_alpha_strength(rgb_image, match)
        return replace(match, valid_ratio=valid_ratio, alpha_strength=alpha_strength)

    def _valid_ratio(self, rgb_image: np.ndarray, match: WatermarkMatch) -> float:
        alpha_map = self._alpha_map(match.size, match.template_size)
        patch = rgb_image[match.y:match.y + match.size, match.x:match.x + match.size, :3]
        if patch.shape[:2] != (match.size, match.size):
            return 0.0

        active_pixels = alpha_map >= (20.0 / 255.0)
        if not np.any(active_pixels):
            return 0.0
        lower_bound = alpha_map * 255.0
        valid = patch.min(axis=2).astype(np.float32) + 3.0 >= lower_bound
        return float(valid[active_pixels].mean())

    def _estimate_alpha_strength(self, rgb_image: np.ndarray, match: WatermarkMatch) -> float:
        alpha_map = self._alpha_map(match.size, match.template_size)
        patch = rgb_image[match.y:match.y + match.size, match.x:match.x + match.size, :3]
        if patch.shape[:2] != (match.size, match.size):
            return 1.0

        mask = (alpha_map >= 0.05).astype(np.uint8) * 255
        if not np.any(mask):
            return 1.0
        background = cv2.inpaint(patch.astype(np.uint8), mask, 3, cv2.INPAINT_TELEA).astype(np.float32)
        patch_float = patch.astype(np.float32)
        influence = alpha_map[:, :, np.newaxis] * (255.0 - background)
        denominator = float(np.sum(influence * influence))
        if denominator <= 0.0:
            return 1.0
        strength = float(np.sum(influence * (patch_float - background)) / denominator)
        return max(0.2, min(1.0, strength))

    def find_near(
        self,
        image: Image.Image,
        center_x: int,
        center_y: int,
        expected_size: int | None = None,
        radius: int | None = None,
        template_size: int | None = None,
        context: DetectionContext | None = None,
    ) -> WatermarkMatch | None:
        context = context or self.create_detection_context(image)
        rgb_image = context.rgb_image
        gray_image = context.gray_image
        image_height, image_width = gray_image.shape

        if expected_size is None:
            sizes = self._detection_sizes((image_width, image_height))
            search_radius = radius or max(96, int(min(image_width, image_height) * 0.15))
        else:
            size = max(self.MIN_WATERMARK_SIZE, min(self.MAX_WATERMARK_SIZE, round(expected_size)))
            sizes = [size]
            search_radius = radius or max(16, round(size * 0.5))

        half_template_size = max(sizes) / 2
        bounds = (
            max(0, int(center_x - search_radius - half_template_size)),
            max(0, int(center_y - search_radius - half_template_size)),
            min(image_width, int(center_x + search_radius + half_template_size)),
            min(image_height, int(center_y + search_radius + half_template_size)),
        )
        match = self._find_best_match(gray_image, sizes, bounds, template_size)
        return self._with_metrics(rgb_image, match)

    def find_best(self, image: Image.Image, context: DetectionContext | None = None) -> WatermarkMatch | None:
        context = context or self.create_detection_context(image)
        rgb_image = context.rgb_image
        gray_image = context.gray_image
        candidates: list[WatermarkMatch] = []
        for template_size in self.watermark_images:
            candidates.extend(
                self._find_top_matches(
                    gray_image,
                    size=template_size,
                    template_size=template_size,
                )
            )

        verified_candidates: list[WatermarkMatch] = []
        for candidate in candidates:
            measured = replace(candidate, valid_ratio=self._valid_ratio(rgb_image, candidate))
            if self.is_valid(measured):
                verified_candidates.append(measured)
        if not verified_candidates:
            return None
        best_candidate = max(verified_candidates, key=lambda candidate: candidate.score)
        return replace(
            best_candidate,
            alpha_strength=self._estimate_alpha_strength(rgb_image, best_candidate),
        )

    def find_default(self, image: Image.Image, context: DetectionContext | None = None) -> WatermarkMatch | None:
        expected = self.default_position(image.size)
        match = self.find_near(
            image,
            expected.x + expected.size // 2,
            expected.y + expected.size // 2,
            expected_size=expected.size,
            radius=8,
            template_size=expected.template_size,
            context=context,
        )
        return match if self.is_valid(match) else None

    def find_saved(
        self,
        image: Image.Image,
        positions: list[dict[str, Any]],
        context: DetectionContext | None = None,
    ) -> WatermarkMatch | None:
        image_width, image_height = image.size
        short_side = min(image_width, image_height)
        aspect_ratio = image_width / image_height
        for position in positions:
            try:
                saved_aspect_ratio = float(position['aspect_ratio'])
                if abs(saved_aspect_ratio - aspect_ratio) / aspect_ratio > 0.05:
                    continue
                x = round(float(position['x_ratio']) * image_width)
                y = round(float(position['y_ratio']) * image_height)
                size = round(float(position['size_ratio']) * short_side)
                template_size = int(position.get('template_size', 48))
            except (KeyError, TypeError, ValueError):
                continue

            match = self.find_near(
                image,
                x + size // 2,
                y + size // 2,
                expected_size=size,
                template_size=template_size,
                context=context,
            )
            if self.is_valid(match):
                return match
        return None

    def find_known(self, image: Image.Image, positions: list[dict[str, Any]]) -> tuple[WatermarkMatch | None, str | None]:
        context = self.create_detection_context(image)
        match = self.find_default(image, context)
        if match is not None:
            return match, '默认位置'
        match = self.find_saved(image, positions, context)
        if match is not None:
            return match, '已记录位置'
        return None, None

    def is_valid(self, match: WatermarkMatch | None) -> bool:
        return bool(
            match
            and match.score >= self.MATCH_THRESHOLD
            and match.valid_ratio >= self.MIN_VALID_RATIO
        )

    def remove(self, image: Image.Image, match: WatermarkMatch) -> Image.Image:
        image_array = np.asarray(image.convert('RGBA')).copy()
        image_height, image_width = image_array.shape[:2]
        if match.x < 0 or match.y < 0 or match.x + match.size > image_width or match.y + match.size > image_height:
            raise ValueError('水印位置超出图片范围')

        alpha_map = self._alpha_map(match.size, match.template_size) * match.alpha_strength
        alpha_map = np.minimum(alpha_map, 0.99)
        active_pixels = np.maximum(0.0, alpha_map - 3.0 / 255.0) >= 0.002
        region = image_array[match.y:match.y + match.size, match.x:match.x + match.size, :3]
        region_float = region.astype(np.float32)
        multipliers = 1.0 - alpha_map[:, :, np.newaxis]
        restored = np.rint((region_float - alpha_map[:, :, np.newaxis] * 255.0) / multipliers)
        restored = np.clip(restored, 0, 255).astype(np.uint8)
        region[active_pixels] = restored[active_pixels]
        return Image.fromarray(image_array, 'RGBA')
