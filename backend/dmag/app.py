"""
DMAG - Deal Memo Auto Generator (CLI)

Run from backend/: python -m dmag.app
(or after pip install -e .: dmag)
"""

from .config import CONFIDENCE_THRESHOLD, OUTPUT_DIR, RAW_DIR, TEMPLATE_PATH
from .pipeline import run_pipeline


def main() -> None:
    result = run_pipeline(
        raw_dir=RAW_DIR,
        template_path=TEMPLATE_PATH,
        output_dir=OUTPUT_DIR,
        confidence_threshold=CONFIDENCE_THRESHOLD,
        on_progress=lambda step, total, msg: print(f"Step {step}/{total}: {msg}"),
    )
    print(f"Done. Exported: {result.output_docx}, {result.output_json}")


if __name__ == "__main__":
    main()
