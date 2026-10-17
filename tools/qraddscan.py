##########################################################
#
# Script: qraddscan.py
# Author: Jani Hirvinen (jpkh)
# Contact: jphelirc@gmail.com
# Repository: https://github.com/jpkh/ki_search
#
# Copyright (c) 2026 Jani Hirvinen
# License: GPL-3.0 - see the LICENSE file
#
# Description: Assign a storage location to components by scanning the QR
# codes on LCSC bags. Each scanned line is parsed for the LCSC product code
# (pc:), manufacturer part number (pm:) and order/qty fields, the part is
# looked up in components.db and the given location is written to all
# matching rows.
#
# Usage:
#   python qraddscan.py R15 [LCSC] [--db PATH] [--dry-run]
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


def parse_qr(line):
    """Return a dict of the QR fields found in the scanned line."""
    return dict(QR_FIELD_RE.findall(line))


def find_location_id(conn, code):
    """Return (id, code, name) of the active location, or None."""
    row = conn.execute(
        "SELECT id, code, name FROM locations "
        "WHERE code = ? COLLATE NOCASE AND disabled = 0",
        (code,)).fetchone()
    return row


def list_active_locations(conn):
    return [r[1] for r in conn.execute(
        "SELECT id, code FROM locations WHERE disabled = 0 ORDER BY id")]


def find_part_rows(conn, pc, pm):
    """Rows matching the LCSC product code first, else the mfg part number."""
    if pc:
        rows = conn.execute(
            "SELECT rowid, lcsc_part_number, manufacture_part_number "
            "FROM components WHERE lcsc_part_number = ? COLLATE NOCASE",
            (pc,)).fetchall()
        if rows:
            return rows
    if pm:
        rows = conn.execute(
            "SELECT rowid, lcsc_part_number, manufacture_part_number "
            "FROM components WHERE manufacture_part_number = ? COLLATE NOCASE",
            (pm,)).fetchall()
        if rows:
            return rows
    return []


def main():
    parser = argparse.ArgumentParser(
        description="Assign a storage location to components by scanning "
                    "LCSC bag QR codes.")
    parser.add_argument('location',
                        help='Location code, e.g. R15 (must exist and be active).')
    parser.add_argument('supplier', nargs='?', default='LCSC',
                        help='Supplier tag, informational only (default: LCSC).')
    parser.add_argument('--db', default=DEFAULT_DB,
                        help='Path to components.db (default: %(default)s).')
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse and look up only; do not write to the DB.')
    args = parser.parse_args()

    if not os.path.isfile(args.db):
        print('Database not found: {}'.format(args.db))
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    loc = find_location_id(conn, args.location)
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
    not_found = 0
    backup_made = False

    def make_backup():
        nonlocal backup_made
        if backup_made:
            return
        backup_path = '{}.bak-{}'.format(
            args.db, time.strftime('%Y%m%d-%H%M%S'))
        shutil.copy2(args.db, backup_path)
        print('Backup created: {}'.format(backup_path))
        backup_made = True

    while True:
        try:
            line = sys.stdin.readline()
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

        scans += 1
        rows = find_part_rows(conn, pc, pm)
        if rows:
            found += 1
            if args.dry_run:
                print('{} / {} -> {} [DRY-RUN, {} row(s) would be set]'.format(
                    pc or '-', pm or '-', loc_code, len(rows)))
            else:
                make_backup()
                for rowid, _lpn, _mpn in rows:
                    conn.execute(
                        "UPDATE components SET location_id = ?, "
                        "location = NULL WHERE rowid = ?", (loc_id, rowid))
                conn.commit()
                updated_rows += len(rows)
                print('{} / {} -> {} ({} row(s) updated)'.format(
                    pc or '-', pm or '-', loc_code, len(rows)))
        else:
            not_found += 1
            print('{} / {} -> NOT FOUND in DB'.format(pc or '-', pm or '-'))

    conn.close()
    print('-' * 60)
    print('Summary: {} scanned, {} found ({} rows updated), {} not found'.format(
        scans, found, updated_rows, not_found))


if __name__ == '__main__':
    main()
