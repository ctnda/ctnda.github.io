import os
import csv
import argparse
from datetime import datetime
import subprocess

DEFAULT_DEVICE = "/dev/sr0"
DEFAULT_OUTPUT = "../data/ctnda.tsv"


def get_mountpoint(device):
    """Ritorna il mountpoint associato a un device block (/dev/sr0)."""
    try:
        result = subprocess.run(
            ["lsblk", "-no", "MOUNTPOINT", device],
            capture_output=True,
            text=True,
            check=True,
        )
        mountpoint = result.stdout.strip()
        if not mountpoint:
            raise RuntimeError(f"{device} non è montato")
        return mountpoint
    except subprocess.CalledProcessError:
        raise RuntimeError(f"Impossibile determinare il mountpoint di {device}")


def human_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KiB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.2f} MiB"
    else:
        return f"{size_bytes / 1024**3:.2f} GiB"


def scan_disk(root_path, media_name):
    records = []
    for dirpath, _, filenames in os.walk(root_path):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                st = os.stat(fpath)
            except FileNotFoundError:
                continue

            size_str = human_size(st.st_size)
            dt = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            rel_path = os.path.relpath(fpath, root_path)

            records.append([media_name, rel_path, size_str, dt])
    return records


def update_cumulative_tsv(device, cumulative_tsv, media_name=None):
    header = ["Media", "File", "Size", "Date"]

    # trova il mountpoint
    mountpoint = get_mountpoint(device)

    if not media_name:
        media_name = os.path.basename(os.path.normpath(mountpoint))

    new_records = scan_disk(mountpoint, media_name)

    # se non esiste il TSV cumulativo → crealo
    if not os.path.exists(cumulative_tsv):
        with open(cumulative_tsv, "w", encoding="utf-8", newline="") as out:
            writer = csv.writer(
                out, delimiter="\t", quoting=csv.QUOTE_NONE, escapechar="\\"
            )
            writer.writerow(header)
            writer.writerows(new_records)
        print(
            f"✅ Creato nuovo file cumulativo {cumulative_tsv} con {len(new_records)} file dal disco {media_name}"
        )
        return

    # leggi TSV esistente
    with open(cumulative_tsv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        existing_records = list(reader)

    existing_media = {row["Media"] for row in existing_records}

    if media_name in existing_media:
        choice = input(
            f"⚠️ Il disco {media_name} è già presente in {cumulative_tsv}. Vuoi aggiornare? (y/n) "
        )
        if choice.lower() != "y":
            print("⏭️ Operazione annullata, nessuna modifica fatta.")
            return
        # rimuovi record vecchi dello stesso disco
        existing_records = [
            row for row in existing_records if row["Media"] != media_name
        ]

    # aggiungi i nuovi record
    with open(cumulative_tsv, "w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(
            out,
            fieldnames=header,
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
            escapechar="\\",
        )
        writer.writeheader()
        writer.writerows(existing_records)
        for rec in new_records:
            writer.writerow(dict(zip(header, rec)))

    print(
        f"✅ Aggiornato {cumulative_tsv}: {len(new_records)} file dal disco {media_name}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scan optical disk (/dev/sr0) and update cumulative TSV"
    )
    parser.add_argument(
        "device",
        nargs="?",
        default=DEFAULT_DEVICE,
        help=f"Device del disco ottico (default: {DEFAULT_DEVICE})",
    )
    parser.add_argument(
        "cumulative_tsv",
        nargs="?",
        default=DEFAULT_OUTPUT,
        help=f"File TSV cumulativo (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--media-name",
        help="Nome da usare come Media (sovrascrive quello del mountpoint)",
    )
    args = parser.parse_args()

    update_cumulative_tsv(args.device, args.cumulative_tsv, args.media_name)
