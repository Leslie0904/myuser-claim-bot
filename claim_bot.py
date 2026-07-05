#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网页活动道具抢领示例工具（可打包为 exe）
功能：
- 可配置 URL、Method、Headers、Form key=value 列表 或 Raw Body(JSON/text)
- 定时开始（指定开始时间），间隔重试（秒）
- 可设置重试次数/无限重试、遇到“成功关键词”停止、代理支持、请求头自定义、保存/载入配置、日志显示与导出
- 仅作技术演示，请遵守目标站点的使用条款和法律法规
"""
import PySimpleGUI as sg
import requests
import threading
import time
import json
import os
from datetime import datetime, timedelta

PROFILES_DIR = "profiles"
os.makedirs(PROFILES_DIR, exist_ok=True)

def parse_kv_lines(text):
    """
    将多行 key=value 文本解析为 dict
    支持空行跳过，值可包含 =
    """
    d = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            d[k.strip()] = v.strip()
        else:
            # 单行键名无值，设为空字符串
            d[line] = ""
    return d

def load_profile(fname):
    try:
        with open(fname, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        sg.popup_error("载入配置失败", e)
        return None

def save_profile(fname, cfg):
    try:
        with open(fname, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        sg.popup_error("保存配置失败", e)
        return False

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 后台工作线程
def worker_thread(config, window):
    """
    config: dict，window: sg.Window，用 window.write_event_value 发送事件回主线程
    事件:
      - ("LOG", text)
      - ("DONE", result_dict)
    """
    session = requests.Session()
    # 代理配置（可为空）
    proxy = config.get("proxy", "").strip()
    if proxy:
        # 例如 http://127.0.0.1:1080
        session.proxies.update({"http": proxy, "https": proxy})

    headers_text = config.get("headers", "").strip()
    headers = {}
    if headers_text:
        # 支持 JSON 或 key:value per line
        try:
            headers = json.loads(headers_text)
            if not isinstance(headers, dict):
                headers = {}
        except Exception:
            for line in headers_text.splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    headers[k.strip()] = v.strip()

    method = config.get("method", "POST").upper()
    url = config.get("url", "").strip()
    if not url:
        window.write_event_value("LOG", f"[{now_str()}] 错误：未指定 URL")
        window.write_event_value("DONE", {"stopped": True})
        return

    content_type = config.get("content_type", "form")
    form_kv = config.get("form_kv", "").strip()
    raw_body = config.get("raw_body", "")
    attempts = int(config.get("attempts", 0))  # 0 = 无限
    interval = float(config.get("interval", 1.0))
    success_keyword = config.get("success_keyword", "").strip()
    stop_on_success = bool(config.get("stop_on_success", True))

    # 计算延时启动
    start_time_str = config.get("start_time", "").strip()
    if start_time_str:
        try:
            start_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            delay = (start_dt - datetime.now()).total_seconds()
            if delay > 0:
                window.write_event_value("LOG", f"[{now_str()}] 等待定时开始：{start_time_str}（{int(delay)}s）")
                # 可以在这里定期检查是否被取消：窗体会通过设置全局变量或事件来停止线程
                # 简单实现：睡眠小片段并检查 stop flag
                slept = 0.0
                while slept < delay:
                    # 检查停止请求
                    if window.user_stop_flag:
                        window.write_event_value("LOG", f"[{now_str()}] 已取消（在定时开始前）")
                        window.write_event_value("DONE", {"stopped": True})
                        return
                    time.sleep(min(1.0, delay - slept))
                    slept += 1.0
        except Exception:
            window.write_event_value("LOG", f"[{now_str()}] 警告：无法解析开始时间，立即开始")

    attempt_no = 0
    success = False

    while True:
        if window.user_stop_flag:
            window.write_event_value("LOG", f"[{now_str()}] 已人工停止")
            break
        if attempts > 0 and attempt_no >= attempts:
            window.write_event_value("LOG", f"[{now_str()}] 达到最大重试次数：{attempts}")
            break

        attempt_no += 1
        timestamp = now_str()
        window.write_event_value("LOG", f"[{timestamp}] 第 {attempt_no} 次请求：{method} {url}")

        # 构建 body/params
        req_kwargs = {"headers": headers, "timeout": 15}
        if method in ("GET", "DELETE"):
            # GET 参数放在 params（从 form_kv 或 raw JSON 的 key-value）
            if form_kv:
                params = parse_kv_lines(form_kv)
                req_kwargs["params"] = params
            elif raw_body:
                # 如果 raw_body 是 json 并且是 dict，则当 params
                try:
                    j = json.loads(raw_body)
                    if isinstance(j, dict):
                        req_kwargs["params"] = j
                except Exception:
                    pass
        else:
            # POST/PUT 等
            if content_type == "json":
                # 优先 raw_body（应为 JSON 文本）
                body = raw_body.strip()
                if not body and form_kv:
                    body = json.dumps(parse_kv_lines(form_kv))
                try:
                    req_kwargs["json"] = json.loads(body) if body else {}
                except Exception:
                    # 非严格 JSON，发送 raw text
                    req_kwargs["data"] = body
                    headers.setdefault("Content-Type", "application/json")
            else:
                # form 表单或 x-www-form-urlencoded
                if form_kv:
                    req_kwargs["data"] = parse_kv_lines(form_kv)
                elif raw_body:
                    req_kwargs["data"] = raw_body
                # headers content-type 可由用户提供

        # 发起请求
        resp = None
        try:
            if method == "GET":
                resp = session.get(url, **req_kwargs)
            elif method == "POST":
                resp = session.post(url, **req_kwargs)
            elif method == "PUT":
                resp = session.put(url, **req_kwargs)
            elif method == "DELETE":
                resp = session.delete(url, **req_kwargs)
            else:
                resp = session.request(method, url, **req_kwargs)

            window.write_event_value("LOG", f"[{now_str()}] 返回状态：{resp.status_code}，长度：{len(resp.text or '')}")
            matched = False
            if success_keyword:
                if success_keyword in (resp.text or ""):
                    matched = True
                    window.write_event_value("LOG", f"[{now_str()}] 成功关键词匹配：{success_keyword}")
            else:
                # 若没有关键词，默认 200 视为成功
                if resp.status_code == 200:
                    matched = True
            if matched:
                success = True
                window.write_event_value("LOG", f"[{now_str()}] 识别为成功（停止后续重试）")
                # 保存或回写结果
                window.write_event_value("DONE", {"stopped": False, "success": True, "attempts": attempt_no, "status_code": resp.status_code, "response": resp.text})
                if stop_on_success:
                    return
        except requests.RequestException as e:
            window.write_event_value("LOG", f"[{now_str()}] 请求异常：{e}")
        except Exception as e:
            window.write_event_value("LOG", f"[{now_str()}] 未知错误：{e}")

        # 间隔等待（可以被外部 stop）
        slept = 0.0
        while slept < interval:
            if window.user_stop_flag:
                window.write_event_value("LOG", f"[{now_str()}] 已人工停止（间隔等待中）")
                window.write_event_value("DONE", {"stopped": True})
                return
            to_sleep = min(0.5, interval - slept)
            time.sleep(to_sleep)
            slept += to_sleep

    # 退出循环，发送 DONE
    window.write_event_value("DONE", {"stopped": True, "success": success, "attempts": attempt_no})

# GUI 部分
def build_window():
    sg.theme("DefaultNoMoreNagging")
    layout = [
        [sg.Text("目标 URL：", size=(12,1)), sg.Input(key="-URL-", size=(60,1))],
        [sg.Text("Method：", size=(12,1)), sg.Combo(["GET","POST","PUT","DELETE","OTHER"], default_value="POST", key="-METHOD-"),
         sg.Text("Content："), sg.Combo(["form","json"], default_value="form", key="-CTYPE-")],
        [sg.Text("请求头（JSON 或 每行 Key: Value）：")],
        [sg.Multiline(key="-HEADERS-", size=(80,4))],
        [sg.Text("表单字段（每行 key=value） 或 留空使用 Raw Body：")],
        [sg.Multiline(key="-FORMKV-", size=(80,6))],
        [sg.Text("Raw Body（优先）:")],
        [sg.Multiline(key="-RAWBODY-", size=(80,6))],
        [sg.Text("成功识别关键词（response 中包含即视为成功，留空则以 HTTP 200 判断）：")],
        [sg.Input(key="-SUCCESSKEY-", size=(60,1))],
        [sg.Text("代理（可选，例如 http://127.0.0.1:1080）：", size=(30,1)), sg.Input(key="-PROXY-", size=(40,1))],
        [sg.Text("定时开始（YYYY-MM-DD HH:MM:SS，留空立即开始）：", size=(40,1)), sg.Input(key="-STARTTIME-", size=(25,1)),
         sg.Text("间隔秒："), sg.Input("1.0", key="-INTERVAL-", size=(8,1)),
         sg.Text("重试次数（0=无限）："), sg.Input("0", key="-ATTEMPTS-", size=(8,1))],
        [sg.Checkbox("遇到成功停止重试", default=True, key="-STOPONSUCCESS-"),
         sg.Button("开始", key="-START-"), sg.Button("停止", key="-STOP-"), sg.Button("导出日志", key="-EXPORT-")],
        [sg.HorizontalSeparator()],
        [sg.Text("配置保存/加载："), sg.Input(key="-PROFILENAME-", size=(30,1)), sg.Button("保存配置", key="-SAVE-"), sg.Button("加载配置", key="-LOAD-"),
         sg.Button("打开配置文件夹", key="-OPENPROF-")],
        [sg.Text("日志：")],
        [sg.Multiline(key="-LOG-", size=(100,20), autoscroll=True, disabled=True)]
    ]
    window = sg.Window("抢道具工具（示例）", layout, finalize=True)
    # 自定义属性用于线程停止标志
    window.user_stop_flag = False
    return window

def main():
    window = build_window()
    worker = None

    # 自动加载上次配置（如果存在）
    last_cfg_path = os.path.join(PROFILES_DIR, "last.json")
    if os.path.exists(last_cfg_path):
        try:
            with open(last_cfg_path,'r',encoding='utf-8') as f:
                last = json.load(f)
                window["-URL-"].update(last.get("url",""))
                window["-METHOD-"].update(last.get("method","POST"))
                window["-CTYPE-"].update(last.get("content_type","form"))
                window["-HEADERS-"].update(last.get("headers",""))
                window["-FORMKV-"].update(last.get("form_kv",""))
                window["-RAWBODY-"].update(last.get("raw_body",""))
                window["-SUCCESSKEY-"].update(last.get("success_keyword",""))
                window["-PROXY-"].update(last.get("proxy",""))
                window["-STARTTIME-"].update(last.get("start_time",""))
                window["-INTERVAL-"].update(str(last.get("interval","1.0")))
                window["-ATTEMPTS-"].update(str(last.get("attempts","0")))
                window["-STOPONSUCCESS-"].update(bool(last.get("stop_on_success",True)))
                window["-PROFILENAME-"].update(last.get("profile_name",""))
                window["-LOG-"].print(f"[{now_str()}] 加载上次配置：{last.get('profile_name','last.json')}")
        except Exception:
            pass

    while True:
        event, values = window.read(timeout=200)
        if event == sg.WIN_CLOSED:
            # 如果后台运行，先设置停止标志并等待
            if worker and worker.is_alive():
                window.user_stop_flag = True
                worker.join(1)
            break

        # handle background events from worker
        if event == "LOG":
            window["-LOG-"].print(values[event])
        if event == "DONE":
            info = values[event]
            window["-LOG-"].print(f"[{now_str()}] 后台线程结束：{info}")
            worker = None
            window.user_stop_flag = False

        if event == "-START-":
            if worker and worker.is_alive():
                sg.popup("后台正在运行中，请先停止当前任务")
                continue
            # collect config
            cfg = {
                "url": values["-URL-"].strip(),
                "method": values["-METHOD-"].strip(),
                "content_type": values["-CTYPE-"].strip(),
                "headers": values["-HEADERS-"],
                "form_kv": values["-FORMKV-"],
                "raw_body": values["-RAWBODY-"],
                "success_keyword": values["-SUCCESSKEY-"].strip(),
                "proxy": values["-PROXY-"].strip(),
                "start_time": values["-STARTTIME-"].strip(),
                "interval": float(values["-INTERVAL-"]) if values["-INTERVAL-"] else 1.0,
                "attempts": int(values["-ATTEMPTS-"]) if values["-ATTEMPTS-"] else 0,
                "stop_on_success": values["-STOPONSUCCESS-"],
                "profile_name": values["-PROFILENAME-"].strip()
            }
            # 保存最后一次配置
            try:
                with open(os.path.join(PROFILES_DIR, "last.json"), 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            window.user_stop_flag = False
            worker = threading.Thread(target=worker_thread, args=(cfg, window), daemon=True)
            worker.start()
            window["-LOG-"].print(f"[{now_str()}] 已启动后台线程")
        if event == "-STOP-":
            if not (worker and worker.is_alive()):
                window["-LOG-"].print(f"[{now_str()}] 没有正在运行的任务")
            else:
                window.user_stop_flag = True
                window["-LOG-"].print(f"[{now_str()}] 已发送停止请求，等待后台线程退出...")
        if event == "-SAVE-":
            prof = values["-PROFILENAME-"].strip()
            if not prof:
                sg.popup("请输入配置名（用于保存）")
            else:
                cfg = {
                    "url": values["-URL-"].strip(),
                    "method": values["-METHOD-"].strip(),
                    "content_type": values["-CTYPE-"].strip(),
                    "headers": values["-HEADERS-"],
                    "form_kv": values["-FORMKV-"],
                    "raw_body": values["-RAWBODY-"],
                    "success_keyword": values["-SUCCESSKEY-"].strip(),
                    "proxy": values["-PROXY-"].strip(),
                    "start_time": values["-STARTTIME-"].strip(),
                    "interval": float(values["-INTERVAL-"]) if values["-INTERVAL-"] else 1.0,
                    "attempts": int(values["-ATTEMPTS-"]) if values["-ATTEMPTS-"] else 0,
                    "stop_on_success": values["-STOPONSUCCESS-"],
                    "profile_name": prof
                }
                fname = os.path.join(PROFILES_DIR, prof + ".json")
                if save_profile(fname, cfg):
                    window["-LOG-"].print(f"[{now_str()}] 已保存配置：{fname}")
        if event == "-LOAD-":
            prof = values["-PROFILENAME-"].strip()
            if not prof:
                # 弹出选择列表
                files = [f for f in os.listdir(PROFILES_DIR) if f.endswith('.json')]
                if not files:
                    sg.popup("没有可用的配置文件")
                else:
                    choice = sg.popup_get_text("请输入要加载的配置文件名（不带 .json），可用：" + ", ".join([os.path.splitext(f)[0] for f in files]))
                    if choice:
                        prof = choice.strip()
            if prof:
                fname = os.path.join(PROFILES_DIR, prof + ".json")
                if os.path.exists(fname):
                    cfg = load_profile(fname)
                    if cfg:
                        window["-URL-"].update(cfg.get("url",""))
                        window["-METHOD-"].update(cfg.get("method","POST"))
                        window["-CTYPE-"].update(cfg.get("content_type","form"))
                        window["-HEADERS-"].update(cfg.get("headers",""))
                        window["-FORMKV-"].update(cfg.get("form_kv",""))
                        window["-RAWBODY-"].update(cfg.get("raw_body",""))
                        window["-SUCCESSKEY-"].update(cfg.get("success_keyword",""))
                        window["-PROXY-"].update(cfg.get("proxy",""))
                        window["-STARTTIME-"].update(cfg.get("start_time",""))
                        window["-INTERVAL-"].update(str(cfg.get("interval","1.0")))
                        window["-ATTEMPTS-"].update(str(cfg.get("attempts","0")))
                        window["-STOPONSUCCESS-"].update(bool(cfg.get("stop_on_success",True)))
                        window["-PROFILENAME-"].update(cfg.get("profile_name",prof))
                        window["-LOG-"].print(f"[{now_str()}] 已加载配置：{fname}")
                else:
                    sg.popup("配置文件不存在：", fname)
        if event == "-OPENPROF-":
            sg.popup_no_buttons("配置文件夹路径：" + os.path.abspath(PROFILES_DIR), title="配置文件夹")
        if event == "-EXPORT-":
            log_text = values["-LOG-"]
            if not log_text:
                sg.popup("日志为空")
            else:
                fname = sg.popup_get_file("保存日志为...", save_as=True, default_extension=".txt", file_types=(("Text files","*.txt"),))
                if fname:
                    try:
                        with open(fname, 'w', encoding='utf-8') as f:
                            f.write(log_text)
                        sg.popup("已保存", fname)
                    except Exception as e:
                        sg.popup_error("保存日志失败", e)

    window.close()

if __name__ == "__main__":
    main()
