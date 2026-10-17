##########################################################
#
# Script: qrscan-add.py
# Author: Jani Hirvinen (jpkh)
# Contact: jphelirc@gmail.com
# Repository: https://github.com/jpkh/ki_search
#
# Copyright (c) 2026 Jani Hirvinen
# License: GPL-3.0 - see the LICENSE file
#
# Description: Assign a storage location to components by scanning the QR
# codes on LCSC bags. Each scanned line is parsed for the LCSC product code
# (pc:), manufacturer part number (pm:), order number (on:) and quantity
# (qty:). A part is matched in components.db by product code (fallback:
# manufacturer part number) **and** the order number + quantity taken from
# the imports table — one bag equals one database row, so rows from other
# orders or with a different quantity are never touched.
#
# Rows that already carry the target location are skipped with a note.
# Rows marked with a different location ask for confirmation before
# anything is written.
#
# When no exact order/qty match exists (old QR labels with GB order
# numbers, or bags whose order was never imported), the candidate rows are
# listed and the user picks the matching one(s) with a number list
# (e.g. 1,3) or N for none.
#
# Usage:
#   python qrscan-add.py R15 [LCSC] [--db PATH] [--dry-run] [--yes]
#
# - The location must be an active code from the locations table (R01..,
#   B01.., BU1..). Invalid codes print the available list and exit.
# - The DB defaults to Documents/KiCad/ki-search/components.db, the same
#   database the plugin uses.
# - A timestamped backup of the DB is created before the first write.
# - Scan away; the scanner acts as a keyboard. Type "exit" (or Ctrl+C) to
#   stop and see the summary.
#
# Example QR line:
#   {pbn:PICK2609280004,on:WM2609280033,pc:C7432363,pm:AT24C02CM5/TR,qty:100,mc:,cc:1,pdi:239503200,hp:11,wc:ZH}
#
##########################################################

import argparse
import os
import re
import shutil
import sqlite3
import sys
import time

DEFAULT_DB = os.path.join(
    os.path.expanduser('~'), 'Documents', 'KiCad', 'ki-search',
    'components.db')

# One QR line holds key:value pairs separated by commas inside braces.
QR_FIELD_RE = re.compile(r'\b(on|pc|pm|qty|mc|cc|pdi|hp|wc):([^,}\s]+)')

# Candidate rows with their import info: the imports table (joined via
# components.import_id) carries the order_key and the source CSV file name.
ROW_SQL = """
SELECT c.rowid, c.order_qty, c.location_id, i.order_key, i.file_name,
       l.code AS loc_code
FROM components c
LEFT JOIN imports i ON i.rowid = c.import_id
LEFT JOIN locations l ON l.id = c.location_id
WHERE {where}
"""


def parse_qr(line):
    """Return a dict of the QR fields found in the scanned line."""
    return dict(QR_FIELD_RE.findall(line))


def norm_order(key):
    """Normalize an order number for comparison.

    The DB stores 'LCSC-2607160614', the QR carries 'WM2607160614' — the
    numeric part is the stable identity for both. Falls back to a
    case-insensitive full compare when no digits exist.
    """
    digits = re.sub(r'\D', '', key or '')
    return digits if digits else (key or '').strip().upper()


def find_location(conn, code):
    """Return (id, code, name) of the active location, or None."""
    return conn.execute(
        "SELECT id, code, name FROM locations "
        "WHERE code = ? COLLATE NOCASE AND disabled = 0",
        (code,)).fetchone()


def list_active_locations(conn):
    return [r[1] for r in conn.execute(
        "SELECT id, code FROM locations WHERE disabled = 0 ORDER BY id")]


def find_candidates(conn, pc, pm):
    """Rows matching the LCSC product code, else the mfg part number."""
    if pc:
        rows = conn.execute(
            ROW_SQL.format(where="c.lcsc_part_number = ? COLLATE NOCASE"),
            (pc,)).fetchall()
        if rows:
            return rows
    if pm:
        rows = conn.execute(
            ROW_SQL.format(where="c.manufacture_part_number = ? COLLATE NOCASE"),
            (pm,)).fetchall()
        if rows:
            return rows
    return []


def narrow_candidates(rows, on, qty):
    """Filter rows by order number and quantity. Returns (exact, details).

    exact    = rows whose order number matches (or is unknown on old
               imports) AND whose quantity matches.
    details  = human-readable description of the candidate rows for
               mismatch reporting.
    """
    rows = [dict(rowid=r[0], order_qty=r[1], location_id=r[2],
                 order_key=r[3], file_name=r[4], loc_code=r[5]) for r in rows]

    def describe(r):
        source = os.path.basename(r['file_name'] or 'unknown import')
        loc = r['loc_code'] or '---'
        return 'row {} qty {} order {} loc {} ({})'.format(
            r['rowid'], r['order_qty'] or '?',
            r['order_key'] or '?', loc, source)

    details = [describe(r) for r in rows]

    if on:
        want = norm_order(on)
        with_order = [r for r in rows
                      if r['order_key'] and norm_order(r['order_key']) == want]
        unknown_order = [r for r in rows if not r['order_key']]
        if with_order:
            rows = with_order
        elif unknown_order:
            # Old imports without an order key: order can't be verified.
            rows = unknown_order
        else:
            return [], details

    if qty is not None:
        qty_rows = [r for r in rows if r['order_qty'] == qty]
        if not qty_rows:
            return [], details
        rows = qty_rows

    return rows, details


def ask_yes_no(prompt, pending):
    """Read a y/n answer. A scanned QR line is kept in pending instead."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if line == '':
        return False
    answer = line.strip().lower()
    if answer in ('y', 'yes'):
        return True
    if answer in ('', 'n', 'no'):
        return False
    # Not an answer: likely another QR scan, keep it for the main loop.
    pending.append(line)
    return False


def ask_selection(prompt, count, pending):
    """Read a row selection like '1,3' or '2'. Returns the chosen 1-based
    indexes (sorted) or [] for none. A scanned QR line is kept in pending.
    """
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if line == '':
        return []
    answer = line.strip().lower()
    if answer in ('', 'n', 'no', 'none', '0'):
        return []
    chosen = set()
    valid = True
    for part in re.split(r'[\s,;]+', answer):
        if not part:
            continue
        if part.isdigit() and 1 <= int(part) <= count:
            chosen.add(int(part))
        else:
            valid = False
    if valid and chosen:
        return sorted(chosen)
    # Not a valid answer: likely another QR scan, keep it for the main loop.
    pending.append(line)
    return []


def main():
    parser = argparse.ArgumentParser(
        description="Assign a storage location to components by scanning "
                    "LCSC bag QR codes (matched by product code + order + qty).")
    parser.add_argument('location',
                        help='Location code, e.g. R15 (must exist and be active).')
    parser.add_argument('supplier', nargs='?', default='LCSC',
                        help='Supplier tag, informational only (default: LCSC).')
    parser.add_argument('--db', default=DEFAULT_DB,
                        help='Path to components.db (default: %(default)s).')
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse and look up only; do not write to the DB.')
    parser.add_argument('--yes', action='store_true',
                        help='Answer yes to every prompt and select all '
                             'proposed candidate rows.')
    args = parser.parse_args()

    if not os.path.isfile(args.db):
        print('Database not found: {}'.format(args.db))
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    loc = find_location(conn, args.location)
    if loc is None:
        print("Location '{}' is not an active code.".format(args.location))
        print('Available locations: {}'.format(
            ', '.join(list_active_locations(conn))))
        conn.close()
        sys.exit(1)
    loc_id, loc_code, loc_name = loc
    loc_label = loc_code + (' ({})'.format(loc_name) if loc_name else '')

    print('Database:    {}'.format(args.db))
    print('Location:    {}'.format(loc_label))
    print('Supplier:    {}'.format(args.supplier))
    print('Mode:        {}'.format('DRY-RUN (no writes)' if args.dry_run
                                   else 'live (backup before first write)'))
    print('Scan QR codes now. Type "exit" or press Ctrl+C to stop.')
    print('-' * 60)

    scans = 0
    found = 0
    updated_rows = 0
    already = 0
    not_found = 0
    backup_made = False
    pending = []  # scanned lines that arrived while a prompt was open

    def make_backup():
        nonlocal backup_made
        if backup_made:
            return
        backup_path = '{}.bak-{}'.format(
            args.db, time.strftime('%Y%m%d-%H%M%S'))
        shutil.copy2(args.db, backup_path)
        print('Backup created: {}'.format(backup_path))
        backup_made = True

    def update_rows(rows):
        nonlocal updated_rows
        if args.dry_run:
            return
        make_backup()
        for r in rows:
            conn.execute(
                "UPDATE components SET location_id = ?, location = NULL "
                "WHERE rowid = ?", (loc_id, r['rowid']))
        conn.commit()
        updated_rows += len(rows)

    def apply_selected(label, rows):
        """Apply the location to the chosen rows: skip rows already at the
        target location, update fresh rows, ask before overwriting rows
        marked with a different location."""
        nonlocal already
        target_rows = [r for r in rows if r['location_id'] == loc_id]
        other_rows = [r for r in rows if r['location_id'] != loc_id]
        overwrite = [r for r in other_rows
                     if r['location_id'] is not None and r['loc_code']]
        fresh = [r for r in other_rows if r not in overwrite]

        if target_rows:
            already += len(target_rows)
            print('{} -> {} row(s) already at {} — skipped'.format(
                label, len(target_rows), loc_code))

        if fresh:
            if args.dry_run:
                print('{} -> {} [DRY-RUN, {} row(s) would be set]'.format(
                    label, loc_code, len(fresh)))
            else:
                update_rows(fresh)
                print('{} -> {} ({} row(s) updated)'.format(
                    label, loc_code, len(fresh)))

        if overwrite:
            if args.dry_run:
                print('{} -> {} [DRY-RUN, {} row(s) marked {} would be '
                      'overwritten]'.format(
                          label, loc_code, len(overwrite),
                          ', '.join(r['loc_code'] for r in overwrite)))
            else:
                if args.yes or ask_yes_no(
                        '{} row(s) marked {} — overwrite with {}? (y/n) '.format(
                            len(overwrite),
                            ', '.join(r['loc_code'] for r in overwrite),
                            loc_code),
                        pending):
                    update_rows(overwrite)
                    print('{} -> {} ({} row(s) updated)'.format(
                        label, loc_code, len(overwrite)))
                else:
                    print('{} -> skipped (marked {}, left unchanged)'.format(
                        label, ', '.join(r['loc_code'] for r in overwrite)))

    while True:
        try:
            line = pending.pop(0) if pending else sys.stdin.readline()
        except KeyboardInterrupt:
            break
        if not line:  # EOF
            break
        line = line.strip()
        if not line:
            continue
        if line.lower() in ('exit', 'quit', 'q'):
            break

        qr = parse_qr(line)
        pc = qr.get('pc', '')
        pm = qr.get('pm', '')
        if not pc and not pm:
            print('Not a QR line (no pc:/pm:): {}'.format(line))
            continue

        on = qr.get('on', '')
        qty = None
        if qr.get('qty', '').isdigit():
            qty = int(qr['qty'])

        scans += 1
        label = '{} / {}'.format(pc or '-', pm or '-')
        candidates = find_candidates(conn, pc, pm)
        if not candidates:
            not_found += 1
            print('{} -> NOT FOUND in DB'.format(label))
            continue

        exact, details = narrow_candidates(candidates, on, qty)
        if exact:
            found += 1
            apply_selected(label, exact)
            continue

        # No exact order/qty match: the QR order field is unreliable
        # (e.g. old GB-prefixed labels) or the bag's order is not in the
        # DB. Propose the candidate rows and let the user pick.
        found += 1
        print('{} -> no exact order/qty match. Candidate rows:'.format(label))
        for idx, d in enumerate(details, 1):
            print('   {}. {}'.format(idx, d))
        if args.dry_run:
            print('[DRY-RUN] would propose the rows above; nothing updated.')
            continue
        if args.yes:
            chosen_indexes = list(range(1, len(candidates) + 1))
        else:
            chosen_indexes = ask_selection(
                'Which row(s) match this bag? (e.g. 1,3 / N for none): ',
                len(candidates), pending)
        if not chosen_indexes:
            print('{} -> skipped (no row selected)'.format(label))
            continue
        chosen = [dict(rowid=c[0], order_qty=c[1], location_id=c[2],
                       order_key=c[3], file_name=c[4], loc_code=c[5])
                  for i, c in enumerate(candidates, 1)
                  if i in chosen_indexes]
        apply_selected(label, chosen)

    conn.close()
    print('-' * 60)
    print('Summary: {} scanned, {} found, {} rows updated, '
          '{} already marked, {} not found'.format(
              scans, found, updated_rows, already, not_found))


if __name__ == '__main__':
    main()

