# PyInstaller spec for Dynamic Load Test (Windows desktop build).
#   .venv\Scripts\pyinstaller build.spec
# Produces dist\DynamicLoadTest\DynamicLoadTest.exe (one-folder build).
# For a single-file exe, add onefile handling — one-folder is used here for
# faster startup and easier troubleshooting on the bench PC.

datas = [
    ("configs", "configs"),
    ("reporting/mapping.example.yaml", "reporting"),
    ("reporting/templates", "reporting/templates"),
]

hiddenimports = [
    "pyvisa",
    "pypdf",
    "PIL.Image",
    "PIL.ImageDraw",
    "testtypes.dynamic_output_response",
    "testtypes.vds_turnoff",
    "testtypes.vds_ovp",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DynamicLoadTest",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no console window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DynamicLoadTest",
)
