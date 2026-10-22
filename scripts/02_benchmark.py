"""Step 2: render the master plan pages that show the drainage service areas
and existing-condition surface flooding to PNG in outputs/benchmark/.

Page numbers are 1-based PDF page indices (not the printed page numbers).
Run with:  conda run -n pluvial python scripts/02_benchmark.py
"""
import csv
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "data" / "raw" / "benchmark"
OUT = ROOT / "outputs" / "benchmark"
DPI = 150

TMR = "storm-drainage-master-plan-technical-modelling-report-final.pdf"
APX = "tecumseh-stormwater-drainage-master-plan-technical-modelling-report-appendices_optimized.pdf"

# (pdf, page, short name, caption)
PAGES = [
    (TMR, 15, "tmr_fig1-2_service_areas", "Fig 1.2 Storm pump station service area and gravity outfall map"),
    (TMR, 91, "tmr_fig8-6_major_system_areas", "Fig 8.6 Existing condition major system drainage area plan"),
    (TMR, 81, "tmr_fig8-1_hgl_2yr_west", "Fig 8.1 West of Manning: existing 1:2 yr storm sewer hydraulic conditions"),
    (TMR, 87, "tmr_fig8-4_hgl_2yr_east", "Fig 8.4 East of Manning: existing 1:2 yr storm sewer hydraulic conditions"),
    (TMR, 84, "tmr_fig8-2_problem_W1_W2", "Fig 8.2 Surface flooding problem areas W-1 & W-2 (1:100 yr existing)"),
    (TMR, 85, "tmr_fig8-3_problem_W3", "Fig 8.3 Surface flooding problem area W-3 (1:100 yr existing)"),
    (TMR, 89, "tmr_fig8-5_problem_E1", "Fig 8.5 Surface flooding problem area E-1 (1:100 yr existing)"),
    (TMR, 151, "tmr_fig11-15_W1_100yr", "Fig 11.15 1:100 yr existing vs future surface flooding, W-1"),
    (TMR, 152, "tmr_fig11-16_W1_100yr40", "Fig 11.16 1:100 yr +40% existing vs future surface flooding, W-1"),
    (TMR, 153, "tmr_fig11-17_W2_100yr", "Fig 11.17 1:100 yr existing vs future surface flooding, W-2"),
    (TMR, 154, "tmr_fig11-18_W2_100yr40", "Fig 11.18 1:100 yr +40% existing vs future surface flooding, W-2"),
    (TMR, 155, "tmr_fig11-19_W3_100yr", "Fig 11.19 1:100 yr existing vs future surface flooding, W-3"),
    (TMR, 156, "tmr_fig11-20_W3_100yr40", "Fig 11.20 1:100 yr +40% existing vs future surface flooding, W-3"),
    (TMR, 157, "tmr_fig11-21_E1_100yr", "Fig 11.21 1:100 yr existing vs future surface flooding, E-1"),
    (TMR, 158, "tmr_fig11-22_E1_100yr40", "Fig 11.22 1:100 yr +40% existing vs future surface flooding, E-1"),
    (APX, 596, "apx_figC-1_ponding", "Appendix C Fig C-1 existing condition 2D surface ponding"),
    (APX, 597, "apx_figC-2_ponding", "Appendix C Fig C-2 existing condition 2D surface ponding"),
    (APX, 598, "apx_figC-3_ponding_24h39", "Appendix C Fig C-3 existing condition 2D surface ponding, 1:100 yr 24 h +39%"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    docs = {}
    rows = []
    for pdf, page, name, caption in PAGES:
        doc = docs.setdefault(pdf, pymupdf.open(BENCH / pdf))
        pix = doc[page - 1].get_pixmap(dpi=DPI)
        png = OUT / f"{name}.png"
        pix.save(png)
        rows.append({"png": png.name, "pdf": pdf, "pdf_page": page, "caption": caption,
                     "width_px": pix.width, "height_px": pix.height})
        print(f"{png.name}: {pix.width}x{pix.height}")
    with open(OUT / "pages.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
