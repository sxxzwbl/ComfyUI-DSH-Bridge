"""Parsing of model answers into node outputs."""

from __future__ import annotations

import json
import re
from typing import Any

_MARKER = re.compile(r"[\u3010]([^\u3011]{1,16})[\u3011]")
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$", re.MULTILINE)

# A refusal often *names* the section markers while declining to produce them —
# "…我会给出【正向提示词】和【负向提示词】两段成品。" Splitting on the markers then
# yields the connector "和" as the positive prompt. Detect that shape and fall back
# to the whole reply so the operator reads what the model actually said.
_CONNECTORS = {"和", "与", "及", "以及", "、", "/", "&", "和：", "和:", "，", ","}
_REFUSAL = re.compile(
    r"(无法|不能|不便|不予|抱歉|对不起|恕难|拒绝|露骨|色情|违规|敏感|请提供|请上传|请更换|请补充"
    r"|not able to|cannot|can't|unable|sorry)",
    re.IGNORECASE,
)


def _degenerate_split(positive: str, negative: str, source: str) -> bool:
    """True when the marker split produced a connector instead of content."""
    head = (positive or "").strip()
    if not head:
        return False
    if head in _CONNECTORS:
        return True
    if len(head) <= 4 and len((negative or "").strip()) <= 12 and _REFUSAL.search(source or ""):
        return True
    return False

_ALIASES = {
    "\u6b63\u5411\u63d0\u793a\u8bcd": "positive",
    "\u6b63\u5411": "positive",
    "\u63d0\u793a\u8bcd": "prompt",
    "negative prompt": "negative",
    "\u8d1f\u5411\u63d0\u793a\u8bcd": "negative",
    "\u8d1f\u5411": "negative",
    "\u5206\u6790": "analysis",
    "\u5173\u952e\u8bcd": "tags",
    "json": "json",
    "\u603b\u8ff0": "overview",
    "\u8fd0\u955c\u63cf\u8ff0": "camera",
    "\u58f0\u97f3": "audio",
    "\u91cd\u7ed8\u63d0\u793a\u8bcd": "rewrite",
}


def strip_fences(text: str) -> str:
    return _FENCE.sub("", text or "").strip()


def iter_json_candidates(text: str):
    """Yield every brace-balanced substring that parses as a JSON object."""
    source = text or ""
    for start, char in enumerate(source):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(source)):
            current = source[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidate = source[start : index + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict):
                        yield candidate, parsed
                    break


def extract_json(text: str) -> tuple[str, dict[str, Any] | None]:
    for raw, parsed in iter_json_candidates(strip_fences(text)):
        return raw, parsed
    return "", None


def sections(text: str) -> dict[str, str]:
    """Split on 【marker】 headings into canonical keys."""
    cleaned = strip_fences(text)
    matches = list(_MARKER.finditer(cleaned))
    if not matches:
        return {}
    out: dict[str, str] = {}
    for position, match in enumerate(matches):
        label = match.group(1).strip()
        key = _ALIASES.get(label.lower(), _ALIASES.get(label, label))
        end = matches[position + 1].start() if position + 1 < len(matches) else len(cleaned)
        value = cleaned[match.end() : end].strip()
        if key not in out or not out[key]:
            out[key] = value
    return out


def _first(mapping: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key, "")
        if value:
            return value
    return ""


def _strip_payload(text: str, raw_json: str, *markers: str) -> str:
    body = text or ""
    if raw_json:
        body = body.replace(raw_json, "")
    for marker in markers:
        body = body.replace(marker, "")
    return body.strip()


# ------------------------------------------------------------ task sections
#
# Task-driven replies use explicit section banners instead of the 【…】 markers the
# old builders relied on. Analysis is kept out of the prompt slot on purpose: it
# carries the mapping table, the retention lists and the precision caveats, none of
# which may reach a CLIP encoder.

_SECTION_LINE = re.compile(r"^[ \t]*={3,}[ \t]*([A-Za-z_\u4e00-\u9fff]+)[ \t]*={3,}[ \t]*$", re.MULTILINE)
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_TICK = re.compile(r"`([^`\n]+)`")
_MD_HEAD = re.compile(r"^#{1,6}[ \t]*", re.MULTILINE)

_SECTION_ALIASES = {
    "ANALYSIS": "analysis",
    "PROMPT": "prompt",
    "NOTES": "notes",
    "分析": "analysis",
    "提示词": "prompt",
    "备注": "notes",
}


def clean_prompt(text: str) -> str:
    """Strip markdown that has no business inside a text encoder input."""
    body = strip_fences(text or "")
    body = _MD_BOLD.sub(r"\1", body)
    body = _MD_TICK.sub(r"\1", body)
    body = _MD_HEAD.sub("", body)
    return body.strip()


def split_sections(text: str) -> dict[str, str]:
    """Split a reply on `=== ANALYSIS ===` / `=== PROMPT ===`.

    Returns whatever sections were found plus `raw`. When no banner is present the
    whole reply lands in `prompt`, so a model that ignores the contract still ships
    something instead of an empty slot.
    """
    body = strip_fences(text or "")
    matches = list(_SECTION_LINE.finditer(body))
    if not matches:
        return {"analysis": "", "prompt": clean_prompt(body), "notes": "", "raw": body}

    found: dict[str, str] = {}
    for position, match in enumerate(matches):
        label = match.group(1).strip()
        key = _SECTION_ALIASES.get(label.upper(), _SECTION_ALIASES.get(label, label.lower()))
        end = matches[position + 1].start() if position + 1 < len(matches) else len(body)
        value = body[match.end() : end].strip()
        if not found.get(key):
            found[key] = value

    prompt = clean_prompt(found.get("prompt", ""))
    analysis = found.get("analysis", "")
    return {
        "analysis": analysis,
        "prompt": prompt,
        "notes": found.get("notes", ""),
        "raw": body,
    }


def split_positive_negative(text: str) -> tuple[str, str, str]:
    """Return `(positive, negative, json_text)` for prompt-producing answers."""
    raw_json, parsed = extract_json(text)
    found = sections(text)
    positive = _first(found, "positive", "prompt", "rewrite")
    negative = _first(found, "negative")
    if parsed:
        positive = positive or str(parsed.get("positive") or parsed.get("prompt") or "")
        negative = negative or str(parsed.get("negative") or "")
    if _degenerate_split(positive, negative, text):
        # The reply declined and only mentioned the markers: keep it verbatim in
        # the prompt slot instead of shipping "和" downstream.
        return strip_fences(text).strip(), "", raw_json
    if not positive:
        positive = strip_fences(text)
    positive = _strip_payload(positive, raw_json, "【正向提示词】", "【提示词】", "【重绘提示词】")
    if negative:
        negative = _strip_payload(negative, raw_json, "【负向提示词】")
    return positive.strip(), negative.strip(), raw_json


def split_analysis(text: str) -> tuple[str, str, str]:
    raw_json, parsed = extract_json(text)
    found = sections(text)
    analysis = _first(found, "analysis")
    tags = _first(found, "tags")
    if _degenerate_split(analysis, tags, text):
        return strip_fences(text).strip(), "", raw_json
    if not analysis:
        analysis = strip_fences(text)
    if not tags and parsed:
        tags = ", ".join(str(v) for v in parsed.values() if isinstance(v, (str, int, float)))
    analysis = _strip_payload(analysis, raw_json, "【分析】", "【关键词】", "【JSON】")
    tags = _strip_payload(tags, raw_json, "【关键词】")
    return analysis.strip(), tags.strip(), raw_json


def _is_timeline(parsed: dict[str, Any]) -> bool:
    return isinstance(parsed.get("segments"), list)


def split_video(text: str) -> tuple[str, str, str]:
    """Return `(prompt, timeline_json, motion)`."""
    raw_json, parsed = extract_json(text)
    found = sections(text)
    prompt = _first(found, "overview", "prompt", "positive")
    motion = _first(found, "camera", "audio")
    if _degenerate_split(prompt, motion, text):
        return strip_fences(text).strip(), raw_json, ""
    if not prompt:
        prompt = strip_fences(text)
    prompt = _strip_payload(prompt, raw_json, "【总述】", "【提示词】", "【运镜描述】", "【声音】")
    if not motion and parsed:
        motion = str(parsed.get("motion") or parsed.get("camera") or "")
    return prompt.strip(), raw_json, motion.strip()


def timeline_summary(timeline_json: str, limit: int = 3) -> str:
    """Short natural-language summary from a timeline payload (for the `prompt` slot)."""
    if not timeline_json:
        return ""
    try:
        parsed = json.loads(timeline_json)
    except json.JSONDecodeError:
        return ""
    segments = parsed.get("segments") if isinstance(parsed, dict) else None
    if not isinstance(segments, list):
        return ""
    pieces = [str(segment.get("desc") or "").strip() for segment in segments[:limit] if isinstance(segment, dict)]
    return "；".join(piece for piece in pieces if piece)


def normalize_timeline(raw_json: str, duration: float) -> str:
    """Validate a timeline payload; return a normalized JSON string."""
    if not raw_json:
        return ""
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return raw_json
    if _is_timeline(parsed):
        segments = []
        for segment in parsed["segments"]:
            if not isinstance(segment, dict):
                continue
            try:
                t0 = float(segment.get("t0", 0.0))
                t1 = float(segment.get("t1", 0.0))
            except (TypeError, ValueError):
                continue
            segments.append(
                {
                    "t0": round(t0, 3),
                    "t1": round(t1, 3),
                    "desc": str(segment.get("desc") or ""),
                    "camera": str(segment.get("camera") or ""),
                }
            )
        parsed["segments"] = segments
        if "duration_s" not in parsed:
            parsed["duration_s"] = duration
    return json.dumps(parsed, ensure_ascii=False)
