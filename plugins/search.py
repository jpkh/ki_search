##########################################################
#
# Script: search.py
# Author: Jani Hirvinen (jpkh)
# Contact: jphelirc@gmail.com
# Repository: https://github.com/jpkh/ki_search
#
# Copyright (c) 2026 Jani Hirvinen
# License: GPL-3.0 - see the LICENSE file
#
# Description: Main search dialog and ActionPlugin for KI-Search.
#
##########################################################

import os
import sqlite3
import wx
import pcbnew
import webbrowser

from .config import COLUMNS, default_db_relpath, default_db_filename, plugin_version, LOCATION_EMPTY
from .settings import load_options, save_options, SettingsDialog
from .importer import (get_db_stats, ensure_schema, ImportDialog,
                       set_component_location, get_locations)
from .qrscan_dialog import ScanQRDialog
from .log_util import log_message


class EditLocationDialog(wx.Dialog):
    """Small picker for a component's storage location (id-based)."""

    CLEAR_LABEL = '(clear location)'

    def __init__(self, parent, current_location_id, locations):
        super().__init__(parent, title="Edit Location")
        self._ids = [self.CLEAR_LABEL] + [str(loc_id) for loc_id, _c, _n, _d in locations]
        choices = [self.CLEAR_LABEL] + [
            "{} — {}".format(code, name) if name else code
            for _id, code, name, _disabled in locations]

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(wx.StaticText(self, label="Storage location:"),
                 flag=wx.ALL, border=10)
        self.choice = wx.Choice(self, choices=choices)
        index = 0
        if current_location_id:
            try:
                index = self._ids.index(str(current_location_id))
            except ValueError:
                index = 0
        self.choice.SetSelection(index)
        vbox.Add(self.choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(btns, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        self.SetSizer(vbox)
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre(wx.BOTH)

    def get_location(self):
        """Return the chosen location id, or None for the clear option."""
        selection = self.choice.GetSelection()
        raw = self._ids[selection]
        return None if raw == self.CLEAR_LABEL else int(raw)


class SearchDatabasePlugin(pcbnew.ActionPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Component Search"
        self.category = "Component Management"
        self.description = "Search for components in the database"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'icon.png')

    def Run(self):
        frame = wx.GetActiveWindow()
        dlg = SearchDialog(frame)
        dlg.ShowModal()
        dlg.Destroy()


class SearchDialog(wx.Dialog):
    # Fixed SELECT order; displayed columns are a subset chosen in settings
    DB_COLUMN_ORDER = [c[0] for c in COLUMNS]

    # Quick-insert buttons shown after the search box
    INSERT_SYMBOLS = ['Ω', 'μ', '±', '°']

    def __init__(self, parent):
        title = "Search Components  Ki-Search V{}".format(plugin_version)
        super().__init__(parent, title=title, size=(1200, 420))
        self.options = load_options()
        # Last used storage location; offers a one-click "Add to <code>"
        # entry in the row context menu. Persisted across sessions.
        self._last_location_id = self.options.get('last_location') or None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Row 1: search + actions
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        self.search_ctrl = wx.TextCtrl(panel, size=(400, -1), style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetToolTip(
            "Wildcards: * = any characters, ? = one character")
        self.search_btn = wx.Button(panel, label="Search")
        self.import_btn = wx.Button(panel, label="Import CSV…")
        self.scanqr_btn = wx.Button(panel, label="Scan QR…")
        self.settings_btn = wx.Button(panel, label="Settings…")
        hbox1.Add(wx.StaticText(panel, label="Search: "),
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        hbox1.Add(self.search_ctrl,
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        hbox1.Add(wx.StaticText(panel, label="Add:"),
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=2)
        for symbol in self.INSERT_SYMBOLS:
            btn = wx.Button(panel, label=symbol, size=(30, -1))
            btn.SetToolTip("Insert {} at the cursor".format(symbol))
            btn.Bind(wx.EVT_BUTTON,
                     lambda evt, s=symbol: self.on_insert_symbol(s))
            hbox1.Add(btn,
                      flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=2)
        hbox1.Add(self.search_btn,
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        hbox1.Add(self.import_btn,
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        hbox1.Add(self.scanqr_btn,
                  flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        hbox1.Add(self.settings_btn, flag=wx.ALIGN_CENTER_VERTICAL, border=5)
        vbox.Add(hbox1, flag=wx.EXPAND | wx.ALL, border=10)

        # Row 2: results
        self.result_list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self._rebuild_columns()
        vbox.Add(self.result_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        # Row 3: info line (left) + version/copyright (right-aligned)
        self.info_label = wx.StaticText(panel, label="")
        hbox_info = wx.BoxSizer(wx.HORIZONTAL)
        hbox_info.Add(self.info_label, flag=wx.ALIGN_CENTER_VERTICAL)
        hbox_info.AddStretchSpacer(1)
        hbox_info.Add(wx.StaticText(panel, label="Ki-Search V{}".format(plugin_version)),
                      flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=10)
        hbox_info.Add(wx.StaticText(panel, label="(c)2026 "),
                      flag=wx.ALIGN_CENTER_VERTICAL)
        hbox_info.Add(wx.adv.HyperlinkCtrl(panel, wx.ID_ANY, "jpkh/fi",
                                           "https://github.com/jpkh"),
                      flag=wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(hbox_info, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        self.search_btn.Bind(wx.EVT_BUTTON, self.on_search)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.import_btn.Bind(wx.EVT_BUTTON, self.on_import)
        self.scanqr_btn.Bind(wx.EVT_BUTTON, self.on_scan_qr)
        self.settings_btn.Bind(wx.EVT_BUTTON, self.on_settings)
        self.result_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_click)
        self.result_list.Bind(wx.EVT_MOTION, self.on_result_motion)
        self.result_list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_result_right_click)
        self._row_meta = []  # dicts (rowid, import_id, source_file, supplier, location) aligned with list rows

        panel.SetSizer(vbox)
        # Defer the info refresh so the main dialog shows before any
        # create-database prompt appears
        wx.CallAfter(self._refresh_info)

    # ----- UI helpers ------------------------------------------------------

    def _rebuild_columns(self):
        self.result_list.ClearAll()
        active = self.options['active_columns']
        self.columns = [c for c in COLUMNS if c[0] in active]
        for i, (key, header, width, right) in enumerate(self.columns):
            fmt = wx.LIST_FORMAT_RIGHT if right else wx.LIST_FORMAT_LEFT
            self.result_list.InsertColumn(i, header, format=fmt, width=width)
        self.lcsc_col = next(
            (i for i, c in enumerate(self.columns) if c[0] == 'lcsc_part_number'), None)
        self.loc_col = next(
            (i for i, c in enumerate(self.columns) if c[0] == 'location'), None)

    def _refresh_info(self):
        db_path = self.get_database_path()
        stats = get_db_stats(db_path)
        if not stats['exists']:
            if not self._ensure_database(db_path):
                self.info_label.SetLabel("Database not found: {}".format(db_path))
                return
            stats = get_db_stats(db_path)
        last = stats['last_update'] or 'unknown'
        self.info_label.SetLabel(
            "Components in DB: {}   |   DB: {}   |   Last update: {}".format(
                stats['total'], db_path, last))

    def _ensure_database(self, db_path):
        """Ask the user to create the database when it does not exist."""
        if os.path.isfile(db_path):
            # Idempotent: also covers schema migrations for existing DBs
            ensure_schema(db_path)
            return True
        dlg = wx.MessageDialog(
            self,
            "Database not found:\n{}\n\nCreate a new empty database?".format(db_path),
            "Database missing", wx.YES_NO | wx.ICON_QUESTION)
        result = dlg.ShowModal()
        dlg.Destroy()
        if result == wx.ID_YES:
            ensure_schema(db_path)
            return True
        return False

    # ----- Paths -----------------------------------------------------------

    def get_database_path(self):
        """Database file path: settings folder override, else USER_DOCS default."""
        override = (self.options.get('db_path') or '').strip()
        if override:
            return os.path.join(override, default_db_filename)
        user_docs = os.getenv('USER_DOCS')
        if not user_docs:
            user_docs = os.path.expanduser("~/Documents")  # Fallback for safety
        return os.path.join(user_docs, default_db_relpath)

    # ----- Events ----------------------------------------------------------

    def on_item_click(self, event):
        """Open the supplier search page (LCSC or DigiKey) for the part."""
        if self.lcsc_col is None:
            return
        item_index = event.GetIndex()
        part_number = self.result_list.GetItemText(item_index, self.lcsc_col)
        if not part_number:
            return
        supplier = 'LCSC'
        if 0 <= item_index < len(self._row_meta):
            supplier = self._row_meta[item_index]['supplier'] or 'LCSC'
        if supplier == 'DK':
            url = "https://www.digikey.com/en/products/result?keywords={}".format(part_number)
        else:
            url = "https://www.lcsc.com/search?q={}".format(part_number)
        webbrowser.open(url)

    def on_insert_symbol(self, symbol):
        """Insert the clicked symbol at the search box cursor position."""
        self.search_ctrl.WriteText(symbol)
        self.search_ctrl.SetFocus()

    def on_search(self, event):
        """Perform a database search based on user input."""
        search_term = self.search_ctrl.GetValue().strip()
        self.result_list.DeleteAllItems()
        self._row_meta = []

        if not search_term:
            wx.MessageBox("Please enter a search term", "Warning", wx.OK | wx.ICON_WARNING)
            return

        db_path = self.get_database_path()
        if not self._ensure_database(db_path):
            return
        results = self.search_database(db_path, search_term)

        if not results:
            wx.MessageBox("No results found.", "Info", wx.OK | wx.ICON_INFORMATION)
            return

        link_font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                            wx.FONTWEIGHT_NORMAL, underline=True)
        for row in results:
            values = dict(zip(
                ['rowid'] + self.DB_COLUMN_ORDER + ['location_id', 'import_id', 'source_file', 'supplier'],
                row))
            first_value = str(values.get(self.columns[0][0], ''))
            index = self.result_list.InsertItem(self.result_list.GetItemCount(), first_value)
            for col, (key, _header, _width, _right) in enumerate(self.columns):
                cell = values.get(key, '')
                if key == 'location' and not cell:
                    cell = LOCATION_EMPTY
                self.result_list.SetItem(index, col, str(cell))
            if self.lcsc_col is not None:
                # Style the LCSC Pn column as a blue, underlined link
                self.result_list.SetItemFont(index, link_font)
                self.result_list.SetItemTextColour(index, wx.Colour(0, 0, 255))
            self._row_meta.append({
                'rowid': values.get('rowid'),
                'import_id': values.get('import_id'),
                'source_file': values.get('source_file'),
                'supplier': values.get('supplier'),
                'location_id': values.get('location_id'),
            })

    def on_result_motion(self, event):
        """Show the source CSV file of the hovered row as a tooltip."""
        if not self.options.get('show_source_tooltip', True):
            if self.result_list.GetToolTip():
                self.result_list.SetToolTip(None)
            event.Skip()
            return
        item, _flags = self.result_list.HitTest(event.GetPosition())
        if 0 <= item < len(self._row_meta):
            source = self._row_meta[item]['source_file'] or 'unknown'
            tip = self.result_list.GetToolTip()
            if tip is None:
                tip = wx.ToolTip('')
                self.result_list.SetToolTip(tip)
            if tip.GetTip() != source:
                tip.SetTip('Source: {}'.format(source))
        else:
            self.result_list.SetToolTip(None)
        event.Skip()

    def on_result_right_click(self, event):
        """Right-click context menu on a result row: Edit Location… plus a
        quick "Add to <last used location>" entry."""
        item_index = event.GetIndex()
        if not (0 <= item_index < len(self._row_meta)):
            return
        menu = wx.Menu()
        edit_item = menu.Append(wx.ID_ANY, "Edit Location…")
        self.Bind(wx.EVT_MENU,
                  lambda evt: self.on_edit_location(item_index), edit_item)
        if self._last_location_id:
            locations = get_locations(self.get_database_path())
            code = next((c for i, c, _n, _d in locations
                         if i == self._last_location_id), None)
            if code:
                quick_item = menu.Append(wx.ID_ANY, "Add to {}".format(code))
                self.Bind(wx.EVT_MENU,
                          lambda evt: self.on_quick_add_location(item_index),
                          quick_item)
        self.result_list.PopupMenu(menu)
        menu.Destroy()

    def on_edit_location(self, item_index):
        """Open the small location picker and persist the choice to the DB."""
        meta = self._row_meta[item_index]
        if meta.get('rowid') is None:
            wx.MessageBox("This row has no database id; cannot edit its location.",
                          "Error", wx.OK | wx.ICON_ERROR)
            return
        db_path = self.get_database_path()
        if not self._ensure_database(db_path):
            return
        locations = get_locations(db_path)  # active locations only
        dlg = EditLocationDialog(self, meta.get('location_id'), locations)
        if dlg.ShowModal() == wx.ID_OK:
            new_id = dlg.get_location()
            self._apply_location(item_index, new_id)
            if new_id is not None:
                self._remember_location(new_id)
        dlg.Destroy()

    def on_quick_add_location(self, item_index):
        """Assign the last used location without opening the picker."""
        self._apply_location(item_index, self._last_location_id)
        self._remember_location(self._last_location_id)

    def _apply_location(self, item_index, location_id):
        """Write location_id for the row and update the visible LOC cell."""
        meta = self._row_meta[item_index]
        if meta.get('rowid') is None:
            wx.MessageBox("This row has no database id; cannot edit its location.",
                          "Error", wx.OK | wx.ICON_ERROR)
            return
        db_path = self.get_database_path()
        if not self._ensure_database(db_path):
            return
        set_component_location(db_path, meta['rowid'], location_id)
        meta['location_id'] = location_id
        if self.loc_col is not None:
            if location_id is None:
                label = LOCATION_EMPTY
            else:
                locations = get_locations(db_path)
                label = next((code for i, code, _n, _d in locations
                              if i == location_id), LOCATION_EMPTY)
            self.result_list.SetItem(item_index, self.loc_col, label)

    def _remember_location(self, location_id):
        """Remember the last used location for the quick-add menu entry."""
        self._last_location_id = location_id
        self.options['last_location'] = location_id
        save_options(self.options)

    def on_import(self, event):
        dlg = ImportDialog(self, self.get_database_path())
        if dlg.ShowModal() == wx.ID_OK:
            self._refresh_info()
        dlg.Destroy()

    def on_scan_qr(self, event):
        """Open the Scan QR dialog for bag scanning against the DB."""
        db_path = self.get_database_path()
        if not self._ensure_database(db_path):
            return
        dlg = ScanQRDialog(self, db_path, self.options)
        dlg.ShowModal()
        dlg.Destroy()
        self._refresh_info()

    def on_settings(self, event):
        dlg = SettingsDialog(self, self.options, self.get_database_path())
        if dlg.ShowModal() == wx.ID_OK:
            self.options.update(dlg.get_options())
            save_options(self.options)
            self._rebuild_columns()
            self._refresh_info()
            log_message("Settings saved: db folder = '{}'".format(
                self.options.get('db_path', '')))
        dlg.Destroy()

    # ----- Search ----------------------------------------------------------

    def search_database(self, db_path, search_term):
        """Query the SQLite database for matching components."""
        if not os.path.isfile(db_path):
            wx.MessageBox("Database not found at {}".format(db_path),
                          "Error", wx.OK | wx.ICON_ERROR)
            return []

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            query = '''
            SELECT c.rowid, c.lcsc_part_number, c.manufacture_part_number, c.manufacturer, c.package,
                   c.description, c.order_qty, c.unit_price, c.order_price,
                   COALESCE(l.code, c.location), c.location_id,
                   c.import_id, i.file_name, i.supplier
            FROM components c
            LEFT JOIN imports i ON i.rowid = c.import_id
            LEFT JOIN locations l ON l.id = c.location_id
            WHERE c.lcsc_part_number LIKE ?
            OR c.manufacture_part_number LIKE ?
            OR c.manufacturer LIKE ?
            OR c.package LIKE ?
            OR c.description LIKE ?
            OR CAST(c.order_qty AS TEXT) LIKE ?
            OR CAST(c.unit_price AS TEXT) LIKE ?
            OR CAST(c.order_price AS TEXT) LIKE ?
            '''
            search_value = "%{}%".format(
                search_term.replace('*', '%').replace('?', '_'))
            cursor.execute(query, [search_value] * 8)
            results = cursor.fetchall()
            conn.close()
            return results
        except Exception as e:
            wx.MessageBox("Database error: {}".format(e), "Error", wx.OK | wx.ICON_ERROR)
            return []
