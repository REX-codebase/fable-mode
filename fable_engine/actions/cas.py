"""CAS storage, payload compression, slice viewing, and accumulation action handlers."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("fable-engine.actions.cas")

from fable_engine.cas import (
    CAS_ENGINE,
    AdaptiveChunkAccumulator,
    CompositeFrame,
    CASSliceViewer,
    DATA_DIR,
    MAX_CAS_OBJECT_BYTES,
    MAX_SLICE_RESPONSE_BYTES,
    MAX_RPC_RESPONSE_BYTES,
)
from fable_engine.session import FableSession

def _handle_compress_payload(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    content = arguments.get("content")
    if content is None:
        content = arguments.get("payload")
    if content is None:
        return "Error: 'content' (or 'payload') is required for action 'compress_payload'."
    label = arguments.get("label", "payload")
    content_text = str(content)
    if len(content_text.encode("utf-8")) > MAX_CAS_OBJECT_BYTES:
        return "Error: payload exceeds maximum CAS object size."

    compressed_node = CAS_ENGINE.compress_payload_to_cas(content_text, label=label)
    raw_len = len(content_text)
    raw_tokens = CAS_ENGINE.estimate_token_count(content_text)
    comp_repr = json.dumps(compressed_node, separators=(",", ":"))
    comp_tokens = CAS_ENGINE.estimate_token_count(comp_repr)
    ratio = CAS_ENGINE.calculate_token_ratio(content_text, comp_repr)

    invariant_met = ratio <= 0.003 if raw_len >= 10000 else True
    badge = "✅ PASS (<= 0.003 tokens/char)" if invariant_met else f"⚠️ Ratio: {ratio:.6f} tokens/char"

    return (
        f"### 🗜️ Fable CAS Payload Compressed\n\n"
        f"- **CAS URI**: `{compressed_node['cas_ref']}`\n"
        f"- **Line Count**: `{compressed_node['lines']}`\n"
        f"- **Raw Size**: `{raw_len}` characters (~`{raw_tokens}` tokens)\n"
        f"- **Compressed Reference Size**: `{len(comp_repr)}` characters (~`{comp_tokens}` tokens)\n"
        f"- **Token Compression Ratio**: `{ratio:.6f}` tokens/char\n"
        f"- **Invariant Status**: {badge}\n"
        f"- **JSON Descriptor**:\n```json\n{json.dumps(compressed_node, indent=2)}\n```\n\n"
        f"> [!TIP]\n"
        f"> Use action `view_slice` with `cas_ref` to inspect specific line windows without loading full payload."
    )


def _handle_decompress_payload(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    cas_ref = arguments.get("cas_ref") or arguments.get("ref_or_hash")
    if not cas_ref:
        return "Error: 'cas_ref' is required for action 'decompress_payload'."
    try:
        text = CAS_ENGINE.cas_store.get_text(cas_ref, verify=True)
        if len(text.encode("utf-8")) > MAX_RPC_RESPONSE_BYTES // 2:
            return "Error: decompressed response exceeds maximum size; use view_slice."
        lines = CAS_ENGINE.slice_viewer.get_line_count(cas_ref)
        return (
            f"### 📦 Fable CAS Payload Retrieved\n\n"
            f"- **CAS URI**: `{cas_ref}`\n"
            f"- **Total Length**: `{len(text)}` characters\n"
            f"- **Total Lines**: `{lines}`\n\n"
            f"```text\n{text}\n```"
        )
    except Exception as e:
        return f"Error decompressing CAS payload: {e}"


def _handle_view_slice(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    cas_ref = arguments.get("cas_ref") or arguments.get("ref_or_hash")
    if not cas_ref:
        return "Error: 'cas_ref' is required for action 'view_slice'."
    start_line = int(arguments.get("start_line", 1))
    end_line = int(arguments.get("end_line", 100))
    include_line_numbers = bool(arguments.get("include_line_numbers", False))

    try:
        slice_text = CAS_ENGINE.slice_viewer.view_slice(
            cas_ref, start_line, end_line, include_line_numbers=include_line_numbers
        )
        total_lines = CAS_ENGINE.slice_viewer.get_line_count(cas_ref)
        return (
            f"### 🔍 Fable CAS Slice View (`{start_line}` - `{end_line}` of `{total_lines}` lines)\n\n"
            f"- **CAS URI**: `{cas_ref}`\n"
            f"- **Range**: Lines {start_line}..{end_line}\n\n"
            f"```text\n{slice_text}\n```"
        )
    except Exception as e:
        return f"Error reading CAS slice: {e}"


def _handle_accumulate_payload(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    payload = arguments.get("payload")
    if payload is None:
        payload = arguments.get("content")
    if payload is None:
        return "Error: 'payload' is required for action 'accumulate_payload'."
    metadata = arguments.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {"raw": metadata}
    force_flush = bool(arguments.get("force_flush", False))

    flushed = CAS_ENGINE.accumulator.add(str(payload), metadata=metadata, force_flush=force_flush)
    stats = CAS_ENGINE.accumulator.get_stats()

    flushed_str = "\n".join([f"- Flushed Composite Frame: `{u}`" for u in flushed]) if flushed else "- No frame flushed yet (buffering micro-payload)."
    return (
        f"### 📥 Micro-Payload Ingested\n\n"
        f"- **Buffered Items**: `{stats['currently_buffered_items']}`\n"
        f"- **Buffered Chars**: `{stats['currently_buffered_chars']}` / `{CAS_ENGINE.accumulator.min_frame_size}` bytes threshold\n"
        f"- **Total Ingested**: `{stats['total_payloads_ingested']}`\n"
        f"- **Total Frames Flushed**: `{stats['total_frames_flushed']}`\n\n"
        f"{flushed_str}"
    )


def _handle_flush_accumulator(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    flushed = CAS_ENGINE.accumulator.flush()
    stats = CAS_ENGINE.accumulator.get_stats()
    if flushed:
        flushed_str = "\n".join([f"- Flushed Frame: `{u}`" for u in flushed])
        return (
            f"### 🚀 Micro-Payload Accumulator Flushed\n\n"
            f"- **Flushed Frames**: `{len(flushed)}`\n"
            f"- **Total CAS Bytes Written**: `{stats['total_cas_bytes_written']}`\n\n"
            f"{flushed_str}"
        )
    return (
        f"### ℹ️ Micro-Payload Accumulator Buffer Empty\n\n"
        f"- **Currently Buffered**: `0` items\n"
        f"- **Total Frames Flushed**: `{stats['total_frames_flushed']}`"
    )


def _handle_get_compression_stats(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    stats = CAS_ENGINE.accumulator.get_stats()
    return (
        f"### 📊 Fable Token Compression Subsystem Telemetry\n\n"
        f"- **CAS Storage Root**: `{CAS_ENGINE.cas_store.root_dir}`\n"
        f"- **Memory Cache Capacity**: `{CAS_ENGINE.cas_store.cache.capacity}` entries (Current: `{len(CAS_ENGINE.cas_store.cache)}`)\n"
        f"- **Micro-Payloads Ingested**: `{stats['total_payloads_ingested']}`\n"
        f"- **Composite Frames Flushed**: `{stats['total_frames_flushed']}`\n"
        f"- **Total Raw Characters**: `{stats['total_raw_chars']}`\n"
        f"- **Total CAS Bytes Written**: `{stats['total_cas_bytes_written']}`\n"
        f"- **Currently Buffered Items**: `{stats['currently_buffered_items']}` (`{stats['currently_buffered_chars']}` chars)\n"
        f"- **Token Compression Invariant**: `<= 0.003 tokens/character`"
    )


