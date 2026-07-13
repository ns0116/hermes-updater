import tkinter as tk
from hermes_updater.app import UpdaterApp
from hermes_updater.gui import UpdaterGUI


def test_gui_import_and_init(tmp_path):
    """GUIのインポートと初期化がエラーなく行えることをテスト。
    ヘッドレス環境（CIなど）でTclErrorが発生した場合はスキップする。
    """
    app = UpdaterApp(base_dir=tmp_path)
    try:
        root = tk.Tk()
        root.withdraw()
        gui = UpdaterGUI(root, app)
        assert gui is not None
        root.destroy()
    except tk.TclError:
        # GUI非対応の環境ではテストを正常終了とする
        pass
