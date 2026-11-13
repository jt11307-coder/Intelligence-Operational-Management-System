"""Product constants. None of these are secrets."""

PRODUCT_NAME = "WPD COMPSTAT Intelligence & Operational Management System"
SHORT_NAME = "WPD COMPSTAT"
INSTALL_FOLDER_NAME = "WPD COMPSTAT"
MANIFEST_NAME = "WPD-COMPSTAT-INSTALL.json"
LAYOUT_VERSION = 1
KEY_CHECK_PLAINTEXT = b"WPD-COMPSTAT-KEY-CHECK"
FILE_MAGIC = b"WPDC1\x00"
AAD_FILE = b"wpd-compstat-file-v1"
AAD_DEK = b"wpd-compstat-dek-v1"
AAD_CHECK = b"wpd-compstat-password-check-v1"
KDF_N = 2**14
KDF_R = 8
KDF_P = 1
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
DEFAULT_SESSION_MINUTES = 15
MIN_PASSWORD_LENGTH = 12
PERCENT_MIN_BASELINE = 5
SAME_DRIVE_BACKUP_WARNING = (
    "Backups stored on this external drive do not protect against loss, "
    "theft, or failure of the drive. Copy encrypted backups to a separately "
    "approved location."
)
ENTRY_RELATIVE_PATH = "Application/ENTRY"
SOURCE_PACKAGING = "source"
WINDOWS_PACKAGING = "windows_executable"

FOLDERS = (
    "Application",
    "Launcher",
    "Database",
    "Source PDFs",
    "Imports",
    "Reports",
    "Presentations",
    "Maps",
    "Backups",
    "Audit",
    "Configuration",
    "Documentation",
    "Working",
    "Logs",
)

ROLES = (
    "administrator",
    "crime_analyst",
    "command_staff",
    "supervisor",
    "read_only",
)

ASSIGNMENT_STATUSES = (
    "proposed",
    "approved",
    "assigned",
    "in_progress",
    "awaiting_resources",
    "completed",
    "effective",
    "partially_effective",
    "ineffective",
    "closed",
    "reopened",
)

UNRESOLVED_ASSIGNMENT_STATUSES = frozenset(
    {"proposed", "approved", "assigned", "in_progress", "awaiting_resources", "reopened"}
)

AGENCY_CODES = ("1500G", "1500K", "0200", "02", "KCMH")

ACCIDENT_CATEGORIES = frozenset(
    {
        "motor_vehicle_accident",
        "property_damage_accident",
        "injury_accident",
        "fatal_accident",
        "hit_and_run",
        "pedestrian_accident",
        "bicycle_accident",
        "motorcycle_accident",
        "dui_accident",
    }
)

INJURY_ACCIDENT_CATEGORIES = frozenset({"injury_accident", "fatal_accident"})
