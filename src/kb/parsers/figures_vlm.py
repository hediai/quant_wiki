"""VLM figure descriptions — pluggable backend, offline placeholder.

Reads existing `converted/<id>/figures/*.png`, writes `*.md` alongside with a
structured description. The default backend is a heuristic that just records
file metadata; real backends (Claude vision, Qwen2-VL, etc.) plug in via env.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class VLMBackend(Protocol):
    name: str
    def describe(self, image_path: Path, caption: str = "") -> str: ...


class HeuristicVLM:
    name = "heuristic"

    def describe(self, image_path: Path, caption: str = "") -> str:
        return (
            f"# 图：{image_path.name}\n\n"
            f"- caption: {caption or '(无)'}\n"
            f"- 路径: {image_path}\n\n"
            "> 未启用真实 VLM 后端。运行 `KB_VLM=claude` 或注册其他后端后重跑 "
            "`kb describe-figures <source-id>` 以生成结构化描述。\n"
        )


class ClaudeVLM:
    name = "claude-vlm"

    def __init__(self, model: str | None = None):
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError("anthropic SDK required for ClaudeVLM") from exc
        import base64, mimetypes
        self._anthropic = anthropic
        self._base64 = base64
        self._mt = mimetypes
        self._client = anthropic.Anthropic()
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    def describe(self, image_path: Path, caption: str = "") -> str:
        data = self._base64.b64encode(image_path.read_bytes()).decode()
        media = self._mt.guess_type(str(image_path))[0] or "image/png"
        msg = self._client.messages.create(
            model=self.model, max_tokens=600,
            system=(
                "你是量化研究图表理解助手。给定一张研报图，请输出 Markdown："
                "1) 图的类型与主轴含义；2) 关键数据点或趋势（可估算的数字）；"
                "3) 与文中可能相关的结论；4) 任何看起来异常的视觉细节。"
                "不要编造未呈现的细节。"
            ),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
                    {"type": "text", "text": f"caption: {caption or '(无)'}"},
                ],
            }],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def get_vlm(prefer: str | None = None) -> VLMBackend:
    pref = (prefer or os.environ.get("KB_VLM", "heuristic")).lower()
    if pref in ("claude", "anthropic"):
        try:
            return ClaudeVLM()
        except Exception as exc:
            log.warning("ClaudeVLM unavailable (%s); using heuristic.", exc)
    return HeuristicVLM()


@dataclass
class DescribeResult:
    source_id: str
    described: int
    skipped: int


def describe_figures(source_id: str, converted_dir: Path, *, backend: VLMBackend | None = None) -> DescribeResult:
    backend = backend or get_vlm()
    src_dir = converted_dir / source_id
    figures_dir = src_dir / "figures"
    if not figures_dir.exists():
        return DescribeResult(source_id=source_id, described=0, skipped=0)

    manifest_path = src_dir / "manifest.json"
    captions: dict[str, str] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for fg in manifest.get("figures") or []:
                captions[fg.get("image_path", "").rsplit("/", 1)[-1]] = fg.get("caption", "")
        except Exception as exc:
            log.warning("manifest read failed: %s", exc)

    described = 0
    skipped = 0
    for img in sorted(figures_dir.glob("*.png")):
        md = img.with_suffix(".md")
        if md.exists():
            skipped += 1
            continue
        text = backend.describe(img, captions.get(img.name, ""))
        md.write_text(text, encoding="utf-8")
        described += 1
    return DescribeResult(source_id=source_id, described=described, skipped=skipped)
