import pandas as pd
import argparse
import os
import re
from difflib import get_close_matches

def detect_delimiter(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    return '\t' if ext == '.tsv' else ','

def normalize_string(text, custom_fixes=None):
    if not isinstance(text, str):
        return ""
    text = text.strip().lower()
    match = re.match(r"(.+)[^a-zA-Z0-9]+(a|an|the)$", text)
    if match:
        text = f"{match.group(2)} {match.group(1)}"
    text = re.sub(r'^(the|a|an)\s+', '', text)
    if custom_fixes:
        for f in custom_fixes:
            text = text.replace(f.lower(), "")
    text = re.sub(r'[^a-z0-9\s]', '', text)
    return " ".join(text.split())

def parse_match_specs(match_args):
    """
    Parse --match arguments like "title:fuzzy" or "year:exact" or just "title".
    Returns list of (col, mode) where mode is 'fuzzy', 'exact', or 'norm'.
    """
    specs = []
    for m in match_args:
        if ':' in m:
            col, mode = m.rsplit(':', 1)
            mode = mode.lower()
            if mode not in ('fuzzy', 'exact', 'norm'):
                raise ValueError(f"Unknown match mode '{mode}' for column '{col}'. Use: fuzzy, exact, norm")
        else:
            col, mode = m, 'norm'
        specs.append((col.strip(), mode))
    return specs

def main():
    parser = argparse.ArgumentParser(
        description="Smart CSV/TSV Merger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Match modes:
  fuzzy  — normalized + fuzzy similarity (good for titles)
  norm   — normalized exact (strips punctuation/articles, case-insensitive)
  exact  — exact string match (good for years, IDs)

Examples:
  merge_tool.py src.tsv dest.tsv --match title:fuzzy
  merge_tool.py src.tsv dest.tsv --match title:fuzzy --match year:exact
  merge_tool.py src.tsv dest.tsv --match id:exact
        """
    )
    parser.add_argument("src",  help="Source file")
    parser.add_argument("dest", help="Destination file")
    parser.add_argument("--match", required=True, nargs='+', metavar="COL[:MODE]",
                        help="Columns to match on, with optional mode (fuzzy/norm/exact)")
    parser.add_argument("-o", "--output", default="merged_output.csv")
    parser.add_argument("-f", "--fixes", nargs='*', help="Custom strings to strip during normalization")
    parser.add_argument("--cols", nargs='*', help="Columns to keep from dest (default: all)")
    parser.add_argument("--show-matches", action="store_true", help="Print every match result (hit or miss)")

    args = parser.parse_args()
    specs = parse_match_specs(args.match)

    # Load
    df_src  = pd.read_csv(args.src,  sep=detect_delimiter(args.src))
    df_dest = pd.read_csv(args.dest, sep=detect_delimiter(args.dest))
    df_src.columns  = df_src.columns.str.strip()
    df_dest.columns = df_dest.columns.str.strip()

    print(f"SRC:  {len(df_src)} rows, columns: {list(df_src.columns)}")
    print(f"DEST: {len(df_dest)} rows, columns: {list(df_dest.columns)}")
    print(f"Match specs: {specs}")

    # Validate columns exist in both files
    errors = []
    for col, mode in specs:
        if col not in df_src.columns:
            errors.append(f"Column '{col}' not found in SRC. Available: {list(df_src.columns)}")
        if col not in df_dest.columns:
            errors.append(f"Column '{col}' not found in DEST. Available: {list(df_dest.columns)}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        raise SystemExit(1)

    # Column selection on dest
    if args.cols:
        keep = list(set(args.cols + [col for col, _ in specs]))
        df_dest = df_dest[[c for c in keep if c in df_dest.columns]]

    # Pre-compute normalized keys for norm/fuzzy columns
    for col, mode in specs:
        if mode in ('fuzzy', 'norm'):
            key = f'_key_{col}'
            df_src[key]  = df_src[col].apply(lambda x: normalize_string(x, args.fixes))
            df_dest[key] = df_dest[col].apply(lambda x: normalize_string(x, args.fixes))

    # Build fuzzy key lists per fuzzy column for get_close_matches
    fuzzy_lists = {
        col: df_dest[f'_key_{col}'].tolist()
        for col, mode in specs if mode == 'fuzzy'
    }

    results_list = []
    mismatches   = []

    print(f"Matching {len(df_src)} records...")

    for _, src_row in df_src.iterrows():
        candidates = df_dest.copy()

        matched_via_fuzzy = {}

        for col, mode in specs:
            if mode == 'exact':
                candidates = candidates[candidates[col].astype(str) == str(src_row[col])]

            elif mode == 'norm':
                key = f'_key_{col}'
                candidates = candidates[candidates[key] == src_row[key]]

            elif mode == 'fuzzy':
                key = f'_key_{col}'
                src_key = src_row[key]
                # First try exact normalized match among remaining candidates
                exact_cands = candidates[candidates[key] == src_key]
                if not exact_cands.empty:
                    candidates = exact_cands
                else:
                    # Fuzzy match within remaining candidate keys
                    cand_keys = candidates[key].tolist()
                    closest = get_close_matches(src_key, cand_keys, n=1, cutoff=0.7)
                    if closest:
                        matched_via_fuzzy[col] = (src_row[col], closest[0])
                        candidates = candidates[candidates[key] == closest[0]]
                    else:
                        candidates = candidates.iloc[0:0]  # empty

        first_col = specs[0][0]
        if not candidates.empty:
            dest_row = candidates.iloc[0]
            combined = {**src_row.to_dict(), **dest_row.to_dict()}
            results_list.append(combined)
            if args.show_matches:
                fuzzy_note = ''.join(f" [fuzzy {c}: '{sv}'→'{dv}']" for c, (sv, dv) in matched_via_fuzzy.items())
                print(f"  HIT:  {src_row[first_col]!r} → {dest_row[first_col]!r}{fuzzy_note}")
        else:
            mismatches.append(src_row[first_col])
            results_list.append(src_row.to_dict())
            if args.show_matches:
                print(f"  MISS: {src_row[first_col]!r}")

    # Drop internal key columns
    key_cols = [f'_key_{col}' for col, mode in specs if mode in ('fuzzy', 'norm')]
    merged_df = pd.DataFrame(results_list)
    merged_df = merged_df.drop(columns=[c for c in key_cols if c in merged_df.columns])

    merged_df.to_csv(args.output, index=False)

    matched = len(df_src) - len(mismatches)
    print(f"\nMatched: {matched}/{len(df_src)}")
    print(f"Saved to: {args.output}")
    if mismatches:
        print(f"Unmatched ({len(mismatches)}), first 10: {mismatches[:10]}")

if __name__ == "__main__":
    main()
