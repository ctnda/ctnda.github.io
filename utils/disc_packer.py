"""
Disc Packer — pack files from a directory onto discs (DVD5, etc.) efficiently.

Uses First-Fit Decreasing (FFD) bin packing to maximise utilisation.

Features
- Recursively scans an input folder (default: current directory)
- Preset media profiles (dvd5, dvd9, bdr25, cd700, custom)
- Configurable capacity, reserve percentage, and per-file overhead
- Exclude patterns / include extensions
- Produces a packing plan printed to stdout
- Optional: export JSON/CSV manifests
- Optional: materialise a staging tree with symlinks/hardlinks/copies

Example
-------
# Plan for DVD5 discs with a 2% safety reserve
python disc_packer.py /path/to/media --profile dvd5 --reserve 2 \
  --export-json plan.json --export-csv plan.csv

# Create a staging directory with symlinks for each disc
python disc_packer.py /path/to/media --profile dvd5 \
  --materialise /tmp/disc_staging --link-type symlink

# Custom capacity (in GiB)
python disc_packer.py /path/to/media --capacity 7.95 --unit GiB

Notes on capacities
-------------------
Real-world DVD5 capacity is ~4,700,372,992 bytes (~4.38 GiB). The preset uses
that value and you can add a reserve (default 2%) for filesystem overhead.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# ------------------------- Capacity presets (bytes) ------------------------- #
MEDIA_PROFILES: Dict[str, int] = {
    # Nominal capacities in bytes (conservative where applicable)
    "dvd5": 4_700_372_992,   # Single-layer DVD (~4.38 GiB)
    "dvd9": 8_540_000_000,   # Dual-layer DVD (~7.95 GiB)
    "cd700": 700 * 1_000_000, # 700 MB CD (mode 1 approx)
    "bdr25": 25 * 1_000_000_000, # 25 GB BD-R single layer
    "bdr50": 50 * 1_000_000_000, # 50 GB BD-R dual layer
}

UNIT_FACTORS = {
    "B": 1,
    "KB": 1_000,
    "KiB": 1024,
    "MB": 1_000_000,
    "MiB": 1024**2,
    "GB": 1_000_000_000,
    "GiB": 1024**3,
}

# ------------------------------ Data classes ------------------------------- #
@dataclass
class FileEntry:
    path: Path
    size: int

@dataclass
class Bin:
    index: int
    capacity: int
    reserve_bytes: int = 0
    used: int = 0
    files: List[FileEntry] = field(default_factory=list)

    @property
    def effective_capacity(self) -> int:
        return max(0, self.capacity - self.reserve_bytes)

    @property
    def remaining(self) -> int:
        return self.effective_capacity - self.used

    @property
    def utilisation(self) -> float:
        if self.effective_capacity == 0:
            return 0.0
        return self.used / self.effective_capacity

    def try_add(self, fe: FileEntry, per_file_overhead: int = 0) -> bool:
        needed = fe.size + per_file_overhead
        if needed <= self.remaining:
            self.files.append(fe)
            self.used += needed
            return True
        return False

# ----------------------------- Core algorithm ------------------------------ #

def first_fit_decreasing(files: List[FileEntry], capacity: int, reserve_bytes: int,
                          per_file_overhead: int) -> Tuple[List[Bin], List[FileEntry]]:
    """Pack files using First-Fit Decreasing.

    Returns (bins, skipped) where `skipped` are files larger than a single bin.
    """
    # Sort by size descending for FFD
    files_sorted = sorted(files, key=lambda f: f.size, reverse=True)

    bins: List[Bin] = []
    skipped: List[FileEntry] = []

    effective_capacity = max(0, capacity - reserve_bytes)
    too_big_thresh = max(0, effective_capacity - per_file_overhead)

    for fe in files_sorted:
        if fe.size > too_big_thresh:
            # Cannot fit even in an empty bin (considering per-file overhead)
            skipped.append(fe)
            continue
        placed = False
        for b in bins:
            if b.try_add(fe, per_file_overhead):
                placed = True
                break
        if not placed:
            new_bin = Bin(index=len(bins) + 1, capacity=capacity, reserve_bytes=reserve_bytes)
            assert new_bin.try_add(fe, per_file_overhead)  # must fit
            bins.append(new_bin)
    return bins, skipped

# ------------------------------ File scanning ------------------------------ #

def scan_files(root: Path, include_ext: Optional[List[str]] = None,
               exclude_globs: Optional[List[str]] = None,
               follow_symlinks: bool = False,
               ignore_hidden: bool = True) -> List[FileEntry]:
    files: List[FileEntry] = []
    include_set = None
    if include_ext:
        include_set = {e.lower().lstrip('.') for e in include_ext}

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        # Optionally skip hidden directories
        if ignore_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        for name in filenames:
            if ignore_hidden and name.startswith('.'):
                continue
            p = Path(dirpath) / name
            # Apply excludes
            if exclude_globs and any(fnmatch.fnmatch(name, pat) for pat in exclude_globs):
                continue
            # Apply include by extension
            if include_set is not None and p.suffix.lower().lstrip('.') not in include_set:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            files.append(FileEntry(path=p, size=size))
    return files

# ------------------------------ Presentation ------------------------------- #

def human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ["KiB", "MiB", "GiB", "TiB"]:
        n /= 1024.0
        if abs(n) < 1024.0:
            return f"{n:.2f} {unit}"
    return f"{n:.2f} PiB"

# ------------------------------ Materialise -------------------------------- #

def materialise_plan(bins: List[Bin], staging_dir: Path, link_type: str) -> None:
    staging_dir.mkdir(parents=True, exist_ok=True)
    for b in bins:
        out_dir = staging_dir / f"disc_{b.index:03d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for fe in b.files:
            dest = out_dir / fe.path.name
            if link_type == "symlink":
                try:
                    dest.symlink_to(fe.path)
                except FileExistsError:
                    dest.unlink()
                    dest.symlink_to(fe.path)
            elif link_type == "hardlink":
                try:
                    os.link(fe.path, dest)
                except FileExistsError:
                    dest.unlink()
                    os.link(fe.path, dest)
            elif link_type == "copy":
                shutil.copy2(fe.path, dest)
            else:
                raise ValueError(f"Unknown link type: {link_type}")

# ------------------------------- Exports ----------------------------------- #

def export_json(bins: List[Bin], skipped: List[FileEntry], path: Path) -> None:
    data = {
        "bins": [
            {
                "index": b.index,
                "capacity_bytes": b.capacity,
                "reserve_bytes": b.reserve_bytes,
                "effective_capacity_bytes": b.effective_capacity,
                "used_bytes": b.used,
                "utilisation": b.utilisation,
                "files": [
                    {"path": str(fe.path), "size": fe.size}
                    for fe in b.files
                ],
            }
            for b in bins
        ],
        "skipped": [{"path": str(f.path), "size": f.size} for f in skipped],
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def export_csv(bins: List[Bin], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["disc_index", "file_path", "size_bytes"])
        for b in bins:
            for fe in b.files:
                w.writerow([b.index, str(fe.path), fe.size])

# ------------------------------- CLI --------------------------------------- #

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pack files onto discs efficiently (FFD)")
    p.add_argument("root", type=Path, nargs="?", default=Path.cwd(),
                   help="Root folder to scan recursively (default: current directory)")

    prof_choices = ", ".join(sorted(MEDIA_PROFILES.keys()))
    p.add_argument("--profile", choices=sorted(MEDIA_PROFILES.keys()),
                   help=f"Media profile to use ({prof_choices})")

    p.add_argument("--capacity", type=float,
                   help="Custom capacity value (use with --unit)")
    p.add_argument("--unit", choices=list(UNIT_FACTORS.keys()), default="GiB",
                   help="Unit for --capacity (default: GiB)")

    p.add_argument("--reserve", type=float, default=2.0,
                   help="Safety reserve as percent of capacity (default: 2.0)")
    p.add_argument("--per-file-overhead", type=int, default=0,
                   help="Per-file overhead in bytes (default: 0)")

    p.add_argument("--include-ext", nargs="*",
                   help="Only include files with these extensions (e.g. mp4 mkv flac wav)")
    p.add_argument("--exclude", nargs="*",
                   help="Glob patterns to exclude (e.g. *.part *.tmp)")
    p.add_argument("--follow-symlinks", action="store_true",
                   help="Follow directory symlinks when scanning")
    p.add_argument("--no-hidden", action="store_true",
                   help="Ignore hidden files and folders (default: on)")

    p.add_argument("--export-json", type=Path,
                   help="Write plan as JSON to this path")
    p.add_argument("--export-csv", type=Path,
                   help="Write plan as CSV (disc_index, file_path, size_bytes)")

    p.add_argument("--materialise", type=Path,
                   help="Create a staging directory with disc_XXX folders")
    p.add_argument("--link-type", choices=["symlink", "hardlink", "copy"], default="symlink",
                   help="How to place files in staging (default: symlink)")

    return p.parse_args(argv)


def resolve_capacity(args: argparse.Namespace) -> int:
    if args.profile:
        cap = MEDIA_PROFILES[args.profile]
    elif args.capacity is not None:
        cap = int(args.capacity * UNIT_FACTORS[args.unit])
    else:
        # Default to DVD5 if nothing specified
        cap = MEDIA_PROFILES["dvd5"]
    return cap

# --------------------------------- Main ------------------------------------ #

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    capacity = resolve_capacity(args)
    reserve_bytes = int(capacity * (args.reserve / 100.0)) if args.reserve else 0

    files = scan_files(
        root=args.root,
        include_ext=args.include_ext,
        exclude_globs=args.exclude,
        follow_symlinks=args.follow_symlinks,
        ignore_hidden=args.no_hidden or True,
    )

    if not files:
        print("No files found to pack.", file=sys.stderr)
        return 2

    bins, skipped = first_fit_decreasing(
        files=files,
        capacity=capacity,
        reserve_bytes=reserve_bytes,
        per_file_overhead=args.per_file_overhead,
    )

    # ----- Print summary ----- #
    print(f"Media capacity: {human_bytes(capacity)} (reserve {human_bytes(reserve_bytes)})")
    print(f"Files considered: {len(files)} | Packed: {sum(len(b.files) for b in bins)} | Skipped: {len(skipped)}")
    print(f"Discs required: {len(bins)}\n")

    for b in bins:
        print(f"Disc {b.index:03d}: used {human_bytes(b.used)} / {human_bytes(b.effective_capacity)}"
              f" ({b.utilisation*100:.1f}% utilised)")
        for fe in b.files:
            print(f"  - {fe.path} ({human_bytes(fe.size)})")
        print()

    if skipped:
        print("Skipped files (too large for one disc):")
        for fe in skipped:
            print(f"  - {fe.path} ({human_bytes(fe.size)})")
        print()

    # ----- Exports ----- #
    if args.export_json:
        export_json(bins, skipped, args.export_json)
        print(f"Wrote JSON plan to {args.export_json}")
    if args.export_csv:
        export_csv(bins, args.export_csv)
        print(f"Wrote CSV plan to {args.export_csv}")

    # ----- Materialise ----- #
    if args.materialise:
        materialise_plan(bins, args.materialise, args.link_type)
        print(f"Materialised plan under {args.materialise} using {args.link_type}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
