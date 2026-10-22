import os
import sys
import time
import platform
import threading
import subprocess
from collections import deque
from datetime import datetime

import telebot
import psutil
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not configured. Set it in your .env file."
    )

if ADMIN_ID <= 0:
    raise RuntimeError(
        "ADMIN_ID is not configured. Set your Telegram user ID in .env."
    )

bot = telebot.TeleBot(TOKEN)


# Store the last 60 minutes of metrics:
# 360 points at 10-second intervals.
MAX_HISTORY_POINTS = 360

cpu_history = deque(maxlen=MAX_HISTORY_POINTS)
ram_history = deque(maxlen=MAX_HISTORY_POINTS)
time_history = deque(maxlen=MAX_HISTORY_POINTS)
event_log = deque(maxlen=50)


# Alert counters and timestamps
high_cpu_count = 0
last_disk_alert_time = 0


def is_admin(user_id):
    """Allow access only to the configured administrator."""
    return ADMIN_ID > 0 and user_id == ADMIN_ID


def log_event(message_text):
    """Add a system event to the local event log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event_log.append(f"[{timestamp}] {message_text}")


def format_bytes(size):
    """Convert bytes into a human-readable format."""
    power = 1024
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0

    while size >= power and index < len(units) - 1:
        size /= power
        index += 1

    return f"{size:.2f} {units[index]}"


def get_system_uptime():
    """Get the system uptime and last boot time."""
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime_duration = datetime.now() - boot_time

    days = uptime_duration.days
    hours, remainder = divmod(uptime_duration.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    return (
        f"{days} days, {hours} hours, {minutes} minutes "
        f"(Boot time: {boot_time.strftime('%Y-%m-%d %H:%M:%S')})"
    )


def get_temperatures():
    """Read hardware temperature sensors when supported."""
    if not hasattr(psutil, "sensors_temperatures"):
        return "Not supported by this operating system."

    try:
        temperatures = psutil.sensors_temperatures()

        if not temperatures:
            return "Temperature sensors are unavailable."

        results = []

        for name, entries in temperatures.items():
            for entry in entries:
                label = entry.label or name
                results.append(f"{label}: {entry.current}°C")

        return ", ".join(results) if results else "No temperature data available."

    except Exception as exc:
        return f"Temperature reading error: {exc}"


def background_monitor():
    """Monitor system resources and send alerts in the background."""
    global high_cpu_count, last_disk_alert_time

    # Notify the administrator when monitoring starts.
    try:
        bot.send_message(
            ADMIN_ID,
            "System monitoring has started or restarted!\n"
            f"OS: {platform.system()} {platform.release()}\n"
            f"Uptime: {get_system_uptime()}"
        )
        log_event("Bot started successfully. Monitoring is active.")

    except Exception as exc:
        print(f"Failed to send startup notification: {exc}")

    while True:
        try:
            current_time = datetime.now()

            cpu_value = psutil.cpu_percent(interval=1)
            ram_value = psutil.virtual_memory().percent

            # Save metrics to history.
            cpu_history.append(cpu_value)
            ram_history.append(ram_value)
            time_history.append(current_time)

            # Alert if CPU usage remains at or above 90%
            # for three consecutive monitoring cycles.
            if cpu_value >= 90.0:
                high_cpu_count += 1
                if high_cpu_count == 3:
                    alert_message = (
                        f"WARNING: CPU usage has remained high "
                        f"for approximately 30 seconds! "
                        f"Current usage: {cpu_value}%"
                    )

                    log_event(alert_message)
                    bot.send_message(ADMIN_ID, alert_message)
            else:
                high_cpu_count = 0

            # Check disk space and limit alerts to once per hour.
            if time.time() - last_disk_alert_time > 3600:
                for partition in psutil.disk_partitions(all=False):
                    try:
                        usage = psutil.disk_usage(partition.mountpoint)
                        free_percent = (usage.free / usage.total) * 100

                        if free_percent < 10.0:
                            alert_message = (
                                f"WARNING: Disk {partition.mountpoint} "
                                f"has less than 10% free space!\n"
                                f"Free: {format_bytes(usage.free)} "
                                f"of {format_bytes(usage.total)} "
                                f"({free_percent:.1f}%)"
                            )

                            log_event(alert_message)
                            bot.send_message(ADMIN_ID, alert_message)
                            last_disk_alert_time = time.time()
                            break

                    except Exception:
                        continue

            time.sleep(10)

        except Exception as exc:
            log_event(f"Monitoring loop error: {exc}")
            print(f"Monitoring loop error: {exc}")
            time.sleep(10)


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(
            message,
            "Access denied. This bot is restricted to its owner."
        )
        return

    text = (
        "PC Monitoring and Management Panel\n\n"
        "Available commands:\n"
        "/status - View CPU, RAM, disk usage, and uptime\n"
        "/chart - View recent CPU and RAM usage history\n"
        "/processes - List the top memory-consuming processes\n"
        "/services - Check system service statuses\n"
        "/ping - Check network connectivity\n"
        "/events - View system warnings and event logs\n"
        "/help - Display this help message"
    )

    bot.reply_to(message, text)


@bot.message_handler(commands=["status"])
def send_status(message):
    if not is_admin(message.from_user.id):
        return

    try:
        cpu = psutil.cpu_percent(interval=0.5)
        cpu_frequency = psutil.cpu_freq()

        frequency_text = (
            f"{cpu_frequency.current:.0f} MHz"
            if cpu_frequency
            else "N/A"
        )

        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Collect disk information.
        disk_info = []

        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(partition.mountpoint)

                disk_info.append(
                    f"Disk {partition.mountpoint} ({partition.fstype}): "
                    f"{usage.percent}% used "
                    f"(Free: {format_bytes(usage.free)} "
                    f"of {format_bytes(usage.total)})"
                )

            except Exception:
                continue

        disks_text = (
            "\n".join(disk_info)
            if disk_info
            else "Disk information is unavailable."
        )

        temperature_text = get_temperatures()

        response = (
            "Current System Status:\n\n"
            f"OS: {platform.system()} {platform.release()}\n"
            f"Uptime: {get_system_uptime()}\n\n"
            f"CPU: {cpu}% "
            f"(Frequency: {frequency_text}, "
            f"Cores: {psutil.cpu_count(logical=True)})\n"
            f"RAM: {ram.percent}% "
            f"(Used: {format_bytes(ram.used)} / "
            f"{format_bytes(ram.total)})\n"
            f"Swap: {swap.percent}% "
            f"(Used: {format_bytes(swap.used)} / "
            f"{format_bytes(swap.total)})\n\n"
            f"Disk Space:\n{disks_text}\n\n"
            f"Temperatures:\n{temperature_text}"
        )

        bot.reply_to(message, response)

    except Exception as exc:
        bot.reply_to(message, f"Failed to retrieve system status: {exc}")


@bot.message_handler(commands=["chart"])
def send_chart(message):
    if not is_admin(message.from_user.id):
        return

    if len(cpu_history) < 2:
        bot.reply_to(
            message,
            "Not enough data to generate a chart. Please wait a little longer."
        )
        return

    wait_message = bot.reply_to(
        message,
        "Generating the system load chart..."
    )

    chart_path = "system_load_chart.png"

    try:
        times = list(time_history)
        cpu_values = list(cpu_history)
        ram_values = list(ram_history)

        plt.figure(figsize=(9, 4.5))

        plt.plot(
            times,
            cpu_values,
            label="CPU (%)",
            color="#e74c3c",
            linewidth=1.8
        )

        plt.plot(
            times,
            ram_values,
            label="RAM (%)",
            color="#3498db",
            linewidth=1.8
        )

        plt.title("CPU and RAM Usage History")
        plt.xlabel("Time")
        plt.ylabel("Usage (%)")
        plt.ylim(0, 105)
        plt.grid(True, linestyle="--", alpha=0.6)
        plt.legend(loc="upper right")
        plt.tight_layout()

        plt.savefig(chart_path, dpi=120)
        plt.close()

        with open(chart_path, "rb") as photo:
            bot.send_photo(
                message.chat.id,
                photo,
                caption="System Load Chart"
            )

        bot.delete_message(
            message.chat.id,
            wait_message.message_id
        )

    except Exception as exc:
        plt.close("all")
        bot.reply_to(
            message,
            f"Failed to generate the chart: {exc}"
        )

    finally:
        if os.path.exists(chart_path):
            try:
                os.remove(chart_path)
            except OSError:
                pass


@bot.message_handler(commands=["processes"])
def send_processes(message):
    if not is_admin(message.from_user.id):
        return

    try:
        processes = []

        for process in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent"]
        ):
            try:
                processes.append(process.info)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort the top 10 processes by RAM usage.
        top_ram = sorted(
            processes,
            key=lambda process: process["memory_percent"] or 0,
            reverse=True
        )[:10]

        lines = ["Top 10 Processes by RAM Usage:"]

        for index, process in enumerate(top_ram, 1):
            name = process["name"] or "Unknown"

            if len(name) > 24:
                name = name[:22] + ".."

            ram_percent = process["memory_percent"] or 0

            lines.append(
                f"{index}. {name} "
                f"(PID: {process['pid']}) - "
                f"RAM: {ram_percent:.1f}%"
            )

        bot.reply_to(message, "\n".join(lines))

    except Exception as exc:
        bot.reply_to(
            message,
            f"Failed to retrieve the process list: {exc}"
        )


@bot.message_handler(commands=["services"])
def send_services(message):
    if not is_admin(message.from_user.id):
        return

    system_name = platform.system()
    try:
        if system_name == "Windows":
            # Check selected Windows system services.
            service_list = [
                "wuauserv",
                "WinDefend",
                "Spooler",
                "Dhcp",
                "Dnscache",
                "lanmanworkstation"
            ]

            lines = ["Windows Service Status:"]

            for service_name in service_list:
                try:
                    service = psutil.win_service_get(service_name)
                    info = service.as_dict()

                    lines.append(
                        f"- {info['display_name']} "
                        f"({service_name}): {info['status']}"
                    )

                except Exception:
                    lines.append(
                        f"- {service_name}: "
                        "Service not found or access denied."
                    )

            bot.reply_to(message, "\n".join(lines))

        elif system_name == "Linux":
            # Check selected systemd services on Linux.
            service_list = ["ssh", "cron", "docker", "ufw"]
            lines = ["Systemd Service Status:"]

            for service_name in service_list:
                try:
                    result = subprocess.run(
                        ["systemctl", "is-active", service_name],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )

                    status = (
                        result.stdout.strip()
                        or result.stderr.strip()
                        or "Unavailable"
                    )

                except Exception:
                    status = "Unavailable"

                lines.append(f"- {service_name}: {status}")

            bot.reply_to(message, "\n".join(lines))

        else:
            bot.reply_to(
                message,
                f"Service status checks are not configured for {system_name}."
            )

    except Exception as exc:
        bot.reply_to(
            message,
            f"Failed to check system services: {exc}"
        )


@bot.message_handler(commands=["ping"])
def send_ping(message):
    if not is_admin(message.from_user.id):
        return

    target = "8.8.8.8"

    parameter = (
        "-n"
        if platform.system().lower() == "windows"
        else "-c"
    )

    command = ["ping", parameter, "3", target]

    try:
        start_time = time.time()

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )

        elapsed = round((time.time() - start_time) * 1000, 2)

        if result.returncode == 0:
            bot.reply_to(
                message,
                "Internet connectivity check completed successfully.\n"
                f"Ping to {target} succeeded "
                f"(execution time: {elapsed} ms)."
            )

        else:
            bot.reply_to(
                message,
                f"Warning: Ping to {target} failed!\n"
                f"Exit code: {result.returncode}"
            )

    except subprocess.TimeoutExpired:
        bot.reply_to(
            message,
            f"Connection timeout: no response from {target} "
            "within 10 seconds."
        )

    except Exception as exc:
        bot.reply_to(
            message,
            f"Network check error: {exc}"
        )


@bot.message_handler(commands=["events"])
def send_events(message):
    if not is_admin(message.from_user.id):
        return

    if not event_log:
        bot.reply_to(message, "The system event log is empty.")
        return

    recent_events = list(event_log)[-15:]

    text = (
        "Recent System Events and Warnings:\n\n"
        + "\n".join(recent_events)
    )

    bot.reply_to(message, text)


if __name__ == "__main__":
    print("Initializing the PC monitoring bot...")
    # Start the background resource monitoring thread.
    monitor_thread = threading.Thread(
        target=background_monitor,
        daemon=True
    )
    monitor_thread.start()

    print("Monitoring started. Waiting for Telegram commands...")

    try:
        bot.infinity_polling(skip_pending=True)

    except KeyboardInterrupt:
        print("Bot stopped by the user.")

    except Exception as exc:
        print(f"Bot polling error: {exc}")
