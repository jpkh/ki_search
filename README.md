# KI-Search — Component Search for KiCad

A KiCad PCB-editor plugin that searches a local SQLite components database
directly inside pcbnew. Click an LCSC part number in the results to open its
page on lcsc.com.

## Features

- Full-text search across LCSC part number, manufacturer part number,
  manufacturer, package, description, order quantity and prices.
- Results in a sortable list with the LCSC part number as a clickable link.
- Database lives outside the plugin package (your documents folder).

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
search term and press **Search**. Double-click an LCSC part number to open it
on lcsc.com.

## License

GPL-3.0 — see [LICENSE](LICENSE).
