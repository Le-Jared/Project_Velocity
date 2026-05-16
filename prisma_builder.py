from pathlib import Path
import pandas as pd


PRISMA_COLUMNS = [
    "Notes",
    "Site Name/Supplier",
    "PACKAGE/PLACEMENT TYPE",
    "Buy Type",
    "Buy Category",
    "Booking Category",
    "Package name",
    "Placement Name",
    "Unit Dimensions",
    "Positioning",
    "Cost Method",
    "Unit Type",
    "Unit Rate",
    "Planned unit amount",
    "Gross/Planned Cost",
    "Flight Start",
    "Flight End",
    "Programmatic Provider",
    "Market place",
    "Social network",
    "Strategy",
]


def _format_excel_date(value):
    if pd.isna(value) or value is None:
        return ""

    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return value

    return parsed.strftime("%m/%d/%Y")


def build_prisma_dataframe(enriched_df):
    if enriched_df.empty:
        raise ValueError("Cannot build Prisma dataframe from empty data.")

    rows = []

    for _, row in enriched_df.iterrows():
        cost_method = row.get("guide_cost_method") or row.get("cost_method") or "CPM"
        unit_type = row.get("guide_unit_type") or row.get("unit_type") or "Impressions"

        rows.append(
            {
                "Notes": "Direct placement",
                "Site Name/Supplier": row.get("supplier_name", ""),
                "PACKAGE/PLACEMENT TYPE": "Standalone",
                "Buy Type": row.get("buy_type", "Display"),
                "Buy Category": row.get("buy_category", "Mobile"),
                "Booking Category": "Standard",
                "Package name": "",
                "Placement Name": row.get("placement_name", ""),
                "Unit Dimensions": row.get("ad_size", "1 x 1"),
                "Positioning": row.get("positioning", "Other"),
                "Cost Method": cost_method,
                "Unit Type": unit_type,
                "Unit Rate": row.get("unit_rate", 0),
                "Planned unit amount": row.get("planned_units", 0),
                "Gross/Planned Cost": row.get("planned_amount", 0),
                "Flight Start": _format_excel_date(row.get("flight_start")),
                "Flight End": _format_excel_date(row.get("flight_end")),
                "Programmatic Provider": "",
                "Market place": "",
                "Social network": "",
                "Strategy": "",
            }
        )

    prisma_df = pd.DataFrame(rows, columns=PRISMA_COLUMNS)

    return prisma_df


def validate_prisma_dataframe(prisma_df):
    errors = []

    required_text_columns = [
        "Site Name/Supplier",
        "PACKAGE/PLACEMENT TYPE",
        "Buy Type",
        "Buy Category",
        "Placement Name",
        "Cost Method",
        "Unit Type",
        "Flight Start",
        "Flight End",
    ]

    required_numeric_columns = [
        "Unit Rate",
        "Planned unit amount",
        "Gross/Planned Cost",
    ]

    for col in PRISMA_COLUMNS:
        if col not in prisma_df.columns:
            errors.append(f"Missing Prisma column: {col}")

    for idx, row in prisma_df.iterrows():
        excel_row = idx + 2

        for col in required_text_columns:
            value = row.get(col)

            if pd.isna(value) or str(value).strip() == "":
                errors.append(f"Row {excel_row}: Missing required field '{col}'")

        for col in required_numeric_columns:
            value = row.get(col)

            try:
                numeric_value = float(value)
            except Exception:
                errors.append(f"Row {excel_row}: Field '{col}' is not numeric")
                continue

            if numeric_value < 0:
                errors.append(f"Row {excel_row}: Field '{col}' cannot be negative")

        if float(row.get("Gross/Planned Cost", 0)) <= 0:
            errors.append(f"Row {excel_row}: Gross/Planned Cost must be greater than 0")

        if float(row.get("Planned unit amount", 0)) <= 0:
            errors.append(f"Row {excel_row}: Planned unit amount must be greater than 0")

    return errors


def export_prisma_import(enriched_df, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    prisma_df = build_prisma_dataframe(enriched_df)

    validation_errors = validate_prisma_dataframe(prisma_df)

    if validation_errors:
        message = "Prisma export validation failed:\n" + "\n".join(validation_errors)
        raise ValueError(message)

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        prisma_df.to_excel(
            writer,
            sheet_name="Digital import sheet ALL TYPES",
            index=False,
            startrow=0,
        )

        workbook = writer.book
        worksheet = writer.sheets["Digital import sheet ALL TYPES"]

        header_format = workbook.add_format(
            {
                "bold": True,
                "bg_color": "#D9EAF7",
                "border": 1,
                "text_wrap": True,
                "valign": "top",
            }
        )

        money_format = workbook.add_format({"num_format": "$#,##0.00"})
        number_format = workbook.add_format({"num_format": "#,##0"})
        rate_format = workbook.add_format({"num_format": "0.00"})

        for col_idx, col_name in enumerate(prisma_df.columns):
            worksheet.write(0, col_idx, col_name, header_format)

            if col_name in ["Placement Name", "Site Name/Supplier"]:
                worksheet.set_column(col_idx, col_idx, 30)
            elif col_name in ["Flight Start", "Flight End"]:
                worksheet.set_column(col_idx, col_idx, 15)
            elif col_name in ["Gross/Planned Cost"]:
                worksheet.set_column(col_idx, col_idx, 18, money_format)
            elif col_name in ["Planned unit amount"]:
                worksheet.set_column(col_idx, col_idx, 18, number_format)
            elif col_name in ["Unit Rate"]:
                worksheet.set_column(col_idx, col_idx, 12, rate_format)
            else:
                worksheet.set_column(col_idx, col_idx, 18)

        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, len(prisma_df), len(prisma_df.columns) - 1)

    return output_path


def export_debug_files(raw_df, normalized_df, consolidated_df, enriched_df, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_df.to_csv(output_dir / "01_raw_parsed.csv", index=False)
    normalized_df.to_csv(output_dir / "02_normalized.csv", index=False)
    consolidated_df.to_csv(output_dir / "03_consolidated.csv", index=False)
    enriched_df.to_csv(output_dir / "04_enriched.csv", index=False)
