"""Write the unlinked balance review list in Excel 97–2003 format."""


def write_unlinked_xls(path, candidates):
    import xlwt

    if len(candidates) > 65535:
        raise ValueError('The .xls format supports at most 65,535 data rows.')
    book = xlwt.Workbook(encoding='utf-8')
    sheet = book.add_sheet('Unlinked Names')
    header = xlwt.easyxf('font: bold on; pattern: pattern solid, fore_colour gray25;')
    for column, title in enumerate(('#', 'Spreadsheet name', 'Proposed employee', 'Link status', 'Source')):
        sheet.write(0, column, title, header)
    for column, width in enumerate((8, 42, 42, 48, 60)):
        sheet.col(column).width = width * 256
    sheet.set_panes_frozen(True)
    sheet.set_horz_split_pos(1)
    for row_number, candidate in enumerate(candidates, 1):
        sheet.write(row_number, 0, row_number)
        for column, value in enumerate(candidate, 1):
            sheet.write(row_number, column, str(value or ''))
    book.save(str(path))
