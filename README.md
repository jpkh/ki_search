# KI-Search — Component Search for KiCad

A KiCad PCB-editor plugin that searches a local SQLite components database
directly inside pcbnew. Click an LCSC part number in the results to open its
page on lcsc.com.

## Features

- Full-text search across LCSC part number, manufacturer part number,
  manufacturer, package, description, order quantity and prices.
- Press **Enter** in the search box to search.
- Info line under the results: total components in the DB, database location,
  and date/time of the last import.
- Import supplier CSV files straight from the dialog (LCSC and DigiKey;
  Mouser planned). Imported files are archived in `cvsdone/` next to the DB.
- Results in a list with the supplier part number as a clickable link.
- Optional row tooltip showing which CSV file a component came from
  (toggled in Settings).
- Settings dialog: choose which columns are visible and set a custom
  database path.
- Database lives outside the plugin package (your documents folder).

## Importing data

In the dialog choose **Import CSV…**, pick the supplier format (LCSC is the
default) and the CSV file. Supported columns are the LCSC order export and
DigiKey order export formats. After a successful import the info line updates
with the new total and last-update time.

Imported files are archived in a `cvsdone/` folder inside the active database
folder (created automatically). Every imported row remembers which file it
came from through an internal import number (not shown in the UI);
re-importing the same file — even renamed — is rejected. Prices keep their
currency: `€` in the price fields is treated as EUR, anything else as USD.

## Database

The plugin expects a SQLite database at:

```
<USER_DOCS>/KiCAD/Gen/scripts/components.db
```

with a table `components` containing the columns:

`lcsc_part_number`, `manufacture_part_number`, `manufacturer`, `package`,
`description`, `order_qty`, `unit_price`, `order_price`

## Installation

Via the KiCad Plugin and Content Manager (PCM): search for **KI-Search**, or
use **Install from File…** with a release zip from
[GitHub Releases](https://github.com/jpkh/ki_search/releases).

## Usage

Open a board in the PCB editor and click the KI-Search toolbar button, enter a
search term and press **Enter** (or click **Search**). Double-click an LCSC
part number to open it on lcsc.com. **Settings…** controls the visible columns
and database path.

## Tools

`tools/processcvs-new.py` bulk-imports supplier CSV files into the database
from the command line (no KiCad needed). It imports oldest first, ordered by
the datecode in the file names, and archives processed files in `cvsdone/`:

```sh
python tools/processcvs-new.py -inDir C:\Temp\comp\cvs -outDir C:\Temp\comp
```

It can also repair missing prices from the CSV history
(`--dry-run` previews without changes):

```sh
python tools/processcvs-new.py -outDir C:\Temp\comp --rescan --dry-run
python tools/processcvs-new.py -outDir C:\Temp\comp --rescan
```

## License

GPL-3.0 — see [LICENSE](LICENSE).
