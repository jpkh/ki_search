##########################################################
#
# Script: importer.py
# Author: Jani Hirvinen (jpkh)
# Contact: jphelirc@gmail.com
# Repository: https://github.com/jpkh/ki_search
#
# Copyright (c) 2026 Jani Hirvinen
# License: GPL-3.0 - see the LICENSE file
#
# Description: CSV import, database schema, stats and import dialog.
#
##########################################################

import csv
import hashlib
import os
import sqlite3
from datetime import datetime

import wx

from .config import SCHEMA_VERSION


def ensure_schema(db_path):
    """Create the components and meta tables if missing."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS components (
        lcsc_part_number TEXT,
        manufacture_part_number TEXT,
        manufacturer TEXT,
        customer_no TEXT,
        package TEXT,
        description TEXT,
        rohs TEXT,
        order_qty INTEGER,
        min_mult_order_qty TEXT,
        unit_price REAL,
        order_price REAL,
        supplier TEXT DEFAULT 'LC',
        import_id INTEGER,
        schema_version INTEGER DEFAULT 1
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS imports (
        file_name TEXT PRIMARY KEY,
        content_hash TEXT,
        supplier TEXT,
        imported_at TEXT,
        rows_added INTEGER,
        currency TEXT
    )
    ''')

    # Migrations for older databases
    cur.execute("PRAGMA table_info(components)")
    columns = [row[1] for row in cur.fetchall()]
    if 'import_id' not in columns:
        cur.execute("ALTER TABLE components ADD COLUMN import_id INTEGER")
    if 'schema_version' not in columns:
        cur.execute("ALTER TABLE components ADD COLUMN schema_version INTEGER")
        # Stamp pre-versioning rows so they are distinguishable from new imports
        cur.execute("UPDATE components SET schema_version = 0 WHERE schema_version IS NULL")

    cur.execute("PRAGMA table_info(imports)")
    import_columns = [row[1] for row in cur.fetchall()]
    if 'currency' not in import_columns:
        cur.execute("ALTER TABLE imports ADD COLUMN currency TEXT")

    cur.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),))

    conn.commit()
    conn.close()


def get_db_stats(db_path):
    """Return {'exists', 'total', 'last_update'} for the info line."""
    if not os.path.isfile(db_path):
        return {'exists': False, 'total': 0, 'last_update': None}

    try:
        conn = sqlite3.connect(db_path)
    except Exception:
        return {'exists': False, 'total': 0, 'last_update': None}
    cur = conn.cursor()
    total = 0
    last_update = None
    try:
        cur.execute('SELECT COUNT(*) FROM components')
        total = cur.fetchone()[0]
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("SELECT value FROM meta WHERE key = 'last_update'")
        row = cur.fetchone()
        if row:
            last_update = row[0]
    except sqlite3.OperationalError:
        pass
    conn.close()
    return {'exists': True, 'total': total, 'last_update': last_update}


def _file_hash(path):
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def _is_duplicate(csv_path, cvsdone_folder):
    """True if an identical file was already imported (content hash)."""
    if not os.path.isdir(cvsdone_folder):
        return False
    new_hash = _file_hash(csv_path)
    for name in os.listdir(cvsdone_folder):
        try:
            if new_hash == _file_hash(os.path.join(cvsdone_folder, name)):
                return True
        except Exception:
            continue
    return False


def _parse_float(val, default=0.0):
    try:
        if val is None:
            return default
        s = str(val).strip().replace('€', '').replace('$', '').replace(',', '.')
        if s == '' or s == '-':
            return default
        return float(s)
    except Exception:
        return default


def _parse_qty(val):
    try:
        s = str(val).strip()
        return int(s) if s.isdigit() else None
    except Exception:
        return None


UNIT_PRICE_KEYS = ('Unit Price($)', 'Unit Price(€)', 'Unit Price')
ORDER_PRICE_KEYS = ('Order Price($)', 'Order Price(€)',
                    'Ext.Price($)', 'Ext.Price(€)', 'Extended Price')


def _get_unit(row):
    for key in UNIT_PRICE_KEYS:
        if row.get(key):
            return _parse_float(row[key])
    return 0.0


def _get_order(row):
    for key in ORDER_PRICE_KEYS:
        if row.get(key):
            return _parse_float(row[key])
    return 0.0


def _header_has_euro(csv_path):
    with open(csv_path, 'r', encoding='utf-8-sig', errors='replace') as f:
        header = f.readline()
    return '€' in header


def import_csv(db_path, csv_path, supplier):
    """Import a supplier CSV into the database.

    Returns a dict: file_name, rows_read, added, skipped, skipped_subtotal,
    skipped_no_qty, no_price, currency. Moves the processed file into
    cvsdone/ next to the database. Raises on error (message shown by the
    caller).
    """
    if supplier not in ('LCSC', 'DK'):
        raise ValueError("{} import is not implemented yet.".format(supplier))

    ensure_schema(db_path)
    db_dir = os.path.dirname(os.path.abspath(db_path))
    cvsdone = os.path.join(db_dir, 'cvsdone')

    file_name = os.path.basename(csv_path)
    content_hash = _file_hash(csv_path)

    # Legacy fallback: identical file already archived in cvsdone/
    if _is_duplicate(csv_path, cvsdone):
        raise RuntimeError(
            "This CSV was already imported (identical file found in cvsdone/).")

    added = 0
    skipped = 0
    skipped_subtotal = 0
    skipped_no_qty = 0
    skipped_no_pn = 0
    no_price = 0
    rows_read = 0
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        # Duplicate check against the import log: content hash or file name
        cur.execute(
            "SELECT file_name, imported_at FROM imports WHERE content_hash = ? OR file_name = ?",
            (content_hash, file_name))
        existing = cur.fetchone()
        if existing:
            raise RuntimeError(
                "This CSV was already imported as '{}' on {}.".format(
                    existing[0], existing[1]))

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        currency = 'EUR' if _header_has_euro(csv_path) else 'USD'

        # Register the import first to get its unique import number
        cur.execute(
            "INSERT INTO imports (file_name, content_hash, supplier, imported_at, rows_added, currency) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (file_name, content_hash, supplier, now, currency))
        import_id = cur.lastrowid

        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows_read += 1
                # EUR detection: a € sign in a price field -> EUR, else USD
                if currency == 'USD':
                    for key in UNIT_PRICE_KEYS + ORDER_PRICE_KEYS:
                        v = row.get(key)
                        if v is not None and '€' in str(v):
                            currency = 'EUR'
                            break
                if any('subtotal' in (str(v or '').lower()) for v in row.values()):
                    skipped += 1
                    skipped_subtotal += 1
                    continue

                qty = _parse_qty(row.get('Quantity') or row.get('Order Qty.')
                                 or row.get('Qty') or row.get('Qty.'))
                if qty is None or qty == 0:
                    skipped += 1
                    skipped_no_qty += 1
                    continue

                if supplier == 'LCSC':
                    if not (row.get('LCSC Part Number') or '').strip():
                        skipped += 1
                        skipped_no_pn += 1
                        continue
                    min_mult_raw = (
                        row.get('Min/Mult Order Qty.') or
                        row.get('Min\\Mult Order Qty.') or
                        row.get('Min Mult Order Qty.') or
                        row.get('Min/Mult Qty') or
                        row.get('Min Mult Qty') or '')
                    data = {
                        'lcsc_part_number': (row.get('LCSC Part Number') or '').strip(),
                        'manufacture_part_number': (row.get('Manufacture Part Number') or '').strip(),
                        'manufacturer': (row.get('Manufacturer') or '').strip(),
                        'customer_no': (row.get('Customer NO.') or '').strip(),
                        'package': (row.get('Package') or '').strip(),
                        'description': (row.get('Description') or '').strip(),
                        'rohs': (row.get('RoHS') or '').strip(),
                        'order_qty': qty,
                        'min_mult_order_qty': min_mult_raw.strip(),
                        'unit_price': _get_unit(row),
                        'order_price': _get_order(row),
                        'supplier': 'LCSC',
                    }
                else:  # DK (DigiKey)
                    if not (row.get('DigiKey Part #') or '').strip():
                        skipped += 1
                        skipped_no_pn += 1
                        continue
                    data = {
                        'lcsc_part_number': (row.get('DigiKey Part #') or '').strip(),
                        'manufacture_part_number': (row.get('Manufacturer Part Number') or '').strip(),
                        'manufacturer': (row.get('Manufacturer') or '').strip(),
                        'customer_no': '',
                        'package': '',
                        'description': (row.get('Description') or '').strip(),
                        'rohs': '',
                        'order_qty': qty,
                        'min_mult_order_qty': '',
                        'unit_price': _get_unit(row),
                        'order_price': _get_order(row),
                        'supplier': 'DK',
                    }

                data['import_id'] = import_id
                data['schema_version'] = SCHEMA_VERSION
                if data['unit_price'] == 0:
                    no_price += 1
                cur.execute('''
                    INSERT INTO components (
                        lcsc_part_number, manufacture_part_number, manufacturer,
                        customer_no, package, description, rohs,
                        order_qty, min_mult_order_qty, unit_price, order_price, supplier, import_id, schema_version
                    ) VALUES (
                        :lcsc_part_number, :manufacture_part_number, :manufacturer,
                        :customer_no, :package, :description, :rohs,
                        :order_qty, :min_mult_order_qty, :unit_price, :order_price, :supplier, :import_id, :schema_version
                    )
                ''', data)
                added += 1

        cur.execute(
            "UPDATE imports SET rows_added = ?, imported_at = ?, currency = ? WHERE rowid = ?",
            (added, now, currency, import_id))
        cur.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_update', ?)",
            (now,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Move the processed file into cvsdone/ (unique name)
    os.makedirs(cvsdone, exist_ok=True)
    target = os.path.join(cvsdone, os.path.basename(csv_path))
    base, ext = os.path.splitext(target)
    n = 1
    while os.path.exists(target):
        target = "{}_{}{}".format(base, n, ext)
        n += 1
    os.rename(csv_path, target)

    return {
        'file_name': file_name,
        'rows_read': rows_read,
        'added': added,
        'skipped': skipped,
        'skipped_subtotal': skipped_subtotal,
        'skipped_no_qty': skipped_no_qty,
        'skipped_no_pn': skipped_no_pn,
        'no_price': no_price,
        'currency': currency,
    }


MAX_IMPORT_FILES = 5

SUPPLIER_LABELS = {'LCSC': 'LCSC', 'DK': 'DigiKey', 'M': 'Mouser'}


def detect_supplier(csv_path):
    """Guess the supplier from the CSV header, falling back to the file name.

    Returns 'LCSC', 'DK', 'M' or None when unknown.
    """
    try:
        with open(csv_path, 'r', encoding='utf-8-sig', errors='replace') as f:
            header = f.readline().lower()
    except Exception:
        header = ''
    if 'digikey part' in header:
        return 'DK'
    if 'mouser part' in header:
        return 'M'
    if 'lcsc part number' in header:
        return 'LCSC'

    name = os.path.basename(csv_path).lower()
    if name.startswith('lcsc'):
        return 'LCSC'
    if name.startswith('dk_') or name.startswith('digikey'):
        return 'DK'
    if 'mouser' in name:
        return 'M'
    return None


class ImportResultsDialog(wx.Dialog):
    """Scrollable summary of a multi-file import run."""

    def __init__(self, parent, lines):
        super().__init__(parent, title="Import Results", size=(560, 420))
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.text = wx.TextCtrl(self,
                                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.text.SetValue("\n".join(lines))
        vbox.Add(self.text, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        close_btn = wx.Button(self, label="Close")
        vbox.Add(close_btn, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)
        self.SetSizer(vbox)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))
        self.Bind(wx.EVT_CLOSE, lambda e: self.EndModal(wx.ID_CANCEL))
        self.Centre(wx.BOTH)


class ImportDialog(wx.Dialog):
    SUPPLIERS = [('LCSC', 'LCSC'), ('DigiKey', 'DK'), ('Mouser', 'M')]

    def __init__(self, parent, db_path):
        super().__init__(parent, title="Import Components CSV", size=(520, 400))
        self.db_path = db_path
        self.files = []

        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(self, label="Supplier format fallback (auto-detected per file when possible):"),
                 flag=wx.ALL, border=10)
        self.supplier_radio = wx.RadioBox(
            self, choices=[s[0] for s in self.SUPPLIERS],
            majorDimension=1, style=wx.RA_SPECIFY_ROWS)
        self.supplier_radio.SetSelection(0)  # LCSC is the default
        vbox.Add(self.supplier_radio, flag=wx.LEFT | wx.RIGHT, border=10)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(wx.StaticText(self, label="CSV files (max {}):".format(MAX_IMPORT_FILES)),
                 flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        self.browse_btn = wx.Button(self, label="Browse…")
        hbox.Add(self.browse_btn,
                 flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        self.count_label = wx.StaticText(self, label="0 selected")
        hbox.Add(self.count_label, flag=wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(hbox, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        self.file_list = wx.ListBox(self, size=(-1, 100))
        vbox.Add(self.file_list, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        self.status = wx.StaticText(self, label="Target DB: {}".format(db_path))
        vbox.Add(self.status, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(btns, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        self.SetSizer(vbox)
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre(wx.BOTH)

        self.browse_btn.Bind(wx.EVT_BUTTON, self.on_browse)
        # Run the import on OK, however the button is reached
        ok_btn = self.FindWindowById(wx.ID_OK)
        if ok_btn:
            ok_btn.Bind(wx.EVT_BUTTON, self.on_import)
        self.Bind(wx.EVT_BUTTON, self.on_import, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL),
                  id=wx.ID_CANCEL)

    def _refresh_file_list(self):
        self.file_list.Set([os.path.basename(p) for p in self.files])
        self.count_label.SetLabel("{} selected".format(len(self.files)))

    def on_browse(self, event):
        dlg = wx.FileDialog(
            self,
            message="Choose CSV files (max {})".format(MAX_IMPORT_FILES),
            defaultDir="",
            defaultFile="",
            wildcard="CSV files (*.csv)|*.csv",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        if dlg.ShowModal() == wx.ID_OK:
            paths = list(dlg.GetPaths())
            if len(paths) > MAX_IMPORT_FILES:
                wx.MessageBox(
                    "Maximum {} files per import; only the first {} are kept.".format(
                        MAX_IMPORT_FILES, MAX_IMPORT_FILES),
                    "Warning", wx.OK | wx.ICON_WARNING)
                paths = paths[:MAX_IMPORT_FILES]
            self.files = paths
            self._refresh_file_list()
        dlg.Destroy()

    def on_import(self, event):
        if not self.files:
            wx.MessageBox("Please choose CSV files.", "Warning", wx.OK | wx.ICON_WARNING)
            return

        selected = self.SUPPLIERS[self.supplier_radio.GetSelection()][1]
        results = []
        for path in self.files:
            entry = {
                'name': os.path.basename(path),
                'selected': selected,
                'detected': detect_supplier(path),
                'res': None,
                'err': None,
            }
            entry['used'] = entry['detected'] or selected
            try:
                entry['res'] = import_csv(self.db_path, path, entry['used'])
            except Exception as e:
                entry['err'] = str(e)
            results.append(entry)

        lines = []
        total_added = 0
        total_skipped = 0
        errors = 0
        ok_count = 0
        for e in results:
            if e['err']:
                errors += 1
                lines.append("{}: ERROR — {}".format(e['name'], e['err']))
            else:
                ok_count += 1
                res = e['res']
                total_added += res['added']
                total_skipped += res['skipped']
                used_label = SUPPLIER_LABELS.get(e['used'], e['used'])
                if e['detected'] is None:
                    note = " — supplier not detected, imported as {}".format(used_label)
                elif e['detected'] != e['selected']:
                    note = " — auto-detected {}, selected was {}".format(
                        used_label, SUPPLIER_LABELS.get(e['selected'], e['selected']))
                else:
                    note = " — {}".format(used_label)
                lines.append("{}: OK{}".format(e['name'], note))
                lines.append("    Lines processed: {}, added: {}, skipped: {}, currency: {}".format(
                    res['rows_read'], res['added'], res['skipped'], res['currency']))
                if res['no_price']:
                    lines.append("    Warning: {} row(s) without price".format(res['no_price']))
                if res['skipped_subtotal']:
                    lines.append("    Warning: {} subtotal row(s) skipped".format(res['skipped_subtotal']))
                if res['skipped_no_qty']:
                    lines.append("    Warning: {} row(s) without quantity skipped".format(res['skipped_no_qty']))
                if res['skipped_no_pn']:
                    lines.append("    Warning: {} row(s) without supplier part number skipped".format(
                        res['skipped_no_pn']))
            lines.append("")

        lines.append("Total: {} file(s) OK, {} error(s); rows added: {}, rows skipped: {}".format(
            ok_count, errors, total_added, total_skipped))
        dlg = ImportResultsDialog(self, lines)
        dlg.ShowModal()
        dlg.Destroy()

        if ok_count:
            self.EndModal(wx.ID_OK)
        else:
            self.EndModal(wx.ID_CANCEL)
