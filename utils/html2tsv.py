from bs4 import BeautifulSoup
import csv
import sys


def html_table_to_tsv(html_file, tsv_file):
    # Legge il file HTML
    with open(html_file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    # Trova intestazioni della tabella
    headers = []
    thead = soup.find("thead")
    if thead:
        headers = [th.get_text(strip=True) for th in thead.find_all("th")]

    # Trova il corpo della tabella
    tbody = soup.find("tbody")
    if not tbody:
        print("⚠️ Nessun <tbody> trovato nell'HTML")
        return

    rows = []
    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cells:  # evita righe vuote
            rows.append(cells)

    # Scrive in TSV
    with open(tsv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        if headers:
            writer.writerow(headers)
        writer.writerows(rows)

    print(f"✅ Tabella convertita in TSV: {tsv_file}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python html2tsv.py input.html output.tsv")
    else:
        html_table_to_tsv(sys.argv[1], sys.argv[2])
