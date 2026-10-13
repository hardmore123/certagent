
import sys
import pythoncom
import win32com.client as win32

src, target = sys.argv[1], sys.argv[2]
pythoncom.CoInitialize()
word = None
doc = None
try:
    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = word.Documents.Open(src, ReadOnly=True, AddToRecentFiles=False)
    doc.SaveAs2(target, FileFormat=16)  # 16 = wdFormatXMLDocument (.docx)
finally:
    if doc is not None:
        try: doc.Close(False)
        except Exception: pass
    if word is not None:
        try: word.Quit()
        except Exception: pass
    pythoncom.CoUninitialize()
