import os

settingsFileName = 'ki-search-options.json'

# Stamp stored on every imported component row (invisible, internal only).
# Bump it whenever the components table schema changes in a way that
# affects how rows are written.
SCHEMA_VERSION = 1

# (key, header, width, right-aligned?)
COLUMNS = [
    ('lcsc_part_number',        'LCSC Pn',      120, False),
    ('manufacture_part_number', 'Mfg Part Nr',  150, False),
    ('manufacturer',            'Manufacturer', 120, False),
    ('package',                 'Package',      100, False),
    ('description',             'Description',  400, False),
    ('order_qty',               'O-Qty',        70,  True),
    ('unit_price',              'UP($)',        70,  True),
    ('order_price',             'OP($)',        70,  True),
]

default_db_filename = 'components.db'

# Default database location relative to USER_DOCS
default_db_relpath = os.path.join('KiCAD', 'Gen', 'scripts', default_db_filename)
