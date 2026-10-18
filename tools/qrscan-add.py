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
# Description: Console frontend for the QR bag scanner. All matching logic
# lives in plugins/qrscan_core.py (shared with the plugin's Scan QR dialog).
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
import importlib.util
import os
import sqlite3
import sys

# Load the shared core without importing the plugin package (whose
# __init__.py pulls in pcbnew and wx, unavailable outside KiCad).
CORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '..', 'plugins', 'qrscan_core.py')


def _load_core():
    spec = importlib.util.spec_from_file_location('qrscan_core', CORE_PATH)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    return core


core = _load_core()

DEFAULT_DB = os.path.join(
    os.path.expanduser('~'), 'Documents', 'KiCad', 'ki-search',
    'components.db')


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
    loc = core.find_location(conn, args.location)
    if loc is None:
        print("Location '{}' is not an active code.".format(args.location))
        print('Available locations: {}'.format(
            ', '.join(core.list_active_locations(conn))))
        conn.close()
        sys.exit(1)
    conn.close()
    loc_id, loc_code, loc_name = loc
    loc_label = loc_code + (' ({})'.format(loc_name) if loc_name else '')

    print('Database:    {}'.format(args.db))
    print('Location:    {}'.format(loc_label))
    print('Supplier:    {}'.format(args.supplier))
    print('Mode:        {}'.format('DRY-RUN (no writes)' if args.dry_run
                                   else 'live (backup before first write)'))
    print('Scan QR codes now. Type "exit" or press Ctrl+C to stop.')
    print('-' * 60)

    session = core.ScanSession(args.db, loc_id, loc_code,
                               dry_run=args.dry_run, auto_yes=args.yes)

    prompt = None
    while True:
        if prompt is not None:
            sys.stdout.write(prompt)
            sys.stdout.flush()
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            break
        if not line:  # EOF
            break
        line = line.strip()
        if prompt is None and line.lower() in ('exit', 'quit', 'q'):
            break
        if not line and prompt is None:
            continue
        msgs, prompt = session.submit(line)
        for m in msgs:
            print(m)

    session.close()
    c = session.counters
    print('-' * 60)
    print('Summary: {} scanned, {} found, {} rows updated, '
          '{} already marked, {} not found'.format(
              c['scanned'], c['found'], c['updated'],
              c['already'], c['not_found']))


if __name__ == '__main__':
    main()


