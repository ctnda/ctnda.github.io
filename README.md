# ctnda.github.io

Archivio e indice HTML di supporti ottici, con utility per:

- catalogare il contenuto di CD/DVD e raccogliere i metadati dei video;
- mantenere un inventario cumulativo in formato TSV;
- pianificare la distribuzione di file su più dischi;
- convertire vecchie tabelle HTML o ASCII in TSV.

## Utility disponibili

| File | Scopo | Stato |
| --- | --- | --- |
| `utils/scandisk.py` | Analizza un disco, conta i tipi di file, estrae i metadati video e aggiorna `videomix.html` | Operativo |
| `utils/scan_disk_cumulative.py` | Aggiunge o aggiorna l'inventario di un disco in `data/ctnda.tsv` | Operativo |
| `utils/disc_packer.py` | Calcola come distribuire una directory su CD, DVD o Blu-ray | Operativo |
| `utils/html2tsv.py` | Converte la tabella di `dvdctnda_old.html` in TSV | Operativo, con nomi file fissi |
| `utils/ascii2tsv.py` | Converte una specifica tabella ASCII multilinea in TSV | Operativo solo con il formato atteso e nomi file fissi |
| `utils/mercoledi_cinema.py` | Prototipo di interrogazione IMDb | Incompleto: l'esecuzione termina con errore durante la serializzazione |
| `utils/videomix.html` | Esempio/output storico dell'indice generato da `scandisk.py` | Non è uno script |

## Prerequisiti

Gli esempi seguenti partono dalla root del repository.

- Python 3.10 o successivo. Il file `pyproject.toml` dichiara Python 3.8, ma `scandisk.py` usa la sintassi dei tipi introdotta in Python 3.10.
- [`uv`](https://docs.astral.sh/uv/) per installare ed eseguire l'ambiente Python bloccato da `utils/uv.lock`.
- Linux per le utility che accedono ai dischi ottici.
- `lsblk` per `scan_disk_cumulative.py`.
- `findmnt`, `mount` e `sudo` per il rilevamento o montaggio automatico usato da `scandisk.py`.
- `ffprobe` (fornito normalmente dal pacchetto FFmpeg) per estrarre i metadati audio/video.
- Accesso a Internet solo per il prototipo IMDb e, nel browser, per caricare jQuery/DataTables usati da `videomix.html`.

Installazione delle dipendenze Python:

```sh
uv sync --project utils
```

Le dipendenze Python esterne sono Beautiful Soup (`html2tsv.py`) e IMDbPY (`mercoledi_cinema.py`); gli altri script usano la libreria standard.

## Catalogare un disco con metadati video

`scandisk.py` riceve un identificativo progressivo, trova il mountpoint del device e analizza il disco. Se il device non è già montato prova a montarlo in `/mnt/dvd` tramite `sudo`.

```sh
uv run --project utils python utils/scandisk.py 015
```

Per usare un device diverso:

```sh
uv run --project utils python utils/scandisk.py 015 --device /dev/sr1
```

Se il disco non contiene directory nella root, si può assegnare un nome descrittivo alla root:

```sh
uv run --project utils python utils/scandisk.py 015 \
  --root-name "Nome raccolta"
```

Lo script:

1. individua il mountpoint con `findmnt` oppure tenta il montaggio in `/mnt/dvd`;
2. classifica i file come `audio`, `video`, `image` o `other` in base all'estensione;
3. esegue `ffprobe` su ogni video e salva durata, bitrate, codec, risoluzione e tracce audio;
4. scrive i dettagli in `mediainfo/<numero>.txt`;
5. inserisce o sostituisce le righe del disco in `videomix.html`.

Se `mediainfo/<numero>.txt` esiste già, viene richiesta conferma prima di sovrascriverlo. Rispondendo con un valore diverso da `y` non viene modificato nulla.

### Regole e limiti della scansione

- Se nella root del disco esiste almeno una directory, vengono analizzate soltanto le directory di primo livello e i file direttamente nella root vengono ignorati.
- Se non esistono directory, viene analizzata l'intera root e `--root-name` ne determina il nome mostrato nell'indice.
- Le estensioni riconosciute sono definite in `FILE_TYPES` dentro `utils/scandisk.py`; quelle non elencate sono conteggiate come `other`.
- Gli output dipendono dalla directory corrente. Eseguire il comando dalla root del repository, come negli esempi, per aggiornare `videomix.html` e `mediainfo/` corretti.
- La pagina HTML usa risorse CDN: i dati restano visibili offline, ma ricerca e ordinamento DataTables richiedono che le librerie siano già in cache o che sia disponibile una connessione.

## Aggiornare l'inventario TSV cumulativo

`scan_disk_cumulative.py` legge tutti i file di un disco già montato e registra per ciascuno:

- nome del supporto (`Media`);
- percorso relativo (`File`);
- dimensione leggibile (`Size`);
- data di ultima modifica (`Date`).

Dalla root del repository usare percorsi espliciti:

```sh
uv run --project utils python utils/scan_disk_cumulative.py \
  /dev/sr0 data/ctnda.tsv
```

Per forzare il nome del supporto invece di ricavarlo dal nome del mountpoint:

```sh
uv run --project utils python utils/scan_disk_cumulative.py \
  /dev/sr0 data/ctnda.tsv \
  --media-name "DVD-015"
```

Il disco deve essere già montato: lo script usa `lsblk` per trovarne il mountpoint e non tenta di montarlo. Se il TSV non esiste, lo crea; se contiene già lo stesso valore `Media`, chiede conferma e, con risposta `y`, sostituisce tutte le vecchie righe di quel supporto.

Il default dell'output è `../data/ctnda.tsv` ed è relativo alla directory corrente. Passare sempre `data/ctnda.tsv` quando si esegue dalla root evita di scrivere accidentalmente fuori dal repository.

## Pianificare la distribuzione su dischi

`disc_packer.py` scansiona ricorsivamente una directory, ordina i file dal più grande al più piccolo e applica **First-Fit Decreasing**: ogni file viene collocato nel primo disco che ha spazio sufficiente. È una buona euristica, ma non garantisce il numero minimo matematico di dischi.

Piano DVD5 con la riserva predefinita del 2%:

```sh
uv run --project utils python utils/disc_packer.py /percorso/dei/file \
  --profile dvd5
```

Profili disponibili:

- `cd700`: 700 MB;
- `dvd5`: 4.700.372.992 byte;
- `dvd9`: 8.540.000.000 byte;
- `bdr25`: 25 GB;
- `bdr50`: 50 GB.

Capacità personalizzata:

```sh
uv run --project utils python utils/disc_packer.py /percorso/dei/file \
  --capacity 7.95 --unit GiB --reserve 3
```

Filtrare per estensione ed escludere file temporanei:

```sh
uv run --project utils python utils/disc_packer.py /percorso/dei/file \
  --profile dvd5 \
  --include-ext mp4 mkv \
  --exclude '*.part' '*.tmp'
```

Esportare il piano:

```sh
uv run --project utils python utils/disc_packer.py /percorso/dei/file \
  --profile dvd5 \
  --export-json plan.json \
  --export-csv plan.csv
```

Creare directory di staging per ciascun disco:

```sh
uv run --project utils python utils/disc_packer.py /percorso/dei/file \
  --profile dvd5 \
  --materialise /tmp/disc_staging \
  --link-type symlink
```

`--link-type` accetta:

- `symlink`: collegamenti simbolici, senza duplicare i dati;
- `hardlink`: hard link, possibili solo sullo stesso filesystem;
- `copy`: copie complete dei file.

Opzioni utili aggiuntive:

- `--reserve PERCENTUALE`: spazio di sicurezza sottratto a ogni disco, default `2.0`;
- `--per-file-overhead BYTE`: costo aggiuntivo conteggiato per ciascun file;
- `--follow-symlinks`: segue i link simbolici alle directory;
- `--unit`: `B`, `KB`, `KiB`, `MB`, `MiB`, `GB` o `GiB` per `--capacity`.

I file che non entrano neppure in un disco vuoto vengono elencati come `Skipped`. File nascosti e directory nascoste sono sempre ignorati: nell'implementazione attuale l'opzione `--no-hidden` non cambia il comportamento. La materializzazione appiattisce i percorsi usando soltanto il nome del file; file omonimi assegnati allo stesso disco possono quindi sovrascriversi nello staging.

## Convertire la vecchia tabella HTML in TSV

`html2tsv.py` usa Beautiful Soup per:

1. leggere le intestazioni da `table thead th`;
2. leggere le celle da `table tbody tr`;
3. rimuovere i tag interni e normalizzare spazi e newline;
4. scrivere colonne separate da tabulazioni.

I nomi sono fissi: lo script legge `dvdctnda_old.html` e genera `output_clean.tsv` nella directory corrente. Dalla root del repository:

```sh
uv run --project utils python utils/html2tsv.py
```

Il file `output_clean.tsv` viene sovrascritto senza richiesta di conferma. Lo script elabora tutte le tabelle corrispondenti ai selettori indicati e non offre opzioni da riga di comando.

## Convertire una tabella ASCII in TSV

`ascii2tsv.py` è un convertitore specializzato, non un parser generico di tabelle testuali. Cerca nella directory corrente `ascii_table.txt` e genera `ascii_table.tsv`.

```sh
uv run --project utils python utils/ascii2tsv.py
```

Il formato atteso:

- contiene una riga di intestazione che inizia con `|Media`;
- usa `|` come separatore di colonna;
- usa righe che iniziano con `+` o `|-` come bordi/separatori;
- rappresenta ogni record su due righe: la prima contiene media, file, valore della dimensione e data; la seconda ha `Media` vuoto e completa unità della dimensione e orario.

Durante la conversione lo slash iniziale del percorso viene rimosso. Il risultato ha le colonne `Media`, `File`, `Size` e `Date`. Record non completi su due righe non vengono scritti e un input senza l'intestazione attesa causa un errore. L'output esistente viene sovrascritto.

## Prototipo IMDb

`mercoledi_cinema.py` contiene codice sperimentale che:

1. interroga IMDb tramite IMDbPY usando l'identificativo hardcoded `0060315`;
2. prova a copiare regista e generi in un oggetto locale;
3. dovrebbe produrre un JSON con informazioni sul film.

Non è attualmente utilizzabile come utility: non accetta argomenti, dipende dalla rete e la chiamata a `json.dump` è priva del file di destinazione, oltre a tentare di serializzare direttamente un oggetto custom. Anche la funzione di scrittura contiene riferimenti incompleti. Va considerato un prototipo da correggere prima dell'uso.
