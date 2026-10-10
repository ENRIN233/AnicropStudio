import sys
print("A: python 启动了")

try:
    from ui import MainWindow
    print("B: ui 导入成功")
except Exception as e:
    import traceback
    traceback.print_exc()
    print("B 失败:", e)
    sys.exit()

try:
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    print("C: QApplication 成功")

    window = MainWindow()
    print("D: MainWindow 成功")

    window.show()
    print("E: window.show() 成功")

    sys.exit(app.exec())
except Exception as e:
    import traceback
    traceback.print_exc()
    print("D/E 失败:", e)