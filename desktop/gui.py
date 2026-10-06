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

import qrcode
from .runtime import InstanceLock, Runtime, data_directory


class Window:
    def __init__(self, root, directory, runtime_factory=Runtime):
        self.root, self.directory = root, directory
        self.events = queue.Queue()
        self.runtime_factory = runtime_factory
        self.runtime = self.thread = None
        self.closing = False
        self.failed = False
        self.urls = {}
        root.title('Pose Parallax — サーバー')
        root.geometry('680x760'); root.minsize(620, 700)
        root.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(root, padding=22); body.pack(fill='both', expand=True)
        ttk.Label(body, text='POSE PARALLAX', font=('Segoe UI', 22, 'bold')).pack(anchor='w')
        self.status = tk.StringVar(value='起動準備中…')
        ttk.Label(body, textvariable=self.status, wraplength=620).pack(anchor='w', pady=12)
        self.url = tk.StringVar()
        ttk.Entry(body, textvariable=self.url, state='readonly').pack(fill='x')
        self.qr = ttk.Label(body, anchor='center'); self.qr.pack(pady=12)
        self.mode = tk.StringVar(value='tunnel')
        methods = ttk.Frame(body); methods.pack(pady=8)
        self.mode_buttons = []
        for label, value in [('インターネット（証明書不要）', 'tunnel'), ('会場LAN（証明書登録が必要）', 'lan')]:
            button = ttk.Radiobutton(methods, text=label, value=value, variable=self.mode)
            button.pack(side='left', padx=6); self.mode_buttons.append(button)
        self.qr_mode = tk.StringVar(value='url')
        self.qr_choices = choices = ttk.Frame(body)
        for label, value in [('初回の証明書設定', 'setup_url'), ('ゲーム参加', 'url')]:
            ttk.Radiobutton(choices, text=label, value=value, variable=self.qr_mode, command=self.update_qr).pack(side='left', padx=8)
        self.remote_buttons = []
        actions = ttk.Frame(body); actions.pack(pady=14)
        for label, command in [('管理画面を開く', self.open_admin), ('URLをコピー', self.copy_url),
                               ('証明書の設定手順', self.open_setup)]:
            button = ttk.Button(actions, text=label, command=command, state='disabled')
            button.pack(side='left', padx=3); self.remote_buttons.append(button)
        controls = ttk.Frame(body); controls.pack()
        self.start_button = ttk.Button(controls, text='サーバー起動', command=self.start)
        self.start_button.pack(side='left', padx=8)
        self.stop_button = ttk.Button(controls, text='サーバー停止', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        ttk.Button(body, text='管理者パスワードをコピー', command=self.copy_password).pack(pady=12)
        ttk.Button(body, text='保存フォルダー・ログを開く', command=self.open_folder).pack()
        self.instructions = tk.StringVar(value='QRを読み、名前を入力してカメラを許可すれば参加できます。\nPCとスマートフォンはプレイ中もインターネット接続が必要です。\n接続し直すとURLが変わります。新しいQRを案内してください。')
        ttk.Label(body, textvariable=self.instructions, wraplength=620, justify='left').pack(anchor='w', pady=14)
        self.fingerprint = tk.StringVar()
        ttk.Label(body, textvariable=self.fingerprint, wraplength=620, font=('Segoe UI', 8)).pack(anchor='w')
        root.after(100, self.poll)
        root.after(200, self.start)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.failed = False
        self.status.set('サーバーを起動しています…')
        for button in self.mode_buttons:
            button.configure(state='disabled')
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.runtime = self.runtime_factory(self.directory, lambda kind, value: self.events.put((kind, value)), mode=self.mode.get())
        self.thread = threading.Thread(target=self.runtime.run, name='pose-server')
        self.thread.start()

    def stop(self, confirm=True):
        if confirm and not messagebox.askokcancel('サーバー停止', 'プレイ中の接続が切れます。サーバーを停止しますか？', parent=self.root):
            return
        if self.runtime:
            self.runtime.stop()
        self.status.set('停止しています…')
        self.stop_button.configure(state='disabled')
        self.disable_links()

    def close(self):
        if self.thread and self.thread.is_alive():
            if not messagebox.askokcancel('終了', 'サーバーを停止してアプリを終了しますか？', parent=self.root):
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
                    if is_lan:
                        self.qr_choices.pack(before=self.remote_buttons[0].master, pady=4)
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
            messagebox.showinfo('管理者パスワード', 'クリップボードにコピーしました。管理画面へ貼り付けてください。', parent=self.root)
        except OSError:
            messagebox.showerror('管理者パスワード', 'サーバーの起動後にもう一度お試しください。', parent=self.root)

    def open_admin(self):
        if self.urls:
            webbrowser.open(self.urls['admin_url'])

    def open_setup(self):
        if self.urls:
            webbrowser.open(self.urls['setup_url'])

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
        messagebox.showerror('Pose Parallax', str(exc), parent=root)
        root.destroy(); return
    handler = RotatingFileHandler(directory / 'desktop.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s', force=True)
    try:
        Window(root, directory)
        root.mainloop()
    finally:
        lock.close()
        handler.close()
