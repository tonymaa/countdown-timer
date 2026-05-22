import time
import win32api
import win32con
import win32gui


def get_mouse_pos():
    """直接读取硬件驱动层的鼠标坐标"""
    return win32api.GetCursorPos()


if __name__ == "__main__":
    print("=== Windows 屏幕无感唤醒 (异步破卡死版) ===")
    print("提示：为你预留 5 秒钟，请立刻把手从鼠标键盘上拿开！")

    for i in range(5, 0, -1):
        print(f"{i}...")
        time.sleep(1)

    # 1. 记录初始坐标
    origin_pos = get_mouse_pos()
    print(f"【当前鼠标位置】: {origin_pos}")

    # 2. 【核心修改】：改用 PostMessage，打死也不允许卡死主线程！
    print("【1】正在异步通知显示器芯片切断背光...")
    win32gui.PostMessage(
        win32con.HWND_BROADCAST,
        win32con.WM_SYSCOMMAND,
        win32con.SC_MONITORPOWER,
        2,
    )

    # 3. 强制冷却，防止黑屏瞬间的手抖误判
    print("【2】指令已发出！主线程顺利逃脱卡死，进入 3 秒抗误触保护期...")
    time.sleep(3)

    # 刷新基准坐标
    origin_pos = get_mouse_pos()
    print("【3】保护期结束！正在死循环监控鼠标坐标变化...")
    print("👉 现在，请晃动鼠标来点亮屏幕...\n")

    # 4. 死循环驱动层检测
    while True:
        current_pos = get_mouse_pos()

        if current_pos != origin_pos:
            current_time = time.strftime("%H:%M:%S")
            print("----------------------------------------")
            print(f"【🎉 终极圆满成功！】成功捕捉到鼠标物理位移！")
            print(f"【原坐标】: {origin_pos} -> 【新坐标】: {current_pos}")
            print(f"【⏰ 唤醒时间】: {current_time}")
            print("----------------------------------------")
            break

        time.sleep(0.1)

    print("测试结束，5秒后退出...")
    time.sleep(5)