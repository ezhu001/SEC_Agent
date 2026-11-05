from pathlib import Path

APPLE_HTML = Path(__file__).parent / "fixtures" / "apple_2025_10k.html"
NOTEBOOK_SHA256 = "d44419f05b5baf1aa3565bc0ec7476f5a659a34ea5d9e2d2443b507b0919fe94"
DEVELOPMENT_REFERENCES = {
    "revenue_growth": (6.425511782832739, 0.10),
    "operating_margin_change": (0.4605768925163183, 0.10),
    "current_ratio_change": (0.025980345684583517, 0.01),
}
