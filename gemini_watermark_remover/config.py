from __future__ import annotations

import datetime
import copy
import json
from pathlib import Path
from typing import Any

from .paths import config_path


DEFAULT_CONFIG: dict[str, Any] = {
    'default_save_dir': '',
    'use_default_dir': False,
    'use_suffix': True,
    'suffix': '_non',
    'theme_mode': 'system',
    'watermark_positions': [],
}


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()
        self.values = copy.deepcopy(DEFAULT_CONFIG)
        self.load()
        if not self.path.exists():
            self.save()

    def load(self) -> None:
        if not self.path.exists():
            return

        try:
            with self.path.open('r', encoding='utf-8') as file:
                loaded = json.load(file)
        except (OSError, json.JSONDecodeError):
            return

        if isinstance(loaded, dict):
            self.values.update(loaded)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f'{self.path.suffix}.tmp')
        with temporary_path.open('w', encoding='utf-8') as file:
            json.dump(self.values, file, ensure_ascii=False, indent=2)
        temporary_path.replace(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value
        self.save()

    def watermark_positions(self) -> list[dict[str, Any]]:
        positions = self.values.get('watermark_positions', [])
        if not isinstance(positions, list):
            return []

        valid_positions = [position for position in positions if self._is_valid_position(position)]
        return sorted(
            valid_positions,
            key=lambda position: position.get('last_confirmed', ''),
            reverse=True,
        )

    @staticmethod
    def _is_valid_position(position: Any) -> bool:
        if not isinstance(position, dict):
            return False
        try:
            x_ratio = float(position['x_ratio'])
            y_ratio = float(position['y_ratio'])
            size_ratio = float(position['size_ratio'])
            aspect_ratio = float(position['aspect_ratio'])
            template_size = int(position.get('template_size', 48))
        except (KeyError, TypeError, ValueError):
            return False
        return (
            0.0 <= x_ratio <= 1.0
            and 0.0 <= y_ratio <= 1.0
            and 0.0 < size_ratio <= 1.0
            and aspect_ratio > 0.0
            and template_size in {48, 96}
        )

    def save_watermark_position(self, match: Any, image_size: tuple[int, int]) -> None:
        image_width, image_height = image_size
        short_side = min(image_width, image_height)
        new_position = {
            'x_ratio': match.x / image_width,
            'y_ratio': match.y / image_height,
            'size_ratio': match.size / short_side,
            'template_size': match.template_size,
            'aspect_ratio': image_width / image_height,
            'last_confirmed': datetime.datetime.now().isoformat(timespec='seconds'),
        }

        positions = self.watermark_positions()
        for index, position in enumerate(positions):
            is_same_position = (
                abs(position.get('x_ratio', -1) - new_position['x_ratio']) < 0.01
                and abs(position.get('y_ratio', -1) - new_position['y_ratio']) < 0.01
                and abs(position.get('size_ratio', -1) - new_position['size_ratio']) < 0.01
                and position.get('template_size', 48) == new_position['template_size']
            )
            if is_same_position:
                positions[index] = new_position
                break
        else:
            positions.append(new_position)

        positions.sort(key=lambda position: position['last_confirmed'], reverse=True)
        self.set('watermark_positions', positions[:20])

    def remove_watermark_position(self, index: int) -> None:
        positions = self.watermark_positions()
        if 0 <= index < len(positions):
            positions.pop(index)
            self.set('watermark_positions', positions)
