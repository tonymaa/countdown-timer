import json
import os
from tkinter import messagebox, colorchooser, Scale, Frame, YES, BOTH
import tkinter.font as tkFont
import random
import webbrowser
import datetime
import schedule
import time
import tkinter as tk
import threading
import pystray
from PIL import Image, ImageTk, ImageFont
import win32api
import win32con
import win32gui
import subprocess

class App:
    def __init__(self):
        self.config = self.read_config()
        self.window_width = 140
        self.window_height = 27
        self.init_pos()
        self.init_url()
        self.init_alpha()
        # 设置目标时间
        self.init_timer_target_time()
        self.is_show_timer_label = True
        self.is_able_move = False
        # 上班倒计时相关
        self.work_countdown_enabled = self.config.get("work_countdown_enabled", False)
        self.work_countdown_end_time = None
        self.work_countdown_active = False
        self._work_browser_opened = False
        self._work_notified = False
        # 恢复未完成的倒计时
        saved_end = self.config.get("work_countdown_end_time")
        if saved_end:
            end_dt = datetime.datetime.fromisoformat(saved_end)
            if end_dt > datetime.datetime.now():
                self.work_countdown_end_time = end_dt
                self.work_countdown_active = True
        self.run_app()

    def init_pos(self):
        self.window_x = self.config.get("window_x")
        self.window_y = self.config.get("window_y")
        if self.window_x is None or self.window_y is None:
            self.window_x = self.get_default_config().get("window_x")
            self.window_y = self.get_default_config().get("window_y")
        self.config["window_x"] = self.window_x
        self.config["window_y"] = self.window_y

    def init_url(self):
        self.url = self.config.get("url")
        if self.url is None:
            self.url = "https://intranet.toppanecquaria.com/sop/workdesk/login.jsp"
        self.config["url"] = self.url

    def init_alpha(self):
        self.alpha = self.config.get("alpha")
        if self.alpha is None:
            self.alpha = "1"
        self.config["alpha"] = self.alpha

    def init_timer_target_time(self):
        try:
            hour = int(self.config.get("hour"))
            minute = int(self.config.get("minute"))
            second = int(self.config.get("second"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
                self.target_time = datetime.time(hour=self.get_default_config().get("hour")
                                                 , minute=self.get_default_config().get("minute")
                                                 , second=self.get_default_config().get("second"))
                return
            self.target_time = datetime.time(hour=hour, minute=minute, second=second)
        except ValueError:
            self.target_time = datetime.time(hour=self.get_default_config().get("hour")
                     , minute=self.get_default_config().get("minute")
                     , second=self.get_default_config().get("second"))

    def get_default_config(self):
        return {
            "url": "https://intranet.toppanecquaria.com/sop/workdesk/login.jsp",
            "hour": 17,
            "minute": 40,
            "second": 0,
            "color": "#1abc9c",
            "alpha": 1,
            "window_y": 0,
            "window_x": 0,
        }

    def reset_default_config(self):
        config = self.get_default_config()
        self.save_config(config)
        return config

    def read_config(self):
        if not os.path.exists("config.cof"): self.reset_default_config()
        with open("config.cof", mode="r") as f:
            return json.load(f)

    def save_config(self, config):
        with open("config.cof", mode="w") as f:
            json.dump(config, f)

    def run_app(self):
        color = self.config.get("color")
        if color is None:
            color = random.sample(
                ["#1abc9c", "#3498db", "#9b59b6", "#34495e", "#e74c3c", "#7bed9f", "#57606f", "#ff4757", "#c0392b",
                 "#22a6b3", "#7ed6df", "#95afc0", "#9aecdb"], 1)[0]
        self.reset_timer_font_color(color)
        self.create_window()

    def reset_timer_font_color(self, color):
        self.timer_font_color = color
        self.timer_bg_color = color[:-1] + "1"

    def choose_color(self):
        r = colorchooser.askcolor(title='颜色选择器')[-1]
        if r is not None:
            self.reset_timer_font_color(r)
            self.timer_label.configure(fg=self.timer_font_color)
            self.timer_label.configure(bg=self.timer_bg_color)
            self.window.attributes("-transparentcolor", self.timer_bg_color)
            self.config["color"] = r
            self.save_config(self.config)

    # 定义要执行的任务
    def open_browser(self):
        # 打开浏览器并进入指定网站
        webbrowser.open(self.url)

    def adjust_alpha(self):
        def save_alpha():
            self.config["alpha"] = self.alpha
            self.save_config(self.config)
            top.destroy()
        top = tk.Toplevel(self.window)
        top.title("设置透明度")
        top.geometry("200x72")
        val = tk.IntVar()
        scale = Scale(top, from_=1, to=100
                      , resolution=1
                      , orient=tk.HORIZONTAL
                      , variable=val
                      ,command=self.get_scale_value
                      ,length=180)
        val.set(int(self.alpha * 100))
        save_button = tk.Button(top, text="保存", command=save_alpha)
        scale.pack()
        save_button.pack()
        # top.mainloop()

    def get_scale_value(self, value):
        print(f"change to {value}")
        self.alpha = int(value) / 100
        self.window.attributes('-alpha', self.alpha)

    # 定义GUI界面
    def create_window(self):
        self.window = tk.Tk()
        self.window.overrideredirect(True)
        self.window.geometry(f"{self.window_width}x{self.window_height}+{self.window_x}+{self.window_y}")
        self.window.attributes("-transparentcolor", self.timer_bg_color)
        self.window.attributes('-alpha', self.alpha)
        self.window.attributes("-toolwindow", 2)  # 去掉窗口最大化最小化按钮，只保留关闭
        self.window.resizable(False, False) #横纵均不允许调整
        self.window.wm_attributes ('-topmost',1)
        self.label_time = tk.StringVar()

        # tk_font = tkFont.Font(family="Times", size=16)
        self.move_label = tk.Label(self.window, text="Move", bg=self.timer_bg_color
                                   ,width="8",justify="right", fg=self.timer_bg_color)
        self.move_label.pack(side="right", fill="y")
        self.timer_label = tk.Label(self.window, textvariable=self.label_time, text="11:00", fg=self.timer_font_color
                                    , font=self.get_font(),
                                    justify="center", bg=self.timer_bg_color) # font=("Times 20 bold")
        self.timer_label.pack(fill="x")
        # 将窗口添加到托盘中

        self.menu = pystray.Menu(
            pystray.MenuItem("打开浏览器", self.open_browser),
            pystray.MenuItem("显示计时器", action=self.display_timer, checked=lambda e: self.is_show_timer_label),
            pystray.MenuItem("切换模式", pystray.Menu(
                pystray.MenuItem("目标时间倒计时", action=self.switch_to_target_mode, checked=lambda e: not self.work_countdown_enabled),
                pystray.MenuItem("上班倒计时", action=self.switch_to_work_mode, checked=lambda e: self.work_countdown_enabled),
            )),
            pystray.MenuItem("修改计时器", action=self.set_target_time, visible=lambda e: not self.work_countdown_enabled),
            pystray.MenuItem("立即倒计时9小时", action=self.reset_work_countdown, visible=lambda e: self.work_countdown_enabled),
            pystray.MenuItem("选择字体颜色", action=self.choose_color),
            pystray.MenuItem("调整字体透明度", action=self.adjust_alpha),
            pystray.MenuItem("调整窗口位置", action=self.move_time_label, checked=lambda e: self.is_able_move),
            pystray.MenuItem("初始化窗口位置", action=self.reset_window_pos),
            pystray.MenuItem("退出", self.stop)
        )
        image = Image.open("icon.png")
        self.menu.icon = ImageTk.PhotoImage(image)
        self.tray_icon = pystray.Icon("打开浏览器", image, menu=self.menu)

        self.start_schedule()
        self.start_timer()
        self.start_tary()
        self.frame = DraggableWindow(self.window, self.move_label, on_move_stop=self.on_move_stop)
        self.frame.pack(fill=BOTH, expand=YES)
        self.window.mainloop()

    def display_timer(self):
        self.is_show_timer_label = not self.is_show_timer_label
        if self.is_show_timer_label:
            self.timer_label.configure(fg=self.timer_font_color)
        else:
            self.timer_label.configure(fg=self.timer_bg_color)

    def move_time_label(self):
        self.is_able_move = not self.is_able_move
        if self.is_able_move:
            self.frame.bind()
            self.move_label.configure(fg=self.timer_font_color, bg="#ffffff")
        else:
            self.move_label.configure(fg=self.timer_bg_color, bg=self.timer_bg_color)



    def start_tary(self):
        thread = threading.Thread(target=self.tray_icon.run)
        thread.setDaemon(True)
        thread.start()

    def start_timer(self):
        thread = threading.Thread(target=lambda: self.changeText())
        thread.setDaemon(True)
        thread.start()

    def changeText(self):
        while True:
            # 上班倒计时优先显示
            if self.work_countdown_active and self.work_countdown_end_time:
                remaining = (self.work_countdown_end_time - datetime.datetime.now()).total_seconds()
                if remaining <= 0:
                    self.label_time.set("下班!")
                    self.work_countdown_active = False
                    self.work_countdown_end_time = None
                    self._save_work_countdown_state()
                    win32gui.PostMessage(win32con.HWND_BROADCAST, win32con.WM_SYSCOMMAND, win32con.SC_MONITORPOWER, 2)
                elif remaining <= 60 and not getattr(self, '_work_notified', False):
                    self._work_notified = True
                    self._show_toast("下班了", "准备收拾收拾，下班打卡！")
                elif remaining <= 1800 and not getattr(self, '_work_browser_opened', False):
                    self._work_browser_opened = True
                    self.open_browser()
                else:
                    hour = int(remaining // 3600)
                    min = int((remaining % 3600) // 60)
                    sec = int(remaining % 60)
                    self.label_time.set(f"{hour}:{min}:{sec}")
                time.sleep(1)
                continue
            end_time = self.target_time
            end_time = (end_time.hour * 60 + end_time.minute) * 60 + end_time.second
            cur_time = datetime.datetime.now().time()
            cur_time = (cur_time.hour * 60 + cur_time.minute) * 60 + cur_time.second
            seconds = end_time - cur_time
            if seconds < 0:
                seconds += 86400
            if seconds <= 60 and not getattr(self, '_target_notified', False):
                self._target_notified = True
                self._show_toast("下班了", "准备收拾收拾，下班打卡！")
            if seconds <= 0:
                win32gui.PostMessage(win32con.HWND_BROADCAST, win32con.WM_SYSCOMMAND, win32con.SC_MONITORPOWER, 2)
                self._target_notified = False
            hour = int(seconds // 60 // 60)
            min = int(seconds // 60 % 60)
            sec = int(seconds % 60)
            self.label_time.set(f"{hour}:{min}:{sec}")
            time.sleep(1)

    # 开始定时任务
    def start_schedule(self):
        self.set_one_new_schedule()
        thread = threading.Thread(target=self.run_task)
        thread.setDaemon(True)
        thread.start()

    def set_one_new_schedule(self):
        schedule.clear()
        early_time = (datetime.datetime.combine(datetime.date.today(), self.target_time) - datetime.timedelta(minutes=30)).time()
        schedule.every().day.at(str(early_time)).do(self.open_browser)

    def get_font(self):
        # # 从字体文件加载字体
        listdir = os.listdir()
        for font in listdir:
            # font_path = "DS-DIGIB-2.ttf"  # 替换为您的字体文件路径
            if not font.endswith(".ttf"): continue
            digit_font = ImageFont.truetype(font, 20)
            if digit_font is not None and digit_font.getname()[0] is not None:
                return tkFont.Font(family=digit_font.getname()[0], size=16)
        return tkFont.Font(family="Times", size=16)

    # 停止定时任务
    def stop(self):
        self.window.quit()
        os._exit(0)

    # 运行任务
    def run_task(self):
        while True:
            schedule.run_pending()
            time.sleep(1)

    def set_target_time(self):
        top = tk.Toplevel(self.window)
        top.title("设置定时器")
        top.geometry("200x50")
        hour_var = tk.StringVar(value=str(self.target_time.hour))
        minute_var = tk.StringVar(value=str(self.target_time.minute))
        second_var = tk.StringVar(value=str(self.target_time.second))

        tk.Label(top, text="小时").grid(row=0, column=0)
        tk.Label(top, text=" 分钟").grid(row=0, column=2)
        tk.Label(top, text=" 秒数").grid(row=0, column=4)
        hour_input = tk.Entry(top, width=3, validate='key', textvariable=hour_var)
        minute_input = tk.Entry(top, width=3, validate='key', textvariable=minute_var)
        second_input = tk.Entry(top, width=3, validate='key', textvariable=second_var)
        hour_input.grid(row=0, column=1)
        minute_input.grid(row=0, column=3)
        second_input.grid(row=0, column=5)

        def save_time():
            try:
                hour = int(hour_var.get())
                minute = int(minute_var.get())
                second = int(second_var.get())
                if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
                    tk.messagebox.showerror("错误", "时间输入错误")
                    return
                self.target_time = datetime.time(hour=hour, minute=minute, second=second)
                self.set_one_new_schedule()
                self.config["hour"] = hour
                self.config["minute"] = minute
                self.config["second"] = second
                self.save_config(self.config)
            except ValueError:
                tk.messagebox.showerror("错误", "时间输入错误")
            top.destroy()

        save_button = tk.Button(top, text="保存", command=save_time)
        save_button.grid(row=2, column=2, columnspan=3)
        # top.mainloop()

    def on_move_stop(self):
        self.config["window_x"] = self.window.winfo_x()
        self.config["window_y"] = self.window.winfo_y()
        self.save_config(self.config)

    def reset_window_pos(self):
        self.window.geometry(f"+{0}+{0}")
        self.on_move_stop()

    def _save_work_countdown_state(self):
        self.config["work_countdown_enabled"] = self.work_countdown_enabled
        if self.work_countdown_active and self.work_countdown_end_time:
            self.config["work_countdown_end_time"] = self.work_countdown_end_time.isoformat()
        else:
            self.config["work_countdown_end_time"] = None
        self.save_config(self.config)

    def switch_to_target_mode(self):
        self.work_countdown_enabled = False
        self.work_countdown_active = False
        self.work_countdown_end_time = None
        schedule.clear("work_screen_off")
        self._save_work_countdown_state()

    def switch_to_work_mode(self):
        if self.work_countdown_enabled:
            return
        self.work_countdown_enabled = True
        self.work_countdown_active = False
        self.work_countdown_end_time = None
        self._schedule_work_screen_off()
        self._save_work_countdown_state()

    def reset_work_countdown(self):
        self.work_countdown_enabled = True
        self.work_countdown_end_time = datetime.datetime.now() + datetime.timedelta(hours=9)
        self.work_countdown_active = True
        self._work_browser_opened = False
        self._work_notified = False
        self._save_work_countdown_state()

    def _schedule_work_screen_off(self):
        schedule.clear("work_screen_off")
        schedule.every().day.at("08:00").do(self._work_screen_off_and_monitor).tag("work_screen_off")

    def _work_screen_off_and_monitor(self):
        if not self.work_countdown_enabled:
            return
        if self.work_countdown_active:
            return
        # 灭屏
        win32gui.PostMessage(win32con.HWND_BROADCAST, win32con.WM_SYSCOMMAND, win32con.SC_MONITORPOWER, 2)
        # 启动监听线程
        thread = threading.Thread(target=self._monitor_screen_wake, daemon=True)
        thread.start()

    def _monitor_screen_wake(self):
        origin_pos = win32api.GetCursorPos()
        # 等待3秒抗误触
        time.sleep(3)
        origin_pos = win32api.GetCursorPos()
        # 死循环检测鼠标移动
        while self.work_countdown_enabled and not self.work_countdown_active:
            current_pos = win32api.GetCursorPos()
            if current_pos != origin_pos:
                wake_time = datetime.datetime.now()
                self.work_countdown_end_time = wake_time + datetime.timedelta(hours=9)
                self.work_countdown_active = True
                self._work_browser_opened = False
                self._work_notified = False
                break
            time.sleep(0.1)

    def _show_toast(self, title, msg):
        ps_script = (
            f'Add-Type -AssemblyName System.Windows.Forms;'
            f'$n=New-Object System.Windows.Forms.NotifyIcon;'
            f'$n.Icon=[System.Drawing.SystemIcons]::Information;'
            f'$n.BalloonTipTitle="{title}";'
            f'$n.BalloonTipText="{msg}";'
            f'$n.Visible=$true;'
            f'$n.ShowBalloonTip(5000);'
            f'Start-Sleep -Seconds 6;'
            f'$n.Dispose()'
        )
        subprocess.Popen(
            ['powershell', '-WindowStyle', 'Hidden', '-Command', ps_script],
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )

class DraggableWindow(Frame):
    def __init__(self, master=None, child_label=None, on_move_stop=None):
        Frame.__init__(self, master)
        self.child_label = child_label
        self.on_move_stop =on_move_stop
        self._offset_x = 0
        self._offset_y = 0

    def bind(self):
        self.child_label.bind("<ButtonPress-1>", self.start_move)
        self.child_label.bind("<ButtonRelease-1>", self.stop_move)
        self.child_label.bind("<B1-Motion>", self.on_move)

    def unbind(self):
        self.child_label.unbind("<ButtonPress-1>")
        self.child_label.unbind("<ButtonRelease-1>")
        self.child_label.unbind("<B1-Motion>")

    def start_move(self, event):
        self._offset_x = event.x
        self._offset_y = event.y


    def stop_move(self, event):
        self.on_move_stop()
        self._offset_x = 0
        self._offset_y = 0

    def on_move(self, event):
        x = self.master.winfo_x() + event.x - self._offset_x
        y = self.master.winfo_y() + event.y - self._offset_y
        self.master.geometry("+{}+{}".format(x, y))
        self.update_idletasks()

# 运行GUI界面
app = App()
