"""Scan data discs and generate a searchable HTML catalogue.

The catalogue stores one JSON file per disc. The disc identifier is read from
its filesystem label unless --disk-id overrides it. HTML is regenerated from
all JSON files and uses jQuery and DataTables from their public CDNs.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_DEVICE = "/dev/sr0"
DEFAULT_CATALOG_DIR = Path("data/disks")
DEFAULT_HTML_OUTPUT = Path("datadisks.html")

VIDEO_EXTENSIONS = {
    ".3g2",
    ".3gp",
    ".asf",
    ".avi",
    ".divx",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogm",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
}
AUDIO_EXTENSIONS = {
    ".aac",
    ".ac3",
    ".aiff",
    ".alac",
    ".ape",
    ".dts",
    ".flac",
    ".m4a",
    ".mp2",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}
IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}

JQUERY_URL = "https://code.jquery.com/jquery-3.7.1.min.js"
DATATABLES_CSS_URL = "https://cdn.datatables.net/1.13.11/css/jquery.dataTables.min.css"
DATATABLES_JS_URL = "https://cdn.datatables.net/1.13.11/js/jquery.dataTables.min.js"


class CatalogError(RuntimeError):
    """An actionable catalogue error suitable for CLI output."""


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def first_output_line(result: subprocess.CompletedProcess[str]) -> str | None:
    for line in result.stdout.splitlines():
        value = line.strip()
        if value:
            return value
    return None


def mounted_path(device: str) -> Path:
    result = run_command(["findmnt", "-n", "-o", "TARGET", device])
    mountpoint = first_output_line(result)
    if result.returncode != 0 or not mountpoint:
        raise CatalogError(
            f"{device} non è montato. Montare il disco oppure usare --path."
        )
    path = Path(mountpoint)
    if not path.is_dir():
        raise CatalogError(f"Il mountpoint {path} non è una directory accessibile.")
    return path


def source_device_for_path(path: Path) -> str | None:
    result = run_command(["findmnt", "-n", "-o", "SOURCE", "--target", str(path)])
    if result.returncode != 0:
        return None
    source = first_output_line(result)
    if not source or not source.startswith("/dev/"):
        return None
    return source


def filesystem_label(device: str) -> str | None:
    result = run_command(["lsblk", "-dno", "LABEL", device])
    label = first_output_line(result)
    if result.returncode == 0 and label:
        return label

    result = run_command(["blkid", "-s", "LABEL", "-o", "value", device])
    label = first_output_line(result)
    if result.returncode == 0 and label:
        return label
    return None


def resolve_scan_source(path: Path | None, device: str | None) -> tuple[Path, str | None]:
    if path is not None:
        resolved = path.expanduser().resolve()
        if not resolved.is_dir():
            raise CatalogError(f"Il percorso {resolved} non è una directory accessibile.")
        return resolved, source_device_for_path(resolved)

    selected_device = device or DEFAULT_DEVICE
    return mounted_path(selected_device), selected_device


def resolve_disk_id(override: str | None, device: str | None) -> str:
    if override is not None:
        disk_id = override.strip()
        if not disk_id:
            raise CatalogError("--disk-id non può essere vuoto.")
        return disk_id

    if not device:
        raise CatalogError(
            "Impossibile individuare il device del volume: specificare --disk-id."
        )

    label = filesystem_label(device)
    if not label:
        raise CatalogError(
            f"Il volume {device} non ha un'etichetta leggibile: specificare --disk-id."
        )
    return label


def catalogue_filename(disk_id: str) -> str:
    slug = "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in disk_id
    )
    slug = re.sub(r"_+", "_", slug).strip("._-")[:60] or "disk"
    digest = hashlib.sha256(disk_id.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}.json"


def human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(value) < 1024.0 or unit == "PiB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PiB"


def classify_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "other"


def optional_float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def optional_int(value: Any) -> int | None:
    number = optional_float(value)
    return int(number) if number is not None else None


def duration_hms(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"


def parse_frame_rate(value: Any) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        rate = float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if math.isfinite(rate) and rate > 0 else None


def derive_aspect_ratio(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def ffprobe_metadata(path: Path, ffprobe: str) -> dict[str, Any]:
    result = run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
    )
    if result.returncode != 0:
        message = result.stderr.strip() or f"ffprobe è terminato con codice {result.returncode}"
        raise CatalogError(message)

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"output JSON di ffprobe non valido: {exc}") from exc

    format_info = payload.get("format") or {}
    streams = payload.get("streams") or []
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    audio_streams = [
        stream for stream in streams if stream.get("codec_type") == "audio"
    ]
    subtitle_streams = [
        stream for stream in streams if stream.get("codec_type") == "subtitle"
    ]

    duration = optional_float(format_info.get("duration"))
    if duration is None:
        stream_durations = [
            candidate
            for candidate in (optional_float(stream.get("duration")) for stream in streams)
            if candidate is not None
        ]
        duration = max(stream_durations, default=None)

    width = optional_int(video_stream.get("width")) if video_stream else None
    height = optional_int(video_stream.get("height")) if video_stream else None
    aspect_ratio = video_stream.get("display_aspect_ratio") if video_stream else None
    if not aspect_ratio or aspect_ratio == "0:1":
        aspect_ratio = derive_aspect_ratio(width, height)

    frame_rate = None
    if video_stream:
        frame_rate = parse_frame_rate(
            video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
        )

    audio_bitrates = [
        bitrate
        for bitrate in (optional_int(stream.get("bit_rate")) for stream in audio_streams)
        if bitrate is not None
    ]
    subtitle_languages = [
        str(stream.get("tags", {}).get("language") or "und")
        for stream in subtitle_streams
    ]

    return {
        "duration_seconds": duration,
        "duration_hms": duration_hms(duration),
        "container": format_info.get("format_long_name") or format_info.get("format_name"),
        "overall_bitrate_bps": optional_int(format_info.get("bit_rate")),
        "video_codec": video_stream.get("codec_name") if video_stream else None,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "frame_rate": frame_rate,
        "audio_bitrates_bps": audio_bitrates,
        "subtitle_count": len(subtitle_streams),
        "subtitle_languages": subtitle_languages,
    }


def scan_disc(
    root: Path,
    disk_id: str,
    label: str | None,
    ffprobe: str,
) -> dict[str, Any]:
    counts = {"video": 0, "audio": 0, "image": 0, "other": 0}
    files: list[dict[str, Any]] = []

    paths = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: str(path.relative_to(root)).casefold(),
    )

    for path in paths:
        try:
            stat = path.stat()
        except OSError as exc:
            print(f"[!] Impossibile leggere {path}: {exc}", file=sys.stderr)
            continue

        category = classify_file(path)
        counts[category] += 1
        relative_path = path.relative_to(root).as_posix()
        record: dict[str, Any] = {
            "path": relative_path,
            "category": category,
            "size_bytes": stat.st_size,
            "size_human": human_size(stat.st_size),
            "modified": datetime.fromtimestamp(stat.st_mtime)
            .astimezone()
            .isoformat(timespec="seconds"),
            "media": None,
        }

        if category in {"video", "audio"}:
            try:
                record["media"] = ffprobe_metadata(path, ffprobe)
            except (CatalogError, OSError) as exc:
                record["probe_error"] = str(exc)
                print(f"[!] ffprobe: {relative_path}: {exc}", file=sys.stderr)

        files.append(record)

    return {
        "schema_version": SCHEMA_VERSION,
        "disk": {
            "id": disk_id,
            "label": label,
            "total_files": len(files),
            "video_files": counts["video"],
            "audio_files": counts["audio"],
            "image_files": counts["image"],
            "other_files": counts["other"],
        },
        "files": files,
    }


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _ = json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_catalog(catalog_dir: Path, catalog: dict[str, Any]) -> Path:
    disk_id = str(catalog["disk"]["id"])
    output = catalog_dir / catalogue_filename(disk_id)
    write_json_atomic(output, catalog)
    return output


def load_catalogues(catalog_dir: Path) -> list[dict[str, Any]]:
    if not catalog_dir.exists():
        return []

    catalogues = []
    for path in sorted(catalog_dir.glob("*.json")):
        try:
            catalog = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError(f"Impossibile leggere {path}: {exc}") from exc
        if catalog.get("schema_version") != SCHEMA_VERSION:
            raise CatalogError(
                f"Versione schema non supportata in {path}: "
                f"{catalog.get('schema_version')!r}"
            )
        if not isinstance(catalog.get("disk"), dict) or not isinstance(
            catalog.get("files"), list
        ):
            raise CatalogError(f"Struttura catalogo non valida in {path}.")
        catalogues.append(catalog)

    return sorted(catalogues, key=lambda item: str(item["disk"]["id"]).casefold())


def format_bitrate(value: int | None) -> str:
    if value is None:
        return ""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} Mbps"
    return f"{value / 1000:.0f} kbps"


def format_frame_rate(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def escaped(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def option_elements(values: Iterable[str]) -> str:
    return "".join(
        f'<option value="{escaped(value)}">{escaped(value)}</option>'
        for value in sorted(set(values), key=str.casefold)
    )


def render_html(catalogues: list[dict[str, Any]]) -> str:
    disk_ids = [str(catalog["disk"]["id"]) for catalog in catalogues]
    categories = ["audio", "image", "other", "video"]

    summary_rows = []
    file_rows = []
    total_files = 0

    for catalog in catalogues:
        disk = catalog["disk"]
        disk_id = str(disk["id"])
        total_files += int(disk["total_files"])
        summary_rows.append(
            "<tr>"
            f"<td>{escaped(disk_id)}</td>"
            f"<td>{escaped(disk.get('label'))}</td>"
            f"<td data-order=\"{int(disk['total_files'])}\">{int(disk['total_files'])}</td>"
            f"<td data-order=\"{int(disk['video_files'])}\">{int(disk['video_files'])}</td>"
            f"<td data-order=\"{int(disk['audio_files'])}\">{int(disk['audio_files'])}</td>"
            f"<td data-order=\"{int(disk['image_files'])}\">{int(disk['image_files'])}</td>"
            f"<td data-order=\"{int(disk['other_files'])}\">{int(disk['other_files'])}</td>"
            "</tr>"
        )

        for file_record in catalog["files"]:
            media = file_record.get("media") or {}
            width = media.get("width")
            height = media.get("height")
            resolution = f"{width}×{height}" if width and height else ""
            audio_bitrates = ", ".join(
                format_bitrate(value) for value in media.get("audio_bitrates_bps", [])
            )
            subtitle_count = int(media.get("subtitle_count") or 0)
            subtitle_languages = media.get("subtitle_languages") or []
            subtitles = str(subtitle_count)
            if subtitle_languages:
                subtitles += f" ({', '.join(subtitle_languages)})"

            path_display = escaped(file_record["path"])
            probe_error = file_record.get("probe_error")
            if probe_error:
                path_display += (
                    f' <span class="probe-error" title="{escaped(probe_error)}">⚠</span>'
                )

            duration_seconds = media.get("duration_seconds")
            overall_bitrate = media.get("overall_bitrate_bps")
            file_rows.append(
                "<tr>"
                f"<td>{escaped(disk_id)}</td>"
                f"<td>{escaped(disk.get('label'))}</td>"
                f"<td class=\"file-path\">{path_display}</td>"
                f"<td>{escaped(file_record['category'])}</td>"
                f"<td data-order=\"{int(file_record['size_bytes'])}\">{escaped(file_record['size_human'])}</td>"
                f"<td data-order=\"{duration_seconds or 0}\">{escaped(media.get('duration_hms'))}</td>"
                f"<td>{escaped(media.get('container'))}</td>"
                f"<td data-order=\"{overall_bitrate or 0}\">{escaped(format_bitrate(overall_bitrate))}</td>"
                f"<td>{escaped(media.get('video_codec'))}</td>"
                f"<td data-order=\"{(width or 0) * (height or 0)}\">{escaped(resolution)}</td>"
                f"<td>{escaped(media.get('aspect_ratio'))}</td>"
                f"<td data-order=\"{media.get('frame_rate') or 0}\">{escaped(format_frame_rate(media.get('frame_rate')))}</td>"
                f"<td>{escaped(audio_bitrates)}</td>"
                f"<td data-order=\"{subtitle_count}\">{escaped(subtitles)}</td>"
                "</tr>"
            )

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Catalogo dischi dati</title>
<link rel="stylesheet" href="{DATATABLES_CSS_URL}">
<style>
:root {{ color-scheme: light; }}
body {{ color: #111; font-family: "DejaVu Sans Mono", monospace; font-size: 10pt; margin: 1rem; }}
a {{ color: inherit; }}
header {{ text-align: center; margin-bottom: 2rem; }}
header pre {{ display: inline-block; text-align: left; line-height: 1.05; }}
h1, h2 {{ text-align: center; }}
.catalogue-stats {{ text-align: center; font-weight: bold; margin: 1rem 0; }}
.filters {{ display: flex; flex-wrap: wrap; gap: 1rem; align-items: end; margin: 1.5rem 0 1rem; }}
.filters label {{ display: grid; gap: .3rem; font-weight: bold; }}
.filters select {{ min-width: 14rem; padding: .35rem; }}
table.dataTable tbody tr:hover {{ background: #fff062; }}
table.dataTable td {{ vertical-align: top; }}
.file-path {{ min-width: 24rem; overflow-wrap: anywhere; }}
.probe-error {{ color: #b00020; cursor: help; font-weight: bold; }}
.dataTables_wrapper {{ margin-bottom: 3rem; }}
</style>
<script src="{JQUERY_URL}"></script>
<script src="{DATATABLES_JS_URL}"></script>
<script>
$(function () {{
    $('#disks').DataTable({{
        paging: false,
        info: false,
        order: [[0, 'asc']]
    }});

    const filesTable = $('#files').DataTable({{
        pageLength: 100,
        lengthMenu: [[25, 50, 100, 250, -1], [25, 50, 100, 250, 'Tutti']],
        order: [[0, 'asc'], [2, 'asc']],
        stateSave: true,
        scrollX: true
    }});

    function applyExactFilter(column, value) {{
        const escaped = $.fn.dataTable.util.escapeRegex(value);
        filesTable.column(column).search(value ? '^' + escaped + '$' : '', true, false).draw();
    }}

    $('#disk-filter').on('change', function () {{ applyExactFilter(0, this.value); }});
    $('#category-filter').on('change', function () {{ applyExactFilter(3, this.value); }});
}});
</script>
</head>
<body>
<header>
<pre>
 ******  ********** ****     **      **     **
**////**/////**/// /**/**   /**     /**    ****
**    //     /**    /**//**  /**     /**   **//**
/**           /**    /** //** /**  ******  **  //**
/**           /**    /**  //**/** **///** **********
//**    **    /**    /**   //****/**  /**/**//////**
 //******     /**    /**    //***//******/**     /**
  //////      //     //      ///  ////// //      //
</pre>
<p><a href="index.html">Back to index</a></p>
</header>

<h1>Catalogo dischi dati</h1>
<p class="catalogue-stats">{len(catalogues)} dischi · {total_files} file</p>

<h2>Dischi</h2>
<table id="disks" class="display compact" style="width:100%">
<thead><tr><th>Identificativo</th><th>Etichetta</th><th>File</th><th>Video</th><th>Audio</th><th>Immagini</th><th>Altro</th></tr></thead>
<tbody>{''.join(summary_rows)}</tbody>
</table>

<h2>File</h2>
<div class="filters">
<label>Disco
<select id="disk-filter"><option value="">Tutti</option>{option_elements(disk_ids)}</select>
</label>
<label>Categoria
<select id="category-filter"><option value="">Tutte</option>{option_elements(categories)}</select>
</label>
</div>
<table id="files" class="display compact" style="width:100%">
<thead><tr>
<th>Disco</th><th>Etichetta</th><th>File</th><th>Categoria</th><th>Dimensione</th>
<th>Durata</th><th>Contenitore</th><th>Bitrate complessivo</th><th>Codec video</th>
<th>Risoluzione</th><th>Aspect ratio</th><th>Frame rate</th><th>Bitrate audio</th><th>Sottotitoli</th>
</tr></thead>
<tbody>{''.join(file_rows)}</tbody>
</table>
</body>
</html>
"""


def write_html_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        _ = temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def render_catalogue(catalog_dir: Path, output: Path) -> int:
    catalogues = load_catalogues(catalog_dir)
    write_html_atomic(output, render_html(catalogues))
    print(
        f"[+] Generato {output} con {len(catalogues)} dischi e "
        f"{sum(len(catalog['files']) for catalog in catalogues)} file."
    )
    return 0


def add_scan_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--path", type=Path, help="Directory montata da scansionare")
    source.add_argument(
        "--device",
        default=None,
        help=f"Device montato da scansionare (default: {DEFAULT_DEVICE})",
    )
    parser.add_argument(
        "--disk-id",
        help="Override dell'identificativo; il default è l'etichetta del filesystem",
    )
    parser.add_argument("--label", help="Etichetta descrittiva opzionale")
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=DEFAULT_CATALOG_DIR,
        help=f"Directory dei JSON (default: {DEFAULT_CATALOG_DIR})",
    )
    parser.add_argument("--ffprobe", default="ffprobe", help="Eseguibile ffprobe")


def scan_from_arguments(args: argparse.Namespace) -> Path:
    root, detected_device = resolve_scan_source(args.path, args.device)
    disk_id = resolve_disk_id(args.disk_id, detected_device)
    print(f"[*] Disco: {disk_id}")
    print(f"[*] Percorso: {root}")
    catalog = scan_disc(root, disk_id, args.label, args.ffprobe)
    output = save_catalog(args.catalog_dir, catalog)
    disk = catalog["disk"]
    print(
        f"[+] Salvato {output}: {disk['total_files']} file "
        f"({disk['video_files']} video, {disk['audio_files']} audio, "
        f"{disk['image_files']} immagini, {disk['other_files']} altri)."
    )
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scansiona dischi dati e genera un catalogo HTML con DataTables."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scansiona e salva un JSON")
    add_scan_arguments(scan_parser)

    render_parser = subparsers.add_parser(
        "render", help="Rigenera l'HTML dai JSON esistenti"
    )
    render_parser.add_argument(
        "--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR
    )
    render_parser.add_argument("--output", type=Path, default=DEFAULT_HTML_OUTPUT)

    build_parser_command = subparsers.add_parser(
        "build", help="Scansiona un disco e rigenera l'HTML"
    )
    add_scan_arguments(build_parser_command)
    build_parser_command.add_argument(
        "--output", type=Path, default=DEFAULT_HTML_OUTPUT
    )

    remove_parser = subparsers.add_parser(
        "remove", help="Rimuove un disco e rigenera l'HTML"
    )
    remove_parser.add_argument("disk_id", help="Identificativo esatto del disco")
    remove_parser.add_argument(
        "--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR
    )
    remove_parser.add_argument("--output", type=Path, default=DEFAULT_HTML_OUTPUT)
    remove_parser.add_argument("--yes", action="store_true", help="Non chiede conferma")

    return parser


def remove_catalogue(args: argparse.Namespace) -> int:
    path = args.catalog_dir / catalogue_filename(args.disk_id)
    if not path.exists():
        raise CatalogError(f"Nessun catalogo trovato per {args.disk_id!r}.")

    if not args.yes:
        answer = input(f"Rimuovere il catalogo {args.disk_id!r}? [y/N]: ").strip().lower()
        if answer != "y":
            print("[*] Operazione annullata.")
            return 0

    path.unlink()
    print(f"[+] Rimosso {path}.")
    return render_catalogue(args.catalog_dir, args.output)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "scan":
            scan_from_arguments(args)
            return 0
        if args.command == "render":
            return render_catalogue(args.catalog_dir, args.output)
        if args.command == "build":
            scan_from_arguments(args)
            return render_catalogue(args.catalog_dir, args.output)
        if args.command == "remove":
            return remove_catalogue(args)
    except (CatalogError, OSError) as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1

    parser.error(f"Comando non supportato: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
