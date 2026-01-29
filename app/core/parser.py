"""CSV/Excel parsing with automatic column detection."""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import BinaryIO, Optional
import structlog
from io import BytesIO

from app.models.schemas import (
    ParseResult, ColumnMapping, DataQualityReport
)

logger = structlog.get_logger()

# Column name mappings (Dutch + English)
COLUMN_PATTERNS: dict[str, list[str]] = {
    'timestamp': [
        'timestamp', 'datetime', 'datum', 'date', 'tijd', 'time',
        'datum/tijd', 'datumtijd', 'periode', 'interval', 'van', 'start',
        'meetdatum', 'meettijd'
    ],
    'afname': [
        'afname', 'verbruik', 'import', 'consumption', 'kwh', 'afname_kwh',
        'afname (kwh)', 'verbruik (kwh)', 'import (kwh)', 'stroom afname',
        'levering', 'elektriciteit', 'e-verbruik', 'verbruik kwh',
        'afgenomen', 'opgenomen', 'totaal verbruik'
    ],
    'teruglevering': [
        'teruglevering', 'export', 'return', 'teruglevering_kwh',
        'teruglevering (kwh)', 'export (kwh)', 'stroom teruglevering',
        'opwek', 'productie', 'solar', 'pv', 'invoeding', 'teruggeleverd'
    ],
    'vermogen': [
        'vermogen', 'power', 'kw', 'vermogen_kw', 'vermogen (kw)',
        'piek', 'peak', 'max', 'capaciteit', 'piekvermogen'
    ]
}


def detect_delimiter(content: str) -> str:
    """Detect CSV delimiter from content sample."""
    first_lines = '\n'.join(content.split('\n')[:10])

    delimiters = {
        ';': first_lines.count(';'),
        ',': first_lines.count(','),
        '\t': first_lines.count('\t')
    }

    return max(delimiters, key=lambda k: delimiters[k])


def find_header_row(df: pd.DataFrame, max_rows: int = 20) -> int:
    """Find the row containing column headers."""
    for idx in range(min(max_rows, len(df))):
        row_values = df.iloc[idx].astype(str).str.lower()

        # Check if this row looks like headers
        matches = sum(
            any(pattern in val for pattern in
                COLUMN_PATTERNS['timestamp'] + COLUMN_PATTERNS['afname'])
            for val in row_values
        )

        if matches >= 2:
            return idx

    return 0


def detect_column_mapping(columns: list[str]) -> Optional[ColumnMapping]:
    """Auto-detect column mapping using fuzzy matching."""
    mapping: dict[str, str] = {}
    columns_lower = [c.lower().strip() for c in columns]

    for field, patterns in COLUMN_PATTERNS.items():
        for idx, col in enumerate(columns_lower):
            if any(pattern in col or col in pattern for pattern in patterns):
                mapping[field] = columns[idx]
                break

    # Require at least timestamp and afname
    if 'timestamp' in mapping and 'afname' in mapping:
        return ColumnMapping(
            timestamp=mapping['timestamp'],
            afname=mapping['afname'],
            teruglevering=mapping.get('teruglevering'),
            vermogen=mapping.get('vermogen')
        )

    return None


def parse_dutch_number(value) -> Optional[float]:
    """Parse number with Dutch formatting (1.234,56)."""
    if pd.isna(value) or value == '':
        return None

    if isinstance(value, (int, float)):
        return float(value)

    try:
        cleaned = str(value).strip()

        # Detect format: if both . and , present
        if '.' in cleaned and ',' in cleaned:
            if cleaned.rfind('.') < cleaned.rfind(','):
                # Dutch: 1.234,56
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                # International: 1,234.56
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            parts = cleaned.split(',')
            if len(parts) == 2 and len(parts[1]) <= 2:
                cleaned = cleaned.replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')

        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def parse_timestamp(value) -> Optional[datetime]:
    """Parse various timestamp formats."""
    if pd.isna(value):
        return None

    # Handle Excel serial dates
    if isinstance(value, (int, float)) and 30000 < value < 60000:
        try:
            return pd.Timestamp('1899-12-30') + pd.Timedelta(days=value)
        except Exception:
            pass

    # Try pandas parsing (handles most formats)
    try:
        return pd.to_datetime(value, dayfirst=True)
    except Exception:
        pass

    # Try specific formats
    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%d-%m-%Y %H:%M:%S',
        '%d-%m-%Y %H:%M',
        '%d/%m/%Y %H:%M',
        '%Y-%m-%dT%H:%M:%S',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(str(value), fmt)
        except Exception:
            continue

    return None


def validate_data_quality(df: pd.DataFrame) -> DataQualityReport:
    """Analyze data quality and generate report."""
    total_rows = len(df)

    # Count valid rows
    valid_mask = df['timestamp'].notna() & (df['afname_kwh'] >= 0)
    valid_rows = int(valid_mask.sum())

    # Detect outliers (> 3 std from rolling mean)
    outliers = 0
    if len(df) > 96:
        rolling_mean = df['afname_kwh'].rolling(96, center=True, min_periods=1).mean()
        rolling_std = df['afname_kwh'].rolling(96, center=True, min_periods=1).std()
        outliers = int(((df['afname_kwh'] - rolling_mean).abs() > 3 * rolling_std).sum())

    # Detect gaps
    gaps = 0
    if df['timestamp'].notna().any():
        time_diffs = df['timestamp'].diff()
        median_diff = time_diffs.median()
        if pd.notna(median_diff):
            gaps = int((time_diffs > median_diff * 2).sum())

    warnings = []
    if total_rows > 0:
        if valid_rows / total_rows < 0.95:
            warnings.append(f"{total_rows - valid_rows} ongeldige rijen gedetecteerd")
        if outliers > total_rows * 0.01:
            warnings.append(f"{outliers} mogelijke outliers gedetecteerd")
        if gaps > 10:
            warnings.append(f"{gaps} gaps in tijdreeks gedetecteerd")

    return DataQualityReport(
        total_rows=total_rows,
        valid_rows=valid_rows,
        completeness=valid_rows / total_rows if total_rows > 0 else 0,
        outlier_percentage=outliers / total_rows if total_rows > 0 else 0,
        gaps_detected=gaps,
        interpolated_points=0,
        warnings=warnings
    )


async def parse_file(
    file: BinaryIO,
    filename: str,
    session_id: str
) -> ParseResult:
    """
    Main parsing function for CSV and Excel files.

    Args:
        file: File-like object with content
        filename: Original filename
        session_id: Session identifier

    Returns:
        ParseResult with parsed data and metadata
    """
    logger.info("Parsing file", filename=filename, session_id=session_id)

    warnings: list[str] = []

    try:
        ext = Path(filename).suffix.lower()
        content = file.read()

        if ext == '.csv':
            text_content = content.decode('utf-8', errors='replace')
            delimiter = detect_delimiter(text_content)

            df = pd.read_csv(
                BytesIO(content),
                delimiter=delimiter,
                header=None,
                dtype=str,
                na_values=['', 'NA', 'N/A', '-', 'null']
            )
        elif ext in ['.xlsx', '.xls']:
            df = pd.read_excel(
                BytesIO(content),
                header=None,
                dtype=str,
                na_values=['', 'NA', 'N/A', '-', 'null']
            )
        else:
            return ParseResult(
                success=False,
                session_id=session_id,
                headers=[],
                detected_mapping=None,
                row_count=0,
                date_range_start=None,
                date_range_end=None,
                detected_interval_minutes=15,
                preview=[],
                data_quality=DataQualityReport(
                    total_rows=0, valid_rows=0, completeness=0,
                    outlier_percentage=0, gaps_detected=0,
                    interpolated_points=0, warnings=[]
                ),
                warnings=[],
                error=f"Niet-ondersteund bestandstype: {ext}"
            )

        # Find header row
        header_idx = find_header_row(df)
        if header_idx > 0:
            warnings.append(
                f"Header gevonden op rij {header_idx + 1}, "
                f"{header_idx} metadata rijen overgeslagen"
            )

        # Set headers and slice data
        headers = [str(h) for h in df.iloc[header_idx].tolist()]
        df = df.iloc[header_idx + 1:].reset_index(drop=True)
        df.columns = headers

        # Detect column mapping
        detected_mapping = detect_column_mapping(headers)

        if detected_mapping:
            # Parse and normalize data
            df_normalized = pd.DataFrame()
            df_normalized['timestamp'] = df[detected_mapping.timestamp].apply(parse_timestamp)
            df_normalized['afname_kwh'] = df[detected_mapping.afname].apply(parse_dutch_number).fillna(0)

            if detected_mapping.teruglevering:
                df_normalized['teruglevering_kwh'] = df[detected_mapping.teruglevering].apply(
                    parse_dutch_number
                ).fillna(0)
            else:
                df_normalized['teruglevering_kwh'] = 0.0

            if detected_mapping.vermogen:
                df_normalized['vermogen_kw'] = df[detected_mapping.vermogen].apply(parse_dutch_number)

            # Sort by timestamp
            df_normalized = df_normalized.sort_values('timestamp').reset_index(drop=True)

            # Detect interval
            time_diffs = df_normalized['timestamp'].diff().dt.total_seconds() / 60
            detected_interval = int(time_diffs.median()) if time_diffs.notna().any() else 15

            # Data quality
            data_quality = validate_data_quality(df_normalized)

            # Date range
            valid_timestamps = df_normalized['timestamp'].dropna()
            date_start = valid_timestamps.min() if len(valid_timestamps) > 0 else None
            date_end = valid_timestamps.max() if len(valid_timestamps) > 0 else None

            preview = df.head(10).to_dict(orient='records')
        else:
            warnings.append("Kon kolommen niet automatisch detecteren. Handmatige mapping vereist.")
            detected_interval = 15
            data_quality = DataQualityReport(
                total_rows=len(df), valid_rows=0, completeness=0,
                outlier_percentage=0, gaps_detected=0,
                interpolated_points=0, warnings=["Mapping niet gedetecteerd"]
            )
            date_start = None
            date_end = None
            preview = df.head(10).to_dict(orient='records')

        return ParseResult(
            success=True,
            session_id=session_id,
            headers=headers,
            detected_mapping=detected_mapping,
            row_count=len(df),
            date_range_start=date_start,
            date_range_end=date_end,
            detected_interval_minutes=detected_interval,
            preview=preview,
            data_quality=data_quality,
            warnings=warnings,
            error=None
        )

    except Exception as e:
        logger.error("Parse error", error=str(e), session_id=session_id)
        return ParseResult(
            success=False,
            session_id=session_id,
            headers=[],
            detected_mapping=None,
            row_count=0,
            date_range_start=None,
            date_range_end=None,
            detected_interval_minutes=15,
            preview=[],
            data_quality=DataQualityReport(
                total_rows=0, valid_rows=0, completeness=0,
                outlier_percentage=0, gaps_detected=0,
                interpolated_points=0, warnings=[]
            ),
            warnings=[],
            error=str(e)
        )


def normalize_dataframe(
    df: pd.DataFrame,
    mapping: ColumnMapping
) -> pd.DataFrame:
    """
    Normalize a raw DataFrame using the provided column mapping.

    Returns DataFrame with standard columns: timestamp, afname_kwh, teruglevering_kwh
    """
    df_normalized = pd.DataFrame()
    df_normalized['timestamp'] = df[mapping.timestamp].apply(parse_timestamp)
    df_normalized['afname_kwh'] = df[mapping.afname].apply(parse_dutch_number).fillna(0)

    if mapping.teruglevering:
        df_normalized['teruglevering_kwh'] = df[mapping.teruglevering].apply(
            parse_dutch_number
        ).fillna(0)
    else:
        df_normalized['teruglevering_kwh'] = 0.0

    if mapping.vermogen:
        df_normalized['vermogen_kw'] = df[mapping.vermogen].apply(parse_dutch_number)

    # Sort and filter valid rows
    df_normalized = df_normalized.dropna(subset=['timestamp'])
    df_normalized = df_normalized.sort_values('timestamp').reset_index(drop=True)

    return df_normalized
