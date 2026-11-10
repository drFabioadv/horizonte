"""Notificações do Windows (opcionais). Em outros sistemas, apenas registra no log."""
from __future__ import annotations

import platform
import subprocess
from xml.sax.saxutils import escape

_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{body}</text></binding></visual></toast>')
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('HORIZONTE').Show($toast)
"""


_TRAY = None


def set_tray(icon) -> None:
    """Quando o HORIZONTE roda na bandeja, os avisos saem pelo próprio ícone."""
    global _TRAY
    _TRAY = icon


def notify(hz, title: str, body: str) -> None:
    if not hz.prefs().get("notificacoes_windows"):
        return
    if _TRAY is not None:
        try:
            _TRAY.notify(body[:250], title[:60])
            return
        except Exception:
            pass
    if platform.system() != "Windows":
        return
    script = _PS.replace("{title}", escape(title).replace("'", "''")).replace("{body}", escape(body).replace("'", "''"))
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        pass
