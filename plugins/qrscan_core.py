##########################################################
#
# Script: qrscan_core.py
# Author: Jani Hirvinen (jpkh)
# Contact: jphelirc@gmail.com
# Repository: https://github.com/jpkh/ki_search
#
# Copyright (c) 2026 Jani Hirvinen
# License: GPL-3.0 - see the LICENSE file
#
# Description: QR bag scanning core shared by the console tool
# (tools/qrscan-add.py) and the plugin UI (qrscan_dialog.py).
# Pure stdlib — no wx — so both consumers can use it.
#
##########################################################

import os
import re
import shutil
import sqlite3
import time

# One QR line holds key:value pairs separated by commas inside braces.
QR_FIELD_RE = re.compile(r'\b(on|pc|pm|qty|mc|cc|pdi|hp|wc):([^,}\s]+)')

# Detects a scanned QR line (for answers that arrive while a prompt is
# waiting).
QR_LIKE_RE = re.compile(r'\b(pc|pm|on):')

# Candidate rows with their import info: the imports table (joined via
# components.import_id) carries the order_key and the source CSV file name.
ROW_SQL = """
SELECT c.rowid, c.order_qty, c.location_id, i.order_key, i.file_name,
       l.code AS loc_code, c.unit_price
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


def _row_dict(rows, index):
    r = rows[index]
    return dict(rowid=r[0], order_qty=r[1], location_id=r[2],
                order_key=r[3], file_name=r[4], loc_code=r[5],
                unit_price=r[6])


def narrow_candidates(rows, on, qty):
    """Filter rows by order number and quantity. Returns (exact, details).

    exact    = rows whose order number matches (or is unknown on old
               imports) AND whose quantity matches. Multiple rows sharing
               the quantity with an unverifiable order are treated as
               uncertain (exact empty) so the user picks.
    details  = human-readable description of the candidate rows.
    """
    rows = [_row_dict(rows, i) for i in range(len(rows))]

    def describe(r):
        source = os.path.basename(r['file_name'] or 'unknown import')
        loc = r['loc_code'] or '---'
        price = ' price {:.4f}'.format(r['unit_price']) \
            if r['unit_price'] is not None else ''
        return 'row {} qty {} order {} loc {} ({}{})'.format(
            r['rowid'], r['order_qty'] or '?',
            r['order_key'] or '?', loc, source, price)

    details = [describe(r) for r in rows]

    order_matched = True
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
            order_matched = False
        else:
            return [], details

    if qty is not None:
        qty_rows = [r for r in rows if r['order_qty'] == qty]
        if not qty_rows:
            return [], details
        rows = qty_rows

    if not order_matched and len(rows) > 1:
        # Multiple rows from unknown orders share the same quantity — the
        # bag can't be mapped to exactly one row. Let the user pick.
        return [], details

    return rows, details


class ScanSession:
    """Stateful scanning session: holds the DB connection, the target
    location, dry-run flag and counters. submit() feeds one input line
    (a scan or an answer to a pending prompt) and returns
    (messages, prompt_or_None). When a prompt is pending, the next
    submit() line is treated as its answer.
    """

    def __init__(self, db_path, location_id, location_code,
                 dry_run=False, auto_yes=False):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.loc_id = location_id
        self.loc_code = location_code
        self.dry_run = dry_run
        self.auto_yes = auto_yes
        self.prompt = None          # question text waiting for an answer
        self._pending = None        # (kind, prompt_text, payload)
        self.backup_made = False
        self.backup_path = None
        self.counters = {'scanned': 0, 'found': 0, 'updated': 0,
                         'already': 0, 'not_found': 0}

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def set_location(self, location_id, location_code):
        self.loc_id = location_id
        self.loc_code = location_code

    def set_dry_run(self, dry_run):
        self.dry_run = dry_run

    # ----- input plumbing -------------------------------------------------

    def submit(self, line):
        line = (line or '').strip()
        if self.prompt is not None:
            pending = self._pending
            self.prompt = None
            self._pending = None
            return self._handle_answer(line, pending)
        return self._process_scan(line)

    def _set_prompt(self, text, pending):
        self.prompt = text
        self._pending = pending

    def _handle_answer(self, line, pending):
        kind, prompt_text, payload = pending
        if QR_LIKE_RE.search(line):
            # A new scan arrived while a prompt was waiting: process it
            # and ask the same question again afterwards.
            msgs, _new_prompt = self._process_scan(line)
            self._set_prompt(prompt_text, pending)
            return msgs, prompt_text
        if kind == 'yes_no':
            label, rows = payload
            answer = line.lower()
            if answer in ('y', 'yes'):
                return self._finish_overwrite(label, rows, True)
            if answer in ('', 'n', 'no'):
                return self._finish_overwrite(label, rows, False)
            self._set_prompt(prompt_text, pending)
            return ['Invalid input — answer y or n.'], prompt_text
        if kind == 'selection':
            count, candidates, display_order, label = payload
            if line in ('', 'n', 'no', 'none', '0'):
                return ['{} -> skipped (no row selected)'.format(label)], None
            if line.isdigit() and 1 <= int(line) <= count:
                chosen = [_row_dict(candidates, display_order[int(line) - 1])]
                return self._apply(label, chosen)
            self._set_prompt(prompt_text, pending)
            return ['Invalid input — give one row number or N.'], prompt_text
        return [], None

    def _finish_overwrite(self, label, rows, do_update):
        if do_update:
            self._update_rows(rows)
            return ['{} -> {} ({} row(s) updated)'.format(
                label, self.loc_code, len(rows))], None
        return ['{} -> skipped (marked {}, left unchanged)'.format(
            label, ', '.join(r['loc_code'] for r in rows))], None

    # ----- scan processing ------------------------------------------------

    def _process_scan(self, line):
        qr = parse_qr(line)
        pc = qr.get('pc', '')
        pm = qr.get('pm', '')
        if not pc and not pm:
            return ['Not a QR line (no pc:/pm:): {}'.format(line)], None

        on = qr.get('on', '')
        qty = None
        if qr.get('qty', '').isdigit():
            qty = int(qr['qty'])

        self.counters['scanned'] += 1
        label = '{} / {}'.format(pc or '-', pm or '-')
        candidates = find_candidates(self.conn, pc, pm)
        if not candidates:
            self.counters['not_found'] += 1
            return ['{} -> NOT FOUND in DB'.format(label)], None

        exact, details = narrow_candidates(candidates, on, qty)
        if exact:
            self.counters['found'] += 1
            return self._apply(label, exact)

        # No exact order/qty match: the QR order field is unreliable
        # (e.g. old GB-prefixed labels) or the bag's order is not in the
        # DB. Propose the candidate rows and let the user pick one.
        # Rows whose quantity matches the bag are strong candidates:
        # listed first and marked with *. In dry-run mode the selection
        # is still requested, but nothing is written.
        self.counters['found'] += 1
        msgs = ['{} -> no exact order/qty match. Candidate rows:'.format(label)]
        display_order = list(range(len(candidates)))
        if qty is not None:
            display_order.sort(
                key=lambda i: 0 if candidates[i][1] == qty else 1)
            if any(candidates[i][1] == qty for i in display_order):
                msgs.append('   (*) = quantity matches the scanned bag')
        for disp, i in enumerate(display_order, 1):
            marker = '*' if (qty is not None and candidates[i][1] == qty) else ' '
            msgs.append('   {}. {} {}'.format(disp, marker, details[i]))

        if self.auto_yes:
            chosen = [_row_dict(candidates, i) for i in display_order]
            more, prompt = self._apply(label, chosen)
            return msgs + more, prompt

        prompt = 'Which row matches this bag? (row number, N = none): '
        self._set_prompt(prompt, ('selection', prompt,
                                  (len(candidates), candidates,
                                   display_order, label)))
        return msgs, prompt

    def _apply(self, label, rows):
        """Apply the location to the chosen rows: skip rows already at the
        target location, update fresh rows, ask before overwriting rows
        marked with a different location."""
        msgs = []
        target_rows = [r for r in rows if r['location_id'] == self.loc_id]
        other_rows = [r for r in rows if r['location_id'] != self.loc_id]
        overwrite = [r for r in other_rows
                     if r['location_id'] is not None and r['loc_code']]
        fresh = [r for r in other_rows if r not in overwrite]

        if target_rows:
            self.counters['already'] += len(target_rows)
            msgs.append('{} -> {} row(s) already at {} — skipped'.format(
                label, len(target_rows), self.loc_code))

        if fresh:
            if self.dry_run:
                msgs.append('{} -> {} [DRY-RUN, {} row(s) would be set]'.format(
                    label, self.loc_code, len(fresh)))
            else:
                self._update_rows(fresh)
                msgs.append('{} -> {} ({} row(s) updated)'.format(
                    label, self.loc_code, len(fresh)))

        if overwrite:
            if self.dry_run:
                msgs.append(
                    '{} -> {} [DRY-RUN, {} row(s) marked {} would be '
                    'overwritten]'.format(
                        label, self.loc_code, len(overwrite),
                        ', '.join(r['loc_code'] for r in overwrite)))
            elif self.auto_yes:
                self._update_rows(overwrite)
                msgs.append('{} -> {} ({} row(s) updated)'.format(
                    label, self.loc_code, len(overwrite)))
            else:
                prompt = ('{} row(s) marked {} — overwrite with {}? (y/n) '
                          .format(len(overwrite),
                                  ', '.join(r['loc_code'] for r in overwrite),
                                  self.loc_code))
                self._set_prompt(
                    prompt, ('yes_no', prompt, (label, overwrite)))
                return msgs, prompt
        return msgs, None

    # ----- writes ---------------------------------------------------------

    def _make_backup(self):
        if self.backup_made:
            return
        self.backup_path = '{}.bak-{}'.format(
            self.db_path, time.strftime('%Y%m%d-%H%M%S'))
        shutil.copy2(self.db_path, self.backup_path)
        self.backup_made = True

    def _update_rows(self, rows):
        if self.dry_run:
            return
        self._make_backup()
        for r in rows:
            self.conn.execute(
                "UPDATE components SET location_id = ?, location = NULL "
                "WHERE rowid = ?", (self.loc_id, r['rowid']))
        self.conn.commit()
        self.counters['updated'] += len(rows)
