# KI-Search — Component Search for KiCad

A KiCad PCB-editor plugin that searches a local SQLite components database
directly inside pcbnew — "what parts do I have at hand, at what price?"
Clicking a result row opens the supplier's product page (LCSC / DigiKey).

## Features

- Full-text search across LCSC part number, manufacturer part number,
  manufacturer, package, description, order quantity and prices.
- Press **Enter** in the search box to search.
- Info line under the results: total components in the DB, database location,
  and date/time of the last import.
- Import supplier CSV files straight from the dialog (LCSC and DigiKey;
  Mouser planned). Imported files are archived in `cvsdone/` next to the DB.
- Results in a list where clicking a row opens the supplier page stored for
  that row (LCSC product page, DigiKey search results; LCSC search fallback).
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
re-importing the same file — even renamed — is rejected.

## Database

The plugin uses a SQLite database at:

```
<USER_DOCS>/KiCAD/Gen/scripts/components.db
```

or inside the folder set in **Settings…** (`components.db` is created
automatically there). The schema is created/migrated automatically and
contains:

- `components` — one row per imported line, with an internal `import_id`
  linking to the source file and a `url` column with the direct supplier
  page (`tags` reserved for future flags). Searchable columns:
  `lcsc_part_number`, `manufacture_part_number`, `manufacturer`, `package`,
  `description`, `order_qty`, `unit_price`, `order_price`.
- `imports` — every imported file (name, content hash, time, row count).
- `meta` — key/value settings (`last_update`, `schema_version`).

This plugin is a search helper, not an inventory system — no stock
counting.

## Installation

Via the KiCad Plugin and Content Manager (PCM): search for **KI-Search**, or
use **Install from File…** with a release zip from
[GitHub Releases](https://github.com/jpkh/ki_search/releases).

## Usage

Open a board in the PCB editor and click the KI-Search toolbar button, enter a
search term and press **Enter** (or click **Search**). Double-click an LCSC
part number to open it on lcsc.com. **Settings…** controls the visible columns
and database path.

## License

GPL-3.0 — see [LICENSE](LICENSE).
