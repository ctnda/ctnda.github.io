from bs4 import BeautifulSoup
import re


def html_to_tsv(html_file, tsv_file):
    with open(html_file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    # intestazione
    headers = [th.get_text(strip=True) for th in soup.select("table thead th")]

    rows = []
    for tr in soup.select("table tbody tr"):
        cells = []
        for td in tr.find_all("td"):
            # prendi solo testo (ignora eventuali tag dentro td)
            text = td.get_text(separator=" ", strip=True)
            # normalizza spazi multipli e newline
            text = re.sub(r"\s+", " ", text)
            cells.append(text)
        if cells:
            rows.append(cells)

    with open(tsv_file, "w", encoding="utf-8") as out:
        # scrivi header
        out.write("\t".join(headers) + "\n")
        # scrivi righe
        for row in rows:
            out.write("\t".join(row) + "\n")


if __name__ == "__main__":
    html_to_tsv("dvdctnda_old.html", "output_clean.tsv")
