import os
import ast
import math
import json
import queue
import time
import threading
import datetime
import platform
import subprocess
import urllib.parse
import urllib.request
import webbrowser
import tkinter as tk

import customtkinter as ctk
import numpy as np
import sounddevice as sd
import speech_recognition as sr
import pyttsx3
import psutil



APP_TITLE = "JARVIS"
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 750

SAMPLE_RATE = 44100
CHANNELS = 1
RECORD_SECONDS = 3

VOICE_SENSITIVITY = 8.0
MAX_VIBRATION = 45


OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

if len(OPENAI_API_KEY) >= 2 and (
    (OPENAI_API_KEY[0] == '"' and OPENAI_API_KEY[-1] == '"') or
    (OPENAI_API_KEY[0] == "'" and OPENAI_API_KEY[-1] == "'")
):
    OPENAI_API_KEY = OPENAI_API_KEY[1:-1].strip()

CYAN = "#00d9ff"
LIGHT_CYAN = "#66eeff"
DARK_CYAN = "#007c99"
WHITE = "#e9fbff"
GREEN = "#00ffb3"
RED = "#ff4268"
YELLOW = "#ffd166"
BACKGROUND = "#02070b"
PANEL = "#06141a"
PANEL_2 = "#031016"


audio_volume = 0.0
microphone_running = False
audio_stream = None
recognition_running = False
app_closing = False
animation_time = 0.0
voice_enabled = True
last_openai_error = ""

background_original = None
background_photo = None

center_x = 0
center_y = 0

recognition_lock = threading.Lock()
speech_queue = queue.Queue()
speech_thread_running = True



ALLOWED_OPERATORS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a ** b,
    ast.Mod: lambda a, b: a % b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.USub: lambda a: -a,
    ast.UAdd: lambda a: +a,
}


def safe_calculate(expression):
    if not expression:
        return None

    expression = expression.lower().strip()
    expression = expression.replace("×", "*").replace("÷", "/")
    expression = expression.replace("^", "**")
    expression = expression.replace(" x ", " * ")

    # Avoid accidental code-like expressions.
    if len(expression) > 100:
        return None

    try:
        tree = ast.parse(expression, mode="eval")

        def calculate(node):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                    return node.value
                raise ValueError

            if isinstance(node, ast.BinOp):
                left = calculate(node.left)
                right = calculate(node.right)
                operation = ALLOWED_OPERATORS.get(type(node.op))
                if operation is None:
                    raise ValueError
                result = operation(left, right)

                if isinstance(result, complex) or abs(result) > 10**100:
                    raise ValueError
                return result

            if isinstance(node, ast.UnaryOp):
                value = calculate(node.operand)
                operation = ALLOWED_OPERATORS.get(type(node.op))
                if operation is None:
                    raise ValueError
                return operation(value)

            raise ValueError

        return calculate(tree.body)
    except Exception:
        return None



def speech_worker():
    global speech_thread_running

    engine = None

    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 170)
        engine.setProperty("volume", 1.0)

        # Prefer a clear English voice when available.
        try:
            voices = engine.getProperty("voices")
            for voice in voices:
                name = (getattr(voice, "name", "") or "").lower()
                lang = str(getattr(voice, "languages", "")).lower()
                if "english" in name or "en_" in lang or "en-" in lang:
                    engine.setProperty("voice", voice.id)
                    break
        except Exception:
            pass

        print("Speech engine: READY")
    except Exception as error:
        print("Speech engine initialization error:", error)

    while speech_thread_running:
        try:
            text = speech_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        if text is None:
            speech_queue.task_done()
            break

        try:
            if voice_enabled and engine:
                engine.say(str(text))
                engine.runAndWait()
        except Exception as error:
            print("Speech error:", error)
        finally:
            speech_queue.task_done()

    if engine:
        try:
            engine.stop()
        except Exception:
            pass


threading.Thread(target=speech_worker, daemon=True).start()


def jarvis_speak(text):
    if not voice_enabled or not text:
        return
    text = str(text).strip()
    if text:
        speech_queue.put(text)



recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8
recognizer.phrase_threshold = 0.3
recognizer.non_speaking_duration = 0.5




def google_search(query):
    query = query.strip()
    if not query:
        return False
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    return bool(webbrowser.open(url))


def youtube_search(query):
    query = query.strip()
    if not query:
        return False
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    return bool(webbrowser.open(url))


def open_website(site):
    site = site.strip()
    if not site:
        return False

    site = site.replace(" ", "")

    if site.startswith(("http://", "https://")):
        url = site
    else:
        aliases = {
            "google": "https://www.google.com",
            "youtube": "https://www.youtube.com",
            "github": "https://github.com",
            "instagram": "https://www.instagram.com",
            "discord": "https://discord.com/app",
            "spotify": "https://open.spotify.com",
            "gmail": "https://mail.google.com",
            "reddit": "https://www.reddit.com",
            "wikipedia": "https://www.wikipedia.org",
            "chatgpt": "https://chatgpt.com",
            "stackoverflow": "https://stackoverflow.com",
        }

        if site.lower() in aliases:
            url = aliases[site.lower()]
        elif "." not in site:
            url = "https://" + site + ".com"
        else:
            url = "https://" + site

    try:
        return bool(webbrowser.open(url))
    except Exception as error:
        print("Website error:", error)
        return False




WINDOWS_APPS = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "task manager": ["taskmgr.exe"],
    "control panel": ["control.exe"],
    "file explorer": ["explorer.exe"],
    "explorer": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "command prompt": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "settings": ["cmd", "/c", "start", "ms-settings:"],
}


def open_windows_app(app_name):
    app_name = app_name.lower().strip()
    command = WINDOWS_APPS.get(app_name)

    if command is None:
        return False

    try:
        subprocess.Popen(command)
        return True
    except Exception as error:
        print("Application error:", error)
        return False



def get_known_folders():
    home = os.path.expanduser("~")
    return {
        "desktop": os.path.join(home, "Desktop"),
        "documents": os.path.join(home, "Documents"),
        "downloads": os.path.join(home, "Downloads"),
        "pictures": os.path.join(home, "Pictures"),
        "music": os.path.join(home, "Music"),
        "videos": os.path.join(home, "Videos"),
    }


def open_folder(folder):
    path = get_known_folders().get(folder.lower().strip())
    if not path or not os.path.exists(path):
        return False

    try:
        os.startfile(path)
        return True
    except Exception as error:
        print("Folder error:", error)
        return False



def format_uptime():
    seconds = max(0, time.time() - psutil.boot_time())
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

    return ", ".join(parts)


def get_system_info():
    cpu = psutil.cpu_percent(interval=0.4)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))

    return (
        f"Operating system: {platform.system()} {platform.release()}. "
        f"Processor: {platform.processor() or 'Unknown'}. "
        f"CPU usage: {cpu:.0f} percent. "
        f"RAM usage: {memory.percent:.0f} percent. "
        f"Disk usage: {disk.percent:.0f} percent."
    )


def get_cpu():
    return f"Current CPU usage is {psutil.cpu_percent(interval=0.4):.0f} percent."


def get_ram():
    memory = psutil.virtual_memory()
    used_gb = memory.used / (1024 ** 3)
    total_gb = memory.total / (1024 ** 3)
    return f"RAM usage is {memory.percent:.0f} percent. {used_gb:.1f} of {total_gb:.1f} gigabytes is currently used."


def get_disk():
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    free_gb = disk.free / (1024 ** 3)
    total_gb = disk.total / (1024 ** 3)
    return f"Disk usage is {disk.percent:.0f} percent. You have {free_gb:.1f} gigabytes free out of {total_gb:.1f}."


def get_battery():
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return "Battery information is not available."

        percent = battery.percent

        if battery.power_plugged:
            return f"Battery is at {percent:.0f} percent and the computer is plugged in."

        return f"Battery is at {percent:.0f} percent."
    except Exception:
        return "I could not read the battery information."


def get_uptime():
    return f"The computer has been running for {format_uptime()}."


def get_network_info():
    try:
        stats = psutil.net_if_stats()
        active = [
            name for name, info in stats.items()
            if info.isup and info.speed >= 0
        ]
        if active:
            return "Active network interfaces: " + ", ".join(active[:4]) + "."
        return "I could not find an active network interface."
    except Exception:
        return "Network information is unavailable."


def get_top_processes():
    try:
        processes = []

        for proc in psutil.process_iter(["name", "cpu_percent"]):
            try:
                name = proc.info["name"] or "Unknown"
                cpu = proc.info["cpu_percent"] or 0.0
                processes.append((cpu, name))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        processes.sort(reverse=True)
        top = processes[:5]

        if not top:
            return "I could not read the running processes."

        text = ", ".join(f"{name} at {cpu:.0f} percent" for cpu, name in top)
        return "Top CPU processes are " + text + "."
    except Exception:
        return "I could not read the running processes."




def take_screenshot():
    try:
        from PIL import ImageGrab

        folder = os.path.join(
            os.path.expanduser("~"),
            "Pictures",
            "JARVIS Screenshots"
        )
        os.makedirs(folder, exist_ok=True)

        filename = "jarvis_" + datetime.datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        ) + ".png"

        path = os.path.join(folder, filename)
        image = ImageGrab.grab()
        image.save(path)
        return path
    except Exception as error:
        print("Screenshot error:", error)
        return None



def get_weather(city):
    city = city.strip()
    if not city:
        return None

    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=3"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "JARVIS/1.0"}
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            result = response.read().decode("utf-8", errors="ignore").strip()

        return result if result else None
    except Exception as error:
        print("Weather error:", error)
        return None




def _openai_headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Accept": "application/json",
        "User-Agent": "JARVIS-Desktop/1.0",
    }


def _openai_prompt(question):
    return (
        "You are JARVIS, a helpful desktop AI assistant. "
        "Answer naturally, clearly, and briefly. "
        "Keep normal answers under about 120 words unless the user asks for detail. "
        "Do not claim you performed a computer action unless this program actually did it.\n\n"
        f"User: {question}"
    )


def _extract_openai_text(data):
    """Extract output text from a non-streaming OpenAI Responses API response."""
    if isinstance(data, dict):
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        parts = []
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    value = content.get("text", "")
                    if isinstance(value, str):
                        parts.append(value)

        if parts:
            return "".join(parts).strip()

    return ""


def _openai_error_message(error):
    """Extract the useful message from an OpenAI HTTP error."""
    try:
        body = error.read().decode("utf-8", errors="replace")
        if body:
            try:
                data = json.loads(body)
                err = data.get("error", {})
                if isinstance(err, dict):
                    message = err.get("message")
                    code = err.get("code")
                    error_type = err.get("type")
                    parts = [str(x) for x in (message, code, error_type) if x]
                    if parts:
                        return " | ".join(parts)
                return body[:700]
            except json.JSONDecodeError:
                return body[:700]
    except Exception:
        pass
    return str(error)


def _validate_openai_configuration():
    """Validate the local API-key configuration without revealing the key."""
    if not OPENAI_API_KEY:
        return "OPENAI_API_KEY is not configured."
    if OPENAI_API_KEY.startswith(("YOUR_", "your_", "sk-...")):
        return "OPENAI_API_KEY still contains a placeholder."
    if len(OPENAI_API_KEY) < 20:
        return "OPENAI_API_KEY appears too short."
    return None


def ask_openai(question):
    """Non-streaming OpenAI Responses API call."""
    global last_openai_error
    last_openai_error = ""

    config_error = _validate_openai_configuration()
    if config_error:
        last_openai_error = config_error
        return None

    url = "https://api.openai.com/v1/responses"
    payload = {
        "model": OPENAI_MODEL,
        "input": _openai_prompt(question),
        "max_output_tokens": 300,
    }

    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=_openai_headers(),
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))

        answer = _extract_openai_text(data)
        if not answer:
            last_openai_error = "OpenAI returned an empty response."
            return None

        return answer

    except urllib.error.HTTPError as exc:
        last_openai_error = f"HTTP {exc.code}: {_openai_error_message(exc)}"
        print("OpenAI error:", last_openai_error)
        return None
    except urllib.error.URLError as exc:
        last_openai_error = f"Network error: {exc.reason}"
        print("OpenAI error:", last_openai_error)
        return None
    except Exception as exc:
        last_openai_error = str(exc)
        print("OpenAI error:", last_openai_error)
        return None


def ask_openai_stream(question, on_text=None):
    """
    Stream OpenAI Responses API output as soon as text is generated.
    on_text(chunk) is called from the worker thread.
    """
    global last_openai_error
    last_openai_error = ""

    config_error = _validate_openai_configuration()
    if config_error:
        last_openai_error = config_error
        return None

    url = "https://api.openai.com/v1/responses"
    payload = {
        "model": OPENAI_MODEL,
        "input": _openai_prompt(question),
        "max_output_tokens": 300,
        "stream": True,
    }

    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=_openai_headers(),
            method="POST",
        )

        chunks = []

        with urllib.request.urlopen(request, timeout=20) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="ignore").strip()

                if not line.startswith("data:"):
                    continue

                raw_data = line[5:].strip()
                if not raw_data or raw_data == "[DONE]":
                    continue

                try:
                    event = json.loads(raw_data)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "response.output_text.delta":
                    chunk = event.get("delta", "")
                    if isinstance(chunk, str) and chunk:
                        chunks.append(chunk)
                        if on_text is not None:
                            on_text(chunk)

                elif event.get("type") == "error":
                    last_openai_error = event.get("message", "OpenAI streaming error.")
                    return None

        answer = "".join(chunks).strip()

        if not answer:
            last_openai_error = "OpenAI returned no streamed text."
            return None

        return answer

    except urllib.error.HTTPError as exc:
        last_openai_error = f"HTTP {exc.code}: {_openai_error_message(exc)}"
        print("OpenAI streaming error:", last_openai_error)
        return None
    except urllib.error.URLError as exc:
        last_openai_error = f"Network error: {exc.reason}"
        print("OpenAI streaming error:", last_openai_error)
        return None
    except Exception as exc:
        last_openai_error = str(exc)
        print("OpenAI streaming error:", last_openai_error)
        return None


def add_chat_message(sender, message):
    try:
        chat_box.configure(state="normal")
        chat_box.insert("end", f"{sender}: {message}\n\n")
        chat_box.configure(state="disabled")
        chat_box.see("end")
    except Exception as error:
        print("Chat error:", error)




streaming_message_open = False


def start_stream_chat():
    """Create the JARVIS message before the first ChatGPT token arrives."""
    global streaming_message_open

    if streaming_message_open:
        return

    streaming_message_open = True

    chat_box.configure(state="normal")
    chat_box.insert("end", "JARVIS: ")
    chat_box.see("end")
    chat_box.configure(state="disabled")


def append_stream_chat(chunk):
    """Append a ChatGPT text chunk safely on the Tkinter thread."""
    if not chunk:
        return

    chat_box.configure(state="normal")
    chat_box.insert("end", chunk)
    chat_box.see("end")
    chat_box.configure(state="disabled")


def finish_stream_chat(answer):
    """Finish the streamed message and start speech once."""
    global streaming_message_open

    if streaming_message_open:
        chat_box.configure(state="normal")
        chat_box.insert("end", "\n\n")
        chat_box.see("end")
        chat_box.configure(state="disabled")
        streaming_message_open = False
    else:
        add_chat_message("JARVIS", answer)

    jarvis_speak(answer)
    update_status("SYSTEM READY")

def clear_chat():
    try:
        chat_box.configure(state="normal")
        chat_box.delete("1.0", "end")
        chat_box.insert("end", "JARVIS: Chat cleared. System ready.\n\n")
        chat_box.configure(state="disabled")
    except Exception:
        pass


def update_status(text):
    try:
        app.after(0, lambda: status_label.configure(text=text))
    except Exception:
        pass


def finish_response(response, speak=True):
    if not response:
        return

    add_chat_message("JARVIS", response)

    if speak and voice_enabled:
        jarvis_speak(response)

    update_status("SYSTEM READY")



def get_offline_response(command):

    c = command.lower().strip()

    if c in {"hi", "hello", "hey", "hey jarvis", "hello jarvis", "hi jarvis"}:
        return "Hello. I am JARVIS. How can I help you?"

    if "how are you" in c:
        return "All systems are operating normally. I am ready."

    if "thank" in c:
        return "You're welcome."

    if c in {"bye", "goodbye", "see you"}:
        return "Goodbye. JARVIS will be here when you need me."

    if any(phrase in c.replace("?", "").replace(".", "").replace("!", "") for phrase in (
        "who made you", "who created you", "who built you",
        "who developed you", "who is your creator", "who is your developer",
        "who made jarvis", "who created jarvis", "who built jarvis",
        "who developed jarvis"
    )):
        return "I am made by Arjun."

    if "who are you" in c or "what are you" in c:
        return (
            "I am JARVIS, your desktop AI assistant. "
            "I can control supported desktop features, search the web, "
            "calculate, monitor your computer, and speak responses."
        )

    if "what can you do" in c or "help" == c or "commands" in c:
        return (
            "I can open apps and folders, search Google or YouTube, "
            "take screenshots, check CPU, RAM, disk and battery, "
            "tell the time and date, calculate expressions, get weather, "
            "and answer questions when ChatGPT is configured."
        )

    if "tell me a joke" in c or c == "joke":
        return "Why do programmers prefer dark mode? Because light attracts bugs."

    if "favorite" in c and "color" in c:
        return "Cyan. It looks right at home in my interface."

    return None



def ai_response_thread(command):
    """Run ChatGPT in the background and display tokens immediately."""
    try:
        app.after(0, lambda: update_status("JARVIS THINKING..."))

        def receive_chunk(chunk):
            app.after(0, start_stream_chat)
            app.after(0, lambda c=chunk: append_stream_chat(c))

        answer = ask_openai_stream(command, receive_chunk)

        if answer:
            app.after(0, lambda a=answer: finish_stream_chat(a))
            return

        answer = ask_openai(command)

        if answer:
            app.after(0, lambda a=answer: finish_response(a))
            return

        error = last_openai_error or "Unknown OpenAI error."
        fallback = (
            "I couldn't connect to ChatGPT right now. "
            f"Error: {error}"
        )

        app.after(0, lambda a=fallback: finish_response(a))

    except Exception as exc:
        app.after(
            0,
            lambda: finish_response(
                f"I ran into an error while processing that: {exc}"
            )
        )


def process_command(command):
    if not command:
        return

    original = str(command).strip()
    if not original:
        return

    command_entry.delete(0, "end")
    add_chat_message("YOU", original)
    update_status("PROCESSING...")

    c = original.lower().strip()

    normalized = c.replace("?", "").replace(".", "").replace("!", "").strip()
    creator_phrases = (
        "who made you",
        "who created you",
        "who built you",
        "who developed you",
        "who is your creator",
        "who is your developer",
        "who made jarvis",
        "who created jarvis",
        "who built jarvis",
        "who developed jarvis",
    )
    if any(phrase in normalized for phrase in creator_phrases):
        finish_response("I am made by Arjun.")
        return

    offline = get_offline_response(c)
    if offline:
        finish_response(offline)
        return

    if c in {"time", "what time is it", "what is the time", "current time"}:
        now = datetime.datetime.now().strftime("%I:%M %p")
        finish_response(f"The time is {now}.")
        return


    if (
        c in {"date", "today", "today's date", "what is the date"}
        or "what day is it" in c
    ):
        today = datetime.datetime.now().strftime("%A, %d %B %Y")
        finish_response(f"Today is {today}.")
        return

    if c in {
        "system info", "system information",
        "computer information", "computer specs",
        "pc specs", "my pc specs"
    }:
        finish_response(get_system_info())
        return

    # ---- CPU
    if "cpu usage" in c or "processor usage" in c:
        finish_response(get_cpu())
        return

    # ---- RAM
    if (
        "ram usage" in c
        or "memory usage" in c
        or "how much ram" in c
        or c == "ram"
    ):
        finish_response(get_ram())
        return

    # ---- disk
    if (
        "disk usage" in c
        or "storage usage" in c
        or "how much storage" in c
        or c == "storage"
        or c == "disk"
    ):
        finish_response(get_disk())
        return

    # ---- battery
    if "battery" in c:
        finish_response(get_battery())
        return

    # ---- uptime
    if "uptime" in c or "how long has my pc been on" in c:
        finish_response(get_uptime())
        return

    # ---- network
    if (
        "network status" in c
        or "network information" in c
        or "wifi status" in c
        or "internet status" in c
    ):
        finish_response(get_network_info())
        return

    # ---- top processes
    if (
        "top processes" in c
        or "running processes" in c
        or "what is using my cpu" in c
    ):
        finish_response(get_top_processes())
        return

    # ---- calculator
    if c.startswith("calculate "):
        expression = original[len("calculate "):].strip()
        result = safe_calculate(expression)

        if result is not None:
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            finish_response(f"The answer is {result}.")
        else:
            # Let ChatGPT handle natural-language math if configured.
            threading.Thread(
                target=ai_response_thread,
                args=(original,),
                daemon=True
            ).start()
        return

    # ---- direct expression
    if c.startswith("what is ") or c.startswith("what's "):
        expression = c.replace("what is ", "", 1).replace("what's ", "", 1).strip()
        result = safe_calculate(expression)
        if result is not None:
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            finish_response(f"The answer is {result}.")
            return

    # ---- Google search
    if c.startswith("search google "):
        query = original[len("search google "):].strip()
        if query:
            google_search(query)
            finish_response(f"Searching Google for {query}.")
        else:
            finish_response("What would you like me to search for?")
        return

    if c.startswith("search "):
        query = original[len("search "):].strip()
        if query:
            google_search(query)
            finish_response(f"Searching Google for {query}.")
        else:
            finish_response("What would you like me to search for?")
        return

    # ---- YouTube
    if c.startswith("search youtube "):
        query = original[len("search youtube "):].strip()
        if query:
            youtube_search(query)
            finish_response(f"Searching YouTube for {query}.")
        else:
            finish_response("What should I search for on YouTube?")
        return

    if c.startswith("play "):
        query = original[len("play "):].strip()
        if query:
            youtube_search(query)
            finish_response(f"Searching YouTube for {query}.")
        return

    # ---- Weather
    if c.startswith("weather in "):
        city = original[len("weather in "):].strip()
        update_status("GETTING WEATHER...")
        threading.Thread(
            target=weather_thread,
            args=(city,),
            daemon=True
        ).start()
        return

    if c == "weather":
        finish_response(
            "Tell me a city, for example, weather in Kochi."
        )
        return

    # ---- screenshot
    if c == "screenshot" or "take a screenshot" in c:
        path = take_screenshot()
        if path:
            finish_response("Screenshot captured and saved in your JARVIS Screenshots folder.")
        else:
            finish_response("I could not take the screenshot.")
        return

    # ---- clear chat
    if c in {"clear chat", "clear conversation", "delete chat"}:
        clear_chat()
        finish_response("Chat cleared.")
        return

    # ---- voice on/off
    if c in {"mute", "mute voice", "voice off", "disable voice"}:
        set_voice(False)
        add_chat_message("JARVIS", "Voice responses are now muted.")
        update_status("VOICE MUTED")
        return

    if c in {"unmute", "voice on", "enable voice"}:
        set_voice(True)
        finish_response("Voice responses are enabled.")
        return

    # ---- common websites
    site_commands = {
        "google": "google",
        "open google": "google",
        "youtube": "youtube",
        "open youtube": "youtube",
        "github": "github",
        "open github": "github",
        "instagram": "instagram",
        "open instagram": "instagram",
        "discord": "discord",
        "open discord": "discord",
        "spotify": "spotify",
        "open spotify": "spotify",
        "gmail": "gmail",
        "open gmail": "gmail",
        "chatgpt": "chatgpt",
        "open chatgpt": "chatgpt",
        "wikipedia": "wikipedia",
        "open wikipedia": "wikipedia",
    }

    if c in site_commands:
        site = site_commands[c]
        if open_website(site):
            finish_response(f"Opening {site.title()}.")
        else:
            finish_response(f"I could not open {site}.")
        return

    # ---- known Windows apps
    app_target = c
    if c.startswith("open "):
        app_target = c[len("open "):].strip()

    if app_target in WINDOWS_APPS:
        if open_windows_app(app_target):
            finish_response(f"Opening {app_target}.")
        else:
            finish_response(f"I could not open {app_target}.")
        return

    # ---- folders
    folder_names = set(get_known_folders().keys())

    if app_target in folder_names:
        if open_folder(app_target):
            finish_response(f"Opening {app_target}.")
        else:
            finish_response(f"I could not open {app_target}.")
        return

    # ---- URL / website
    if c.startswith("open "):
        target = original[len("open "):].strip()

        if target:
            # Try a URL/site before sending to AI.
            if open_website(target):
                finish_response(f"Opening {target}.")
            else:
                finish_response(f"I could not open {target}.")
            return

    # ---- settings
    if c in {"settings", "open settings"}:
        if open_windows_app("settings"):
            finish_response("Opening Windows Settings.")
        else:
            finish_response("I could not open Settings.")
        return

    # ---- AI / fallback
    threading.Thread(
        target=ai_response_thread,
        args=(original,),
        daemon=True
    ).start()


def weather_thread(city):
    result = get_weather(city)
    if result:
        app.after(0, lambda r=result: finish_response(r))
    else:
        app.after(
            0,
            lambda: finish_response(
                "I could not get the weather right now."
            )
        )

def set_voice(enabled):
    global voice_enabled
    voice_enabled = bool(enabled)

    try:
        if voice_enabled:
            voice_toggle_button.configure(
                text="VOICE ON",
                fg_color="#12313b",
                hover_color="#174652",
                text_color=WHITE
            )
        else:
            voice_toggle_button.configure(
                text="VOICE OFF",
                fg_color=RED,
                hover_color="#cc3454",
                text_color="white"
            )
    except Exception:
        pass


def listen_for_command():
    global recognition_running

    with recognition_lock:
        if recognition_running:
            return
        recognition_running = True

    was_mic_running = microphone_running

    try:
        if was_mic_running:
            stop_microphone()

        update_status("LISTENING...")

        app.after(
            0,
            lambda: mic_button.configure(
                text="LISTENING...",
                fg_color=GREEN,
                hover_color="#00cc91",
                text_color="black"
            )
        )

        recording = sd.rec(
            int(RECORD_SECONDS * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=np.int16
        )
        sd.wait()

        audio_float = recording.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(audio_float ** 2)))

        print("Voice RMS:", rms)

        if rms < 0.0005:
            update_status("NO SPEECH")
            if voice_enabled:
                jarvis_speak("I did not hear anything.")
            return

        update_status("RECOGNIZING...")

        audio_data = sr.AudioData(
            recording.tobytes(),
            SAMPLE_RATE,
            2
        )

        command = recognizer.recognize_google(
            audio_data,
            language="en-US"
        ).strip()

        print("JARVIS HEARD:", command)

        if command:
            app.after(0, lambda c=command: process_command(c))

    except sr.UnknownValueError:
        update_status("NOT UNDERSTOOD")
        if voice_enabled:
            jarvis_speak("Sorry, I could not understand you.")

    except sr.RequestError as error:
        print("Speech recognition service error:", error)
        update_status("RECOGNITION ERROR")
        if voice_enabled:
            jarvis_speak("I cannot connect to the speech recognition service.")

    except sd.PortAudioError as error:
        print("Microphone error:", error)
        update_status("MICROPHONE ERROR")
        if voice_enabled:
            jarvis_speak("There is a problem with the microphone.")

    except Exception as error:
        print("Voice error:", repr(error))
        update_status("VOICE ERROR")

    finally:
        with recognition_lock:
            recognition_running = False

        app.after(0, reset_voice_button)

        if was_mic_running and not app_closing:
            app.after(100, start_microphone)


def reset_voice_button():
    try:
        mic_button.configure(
            text="🎤 SPEAK",
            fg_color="#12313b",
            hover_color="#174652",
            text_color=WHITE
        )
        if not microphone_running:
            status_label.configure(text="SYSTEM READY")
    except Exception:
        pass


def start_voice_command():
    with recognition_lock:
        if recognition_running:
            return

    threading.Thread(
        target=listen_for_command,
        daemon=True
    ).start()


def audio_callback(indata, frames, time_info, status):
    global audio_volume

    try:
        samples = indata[:, 0]
        rms = float(np.sqrt(np.mean(samples ** 2)))
        volume = max(0.0, min(rms * VOICE_SENSITIVITY, 1.0))

        audio_volume = audio_volume * 0.65 + volume * 0.35
    except Exception:
        pass


def start_microphone():
    global microphone_running, audio_stream

    if microphone_running or app_closing:
        return

    try:
        audio_stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            callback=audio_callback,
            blocksize=1024
        )
        audio_stream.start()
        microphone_running = True

        visualizer_button.configure(
            text="CORE ON",
            fg_color=GREEN,
            hover_color="#00cc91",
            text_color="black"
        )
        status_label.configure(text="MIC ACTIVE")

    except Exception as error:
        print("Core microphone error:", error)
        audio_stream = None
        microphone_running = False
        status_label.configure(text="MICROPHONE ERROR")


def stop_microphone():
    global microphone_running, audio_stream

    try:
        if audio_stream:
            audio_stream.stop()
            audio_stream.close()
    except Exception:
        pass

    audio_stream = None
    microphone_running = False

    try:
        visualizer_button.configure(
            text="CORE MIC",
            fg_color="#12313b",
            hover_color="#174652",
            text_color=WHITE
        )
        status_label.configure(text="SYSTEM READY")
    except Exception:
        pass


def toggle_microphone():
    if microphone_running:
        stop_microphone()
    else:
        start_microphone()


ctk.set_appearance_mode("dark")

app = ctk.CTk()
app.title(APP_TITLE)
app.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
app.minsize(900, 600)
app.configure(fg_color=BACKGROUND)

canvas = tk.Canvas(
    app,
    bg=BACKGROUND,
    highlightthickness=0,
    bd=0
)
canvas.pack(fill="both", expand=True)



def find_background_image():
    folder = os.path.dirname(os.path.abspath(__file__))
    assets = os.path.join(folder, "assets")

    names = [
        "jarvis_ui.png",
        "jarvis_ui.webp",
        "jarvis_ui.jpg",
        "jarvis_ui.jpeg",
        "Jarvis.png",
        "Jarvis.webp",
        "Jarvis.jpg",
        "Jarvis.jpeg",
    ]

    for name in names:
        path = os.path.join(assets, name)
        if os.path.isfile(path):
            return path

    return None


image_path = find_background_image()

if image_path:
    try:
        from PIL import Image, ImageTk
        background_original = Image.open(image_path).convert("RGB")
    except Exception as error:
        print("Background error:", error)
        background_original = None


def resize_background(event=None):
    global background_photo

    width = canvas.winfo_width()
    height = canvas.winfo_height()

    if width <= 1 or height <= 1:
        return

    if background_original:
        image = background_original.copy()

        image_ratio = image.width / image.height
        window_ratio = width / height

        if image_ratio > window_ratio:
            new_height = height
            new_width = int(height * image_ratio)
        else:
            new_width = width
            new_height = int(width / image_ratio)

        image = image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS
        )

        left = max(0, (new_width - width) // 2)
        top = max(0, (new_height - height) // 2)

        image = image.crop(
            (left, top, left + width, top + height)
        )

        background_photo = ImageTk.PhotoImage(image)

        canvas.delete("background")
        canvas.create_image(
            width // 2,
            height // 2,
            image=background_photo,
            anchor="center",
            tags="background"
        )
        canvas.tag_lower("background")

    draw_static_ui()


def draw_static_ui():
    global center_x, center_y

    width = canvas.winfo_width()
    height = canvas.winfo_height()

    if width <= 1 or height <= 1:
        return

    center_x = width * 0.46
    center_y = height * 0.40

    canvas.delete("static")

    canvas.create_text(
        width * 0.46,
        height * 0.07,
        text="J A R V I S",
        fill=CYAN,
        font=("Arial", 22, "bold"),
        tags="static"
    )

    canvas.create_text(
        width * 0.46,
        height * 0.105,
        text="JUST A RATHER VERY INTELLIGENT SYSTEM",
        fill="#5ca9ba",
        font=("Arial", 9),
        tags="static"
    )

    canvas.create_text(
        50,
        55,
        text="SYSTEM",
        fill=CYAN,
        font=("Arial", 14, "bold"),
        anchor="w",
        tags="static"
    )

    canvas.create_text(
        50,
        78,
        text="ONLINE",
        fill=GREEN,
        font=("Arial", 17, "bold"),
        anchor="w",
        tags="static"
    )

    canvas.create_text(
        width - 50,
        55,
        text="VOICE SYSTEM",
        fill=CYAN,
        font=("Arial", 13, "bold"),
        anchor="e",
        tags="static"
    )

    canvas.create_text(
        width - 50,
        78,
        text="READY",
        fill=GREEN,
        font=("Arial", 17, "bold"),
        anchor="e",
        tags="static"
    )

    canvas.create_text(
        width * 0.46,
        height * 0.69,
        text="VOICE REACTIVE CORE",
        fill=CYAN,
        font=("Arial", 13, "bold"),
        tags="static"
    )




def animate_core():
    global animation_time

    if app_closing:
        return

    animation_time += 0.12

    canvas.delete("core")

    volume = audio_volume
    breathing = math.sin(animation_time) * 2
    vibration = volume * MAX_VIBRATION

    radius = 140 + breathing + vibration

    for i in range(5):
        ring_radius = radius + i * 12
        canvas.create_oval(
            center_x - ring_radius,
            center_y - ring_radius,
            center_x + ring_radius,
            center_y + ring_radius,
            outline=CYAN,
            width=2,
            tags="core"
        )

    canvas.create_oval(
        center_x - 105,
        center_y - 105,
        center_x + 105,
        center_y + 105,
        outline=LIGHT_CYAN,
        width=3,
        tags="core"
    )

    canvas.create_oval(
        center_x - 70,
        center_y - 70,
        center_x + 70,
        center_y + 70,
        outline="#00fff0",
        width=2,
        tags="core"
    )

    canvas.create_text(
        center_x,
        center_y,
        text="JARVIS",
        fill=WHITE,
        font=("Arial", 26, "bold"),
        tags="core"
    )

    app.after(30, animate_core)




chat_box = ctk.CTkTextbox(
    app,
    width=330,
    height=250,
    corner_radius=15,
    border_width=1,
    border_color=DARK_CYAN,
    fg_color=PANEL_2,
    text_color=WHITE,
    font=("Consolas", 11)
)

chat_box.place(
    relx=0.83,
    rely=0.43,
    anchor="center"
)

chat_box.insert(
    "end",
    "JARVIS: System online. Ask me something.\n\n"
)
chat_box.configure(state="disabled")



command_entry = ctk.CTkEntry(
    app,
    width=430,
    height=45,
    corner_radius=22,
    border_width=2,
    border_color=CYAN,
    fg_color=PANEL,
    text_color=WHITE,
    placeholder_text="Speak or type anything...",
    placeholder_text_color="#64909a",
    font=("Arial", 14)
)

command_entry.place(
    relx=0.46,
    rely=0.845,
    anchor="center"
)


def send_command():
    command = command_entry.get().strip()
    if command:
        process_command(command)


def enter_pressed(event):
    send_command()


command_entry.bind("<Return>", enter_pressed)


status_label = ctk.CTkLabel(
    app,
    text="SYSTEM READY",
    text_color=CYAN,
    fg_color=BACKGROUND,
    font=("Arial", 13, "bold")
)

status_label.place(
    relx=0.18,
    rely=0.845,
    anchor="center"
)


ask_button = ctk.CTkButton(
    app,
    text="ASK JARVIS",
    width=150,
    height=42,
    corner_radius=21,
    fg_color="#073b49",
    hover_color="#07566a",
    border_width=1,
    border_color=CYAN,
    text_color=WHITE,
    font=("Arial", 13, "bold"),
    command=send_command
)

ask_button.place(
    relx=0.46,
    rely=0.915,
    anchor="center"
)


mic_button = ctk.CTkButton(
    app,
    text="🎤 SPEAK",
    width=120,
    height=38,
    corner_radius=19,
    fg_color="#12313b",
    hover_color="#174652",
    text_color=WHITE,
    font=("Arial", 12, "bold"),
    command=start_voice_command
)

mic_button.place(
    relx=0.69,
    rely=0.845,
    anchor="center"
)


visualizer_button = ctk.CTkButton(
    app,
    text="CORE MIC",
    width=110,
    height=38,
    corner_radius=19,
    fg_color="#12313b",
    hover_color="#174652",
    text_color=WHITE,
    font=("Arial", 11, "bold"),
    command=toggle_microphone
)

visualizer_button.place(
    relx=0.69,
    rely=0.915,
    anchor="center"
)


voice_toggle_button = ctk.CTkButton(
    app,
    text="VOICE ON",
    width=100,
    height=34,
    corner_radius=17,
    fg_color="#12313b",
    hover_color="#174652",
    text_color=WHITE,
    font=("Arial", 10, "bold"),
    command=lambda: set_voice(not voice_enabled)
)

voice_toggle_button.place(
    relx=0.83,
    rely=0.78,
    anchor="center"
)


clear_button = ctk.CTkButton(
    app,
    text="CLEAR CHAT",
    width=100,
    height=34,
    corner_radius=17,
    fg_color="#12313b",
    hover_color="#174652",
    text_color=WHITE,
    font=("Arial", 10, "bold"),
    command=clear_chat
)

clear_button.place(
    relx=0.93,
    rely=0.78,
    anchor="center"
)


def close_app():
    global app_closing
    global microphone_running
    global audio_stream
    global speech_thread_running

    app_closing = True
    microphone_running = False

    try:
        if audio_stream:
            audio_stream.stop()
            audio_stream.close()
    except Exception:
        pass

    audio_stream = None

    speech_thread_running = False

    try:
        speech_queue.put(None)
    except Exception:
        pass

    try:
        sd.stop()
    except Exception:
        pass

    try:
        app.destroy()
    except Exception:
        pass


app.protocol("WM_DELETE_WINDOW", close_app)
app.bind("<Configure>", resize_background)




def startup_message():
    if OPENAI_API_KEY:
        message = "Hello. I am JARVIS. System online and ChatGPT connection ready."
    else:
        message = (
            "Hello. I am JARVIS. System online. "
            "Local commands are ready."
        )

    add_chat_message("JARVIS", message)
    if voice_enabled:
        jarvis_speak(message)


app.after(100, resize_background)
app.after(200, animate_core)
app.after(1200, startup_message)

print()
print("=" * 48)
print("                 JARVIS")
print("=" * 48)
print("Text commands      : READY")
print("Voice commands     : READY")
print("Speech engine      : READY")
print("Calculator         : READY")
print("Web control        : READY")
print("Windows apps       : READY")
print("System monitor     : READY")
print("Weather            : READY")
print("Screenshot         : READY")
config_status = _validate_openai_configuration()
print("ChatGPT AI          :", "READY" if not config_status else "NOT CONFIGURED")
print("ChatGPT model       :", OPENAI_MODEL)
if config_status:
    print("ChatGPT config      :", config_status)
else:
    print("ChatGPT key         : DETECTED (hidden)")
print("=" * 48)
print()

app.mainloop()


