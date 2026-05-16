# run_media.py

from pathlib import Path

from plan_parser import parse_media_plan
from plan_adapters import adapt_media_plan, consolidate_for_prisma
from buying_guide import (
    load_buying_guide,
    enrich_with_buying_guide,
    preview_buying_guide_matches,
)
from prisma_builder import export_prisma_import, export_debug_files


def run_media_plan_to_prisma(
    media_plan_path,
    buying_guide_path,
    output_path,
    client="GU",
    debug=True,
):
    print("1. Reading media plan...")
    raw_df = parse_media_plan(media_plan_path)

    print("2. Normalizing media plan...")
    normalized_df = adapt_media_plan(raw_df, client=client)

    print("3. Consolidating placements...")
    consolidated_df = consolidate_for_prisma(normalized_df)

    print("4. Loading Buying Guide...")
    guide_df = load_buying_guide(buying_guide_path)

    print("5. Previewing Buying Guide matches...")
    preview_df = preview_buying_guide_matches(consolidated_df, guide_df)
    print(preview_df)

    print("6. Enriching with Buying Guide...")
    enriched_df = enrich_with_buying_guide(consolidated_df, guide_df)

    if debug:
        print("7. Exporting debug files...")
        export_debug_files(
            raw_df=raw_df,
            normalized_df=normalized_df,
            consolidated_df=consolidated_df,
            enriched_df=enriched_df,
            output_dir=Path(output_path).parent / "debug_media",
        )

    print("8. Exporting Prisma import...")
    final_path = export_prisma_import(enriched_df, output_path)

    print(f"Done. Prisma import saved to: {final_path}")

    return final_path


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent

    run_media_plan_to_prisma(
        media_plan_path=BASE_DIR / "media_plans" / "Skillignition_Media_plan_sample.xlsx",
        buying_guide_path=BASE_DIR / "Input" / "ACCT 108 BuyingGuide.xlsx",
        output_path=BASE_DIR / "Output" / "GU_prisma_import.xlsx",
        client="GU",
        debug=True,
    )
