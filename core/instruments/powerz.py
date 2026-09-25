"""POWER-Z KM003C/KM002C PD profile selector.

Three control paths (unchanged behaviour from the original CLI tool, but the
manual pause is now delivered through an injected prompt callback so it can be a
GUI dialog instead of a blocking input() on the terminal):

1. manual (default, always works)
   Asks the operator to trigger the PD voltage (on the tester or in the POWER-Z
   PC software), then waits for confirmation. Because the PD profile is the
   OUTER loop, this happens only once per output voltage.

2. gui (works, needs one-time calibration)
   Automates the official POWER-Z Windows software with pyautogui by clicking
   saved screen coordinates. Record them once via the calibrate() helper.

3. usb (not implemented)
   The KM003C USB protocol is partly reverse-engineered by the community, but
   scripted PD *trigger* commands are not reliably documented yet.

`prompt_fn(message: str) -> None` is supplied by the caller. It must block until
the operator confirms, and may raise to abort the run. If not supplied, manual
mode falls back to the terminal input().
"""
import json
import os
import time

CALIB_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "powerz_buttons.json")


class PowerZ:
    role = "powerz"

    def __init__(self, mode="manual", prompt_fn=None):
        self.mode = mode
        self.prompt_fn = prompt_fn
        if mode == "gui":
            import pyautogui  # noqa: F401  (fail early if missing)
            if not os.path.exists(CALIB_FILE):
                raise FileNotFoundError(
                    "powerz_buttons.json not found. Run POWER-Z calibration first."
                )
            with open(CALIB_FILE) as f:
                self.buttons = json.load(f)

    def request_profile(self, label, voltage):
        if self.mode == "manual":
            message = (f"Set the POWER-Z decoy to {label} ({voltage} V), confirm the "
                       f"DUT output changed, then continue.")
            if self.prompt_fn is not None:
                self.prompt_fn(message)
            else:
                input(f"\n>>> {message} Press Enter... ")
        elif self.mode == "gui":
            import pyautogui
            if label not in self.buttons:
                raise KeyError(f"No calibrated button for profile '{label}'")
            x, y = self.buttons[label]
            pyautogui.click(x, y)
            time.sleep(2.0)  # allow PD renegotiation
            print(f"[Power-Z] clicked {label} button at ({x},{y})")
        else:
            raise ValueError(f"Unknown powerz mode: {self.mode}")

    def close(self):
        """No persistent connection in manual/gui modes."""
        pass


def calibrate(profiles, out_file=CALIB_FILE):
    """Interactive one-time recording of button coordinates in the POWER-Z app.

    Kept as a standalone helper; the GUI exposes it as a guided wizard later.
    """
    import pyautogui
    print("Open the POWER-Z software, go to the Power Delivery trigger menu,")
    print("and keep the window in its final position (maximized recommended).\n")
    buttons = {}
    for p in profiles:
        input(f"Hover your mouse over the '{p}' voltage button, then press Enter here...")
        pos = pyautogui.position()
        buttons[p] = [pos.x, pos.y]
        print(f"  recorded {p} -> ({pos.x}, {pos.y})")
    with open(out_file, "w") as f:
        json.dump(buttons, f, indent=2)
    print(f"\nSaved to {out_file}. Set powerz.mode: gui in the config to use it.")
