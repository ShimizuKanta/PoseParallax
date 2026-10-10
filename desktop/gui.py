"""Small native control window; camera/game UI remains in the browser."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser
from urllib.parse import urlsplit, urlunsplit

import qrcode
from .runtime import InstanceLock, Runtime, data_directory
from .i18n import LocalizedVar, Translator


class Window:
    def __init__(self, root, directory, runtime_factory=Runtime):
        self.root, self.directory = root, directory
        self.events = queue.Queue()
        self.runtime_factory = runtime_factory
        self.runtime = self.thread = None
        self.closing = False
        self.failed = False
        self.urls = {}
        self.translator = Translator(directory)
        self.text = self.translator.text
        root.title(self.text('Pose Parallax — サーバー'))
        root.geometry('680x660'); root.minsize(580, 620)
        root.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(root, padding=22); body.pack(fill='both', expand=True)
        top = ttk.Frame(body); top.pack(fill='x')
        ttk.Label(top, text='POSE PARALLAX', font=('Segoe UI', 22, 'bold')).pack(side='left')
        self.language = tk.StringVar(value='English' if self.translator.language == 'en' else '日本語')
        language = ttk.Combobox(top, textvariable=self.language, values=('日本語', 'English'), state='readonly', width=10)
        language.pack(side='right'); language.bind('<<ComboboxSelected>>', self.change_language)
        self.status = LocalizedVar(self.translator, '起動準備中…')
        ttk.Label(body, textvariable=self.status, wraplength=570).pack(anchor='w', pady=12)
        self.qr = ttk.Label(body, anchor='center'); self.qr.pack(pady=8)
        self.url = tk.StringVar()
        ttk.Entry(body, textvariable=self.url, state='readonly').pack(fill='x')
        self.qr_mode = tk.StringVar(value='url')
        self.qr_choices = choices = ttk.Frame(body)
        for label, value in [('初回の証明書設定', 'setup_url'), ('ゲーム参加', 'url')]:
            self.label(ttk.Radiobutton(choices, value=value, variable=self.qr_mode, command=self.update_qr), label).pack(side='left', padx=8)
        self.actions = actions = ttk.Frame(body); actions.pack(pady=12)
        self.remote_buttons = []
        for label, command in [('管理画面を開く', self.open_admin), ('URLをコピー', self.copy_url)]:
            button = self.label(ttk.Button(actions, command=command, state='disabled'), label)
            button.pack(side='left', padx=4); self.remote_buttons.append(button)
        self.label(ttk.Button(body, command=self.copy_password), '管理者パスワードをコピー').pack(pady=4)
        controls = ttk.Frame(body); controls.pack(pady=10)
        self.start_button = self.label(ttk.Button(controls, command=self.start), 'サーバー起動')
        self.start_button.pack(side='left', padx=6)
        self.stop_button = self.label(ttk.Button(controls, command=self.stop, state='disabled'), 'サーバー停止')
        self.stop_button.pack(side='left', padx=6)
        self.label(ttk.Button(controls, command=self.open_details), '詳細').pack(side='left', padx=6)
        self.quick_guide = LocalizedVar(self.translator, 'QRを読み、名前を入力してカメラを許可すれば参加できます。')
        ttk.Label(body, textvariable=self.quick_guide, wraplength=570).pack(anchor='w', pady=8)
        # The advanced window stays alive when closed; language changes do not restart anything.
        self.details = tk.Toplevel(root); self.details.withdraw()
        self.details.geometry(f'640x{min(650, root.winfo_screenheight() - 100)}')
        self.details.protocol('WM_DELETE_WINDOW', self.details.withdraw)
        canvas = tk.Canvas(self.details, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.details, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        advanced = ttk.Frame(canvas, padding=20)
        item = canvas.create_window((0, 0), window=advanced, anchor='nw')
        advanced.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        self.label(ttk.Label(advanced, font=('Segoe UI', 14, 'bold')), '接続方式').pack(anchor='w', pady=8)
        self.mode = tk.StringVar(value='tunnel')
        self.mode_buttons = []
        for label, value in [('インターネット（証明書不要）', 'tunnel'), ('会場LAN（証明書登録が必要）', 'lan')]:
            button = self.label(ttk.Radiobutton(advanced, value=value, variable=self.mode), label)
            button.pack(anchor='w', pady=5); self.mode_buttons.append(button)
        setup_button = self.label(ttk.Button(advanced, command=self.open_setup, state='disabled'), '証明書の設定手順')
        setup_button.pack(anchor='w', pady=12); self.remote_buttons.append(setup_button)
        self.instructions = LocalizedVar(self.translator, 'QRを読み、名前を入力してカメラを許可すれば参加できます。\nPCとスマートフォンはプレイ中もインターネット接続が必要です。\n接続し直すとURLが変わります。新しいQRを案内してください。')
        ttk.Label(advanced, textvariable=self.instructions, wraplength=560, justify='left').pack(anchor='w', pady=12)
        self.fingerprint = LocalizedVar(self.translator)
        ttk.Label(advanced, textvariable=self.fingerprint, wraplength=560, font=('Segoe UI', 9)).pack(anchor='w', pady=12)
        self.label(ttk.Button(advanced, command=self.open_folder), '保存フォルダー・ログを開く').pack(anchor='w', pady=12)
        self.label(ttk.Button(advanced, command=self.details.withdraw), '閉じる').pack(anchor='e', pady=12)
        root.after(100, self.poll)
        root.after(200, self.start)

    def label(self, widget, source):
        return self.translator.bind(widget, source)

    def change_language(self, event=None):
        self.translator.select('en' if self.language.get() == 'English' else 'ja')
        self.root.title(self.text('Pose Parallax — サーバー'))
        self.details.title(self.text('詳細'))

    def open_details(self):
        self.details.title(self.text('詳細'))
        self.details.deiconify(); self.details.lift()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.failed = False
        self.status.set('サーバーを起動しています…')
        for button in self.mode_buttons:
            button.configure(state='disabled')
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        # Capture the queue rather than this Window: a runtime -> notify ->
        # Window cycle can defer Tk finalizers to a later server thread.
        events = self.events
        self.runtime = self.runtime_factory(self.directory, lambda kind, value: events.put((kind, value)), mode=self.mode.get())
        self.thread = threading.Thread(target=self.runtime.run, name='pose-server')
        self.thread.start()

    def stop(self, confirm=True):
        if confirm and not messagebox.askokcancel(self.text('サーバー停止'), self.text('プレイ中の接続が切れます。サーバーを停止しますか？'), parent=self.root):
            return
        if self.runtime:
            self.runtime.stop()
        self.status.set('停止しています…')
        self.stop_button.configure(state='disabled')
        self.disable_links()

    def close(self):
        if self.thread and self.thread.is_alive():
            if not messagebox.askokcancel(self.text('終了'), self.text('サーバーを停止してアプリを終了しますか？'), parent=self.root):
                return
            self.closing = True
            self.stop(confirm=False)
        else:
            self.root.destroy()

    def disable_links(self):
        self.urls = {}
        self.url.set('')
        self.qr.configure(image='')
        self.fingerprint.set('')
        for button in self.remote_buttons:
            button.configure(state='disabled')

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'ready' and not self.runtime.stop_requested.is_set():
                    self.urls = value
                    self.status.set('稼働中 — このウィンドウを開いたままにしてください。')
                    is_lan = value['mode'] == 'lan'
                    self.qr_mode.set('setup_url' if is_lan else 'url')
                    self.quick_guide.set('PCとスマートフォンを同じLANに接続してください。' if is_lan else 'QRを読み、名前を入力してカメラを許可すれば参加できます。\nPCとスマートフォンはプレイ中もインターネット接続が必要です。')
                    if is_lan:
                        self.qr_choices.pack(before=self.actions, pady=4)
                        self.instructions.set('PCとスマートフォンを同じLANに接続してください。\n初回は各端末で証明書を登録します。Windowsのファイアウォールは\nプライベートネットワークでTCP 8000・8443の接続を許可してください。')
                    else:
                        self.qr_choices.pack_forget()
                        self.instructions.set('QRを読み、名前を入力してカメラを許可すれば参加できます。\nPCとスマートフォンはプレイ中もインターネット接続が必要です。\n接続し直すとURLが変わります。新しいQRを案内してください。')
                    self.fingerprint.set('会場CA SHA-256: ' + value['fingerprint'] if is_lan else '画面・表示名・姿勢の座標・結果の通信はCloudflareを経由します。\nカメラ映像は送信しません。Quick Tunnelは稼働保証のない試用サービスです。')
                    for button in self.remote_buttons[:2]:
                        button.configure(state='normal')
                    self.remote_buttons[2].configure(state='normal' if is_lan else 'disabled')
                    self.update_qr()
                elif kind == 'progress' and not self.runtime.stop_requested.is_set():
                    self.status.set(value)
                elif kind == 'error':
                    self.failed = True
                    self.status.set('起動・動作エラー: ' + value + '\n保存フォルダーの desktop.log を確認してください。')
                    self.disable_links()
                elif kind == 'stopped':
                    self.disable_links()
                    if not self.failed:
                        self.status.set('停止しました。')
        except queue.Empty:
            pass
        if self.thread and not self.thread.is_alive():
            if self.closing:
                self.root.destroy(); return
            self.start_button.configure(state='normal')
            for button in self.mode_buttons:
                button.configure(state='normal')
            self.stop_button.configure(state='disabled')
        self.root.after(100, self.poll)

    def update_qr(self):
        url = self.urls.get(self.qr_mode.get())
        if not url:
            return
        self.url.set(url)
        code = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
        code.add_data(url); code.make(fit=True)
        matrix = code.get_matrix()
        image = tk.PhotoImage(width=len(matrix), height=len(matrix))
        image.put(' '.join('{' + ' '.join('#101827' if cell else '#ffffff' for cell in row) + '}' for row in matrix))
        self.qr_image = image.zoom(max(1, 240 // len(matrix)))
        self.qr.configure(image=self.qr_image)

    def copy(self, value):
        self.root.clipboard_clear(); self.root.clipboard_append(value)

    def copy_url(self):
        self.copy(self.url.get())

    def copy_password(self):
        try:
            self.copy(os.environ.get('POSE_ADMIN_PASSWORD') or (self.directory / 'admin-password.txt').read_text().strip())
            messagebox.showinfo(self.text('管理者パスワード'), self.text('クリップボードにコピーしました。管理画面へ貼り付けてください。'), parent=self.root)
        except OSError:
            messagebox.showerror(self.text('管理者パスワード'), self.text('サーバーの起動後にもう一度お試しください。'), parent=self.root)

    def open_admin(self):
        if self.urls:
            webbrowser.open(self.urls['admin_url'] + '?lang=' + self.translator.language)

    def open_setup(self):
        if self.urls:
            if self.urls.get('setup_url'):
                url = urlsplit(self.urls['setup_url'])
                webbrowser.open(urlunsplit(url._replace(query='lang=' + self.translator.language)))

    def open_folder(self):
        if os.name == 'nt':
            os.startfile(self.directory)
        else:
            webbrowser.open(self.directory.as_uri())


def main():
    directory = data_directory()
    root = tk.Tk()
    try:
        lock = InstanceLock(directory)
    except (OSError, RuntimeError) as exc:
        messagebox.showerror('Pose Parallax', Translator(directory).text(str(exc)), parent=root)
        root.destroy(); return
    handler = RotatingFileHandler(directory / 'desktop.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s', force=True)
    try:
        Window(root, directory)
        root.mainloop()
    finally:
        lock.close()
        handler.close()
