"""Small native QR window. Network and SQLite work stay off the UI thread."""
import io
import os
import queue
import time
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import webbrowser
from PIL import Image, ImageTk
from .online import QQSession, ProtocolError
from .trial import run_trial
from .statistics import archive_statistics, format_statistics


def main():
    os.umask(0o077)
    window = tk.Tk()
    window.title('空间记忆 · 实时进度 v0.3')
    window.geometry('680x820')
    messages = queue.Queue()
    stop = threading.Event()
    active = False
    closing = False
    logged_in = threading.Event()
    output = None
    stopping_since = None
    ttk.Label(window, text='QQ 空间恢复与备份', font=('', 21)).pack(pady=16)
    ttk.Label(window, text='请用手机 QQ 扫码，并在手机上确认登录。\n登录后自动进行有限历史探测，并生成本地 HTML。', justify='center').pack()
    image_label = ttk.Label(window, text='点击下方按钮获取二维码', anchor='center')
    image_label.pack(pady=12, fill='both', expand=True)
    status = tk.StringVar(value='凭证仅保留在本次进程内；退出后清除。')
    ttk.Label(window, textvariable=status, wraplength=510, justify='center').pack(padx=20, pady=12)
    media_status = tk.StringVar(value='图片队列：等待登录（默认 6 路并发）')
    ttk.Label(window, textvariable=media_status, wraplength=550).pack(pady=5)
    counters = tk.StringVar(value='说说 0 条 · 照片 0 张（等待登录）')
    ttk.Label(window, textvariable=counters, wraplength=640, justify='left').pack(pady=6)
    batch_status = tk.StringVar(value='最近一批：等待采集')
    ttk.Label(window, textvariable=batch_status, wraplength=640).pack(pady=3)
    stop_status = tk.StringVar(value='')
    ttk.Label(window, textvariable=stop_status, wraplength=640).pack()
    settings = ttk.Frame(window)
    settings.pack(pady=5)
    ttk.Label(settings, text='图片并发数（1–12）：').pack(side='left')
    concurrency = tk.IntVar(value=6)
    concurrency_input = ttk.Spinbox(settings, from_=1, to=12, textvariable=concurrency, width=4)
    concurrency_input.pack(side='left')
    ttk.Label(window, text='文字采集最多 10 分钟 / 120 次请求；图片边采边下，最多 300 张。\n图片总时间预算为登录后 20 分钟。停止仍导出已有成果。', justify='center').pack(pady=5)
    buttons = ttk.Frame(window)
    buttons.pack(pady=15)
    root = Path(__file__).resolve().parent.parent / 'local-data'
    def notify(kind, value):
        messages.put((kind, value))
    def worker(media_workers):
        qq = QQSession()
        monitor_stop = threading.Event()
        monitor_thread = None
        def monitor(path):
            while not monitor_stop.is_set():
                try:
                    notify('stats', archive_statistics(path))
                except (OSError, sqlite3.Error, ValueError):
                    pass
                monitor_stop.wait(1)

        try:
            while not stop.is_set():
                notify('status', '正在获取 QQ 登录二维码…')
                notify('qr', qq.qr())
                while not stop.wait(2):
                    state = qq.poll()
                    if state == '65':
                        notify('status', '二维码已过期，正在自动刷新…')
                        break
                    if state == 'ok':
                        logged_in.set()
                        notify('logged_in', None)
                        monitor_thread = threading.Thread(target=monitor, args=(root / qq.uin / 'archive.sqlite3',), daemon=True)
                        monitor_thread.start()
                        path, summary = run_trial(qq, root, stop, notify, media_workers=media_workers)
                        notify('done', (path, summary))
                        return
                    notify('status', '已扫码，请在手机 QQ 上确认登录' if state in ('67', '68') else '请用手机 QQ 扫描上方二维码')
        except Exception as exc:
            # Never display raw network exceptions: they can contain tokens in URLs.
            notify('error', str(exc) if isinstance(exc, ProtocolError) else f'请求失败：{type(exc).__name__}。请检查网络后重试。')
        finally:
            monitor_stop.set()
            if monitor_thread:
                monitor_thread.join(timeout=2)
            qq.close()
            notify('idle', None)
    def start():
        nonlocal active, stopping_since
        if active:
            return
        try:
            selected_workers = concurrency.get()
            if not 1 <= selected_workers <= 12:
                raise ValueError()
        except (ValueError, tk.TclError):
            status.set('请输入 1 到 12 之间的并发数')
            return
        concurrency_input.configure(state='disabled')
        stopping_since = None
        stop_status.set('')
        stop_button.configure(state='normal')
        stop.clear()
        logged_in.clear()
        active = True
        login_button.configure(state='disabled')
        threading.Thread(target=worker, args=(selected_workers,), daemon=False).start()
    def cancel():
        nonlocal stopping_since
        if not active or stop.is_set():
            return
        stopping_since = time.monotonic()
        stop_button.configure(state='disabled')
        stop.set()
        image_label.configure(image='', text='正在停止网络采集\n准备导出已有成果…')
        status.set('正在停止，请等待在途请求结束并导出已有成果…')
    def close():
        nonlocal closing
        if active:
            closing = True
            cancel()
        else:
            window.destroy()
    login_button = ttk.Button(buttons, text='获取 QQ 登录二维码 / 重试', command=start)
    login_button.pack(side='left', padx=4)
    stop_button = ttk.Button(buttons, text='停止并导出', command=cancel)
    stop_button.pack(side='left', padx=4)
    open_button = ttk.Button(buttons, text='打开导出结果', command=lambda: webbrowser.open(output.as_uri()) if output else None, state='disabled')
    open_button.pack(side='left', padx=4)
    def drain():
        nonlocal active, output, stopping_since
        try:
            while True:
                kind, value = messages.get_nowait()
                if kind == 'status':
                    status.set(value)
                elif kind == 'stats':
                    counters.set(format_statistics(value))
                elif kind == 'batch':
                    batch_status.set(value)
                elif kind == 'media':
                    media_status.set(value)
                elif kind == 'qr':
                    picture = Image.open(io.BytesIO(value)).convert('RGB').resize((250, 250))
                    image_label.image = ImageTk.PhotoImage(picture)
                    image_label.configure(image=image_label.image, text='')
                elif kind == 'logged_in':
                    image_label.configure(image='', text='QQ 登录成功\n正在后台采集…')
                    image_label.image = None
                elif kind == 'done':
                    output, report = value
                    stopping_since = None
                    stop_status.set('已完成保存和导出')
                    status.set(f'已导出 {report["exported_posts"]} 条说说、{report["exported_photos"]} 张照片。' + ('部分步骤未完成，请查看 trial-report.json。' if report['issues'] else '试跑流程已结束。'))
                    image_label.configure(image='', text='成果已保存，可以打开 HTML 查看。')
                    open_button.configure(state='normal')
                    webbrowser.open(output.as_uri())
                elif kind == 'error':
                    status.set(value)
                    image_label.configure(image='', text='连接未完成，可重试')
                elif kind == 'idle':
                    active = False
                    stopping_since = None
                    stop_button.configure(state='disabled')
                    login_button.configure(state='normal')
                    concurrency_input.configure(state='normal')
                    if closing:
                        window.destroy()
                        return
        except queue.Empty:
            pass
        if stopping_since is not None:
            stop_status.set(f'停止收尾已等待 {int(time.monotonic() - stopping_since)} 秒；具体步骤见上方进度')
        window.after(150, drain)
    window.protocol('WM_DELETE_WINDOW', close)
    drain()
    window.after(400, start)
    window.mainloop()


if __name__ == '__main__':
    main()
