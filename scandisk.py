import os
import json
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

FILE_TYPES = {
    "audio": [".mp3", ".wav", ".flac", ".aac", ".ogg"],
    "video": [".mp4", ".mkv", ".avi", ".mov", ".wmv"],
    "image": [".jpg", ".jpeg", ".png", ".tiff", ".gif"],
}

CWD = Path.cwd()
MEDIAINFO_DIR = CWD / "mediainfo"
HTML_FILE = CWD / "videomix.html"


# ----------------------------
def get_mountpoint(device: str) -> Path | None:
    """Trova o monta un device (es. /dev/sr0)."""
    try:
        result = subprocess.run(
            ["findmnt", "-n", "-o", "TARGET", device],
            capture_output=True,
            text=True,
            check=True,
        )
        mountpoint = result.stdout.strip()
        if mountpoint:
            return Path(mountpoint)
    except subprocess.CalledProcessError:
        pass

    fallback = Path("/mnt/dvd")
    fallback.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["sudo", "mount", device, str(fallback)], check=True)
        print(f"[*] Mounted {device} at {fallback}")
        return fallback
    except subprocess.CalledProcessError as e:
        print(f"[!] Failed to mount {device}: {e}")
        return None


# ----------------------------
def get_category(extension: str) -> str:
    extension = extension.lower()
    for cat, exts in FILE_TYPES.items():
        if extension in exts:
            return cat
    return "other"


def run_ffprobe_parse(file: Path, disk_path: Path) -> str:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(file),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        data = json.loads(result.stdout)
    except Exception as e:
        return f"Error processing {file}: {e}"

    try:
        relpath = file.relative_to(disk_path.parent)
    except Exception:
        relpath = file.name

    lines = [f"=== VIDEO FILE ===", f"File: {relpath}"]

    fmt = data.get("format", {})
    duration = fmt.get("duration", "n/a")
    try:
        if duration and duration != "n/a":
            duration = float(duration)
            mins, secs = divmod(int(duration), 60)
            hours, mins = divmod(mins, 60)
            duration_str = f"{hours:02}:{mins:02}:{secs:02}"
        else:
            duration_str = "n/a"
    except Exception:
        duration_str = str(duration)

    fmt_br = fmt.get("bit_rate")
    if fmt_br:
        try:
            fmt_br = f"{int(fmt_br) // 1000} kbps"
        except Exception:
            pass

    lines.append(f"Duration: {duration_str}")
    lines.append(f"Container bitrate: {fmt_br or 'n/a'}")

    for stream in data.get("streams", []):
        codec = stream.get("codec_name", "n/a")
        if stream.get("codec_type") == "video":
            width = stream.get("width", "n/a")
            height = stream.get("height", "n/a")
            br = stream.get("bit_rate")
            try:
                br = f"{int(br) // 1000} kbps" if br else "n/a"
            except Exception:
                br = "n/a"
            lines.append(
                f"[Video] Codec: {codec}, Resolution: {width}x{height}, Bitrate: {br}"
            )
        elif stream.get("codec_type") == "audio":
            channels = stream.get("channels", "n/a")
            sr = stream.get("sample_rate", "n/a")
            br = stream.get("bit_rate")
            try:
                br = f"{int(br) // 1000} kbps" if br else "n/a"
            except Exception:
                br = "n/a"
            lang = stream.get("tags", {}).get("language", "n/a")
            lines.append(
                f"[Audio] Codec: {codec}, Channels: {channels}, SampleRate: {sr} Hz, "
                f"Bitrate: {br}, Language: {lang}"
            )

    return "\n".join(lines)


# ----------------------------
def analyse_disk(disk_number: str, disk_path: Path, root_name: str | None):
    MEDIAINFO_DIR.mkdir(parents=True, exist_ok=True)
    txt_output = MEDIAINFO_DIR / f"{disk_number}.txt"

    if txt_output.exists():
        ans = input(
            f"[?] mediainfo/{disk_number}.txt esiste già. Vuoi aggiornare? [y/N]: "
        ).lower()
        if ans != "y":
            print("[*] Operazione annullata.")
            return

    results = []

    with open(txt_output, "w", encoding="utf-8") as txtfile:
        # controlla se ci sono cartelle in root
        root_folders = [p for p in disk_path.iterdir() if p.is_dir()]

        if root_folders:
            # caso B: ci sono cartelle in root → processa solo quelle
            items_to_scan = root_folders
        else:
            # caso A: nessuna cartella → processa solo la root
            items_to_scan = [disk_path]

        for item in items_to_scan:
            counts = {"audio": 0, "video": 0, "image": 0, "other": 0}
            files = sorted(item.rglob("*")) if item.is_dir() else [item]
            for file in files:
                if file.is_file():
                    cat = get_category(file.suffix)
                    counts[cat] += 1
                    if cat == "video":
                        txtfile.write(run_ffprobe_parse(file, disk_path) + "\n\n")

            if item == disk_path:
                folder_name = root_name if root_name else "<ROOT>"
            else:
                folder_name = item.name

            results.append((folder_name, counts, txt_output.name))

    update_html(disk_number, results)


# ----------------------------
def update_html(disk_number, results):
    # se non esiste, creo tutto con righe iniziali
    if not HTML_FILE.exists():
        with open(HTML_FILE, "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Disk Index</title>
<style>
body { color: #000; font-family: "DejaVu Sans Mono", monospace; font-size: 10pt; }
tr:hover td { background: #fff062 !important; }
#example td, #example th { text-align: center; }
#example td:first-child, #example th:first-child { text-align: left; }
</style>
<script src="https://code.jquery.com/jquery-3.4.1.js"></script>
<link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.10.20/css/jquery.dataTables.css">
<script src="https://cdn.datatables.net/1.10.20/js/jquery.dataTables.js"></script>
<script>
$(document).ready(function () {
    var myTable = $("#example").DataTable({ paging: false });
});
</script>
</head>
<body class="wide comments example">
	<pre class="western" style="text-align: center">
		******  ********** ****     **      **     **
		**////**/////**/// /**/**   /**     /**    ****
		**    //     /**    /**//**  /**     /**   **//**
		/**           /**    /** //** /**  ******  **  //**
		/**           /**    /**  //**/** **///** **********
		//**    **    /**    /**   //****/**  /**/**//////**
		 //******     /**    /**    //***//******/**     /**
		  //////      //     //      ///  ////// //      //
		..::::::......::.....::......:::..::::::.::......::.
		::::::::::::::::::::::::::::::::::::::::::::::::::::
		::::::::::::::::::43 54 4E 64 41::::::::::::::::::::

		<a href="../index.html">Back to index</a>

		▗▖  ▗▖▄    ▐▌▗▞▀▚▖ ▄▄▄  ▗▖  ▗▖▄ ▄   ▄
▐▌  ▐▌▄    ▐▌▐▛▀▀▘█   █ ▐▛▚▞▜▌▄  ▀▄▀
▐▌  ▐▌█ ▗▞▀▜▌▝▚▄▄▖▀▄▄▄▀ ▐▌  ▐▌█ ▄▀ ▀▄
 ▝▚▞▘ █ ▝▚▄▟▌           ▐▌  ▐▌█



		<font color="#ff0000">Last update: 27 December 2022
		FOR NEW ARRIVALS: double click on the "NEW" column
		Asian movies have the label [ASIA] in the "info" column</font><div align="right"></pre>
<table id="example" class="display" style="width:100%">
<thead>
<tr>
<th>Disk #</th>
<th>Main Folder</th>
<th>Audio</th>
<th>Video</th>
<th>Images</th>
<th>Other</th>
<th>Media Info</th>
</tr>
</thead>
<tbody>
""")
            for folder, counts, txtfile in results:
                f.write(f"<tr data-disk='{disk_number}'>")
                f.write(f"<td>{disk_number}</td>")
                f.write(f"<td>{folder}</td>")
                f.write(f"<td>{counts['audio']}</td>")
                f.write(f"<td>{counts['video']}</td>")
                f.write(f"<td>{counts['image']}</td>")
                f.write(f"<td>{counts['other']}</td>")
                f.write(f"<td><a href='mediainfo/{txtfile}'>{txtfile}</a></td>")
                f.write("</tr>\n")
            f.write("</tbody></table></body></html>")
        return

    # se esiste già: rimuovo vecchie righe e reinserisco
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = [l for l in lines if f"data-disk='{disk_number}'" not in l]

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        for l in new_lines:
            if "</tbody>" in l:  # più tollerante
                for folder, counts, txtfile in results:
                    f.write(f"<tr data-disk='{disk_number}'>")
                    f.write(f"<td>{disk_number}</td>")
                    f.write(f"<td>{folder}</td>")
                    f.write(f"<td>{counts['audio']}</td>")
                    f.write(f"<td>{counts['video']}</td>")
                    f.write(f"<td>{counts['image']}</td>")
                    f.write(f"<td>{counts['other']}</td>")
                    f.write(
                        f"<td><a href='mediainfo/{txtfile}' target='_blank'>{txtfile}</a></td>"
                    )
                    f.write("</tr>\n")
            f.write(l)


# ----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan a disk and index contents.")
    parser.add_argument("disk_number", help="Progressive number of the disk")
    parser.add_argument(
        "--root-name",
        help="Custom name for the root folder if the disk has no subfolders",
    )
    parser.add_argument(
        "--device", default="/dev/sr0", help="Device to scan (default: /dev/sr0)"
    )
    args = parser.parse_args()

    disk_path = get_mountpoint(args.device)
    if not disk_path or not disk_path.exists():
        print("[!] Disk not mounted and auto-mount failed.")
        exit(1)

    print(f"[*] Using disk mounted at: {disk_path}")
    analyse_disk(args.disk_number, disk_path=disk_path, root_name=args.root_name)
