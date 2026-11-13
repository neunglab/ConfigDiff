from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import codecs
import hashlib
import json
import os
import stat
import tempfile
from datetime import datetime


@dataclass
class Source:
    name: str = ""
    path: str = ""
    text: str = ""
    disk_hash: str = ""
    encoding: str = "Unknown"

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()


@dataclass
class Block:
    key: str
    category: str
    start: int
    lines: list[str]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_source(path: str) -> Source:
    data = Path(path).read_bytes()
    if b"\0" in data:
        raise ValueError("Binary files are not supported")
    has_bom = data.startswith(b"\xef\xbb\xbf")
    try:
        content = (data[3:] if has_bom else data).decode("utf-8")
        encoding = "UTF-8 BOM" if has_bom else "UTF-8"
    except UnicodeDecodeError:
        content = codecs.latin_1_decode(data)[0]
        encoding = "Latin-1 fallback"
    return Source(Path(path).name, str(Path(path).resolve()), content, digest(data), encoding)


def encode_source_text(text: str, encoding: str) -> bytes:
    if encoding == "UTF-8 BOM":
        return b"\xef\xbb\xbf" + text.encode("utf-8")
    return codecs.latin_1_encode(text)[0] if encoding == "Latin-1 fallback" else text.encode("utf-8")


def platform(text: str) -> str:
    low = text.lower()
    if "nx-os" in low or "feature vpc" in low or "vpc domain" in low:
        return "NX-OS"
    if "ios xe" in low or "ios-xe" in low:
        return "IOS XE"
    return "IOS / unknown"


def category(header: str) -> str:
    if header.startswith("interface "): return "Interfaces"
    if header.startswith(("router bgp ", "router ospf ", "router eigrp ", "router isis ")): return "Routing"
    if header.startswith(("ip access-list ", "ipv6 access-list ", "access-list ")): return "ACLs"
    if header.startswith("route-map "): return "Route Maps"
    if header.startswith(("policy-map ", "class-map ")): return "QoS"
    if header.startswith(("vrf definition ", "vrf context ", "ip vrf ")): return "VRFs"
    if header.startswith(("vpc domain ", "feature ")): return "NX-OS"
    return "Other"


def parse_blocks(lines: list[str]) -> list[Block]:
    """Conservative top-level grouping; never drops unknown text or reorders children."""
    blocks: list[Block] = []
    for i, line in enumerate(lines):
        if line and not line[0].isspace() and line != "!":
            blocks.append(Block(line.strip(), category(line.strip()), i, [line]))
        elif blocks:
            blocks[-1].lines.append(line)
        else:
            blocks.append(Block("(preamble)", "Other", i, [line]))
    # Duplicate top-level commands remain distinct; their order is significant.
    return blocks


def block_summary(base: list[str], other: list[str]) -> list[tuple[str, str, int]]:
    a, b = parse_blocks(base), parse_blocks(other)
    # Match repeated headers by occurrence, preserving potentially ordered ACL/route-map clauses.
    def indexed(items: list[Block]) -> dict[tuple[str, int], Block]:
        counts: dict[str, int] = {}
        result = {}
        for block in items:
            n = counts.get(block.key, 0)
            counts[block.key] = n + 1
            result[(block.key, n)] = block
        return result
    left, right = indexed(a), indexed(b)
    results = []
    for key in list(left) + [k for k in right if k not in left]:
        x, y = left.get(key), right.get(key)
        status = "Removed" if y is None else "Added" if x is None else "Changed" if x.lines != y.lines else "Same"
        results.append((x.category if x else y.category, f"{key[0]}{f' ({key[1]+1})' if key[1] else ''} — {status}", x.start if x else 0))
    return results


@dataclass
class Aligned:
    indexes: list[tuple[int | None, ...]]
    kinds: list[tuple[str, ...]]


def _pair(base: list[str], other: list[str]) -> tuple[list[int | None], list[list[int]]]:
    anchors: list[int | None] = [None] * len(base)
    slots: list[list[int]] = [[] for _ in range(len(base) + 1)]
    def command_key(line: str) -> str:
        words = line.split(maxsplit=1)
        return words[0] if words else ""

    for tag, i1, i2, j1, j2 in SequenceMatcher(None, base, other, autojunk=False).get_opcodes():
        if tag == "insert":
            slots[i1].extend(range(j1, j2))
        elif tag == "replace" and (i2-i1 != j2-j1) and max(i2-i1, j2-j1) <= 120:
            # In an uneven hunk, positional matching can link unrelated Cisco
            # commands (for example a removed peer to a changed logging line).
            # Keep only plausible, order-preserving command matches.
            next_base = i1
            pending: list[int] = []
            for right in range(j1, j2):
                right_command = command_key(other[right])
                candidates = [left for left in range(next_base, i2)
                              if command_key(base[left]) == right_command]
                best = max(candidates, key=lambda left: SequenceMatcher(None, base[left], other[right]).ratio(), default=None)
                score = SequenceMatcher(None, base[best], other[right]).ratio() if best is not None else 0
                if best is None or score < .5:
                    pending.append(right)
                    continue
                slots[best].extend(pending)
                pending.clear()
                anchors[best] = right
                next_base = best + 1
            slots[i2].extend(pending)
        elif tag in ("equal", "replace"):
            common = min(i2-i1, j2-j1)
            for offset in range(common):
                anchors[i1+offset] = j1+offset
            slots[i1+common].extend(range(j1+common, j2))
    return anchors, slots


def _pair_with_anchors(base: list[str], other: list[str], manual: list[tuple[int, int]]):
    """Pair ordered segments around user-selected lines without moving source lines."""
    if not manual:
        return _pair(base, other)
    anchors: list[int | None] = [None] * len(base)
    slots: list[list[int]] = [[] for _ in range(len(base) + 1)]
    previous_left = previous_right = -1
    for left, right in [*manual, (len(base), len(other))]:
        if not (previous_left < left <= len(base) and previous_right < right <= len(other)):
            raise ValueError("Alignment lines must be in the same order on both sides")
        a_start, b_start = previous_left + 1, previous_right + 1
        matched, inserted = _pair(base[a_start:left], other[b_start:right])
        for offset, index in enumerate(matched):
            anchors[a_start + offset] = b_start + index if index is not None else None
        for offset, indexes in enumerate(inserted):
            slots[a_start + offset].extend(b_start + index for index in indexes)
        if left < len(base):
            anchors[left] = right
        previous_left, previous_right = left, right
    return anchors, slots


def align(sources: list[Source], manual_anchors: dict[int, list[tuple[int, int]]] | None = None) -> Aligned:
    if len(sources) < 2 or len(sources) > 3:
        raise ValueError("Compare two or three sources")
    base = sources[0].lines
    pairs = [_pair_with_anchors(base, source.lines, sorted((manual_anchors or {}).get(side, [])))
             for side, source in enumerate(sources[1:], 1)]
    indexes: list[tuple[int | None, ...]] = []
    kinds: list[tuple[str, ...]] = []
    for slot in range(len(base) + 1):
        height = max(len(p[1][slot]) for p in pairs)
        for j in range(height):
            idx = (None, *(p[1][slot][j] if j < len(p[1][slot]) else None for p in pairs))
            indexes.append(idx)
            kinds.append(tuple("gap" if k is None else "added" for k in idx))
        if slot < len(base):
            idx = (slot, *(p[0][slot] for p in pairs))
            indexes.append(idx)
            values = ["same"]
            for side, index in enumerate(idx[1:], 1):
                values.append("removed" if index is None else "same" if base[slot] == sources[side].lines[index] else "changed")
            kinds.append(tuple(values))
    return Aligned(indexes, kinds)


def backup_paths(path: str) -> list[Path]:
    target = Path(path)
    return sorted(target.parent.glob(target.name + ".*.bak"), reverse=True)


def atomic_save(path: str, data: bytes, keep: int = 10) -> None:
    """Back up an existing target, then atomically replace it. Never prune on failed writes."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("Refusing to overwrite a symbolic link; choose a regular file")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix="." + target.name + ".", delete=False) as file:
            temp_path = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if target.exists():
            os.chmod(temp_path, stat.S_IMODE(target.stat().st_mode))
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = target.with_name(f"{target.name}.{stamp}.bak")
            # Exclusive creation prevents a backup name collision from overwriting history.
            with backup.open("xb") as file:
                file.write(target.read_bytes())
                file.flush()
                os.fsync(file.fileno())
        os.replace(temp_path, target)
        temp_path = None
        for old in backup_paths(path)[keep:]:
            old.unlink()
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def project_bytes(sources: list[Source], font_size: float, font_family: str = "Menlo") -> bytes:
    return json.dumps({"format": 1, "font_size": font_size, "font_family": font_family,
                       "sources": [{"name": s.name, "path": s.path, "text": s.text,
                                    "disk_hash": s.disk_hash, "encoding": s.encoding} for s in sources]},
                      ensure_ascii=False, indent=2).encode("utf-8")


def open_project(path: str) -> tuple[list[Source], float, str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != 1 or not 2 <= len(data.get("sources", [])) <= 3:
        raise ValueError("Unsupported or incomplete project")
    return ([Source(**item) for item in data["sources"]],
            max(9.0, min(30.0, float(data.get("font_size", 14)))),
            data.get("font_family", "Menlo"))
