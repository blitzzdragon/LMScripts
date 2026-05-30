#!/usr/bin/env python3
import os
import subprocess
import time

import dbus
import psutil
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

SCHEMA = "org.cinnamon.desktop.notifications"
KEY = "display-notifications"


class SpotifyBlocker:
    def __init__(self):
        self.spotify_active = False
        self.heartbeat()

    def is_process_running(self):
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info["name"] or "").lower()
                cmd = " ".join(proc.info["cmdline"] or "").lower()
                if "spotify" in name or "spotify" in cmd:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    def set_notification_state(self, spotify_is_on):
        if self.spotify_active == spotify_is_on:
            return

        self.spotify_active = spotify_is_on

        if spotify_is_on:
            self.notify("Spotify Mode", "Do Not Disturb active.")
            time.sleep(0.5)
            os.system(f"gsettings set {SCHEMA} {KEY} false")
            print("[!] Spotify detected: Notifications Disabled.")
        else:
            os.system(f"gsettings set {SCHEMA} {KEY} true")
            time.sleep(0.5)
            self.notify("Spotify Closed", "Do Not Disturb Disabled.")
            print("[+] Spotify closed: Notifications Enabled.")

    def notify(self, title, msg):
        subprocess.run(
            [
                "notify-send",
                title,
                msg,
                "--hint=int:transient:1",
                "-i",
                "spotify-client",
            ]
        )

    def on_name_owner_changed(self, name, old_owner, new_owner):
        if "org.mpris.MediaPlayer2.spotify" in name:
            self.set_notification_state(bool(new_owner))

    def heartbeat(self):
        self.set_notification_state(self.is_process_running())
        return True


def main():
    DBusGMainLoop(set_as_default=True)
    blocker = SpotifyBlocker()

    bus = dbus.SessionBus()
    bus.add_signal_receiver(
        blocker.on_name_owner_changed,
        dbus_interface="org.freedesktop.DBus",
        signal_name="NameOwnerChanged",
    )

    GLib.timeout_add_seconds(5, blocker.heartbeat)

    print("Spotify Blocker (Visual Feedback Mode) is active.")
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        os.system(f"gsettings set {SCHEMA} {KEY} true")
    finally:
        os.system(f"gsettings set {SCHEMA} {KEY} true")


if __name__ == "__main__":
    main()
