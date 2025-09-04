import re
import csv

input_file = "ascii_table.txt"
output_file = "ascii_table.tsv"

records = []
header_written = False
current = None

with open(input_file, encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        # ignora separatori e righe vuote
        if not line.strip() or line.startswith("+") or re.match(r"^\|\-+", line):
            continue

        # riga di intestazione
        if line.startswith("|Media"):
            header = ["Media", "File", "Size", "Date"]
            continue

        # spezza le celle
        cells = [c.strip() for c in line.strip("|").split("|")]

        # se la colonna Media è vuota → è la seconda parte del record
        if cells[0] == "":
            if current:
                size_unit = cells[2]
                time_part = cells[3]
                if size_unit:
                    current["Size"] = (current["Size"] + " " + size_unit).strip()
                current["Date"] = f"{current['Date']} {time_part}"
                records.append(current)
                current = None
        else:
            # prima parte del record
            current = {
                "Media": cells[0],
                "File": cells[1].lstrip("/"),
                "Size": cells[2],
                "Date": cells[3],
            }

# scrittura TSV
with open(output_file, "w", encoding="utf-8", newline="") as out:
    writer = csv.DictWriter(
        out, fieldnames=header, delimiter="\t", quoting=csv.QUOTE_NONE, escapechar="\\"
    )
    writer.writeheader()
    for rec in records:
        writer.writerow(rec)

print(f"✅ Conversione completata: {len(records)} righe scritte in {output_file}")
