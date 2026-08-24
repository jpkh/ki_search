#!/usr/bin/env python3
"""Batch import of supplier CSVs into the KI-Search components database.

Processes every .csv in the input folder, oldest first (ordered by the
datecode in the file name; files without a datecode fall back to file time).
Supports LCSC and DigiKey exports. After a successful import the file is
moved to <outDir>/cvsdone/ (created when missing).

Uses the same schema as the KI-Search plugin:
  components(..., import_id, schema_version)
  imports(file_name, content_hash, supplier, imported_at, rows_added, currency)
  meta(schema_version, last_update)

Usage:
    python processcvs-new.py -inDir C:\\Temp\\comp\\cvs -outDir C:\\Temp\\comp
"""

import argparse
import csv
import hashlib
import os
import re
import sqlite3
from datetime import datetime

SCHEMA_VERSION = 1
DB_FILENAME = 'components.db'


# ---------------------------------------------------------------- schema

def ensure_schema(db_path):
    """Create tables if missing and migrate older databases."""
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


# ------------------------------------------------------------- helpers

def file_hash(path):
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def folder_has_duplicate(csv_path, cvsdone):
    """True if an identical file is already archived in cvsdone/."""
    if not os.path.isdir(cvsdone):
        return False
    new_hash = file_hash(csv_path)
    for name in os.listdir(cvsdone):
        try:
            if new_hash == file_hash(os.path.join(cvsdone, name)):
                return True
        except Exception:
            continue
    return False


def detect_supplier(csv_path):
    """LCSC / DK detection from the CSV header line."""
    with open(csv_path, 'r', encoding='utf-8-sig', errors='replace') as f:
        header = f.readline().strip().lower()
    if 'digikey' in header:
        return 'DK'
    if 'lcsc' in header:
        return 'LCSC'
    return None


def datecode(name):
    """Extract YYYYMMDDHHMMSS (or YYYYMMDD) from a file name, if present.

    Digit runs that are not real dates (e.g. order numbers like 84721215 in
    DK_PRODUCTS_84721215.csv) are ignored.
    """
    m = re.search(r'(\d{14})', name)
    if m and _is_datetime(m.group(1)):
        return m.group(1)
    m = re.search(r'(\d{8})', name)
    if m and _is_date(m.group(1)):
        return m.group(1)
    return None


def _is_datetime(s):
    try:
        datetime.strptime(s, '%Y%m%d%H%M%S')
        return True
    except ValueError:
        return False


def _is_date(s):
    try:
        datetime.strptime(s, '%Y%m%d')
        return True
    except ValueError:
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


# ---------------------------------------------------------------- import

def import_csv(db_path, csv_path, supplier):
    """Import one CSV; returns (added, skipped, currency). Raises on error."""
    if supplier not in ('LCSC', 'DK'):
        raise ValueError('{} import is not implemented yet.'.format(supplier))

    ensure_schema(db_path)
    db_dir = os.path.dirname(os.path.abspath(db_path))
    cvsdone = os.path.join(db_dir, 'cvsdone')
    os.makedirs(cvsdone, exist_ok=True)

    file_name = os.path.basename(csv_path)
    content_hash = file_hash(csv_path)

    if folder_has_duplicate(csv_path, cvsdone):
        raise RuntimeError('already imported (identical file found in cvsdone/)')

    added = 0
    skipped = 0
    no_price = 0
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT file_name, imported_at FROM imports WHERE content_hash = ? OR file_name = ?",
            (content_hash, file_name))
        existing = cur.fetchone()
        if existing:
            raise RuntimeError(
                "already imported as '{}' on {}".format(existing[0], existing[1]))

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        currency = 'EUR' if _header_has_euro(csv_path) else 'USD'

        # Register the import first to get its unique import number
        cur.execute(
            "INSERT INTO imports (file_name, content_hash, supplier, imported_at, rows_added, currency) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (file_name, content_hash, supplier, now, currency))
        import_id = cur.lastrowid

        with open(csv_path, newline='', encoding='utf-8-sig', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if any('subtotal' in (str(v or '').lower()) for v in row.values()):
                    skipped += 1
                    continue

                qty = _parse_qty(row.get('Quantity') or row.get('Order Qty.'))
                if qty is None or qty == 0:
                    skipped += 1
                    continue

                # EUR detection: a € sign in a price field -> EUR, else USD
                if currency == 'USD':
                    for key in UNIT_PRICE_KEYS + ORDER_PRICE_KEYS:
                        v = row.get(key)
                        if v is not None and '€' in str(v):
                            currency = 'EUR'
                            break

                if supplier == 'LCSC':
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
    target = os.path.join(cvsdone, file_name)
    base, ext = os.path.splitext(target)
    n = 1
    while os.path.exists(target):
        target = '{}_{}{}'.format(base, n, ext)
        n += 1
    os.rename(csv_path, target)

    return added, skipped, currency, no_price


# ------------------------------------------------------------- rescan

def _build_history_index(cvsdone):
    """Scan cvsdone CSVs; index by full key (incl. qty), part-only key and
    part-code-only key.

    Returns (index, partial, by_code) where each maps key -> list of
    {'unit','order','qty','file','mtime'}, newest first.
    """
    index = {}
    partial = {}
    by_code = {}
    file_has_euro = {}
    if not os.path.isdir(cvsdone):
        return index, partial, by_code, file_has_euro
    for name in os.listdir(cvsdone):
        if not name.lower().endswith('.csv'):
            continue
        fpath = os.path.join(cvsdone, name)
        try:
            mtime = os.path.getmtime(fpath)
        except Exception:
            mtime = 0
        if _header_has_euro(fpath):
            file_has_euro[name] = True
        try:
            with open(fpath, newline='', encoding='utf-8-sig', errors='replace') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    lcsc = (row.get('LCSC Part Number') or row.get('DigiKey Part #') or '').strip()
                    mfg = (row.get('Manufacture Part Number') or '').strip()
                    package = (row.get('Package') or '').strip()
                    desc = (row.get('Description') or '').strip()
                    qty = _parse_qty(row.get('Quantity') or row.get('Order Qty.'))
                    unit = _get_unit(row)
                    order = _get_order(row)
                    if not file_has_euro.get(name):
                        for key in UNIT_PRICE_KEYS + ORDER_PRICE_KEYS:
                            v = row.get(key)
                            if v is not None and '€' in str(v):
                                file_has_euro[name] = True
                                break
                    if order == 0 and unit and qty:
                        order = unit * qty
                    if not lcsc:
                        continue
                    entry = {'unit': unit, 'order': order, 'qty': qty,
                             'file': name, 'mtime': mtime}
                    index.setdefault((lcsc, mfg, package, desc, qty), []).append(entry)
                    partial.setdefault((lcsc, mfg, package, desc), []).append(entry)
                    by_code.setdefault(lcsc, []).append(entry)
        except Exception:
            continue
    for d in (index, partial, by_code):
        for entries in d.values():
            entries.sort(key=lambda e: e['mtime'], reverse=True)
    return index, partial, by_code, file_has_euro


def rescan_and_repair(db_path, cvsdone, dry_run=True):
    """Repair zero/missing unit/order prices from the CSV history.

    Returns (repaired, unresolved) lists.
    """
    index, partial, by_code, file_has_euro = _build_history_index(cvsdone)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('''
        SELECT rowid, lcsc_part_number, manufacture_part_number, package,
               description, order_qty, unit_price, order_price
        FROM components
    ''')
    rows = cur.fetchall()

    repaired = []
    unresolved = []
    for row in rows:
        unit = row['unit_price'] or 0
        order = row['order_price'] or 0
        qty = row['order_qty']

        if unit > 0 and order > 0:
            continue

        lcsc = (row['lcsc_part_number'] or '').strip()
        mfg = (row['manufacture_part_number'] or '').strip()
        package = (row['package'] or '').strip()
        desc = (row['description'] or '').strip()

        new_unit = None
        new_order = None
        src = None

        # 1) exact part + qty match with non-zero prices
        for e in index.get((lcsc, mfg, package, desc, qty), []):
            if e['unit'] > 0 and e['order'] > 0:
                new_unit, new_order, src = e['unit'], e['order'], e['file']
                break

        # 2) fallback: same part with any qty -> scale order price by our qty
        if new_unit is None:
            for e in partial.get((lcsc, mfg, package, desc), []):
                if e['unit'] > 0:
                    new_unit = e['unit']
                    new_order = round(e['unit'] * qty, 4) if qty else 0.0
                    src = e['file']
                    break

        # 3) last resort: same part code only (safe for LCSC/DK codes)
        if new_unit is None and lcsc:
            for e in by_code.get(lcsc, []):
                if e['unit'] > 0:
                    new_unit = e['unit']
                    new_order = round(e['unit'] * qty, 4) if qty else 0.0
                    src = e['file'] + ' (by part code)'
                    break

        # 4) unit price present but order price missing -> derive it
        if new_unit is None and unit > 0:
            new_unit = unit
            new_order = round(unit * qty, 4) if qty else 0.0
            src = '(unit price kept)'

        if new_unit is not None:
            repaired.append((row['rowid'], lcsc, new_unit, new_order, src))
            if not dry_run:
                cur.execute(
                    "UPDATE components SET unit_price = ?, order_price = ? WHERE rowid = ?",
                    (new_unit, new_order, row['rowid']))
        else:
            unresolved.append((lcsc, desc))

    if not dry_run and repaired:
        conn.commit()
    if not dry_run:
        # correct per-file currency mismatches using the header/value scan
        cur = conn.cursor()
        for name in file_has_euro:
            cur_ = 'EUR' if file_has_euro[name] else 'USD'
            cur.execute(
                "UPDATE imports SET currency = ? WHERE file_name = ? "
                "AND (currency IS NULL OR currency != ?)",
                (cur_, name, cur_))
        cur.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_repair', ?)",
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
        conn.commit()
    conn.close()
    return repaired, unresolved

def sort_key_for(path):
    code = datecode(os.path.basename(path))
    if code:
        return code
    # No datecode: fall back to the file's modification time
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y%m%d%H%M%S')


def main():
    parser = argparse.ArgumentParser(
        description='Import supplier CSVs into the KI-Search components database')
    parser.add_argument('-inDir', '--inDir',
                        help='Folder containing the supplier CSV files')
    parser.add_argument('-outDir', '--outDir', required=True,
                        help='Folder where components.db lives (cvsdone/ is created inside)')
    parser.add_argument('--rescan', action='store_true',
                        help='Repair zero/missing prices using the cvsdone history')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report only; do not modify the database')
    args = parser.parse_args()

    out_dir = args.outDir
    os.makedirs(out_dir, exist_ok=True)
    db_path = os.path.join(out_dir, DB_FILENAME)
    cvsdone = os.path.join(out_dir, 'cvsdone')
    os.makedirs(cvsdone, exist_ok=True)

    ensure_schema(db_path)

    if args.rescan:
        repaired, unresolved = rescan_and_repair(db_path, cvsdone, dry_run=args.dry_run)
        mode = 'Dry run' if args.dry_run else 'Repair'
        print('{}: {} row(s) would be repaired'.format(mode, len(repaired)))
        for rowid, lcsc, unit, order, src in repaired[:50]:
            print('    {} {} -> unit={} order={} ({})'.format(lcsc, rowid, unit, order, src))
        if len(repaired) > 50:
            print('    ...and {} more'.format(len(repaired) - 50))
        print('Unresolved (no price found anywhere): {}'.format(len(unresolved)))
        for lcsc, desc in unresolved[:50]:
            print('    {} {}'.format(lcsc, desc[:60]))
        if len(unresolved) > 50:
            print('    ...and {} more'.format(len(unresolved) - 50))
        return

    if not args.inDir:
        raise SystemExit('Input folder not found: -inDir is required (or use --rescan)')

    in_dir = args.inDir
    if not os.path.isdir(in_dir):
        raise SystemExit("Input folder not found: {}".format(in_dir))

    files = [f for f in os.listdir(in_dir) if f.lower().endswith('.csv')]
    # Oldest first, ordered by the datecode in the file name
    files.sort(key=lambda f: sort_key_for(os.path.join(in_dir, f)))

    print('Importing {} CSV files from {} into {}'.format(len(files), in_dir, db_path))
    print('Order: oldest first (datecode in file name, file time as fallback)\n')

    total_added = 0
    for name in files:
        path = os.path.join(in_dir, name)
        code = datecode(name) or '(no datecode)'
        print('{}  [{}]'.format(name, code))
        supplier = detect_supplier(path)
        if supplier is None:
            print('    SKIP: unrecognized CSV format\n')
            continue
        try:
            added, skipped, currency, no_price = import_csv(db_path, path, supplier)
            price_note = '  *** {} row(s) WITHOUT price!'.format(no_price) if no_price else ''
            print('    OK: supplier={} added={} skipped={} currency={} -> cvsdone/{}{}'.format(
                supplier, added, skipped, currency, price_note))
            total_added += added
        except Exception as e:
            print('    ERROR: {}\n'.format(e))

    print('Done. Total rows added: {}'.format(total_added))


if __name__ == '__main__':
    main()
