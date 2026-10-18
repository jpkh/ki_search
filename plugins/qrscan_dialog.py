##########################################################
#
# Script: qrscan_dialog.py
# Author: Jani Hirvinen (jpkh)
# Contact: jphelirc@gmail.com
# Repository: https://github.com/jpkh/ki_search
#
# Copyright (c) 2026 Jani Hirvinen
# License: GPL-3.0 - see the LICENSE file
#
# Description: Scan QR dialog: one focus area for the scanner/keyboard
# plus a location pulldown on the right. All matching logic lives in
# qrscan_core.py.
#
##########################################################

import wx

from .importer import get_locations
from .qrscan_core import ScanSession, QR_LIKE_RE
from .settings import save_options


class ScanQRDialog(wx.Dialog):
    def __init__(self, parent, db_path, options):
        super().__init__(parent, title='Scan QR — add components to a location',
                         size=(1000, 560))
        self.db_path = db_path
        self.options = options

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        hbox = wx.BoxSizer(wx.HORIZONTAL)

        # Left: the only input area. Scans and prompt answers are typed
        # here; results are appended to the same box (terminal style).
        self.text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER,
                                size=(740, 440))
        hbox.Add(self.text, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        # Right column: location, dry-run, supplier, counters, actions.
        right = wx.BoxSizer(wx.VERTICAL)

        right.Add(wx.StaticText(panel, label='Location:'),
                  flag=wx.LEFT | wx.TOP, border=10)

        self.locations = get_locations(db_path)  # (id, code, name, disabled)
        self.loc_ids = [loc[0] for loc in self.locations]
        choices = ['{} — {}'.format(code, name) if name else code
                   for _id, code, name, _d in self.locations]
        self.loc_choice = wx.Choice(panel, choices=choices)
        initial = options.get('last_location')
        index = self.loc_ids.index(initial) if initial in self.loc_ids else 0
        self.loc_choice.SetSelection(index)
        self.loc_choice.Bind(wx.EVT_CHOICE, self.on_location_change)
        right.Add(self.loc_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        self.dry_run_cb = wx.CheckBox(panel, label='Dry run (no writes)')
        self.dry_run_cb.Bind(wx.EVT_CHECKBOX, self.on_dry_run_change)
        right.Add(self.dry_run_cb, flag=wx.LEFT | wx.TOP, border=10)

        right.AddSpacer(10)

        right.Add(wx.StaticText(panel, label='Supplier:'),
                  flag=wx.LEFT | wx.TOP, border=10)
        # 1 = LCSC (default), 2 = DigiKey, 3 = Mouser. Only the variable
        # is wired for now; LCSC codes are the only ones parsed.
        self.SUPPLIER_NAMES = {1: 'LCSC', 2: 'DigiKey', 3: 'Mouser'}
        self.supplier = 1
        self.supplier_radios = {}
        for key in (1, 2, 3):
            rb = wx.RadioButton(panel, label=self.SUPPLIER_NAMES[key],
                                style=wx.RB_GROUP if key == 1 else 0)
            rb.SetValue(key == 1)
            # DigiKey/Mouser parsing arrives in a later version.
            if key != 1:
                rb.Enable(False)
            rb.Bind(wx.EVT_RADIOBUTTON,
                    lambda evt, k=key: self.on_supplier(k))
            self.supplier_radios[key] = rb
            right.Add(rb, flag=wx.LEFT | wx.TOP, border=10)

        right.AddStretchSpacer(1)

        # Counters stacked, left aligned, directly above the buttons.
        self.counter_names = {
            'scanned': 'Scanned', 'found': 'Found', 'updated': 'Updated',
            'already': 'Already marked', 'not_found': 'Not found'}
        self.counter_labels = {}
        for key, name in self.counter_names.items():
            label = wx.StaticText(panel, label='')
            self.counter_labels[key] = label
            right.Add(label, flag=wx.LEFT | wx.TOP, border=10)
        self.dry_run_label = wx.StaticText(panel, label='')
        right.Add(self.dry_run_label, flag=wx.LEFT | wx.TOP, border=10)

        right.AddSpacer(10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.clear_btn = wx.Button(panel, label='Clear log')
        self.clear_btn.Bind(wx.EVT_BUTTON, self.on_clear)
        self.close_btn = wx.Button(panel, label='Close')
        self.close_btn.Bind(wx.EVT_BUTTON, self.on_close)
        btn_row.Add(self.clear_btn, flag=wx.RIGHT, border=5)
        btn_row.Add(self.close_btn)
        right.Add(btn_row, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.TOP,
                  border=10)

        hbox.Add(right, flag=wx.EXPAND)
        vbox.Add(hbox, proportion=1, flag=wx.EXPAND)
        panel.SetSizer(vbox)
        self.Layout()

        # Session starts with the preselected location.
        self._loc_id = self.loc_ids[index]
        self._loc_code = self.locations[index][1]
        self.session = ScanSession(db_path, self._loc_id, self._loc_code)

        self.text.Bind(wx.EVT_TEXT_ENTER, self.on_enter)
        self._append('Database: {}'.format(db_path))
        self._append('Location: {}'.format(self._loc_code))
        self._append('Scan bags now. Scans and answers are typed in this box; '
                     'press Enter after each one.')
        self._append('-' * 60)
        self._update_status()
        self.text.SetFocus()

    # ----- helpers --------------------------------------------------------

    def _append(self, line):
        self.text.AppendText(line + '\n')

    def _update_status(self):
        c = self.session.counters
        for key, label in self.counter_labels.items():
            label.SetLabel('{}: {}'.format(self.counter_names[key], c[key]))
        self.dry_run_label.SetLabel(
            'Dry run: {}'.format('ON' if self.session.dry_run else 'OFF'))

    # ----- events ---------------------------------------------------------

    def on_enter(self, event):
        """Process the last typed line (a scan or a prompt answer)."""
        value = self.text.GetValue()
        lines = value.split('\n')
        last = lines[-1] if lines else ''
        if not last.strip():
            return
        prefix = '\n'.join(lines[:-1])
        display_line = 'SCAN: ' + last if QR_LIKE_RE.search(last) else last
        msgs, prompt = self.session.submit(last)
        out = prefix + ('\n' if prefix else '') + display_line + '\n'
        if msgs:
            rendered = []
            for m in msgs:
                if ' -> ' in m or m.startswith('Not a QR line') \
                        or m.startswith('Invalid input'):
                    rendered.append('- ' + m)
                else:
                    rendered.append(m)
            out += '\n'.join(rendered) + '\n'
        if prompt:
            # The question belongs to the current scan: no blank line yet.
            out += prompt + '\n'
        else:
            # Scan fully done: one blank line before the next scan.
            out += '\n'
        self.text.ChangeValue(out)
        self.text.SetInsertionPointEnd()
        self._update_status()

    def on_location_change(self, event):
        index = self.loc_choice.GetSelection()
        if 0 <= index < len(self.loc_ids):
            self._loc_id = self.loc_ids[index]
            self._loc_code = self.locations[index][1]
            self.session.set_location(self._loc_id, self._loc_code)
            self._append('Location set to {}'.format(self._loc_code))
            self.options['last_location'] = self._loc_id
            save_options(self.options)
        self.text.SetFocus()

    def on_dry_run_change(self, event):
        self.session.set_dry_run(self.dry_run_cb.IsChecked())
        self._append('Dry run {}'.format(
            'ON (no writes)' if self.session.dry_run else 'OFF (live)'))
        self._update_status()
        self.text.SetFocus()

    def on_supplier(self, key):
        """Remember the selected supplier for later code filtering.
        1 = LCSC, 2 = DigiKey, 3 = Mouser. Only LCSC codes are parsed
        for now, so the choice is stored but not acted on yet."""
        self.supplier = key
        self.text.SetFocus()

    def on_clear(self, event):
        self.text.ChangeValue('')
        self.text.SetFocus()

    def on_close(self, event):
        self.session.close()
        self.EndModal(wx.ID_OK)
