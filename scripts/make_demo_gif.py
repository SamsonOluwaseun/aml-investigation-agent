"""Record an animated demo GIF of the AML investigator review screen.

Captures five representative steps from the Streamlit review screen using
the Chrome DevTools Protocol (CDP) driven over a local Chromium browser:
1. Investigation queue with synthetic data banner.
2. Case view for C-001 with summary and cited claims.
3. Interactive inspection of a cited banking transaction record.
4. Completed investigator decision form with mandatory rationale.
5. Saved human decision confirmation and case audit history.

Owner: Antigravity · Build plan: item 11 · Issue: #12
"""

import argparse
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Optional
import urllib.request

from PIL import Image


# Default browser candidate paths for Microsoft Edge and Google Chrome
def get_default_browser_candidates() -> list[str]:
    """Return default candidate paths for Edge and Chrome across platforms."""
    candidates: list[str] = []

    # Windows standard directories
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    # Microsoft Edge on Windows
    candidates.append(os.path.join(prog_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"))
    candidates.append(os.path.join(prog_files, "Microsoft", "Edge", "Application", "msedge.exe"))
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "Microsoft", "Edge", "Application", "msedge.exe"))

    # Google Chrome on Windows
    candidates.append(os.path.join(prog_files, "Google", "Chrome", "Application", "chrome.exe"))
    candidates.append(os.path.join(prog_files_x86, "Google", "Chrome", "Application", "chrome.exe"))
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"))

    # macOS standard locations
    candidates.append("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
    candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    # Command names resolvable via PATH (Linux / BSD / container environments)
    candidates.extend([
        "msedge",
        "microsoft-edge",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    ])
    return candidates


def find_browser_path(
    override: Optional[str] = None,
    candidate_paths: Optional[list[str]] = None,
) -> str:
    """Find a Chromium browser executable (Microsoft Edge or Google Chrome).

    Args:
        override: Explicit path or command name to browser executable.
        candidate_paths: Optional list of candidate paths to search.

    Returns:
        Resolved absolute path to the browser executable.

    Raises:
        FileNotFoundError: If no browser executable is found.
    """
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path.resolve())
        which_path = shutil.which(override)
        if which_path:
            return str(Path(which_path).resolve())
        raise FileNotFoundError(f"Specified browser executable not found: {override}")

    candidates = candidate_paths if candidate_paths is not None else get_default_browser_candidates()
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path.resolve())
        which_path = shutil.which(candidate)
        if which_path:
            return str(Path(which_path).resolve())

    raise FileNotFoundError(
        "No Chromium browser (Microsoft Edge or Google Chrome) was found. "
        "Please ensure Edge or Chrome is installed, or pass the browser path with --browser PATH."
    )


def get_free_port() -> int:
    """Find and return an unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def copy_db_to_temp(source_db: str | Path, temp_dir: str | Path) -> Path:
    """Copy source database to a temporary directory for safe review interaction.

    This ensures that recording a decision in the demo never touches the original bank DB.

    Args:
        source_db: Path to the original SQLite bank database.
        temp_dir: Temporary directory where the copy will reside.

    Returns:
        Path to the copied bank.db file.
    """
    src = Path(source_db).resolve()
    dst_dir = Path(temp_dir).resolve()
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "bank.db"
    shutil.copy2(src, dst)
    return dst


def assemble_gif(
    images: list[Image.Image],
    out_path: str | Path,
    target_width: int = 1000,
    duration_ms: int = 2500,
) -> Path:
    """Resize images to target width and save as an optimised animated GIF.

    Args:
        images: List of PIL images to include in the GIF.
        out_path: Destination file path for the GIF.
        target_width: Target width in pixels (height scales proportionally).
        duration_ms: Frame display duration in milliseconds.

    Returns:
        Resolved Path to the saved GIF file.
    """
    if not images:
        raise ValueError("At least one image is required to assemble a GIF.")

    frames: list[Image.Image] = []
    resample_filter = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)

    for img in images:
        rgb_img = img.convert("RGB") if img.mode != "RGB" else img
        w, h = rgb_img.size
        if w != target_width:
            new_h = int(round(h * (target_width / w)))
            resized = rgb_img.resize((target_width, new_h), resample_filter)
        else:
            resized = rgb_img.copy()

        # Convert to palette mode with adaptive colour quantization
        palette_mode = getattr(getattr(Image, "Palette", Image), "ADAPTIVE", Image.ADAPTIVE)
        quantized = resized.convert("P", palette=palette_mode, colors=256)
        frames.append(quantized)

    destination = Path(out_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    frames[0].save(
        destination,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )
    return destination


class CDPClient:
    """Chrome DevTools Protocol client over a WebSocket connection."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self._next_id: int = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        """Continuously read messages from the WebSocket and resolve pending requests."""
        import websockets.exceptions

        try:
            while True:
                try:
                    msg = await self.ws.recv()
                except websockets.exceptions.ConnectionClosed:
                    break
                if isinstance(msg, bytes):
                    msg = msg.decode("utf-8")
                try:
                    data = json.loads(msg)
                except Exception:
                    continue

                msg_id = data.get("id")
                if msg_id is not None and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        fut.set_result(data)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(exc)

    async def call(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a CDP command and await its response."""
        msg_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[msg_id] = fut

        payload: dict[str, Any] = {"id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params

        await self.ws.send(json.dumps(payload))
        try:
            resp = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise TimeoutError(f"CDP call '{method}' timed out after {timeout:.1f} seconds")

        if "error" in resp:
            err = resp["error"]
            err_msg = err.get("message", str(err))
            raise RuntimeError(f"CDP command '{method}' failed: {err_msg}")

        return resp.get("result", {})

    async def evaluate(self, expression: str, timeout: float = 30.0) -> Any:
        """Evaluate a JavaScript expression in the page and return the result value."""
        res = await self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
            timeout=timeout,
        )
        if "exceptionDetails" in res:
            details = res["exceptionDetails"]
            exc = details.get("exception", {})
            desc = exc.get("description") or exc.get("value") or details.get("text", "JS exception")
            raise RuntimeError(f"JavaScript evaluation failed: {desc}")
        val_obj = res.get("result", {})
        return val_obj.get("value")

    async def capture_screenshot(self, timeout: float = 30.0) -> Image.Image:
        """Capture a screenshot of the visible viewport and return as a PIL Image."""
        res = await self.call("Page.captureScreenshot", {"format": "png"}, timeout=timeout)
        data_b64 = res.get("data")
        if not data_b64:
            raise RuntimeError("Page.captureScreenshot returned empty data")
        raw_bytes = base64.b64decode(data_b64)
        img = Image.open(io.BytesIO(raw_bytes))
        return img.convert("RGB")

    async def close(self) -> None:
        """Close the WebSocket connection and cancel the reader loop."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        try:
            await self.ws.close()
        except Exception:
            pass


def get_browser_ws_url(cdp_port: int, timeout: float = 15.0) -> str:
    """Fetch the DevTools WebSocket target URL from Chromium."""
    url = f"http://127.0.0.1:{cdp_port}/json"
    start_time = time.monotonic()
    last_err: Optional[Exception] = None
    while (time.monotonic() - start_time) < timeout:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "demo-gif-recorder"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list) and len(data) > 0:
                    for target in data:
                        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                            return str(target["webSocketDebuggerUrl"])
                    for target in data:
                        if target.get("webSocketDebuggerUrl"):
                            return str(target["webSocketDebuggerUrl"])
        except Exception as err:
            last_err = err
        time.sleep(0.3)

    # Fallback to create a new page target if list was empty
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{cdp_port}/json/new", method="PUT")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("webSocketDebuggerUrl"):
                return str(data["webSocketDebuggerUrl"])
    except Exception as err:
        last_err = err

    raise RuntimeError(
        f"Could not connect to browser DevTools on port {cdp_port} within {timeout} seconds: {last_err}"
    )


def wait_for_http(
    url: str,
    proc: subprocess.Popen,
    timeout: float = 30.0,
    temp_dir: Optional[Path] = None,
) -> None:
    """Poll an HTTP URL until it returns 200 OK or the process exits."""
    start_time = time.monotonic()
    last_err: Optional[Exception] = None
    while (time.monotonic() - start_time) < timeout:
        if proc.poll() is not None:
            log_output = ""
            if temp_dir:
                log_file = temp_dir / "streamlit.log"
                if log_file.is_file():
                    try:
                        log_output = log_file.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass
            raise RuntimeError(
                f"Streamlit application process exited prematurely (exit code {proc.returncode}).\n"
                f"Process output:\n{log_output}"
            )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "demo-gif-recorder"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except Exception as err:
            last_err = err
        time.sleep(0.5)

    raise TimeoutError(f"Timed out waiting for Streamlit to respond at {url} within {timeout} seconds: {last_err}")


def terminate_process(proc: Optional[subprocess.Popen], name: str = "Process") -> None:
    """Safely terminate a subprocess with escalation to kill."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)
    except Exception:
        pass


async def wait_for_page_text(cdp: CDPClient, text: str, timeout: float = 20.0) -> None:
    """Wait until an element containing the specified text is present in the document."""
    start_time = time.monotonic()
    escaped = json.dumps(text)
    js = f"Boolean(document.body && document.body.innerText.includes({escaped}))"
    while (time.monotonic() - start_time) < timeout:
        res = await cdp.evaluate(js)
        if res is True:
            return
        await asyncio.sleep(0.3)
    raise TimeoutError(f"Timed out waiting for text '{text}' on page after {timeout} seconds")


async def wait_for_streamlit_settled(
    cdp: CDPClient,
    timeout: float = 15.0,
    settle_delay: float = 0.8,
) -> None:
    """Wait for Streamlit running indicators to clear and rendering to settle."""
    # Allow React and Streamlit websocket a moment to register changes
    await asyncio.sleep(0.4)
    start_time = time.monotonic()
    check_js = """
    (() => {
        const widget = document.querySelector('[data-testid="stStatusWidget"]');
        if (!widget) return true;
        const style = window.getComputedStyle(widget);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            return true;
        }
        const text = (widget.innerText || '').toLowerCase();
        return !text.includes('running') && !text.includes('stop');
    })()
    """
    while (time.monotonic() - start_time) < timeout:
        res = await cdp.evaluate(check_js)
        if res is True:
            break
        await asyncio.sleep(0.2)
    # Give the DOM an extra settle delay for stable layout and rendering
    await asyncio.sleep(settle_delay)


async def record_demo_session(
    ws_url: str,
    app_port: int,
) -> list[Image.Image]:
    """Drive browser through review flow over CDP and capture the five demo frames."""
    from websockets.asyncio.client import connect

    print(f"Connecting to browser DevTools at {ws_url}...")
    ws = await connect(ws_url, max_size=50 * 1024 * 1024)
    cdp = CDPClient(ws)
    try:
        await cdp.call("Page.enable")
        # Headless pages are never focused, so focus and blur events would not fire
        await cdp.call("Emulation.setFocusEmulationEnabled", {"enabled": True})

        # Frame 1: Page loaded: banner and investigation queue
        print("Step 1/5: Loading page and capturing investigation queue...")
        app_url = f"http://127.0.0.1:{app_port}/"
        await cdp.call("Page.navigate", {"url": app_url})
        await wait_for_page_text(cdp, "AML Investigator Review Screen")
        await wait_for_streamlit_settled(cdp)
        # Hide the sidebar: it shows local file paths, which do not belong in a public GIF
        await cdp.evaluate("""
        (() => {
            const style = document.createElement('style');
            style.textContent = '[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }';
            document.head.appendChild(style);
            return true;
        })()
        """)
        await asyncio.sleep(0.5)
        await cdp.evaluate("window.scrollTo(0, 0);")
        await asyncio.sleep(0.5)
        frame1 = await cdp.capture_screenshot()
        print("  Captured frame 1: Banner and investigation queue.")

        # Frame 2: Scroll to case view for C-001: summary and cited claims
        print("Step 2/5: Scrolling to case view for C-001 (summary and cited claims)...")
        await cdp.evaluate("""
        (() => {
            const headings = [...document.querySelectorAll('h2, h3, [data-testid="stHeading"]')];
            const h = headings.find(el => el.innerText && el.innerText.includes('Case Summary'));
            if (!h) throw new Error('Heading "Case Summary" not found');
            h.scrollIntoView({ block: 'start' });
            window.scrollBy(0, -60);
            return true;
        })()
        """)
        await asyncio.sleep(0.8)
        frame2 = await cdp.capture_screenshot()
        print("  Captured frame 2: Case summary and cited claims.")

        # Frame 3: Click first source-ID button (starts with "📄 T-") and capture inspected record
        print("Step 3/5: Inspecting first cited transaction record...")
        clicked_text = await cdp.evaluate("""
        (() => {
            const buttons = [...document.querySelectorAll('button')];
            const btn = buttons.find(b => b.innerText && b.innerText.includes('📄 T-'));
            if (!btn) throw new Error('First source-ID button starting with "📄 T-" not found');
            btn.click();
            return btn.innerText.trim();
        })()
        """)
        print(f"  Clicked source button: {clicked_text}")
        await wait_for_streamlit_settled(cdp)
        await wait_for_page_text(cdp, "Inspected Record")
        await cdp.evaluate("""
        (() => {
            const headings = [...document.querySelectorAll('h3, h4, [data-testid="stHeading"]')];
            const recH = headings.find(h => h.innerText && h.innerText.includes('Inspected Record'));
            if (recH) {
                recH.scrollIntoView({ block: 'start' });
                window.scrollBy(0, -60);
            }
            return true;
        })()
        """)
        await asyncio.sleep(0.8)
        frame3 = await cdp.capture_screenshot()
        print("  Captured frame 3: Inspected banking transaction record.")

        # Frame 4: Scroll to decision form, choose Escalate, fill reason and investigator name
        print("Step 4/5: Recording investigator decision (Escalate)...")
        await cdp.evaluate("""
        (() => {
            const headings = [...document.querySelectorAll('h2, h3, [data-testid="stHeading"]')];
            const decH = headings.find(h => h.innerText && h.innerText.includes('Investigator Decision'));
            if (!decH) throw new Error('"Investigator Decision" heading not found');
            decH.scrollIntoView({ block: 'start' });
            window.scrollBy(0, -60);
            return true;
        })()
        """)
        await asyncio.sleep(0.5)

        # Select Escalate radio option
        await cdp.evaluate("""
        (() => {
            const labels = [...document.querySelectorAll('label')];
            const escalateLabel = labels.find(l => l.innerText && l.innerText.includes('Escalate'));
            if (!escalateLabel) throw new Error('Radio option "Escalate" not found');
            const radioInput = escalateLabel.querySelector('input[type="radio"]');
            if (radioInput) {
                radioInput.click();
            } else {
                escalateLabel.click();
            }
            return true;
        })()
        """)
        await wait_for_streamlit_settled(cdp)

        # Fill Reason and Investigator Name by focusing each field and typing
        # through CDP (Input.insertText). Setting values from JavaScript does not
        # reach Streamlit's React state; real input plus a blur does.
        reason_val = "Sanctions matches on two new payees; escalating for review."
        investigator_val = "Demo Investigator"

        await cdp.evaluate("""
        (() => {
            const ta = document.querySelector('section.main textarea, [data-testid="stMain"] textarea')
                || document.querySelector('textarea');
            if (!ta) throw new Error('Decision reason textarea not found');
            ta.focus();
            return true;
        })()
        """)
        await cdp.call("Input.insertText", {"text": reason_val})
        await cdp.evaluate("""
        (() => {
            const inputs = [...document.querySelectorAll('input[type="text"]')]
                .filter(i => !i.closest('[data-testid="stSidebar"]'));
            const nameInput = inputs.find(i => (i.getAttribute('aria-label') || '').includes('Investigator Name')
                || (i.placeholder || '').includes('Smith')) || inputs[inputs.length - 1];
            if (!nameInput) throw new Error('Investigator name input not found');
            nameInput.focus();  // blurs the textarea, which commits it
            return true;
        })()
        """)
        await wait_for_streamlit_settled(cdp)
        await cdp.call("Input.insertText", {"text": investigator_val})
        for event_type in ("keyDown", "keyUp"):  # Enter commits a text input
            await cdp.call("Input.dispatchKeyEvent", {
                "type": event_type, "key": "Enter", "code": "Enter",
                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                **({"text": "\r"} if event_type == "keyDown" else {}),
            })
        await wait_for_streamlit_settled(cdp)

        # Scroll to keep the filled form and Save Decision button in view
        await cdp.evaluate("""
        (() => {
            const headings = [...document.querySelectorAll('h2, h3, [data-testid="stHeading"]')];
            const decH = headings.find(h => h.innerText && h.innerText.includes('Investigator Decision'));
            if (decH) {
                decH.scrollIntoView({ block: 'start' });
                window.scrollBy(0, -60);
            }
            return true;
        })()
        """)
        await asyncio.sleep(0.8)
        frame4 = await cdp.capture_screenshot()
        print("  Captured frame 4: Completed decision form.")

        # Frame 5: Click Save Decision and capture success message & audit history
        print("Step 5/5: Submitting decision and capturing confirmation...")
        await cdp.evaluate("""
        (() => {
            const buttons = [...document.querySelectorAll('button')];
            const saveBtn = buttons.find(b => b.innerText && b.innerText.includes('Save Decision'));
            if (!saveBtn) throw new Error('Button "Save Decision" not found');
            saveBtn.click();
            return true;
        })()
        """)
        await wait_for_streamlit_settled(cdp)
        await wait_for_page_text(cdp, "Decision recorded successfully")

        # Scroll to show success confirmation and Decision History
        await cdp.evaluate("""
        (() => {
            const headings = [...document.querySelectorAll('h2, h3, [data-testid="stHeading"]')];
            const histH = headings.find(h => h.innerText && h.innerText.includes('Decision History'));
            if (histH) {
                histH.scrollIntoView({ block: 'center' });
                return true;
            }
            return true;
        })()
        """)
        await asyncio.sleep(0.8)
        frame5 = await cdp.capture_screenshot()
        print("  Captured frame 5: Decision confirmation and audit history.")

        return [frame1, frame2, frame3, frame4, frame5]
    finally:
        await cdp.close()


def parse_args(args: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Record an animated demo GIF of the AML investigator review screen."
    )
    parser.add_argument(
        "--db",
        default="bank/bank.db",
        help="Path to source SQLite bank database (default: bank/bank.db)",
    )
    parser.add_argument(
        "--cases",
        default="docs/samples/cases",
        help="Path to directory containing case JSON files (default: docs/samples/cases)",
    )
    parser.add_argument(
        "--usage",
        default="docs/samples/usage.sample.jsonl",
        help="Path to token usage JSONL log (default: docs/samples/usage.sample.jsonl)",
    )
    parser.add_argument(
        "--out",
        default="docs/demo/demo.gif",
        help="Output path for the animated GIF (default: docs/demo/demo.gif)",
    )
    parser.add_argument(
        "--browser",
        default=None,
        help="Path to Chromium browser executable (defaults to auto-detecting Edge or Chrome)",
    )
    return parser.parse_args(args)


def main(argv: Optional[list[str]] = None) -> int:
    """Run the demo recording pipeline and assemble the output GIF."""
    args = parse_args(argv)

    # 1. Validate inputs
    source_db = Path(args.db).resolve()
    if not source_db.is_file():
        print(
            f"Error: Database file not found at '{args.db}'.\n"
            "Please generate the bank database first:\n"
            "  python bank/generate.py\n"
            "  python rules/run_rules.py",
            file=sys.stderr,
        )
        return 1

    cases_dir = Path(args.cases).resolve()
    if not cases_dir.is_dir():
        print(f"Error: Cases directory not found at '{args.cases}'.", file=sys.stderr)
        return 1

    usage_file = Path(args.usage).resolve()
    if not usage_file.is_file():
        print(f"Error: Usage log file not found at '{args.usage}'.", file=sys.stderr)
        return 1

    # 2. Locate browser executable
    try:
        browser_path = find_browser_path(override=args.browser)
        print(f"Using browser: {browser_path}")
    except FileNotFoundError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    repo_root = Path(__file__).resolve().parents[1]
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="aml_demo_")
    temp_dir = Path(temp_dir_obj.name)

    app_proc: Optional[subprocess.Popen] = None
    browser_proc: Optional[subprocess.Popen] = None
    streamlit_log_fp = None
    browser_log_fp = None

    try:
        # 3. Copy DB to temp directory so real DB is never modified
        temp_db = copy_db_to_temp(source_db, temp_dir)
        print(f"Copied database to temporary location: {temp_db}")

        # 4. Prepare ports and environment
        app_port = get_free_port()
        cdp_port = get_free_port()
        while cdp_port == app_port:
            cdp_port = get_free_port()

        app_env = os.environ.copy()
        app_env["AML_BANK_DB"] = str(temp_db)
        app_env["AML_CASES_DIR"] = str(cases_dir)
        app_env["AML_USAGE_LOG"] = str(usage_file)
        if "PYTHONPATH" in app_env:
            app_env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{app_env['PYTHONPATH']}"
        else:
            app_env["PYTHONPATH"] = str(repo_root)

        # 5. Start Streamlit app
        print(f"Starting Streamlit review app on port {app_port}...")
        streamlit_log_fp = open(temp_dir / "streamlit.log", "w", encoding="utf-8")
        app_cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "ui/app.py",
            "--server.headless",
            "true",
            "--server.port",
            str(app_port),
            "--browser.gatherUsageStats",
            "false",
            "--client.toolbarMode",
            "minimal",
        ]
        app_proc = subprocess.Popen(
            app_cmd,
            cwd=str(repo_root),
            env=app_env,
            stdout=streamlit_log_fp,
            stderr=streamlit_log_fp,
        )

        app_url = f"http://127.0.0.1:{app_port}/"
        wait_for_http(app_url, app_proc, timeout=30.0, temp_dir=temp_dir)
        print(f"Streamlit application is ready at {app_url}")

        # 6. Start headless browser with CDP debugging enabled
        browser_user_data = temp_dir / "browser_profile"
        browser_user_data.mkdir(parents=True, exist_ok=True)
        browser_cmd = [
            browser_path,
            "--headless=new",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={browser_user_data}",
            "--window-size=1400,1000",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ]
        browser_log_fp = open(temp_dir / "browser.log", "w", encoding="utf-8")
        browser_proc = subprocess.Popen(
            browser_cmd,
            stdout=browser_log_fp,
            stderr=browser_log_fp,
        )

        # 7. Obtain CDP WebSocket URL
        ws_url = get_browser_ws_url(cdp_port, timeout=15.0)

        # 8. Record frames over CDP session
        frames = asyncio.run(record_demo_session(ws_url, app_port))

        # 9. Assemble animated GIF
        out_path = Path(args.out).resolve()
        print(f"Assembling animated GIF: {out_path} (width 1000 px, 2.5 s/frame)...")
        saved_file = assemble_gif(frames, out_path, target_width=1000, duration_ms=2500)

        size_bytes = saved_file.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        print(f"Done: Demo GIF saved successfully to {saved_file} ({size_mb:.2f} MB, {len(frames)} frames)")
        if size_mb > 5.0:
            print(f"Warning: Output file size ({size_mb:.2f} MB) exceeds 5 MB target.", file=sys.stderr)
        return 0

    except Exception as exc:
        print(f"\nError recording demo GIF: {exc}", file=sys.stderr)
        return 1

    finally:
        terminate_process(browser_proc, "Browser")
        terminate_process(app_proc, "Streamlit")
        if browser_log_fp is not None:
            try:
                browser_log_fp.close()
            except Exception:
                pass
        if streamlit_log_fp is not None:
            try:
                streamlit_log_fp.close()
            except Exception:
                pass
        try:
            temp_dir_obj.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
