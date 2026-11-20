import json
import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from PyQt6.QtCore import QObject, QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QPixmap
from PyQt6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("mobase")


class _UpdateWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    _LATEST_RELEASE_API = "https://api.github.com/repos/J0-o/KOTORganizer/releases/latest"
    _MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

    def __init__(self, action: str, mo2_root: Path | None = None, asset_url: str = "", tag: str = ""):
        super().__init__()
        self._action = action
        self._mo2_root = mo2_root
        self._asset_url = asset_url
        self._tag = tag

    def run(self):
        try:
            if self._action == "check":
                self.finished.emit(self._latest_release())
            elif self._action == "install" and self._mo2_root is not None:
                self._install_release()
                self.finished.emit({"tag": self._tag})
            else:
                raise RuntimeError("Invalid updater action.")
        except Exception as exc:
            self.failed.emit(str(exc))

    @classmethod
    def _request(cls, url: str):
        return Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "KOTORganizer-MO2-Updater/1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    @classmethod
    def _latest_release(cls) -> dict:
        with urlopen(cls._request(cls._LATEST_RELEASE_API), timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        tag = str(payload.get("tag_name") or "").strip()
        assets = payload.get("assets") if isinstance(payload.get("assets"), list) else []
        zip_assets = [
            asset for asset in assets
            if isinstance(asset, dict)
            and str(asset.get("name") or "").lower().endswith(".zip")
            and str(asset.get("browser_download_url") or "").startswith("https://github.com/")
        ]
        preferred = [
            asset for asset in zip_assets
            if str(asset.get("name") or "").lower().startswith("mo2_plugin_kotorganizer_")
        ]
        selected = preferred[0] if len(preferred) == 1 else (zip_assets[0] if len(zip_assets) == 1 else None)
        if not tag:
            raise RuntimeError("The latest GitHub release has no version tag.")
        if selected is None:
            raise RuntimeError("The latest GitHub release does not have one identifiable KOTORganizer MO2 ZIP asset.")
        size = int(selected.get("size") or 0)
        if size <= 0 or size > cls._MAX_DOWNLOAD_BYTES:
            raise RuntimeError("The GitHub release asset has an invalid size.")
        return {
            "tag": tag,
            "name": str(payload.get("name") or tag).strip(),
            "asset_name": str(selected.get("name") or "").strip(),
            "asset_url": str(selected.get("browser_download_url") or "").strip(),
            "asset_size": size,
            "html_url": str(payload.get("html_url") or "").strip(),
        }

    def _install_release(self):
        with tempfile.TemporaryDirectory(prefix="kotorganizer_update_") as temp_dir:
            temp_root = Path(temp_dir)
            archive_path = temp_root / "release.zip"
            self._download(archive_path)
            extract_root = temp_root / "extract"
            self._extract_safely(archive_path, extract_root)
            payload_root = self._find_payload_root(extract_root)
            for folder_name in ("plugins", "stylesheets"):
                source = payload_root / folder_name
                if source.exists():
                    shutil.copytree(source, self._mo2_root / folder_name, dirs_exist_ok=True)

    def _download(self, destination: Path):
        received = 0
        with urlopen(self._request(self._asset_url), timeout=60) as response, destination.open("wb") as output:
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > self._MAX_DOWNLOAD_BYTES:
                raise RuntimeError("The release download is unexpectedly large.")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > self._MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("The release download exceeded the size limit.")
                output.write(chunk)
        if received == 0:
            raise RuntimeError("The release download was empty.")

    @staticmethod
    def _extract_safely(archive_path: Path, extract_root: Path):
        extract_root.mkdir(parents=True, exist_ok=True)
        resolved_root = extract_root.resolve()
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                destination = (extract_root / member.filename).resolve()
                if destination != resolved_root and resolved_root not in destination.parents:
                    raise RuntimeError(f"Unsafe path in release archive: {member.filename}")
            archive.extractall(extract_root)

    @staticmethod
    def _find_payload_root(extract_root: Path) -> Path:
        marker = Path("plugins/basic_games/games/game_kotor.py")
        direct = extract_root / marker
        if direct.is_file():
            return extract_root
        matches = list(extract_root.glob(f"*/{marker.as_posix()}"))
        if len(matches) != 1:
            raise RuntimeError("The release ZIP does not contain the expected KOTORganizer plugin layout.")
        return matches[0].parents[3]


class KotorInfoTab(QWidget):
    _COMMUNITY_PORTAL = (
        "KOTOR Community Portal",
        "https://kotor.neocities.org/",
    )
    _TOOLS = (
        (
            "HoloPatcher",
            "https://github.com/vrifftech/HoloPatcher",
        ),
        (
            "DeadlyScraper",
            "https://github.com/J0-o/DeadlyScraper",
        ),
        (
            "PyZip",
            "https://github.com/Modding-Forge/7z.py",
        ),
        (
            "xxHash",
            "https://github.com/Cyan4973/xxHash",
        ),
    )


    def __init__(self, parent: QWidget | None, organizer, game):
        super().__init__(parent)
        self._organizer = organizer
        self._game = game
        self._plugin_dir = Path(__file__).resolve().parent

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(self._logo_widget(), 0, Qt.AlignmentFlag.AlignCenter)

        version = QLabel(f"{self._game_short_name()} Plugin {self._game_version()}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version, 0, Qt.AlignmentFlag.AlignCenter)
        self._update_btn = QPushButton("Check for Updates")
        self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_btn.setMinimumWidth(220)
        self._update_btn.clicked.connect(self._check_for_updates)
        layout.addWidget(self._update_btn, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(18)

        self._update_thread: QThread | None = None
        self._update_worker: _UpdateWorker | None = None
        self._pending_install_release: dict | None = None

        name, url = self._COMMUNITY_PORTAL
        button = QPushButton(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumWidth(220)
        button.clicked.connect(lambda _checked=False, link=url: QDesktopServices.openUrl(QUrl(link)))
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(18)

        for name, url in self._TOOLS:
            button = QPushButton(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumWidth(220)
            button.clicked.connect(lambda _checked=False, link=url: QDesktopServices.openUrl(QUrl(link)))
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addStretch(1)


    def _logo_widget(self) -> QLabel:
        label = QLabel("KOTORganizer")
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        logo_path = self._logo_path()
        if logo_path is not None:
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                label.setText("")
                label.setPixmap(
                    pixmap.scaledToHeight(
                        56,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                label.setToolTip(str(logo_path))
                return label

        logo_font = QFont()
        logo_font.setPointSize(18)
        logo_font.setBold(True)
        label.setFont(logo_font)
        return label


    def _logo_path(self) -> Path | None:
        candidates = (
            "logo.png",
            "kotorganizer.png",
            "kotor_organizer.png",
            "kotor-logo.png",
            "kotor_logo.png",
        )
        search_dirs = (self._plugin_dir, self._plugin_dir.parent)
        for directory in search_dirs:
            for name in candidates:
                path = directory / name
                if path.exists():
                    return path
        for directory in search_dirs:
            matches = sorted(directory.glob("*.png"))
            if matches:
                return matches[0]
        return None


    def _game_short_name(self) -> str:
        try:
            return str(self._game.gameShortName())
        except Exception:
            return str(getattr(self._game, "GameShortName", "KOTOR"))


    def _game_version(self) -> str:
        try:
            version = self._game.version()
            for attr in ("canonicalString", "displayString"):
                method = getattr(version, attr, None)
                if callable(method):
                    return str(method())
            return str(version)
        except Exception:
            return str(getattr(self._game, "Version", ""))


    def _check_for_updates(self):
        if self._update_thread is not None:
            return
        self._update_btn.setEnabled(False)
        self._update_btn.setText("Checking...")
        self._start_update_worker(_UpdateWorker("check"), self._finish_update_check)


    def _finish_update_check(self, release: dict):
        current = self._version_key(self._game_version())
        latest = self._version_key(str(release.get("tag") or ""))
        logger.info(
            f"[KOTORganizer Update] Update check succeeded: installed {self._game_version()}, "
            f"latest {release.get('tag')}."
        )
        if latest <= current:
            QMessageBox.information(
                self,
                "KOTORganizer Update",
                f"KOTORganizer {self._game_version()} is up to date.\nLatest release: {release.get('tag')}",
            )
            return
        response = QMessageBox.question(
            self,
            "KOTORganizer Update Available",
            "\n".join(
                [
                    f"KOTORganizer {release.get('tag')} is available.",
                    f"Installed version: {self._game_version()}",
                    "",
                    "Download and install it now?",
                ]
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            self._pending_install_release = release


    def _install_update(self, release: dict):
        self._update_btn.setEnabled(False)
        self._update_btn.setText("Installing...")
        worker = _UpdateWorker(
            "install",
            mo2_root=self._mo2_root(),
            asset_url=str(release.get("asset_url") or ""),
            tag=str(release.get("tag") or ""),
        )
        self._start_update_worker(worker, self._finish_update_install)


    def _finish_update_install(self, result: dict):
        logger.info(f"[KOTORganizer Update] Successfully installed {result.get('tag')}.")
        QMessageBox.information(
            self,
            "KOTORganizer Update Installed",
            f"KOTORganizer {result.get('tag')} was installed.\n\nClose and restart Mod Organizer 2 to load the update.",
        )


    def _start_update_worker(self, worker: _UpdateWorker, finished_callback):
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(finished_callback)
        worker.finished.connect(thread.quit)
        worker.failed.connect(self._fail_update)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_update_worker)
        self._update_thread = thread
        self._update_worker = worker
        thread.start()


    def _fail_update(self, message: str):
        self._pending_install_release = None
        logger.warning(f"[KOTORganizer Update] Update failed: {message}")
        QMessageBox.warning(self, "KOTORganizer Update Failed", message)


    def _clear_update_worker(self):
        self._update_thread = None
        self._update_worker = None
        self._update_btn.setEnabled(True)
        self._update_btn.setText("Check for Updates")
        pending_release = self._pending_install_release
        self._pending_install_release = None
        if pending_release is not None:
            self._install_update(pending_release)


    def _mo2_root(self) -> Path:
        return self._plugin_dir.parents[3]


    @staticmethod
    def _version_key(value: str) -> tuple[int, ...]:
        parts = [int(part) for part in re.findall(r"\d+", value)]
        return tuple((parts + [0, 0, 0])[:3])
