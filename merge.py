import pandas as pd
import argparse
import os
import re
from difflib import get_close_matches

def detect_delimiter(file_path):
    """Detects if a file is CSV or TSV based on extension."""
    ext = os.path.splitext(file_path)[1].lower()
    return '\t' if ext == '.tsv' else ','

def normalize_string(text, custom_fixes=None):
    """
    Cleans strings and removes specified prefixes/suffixes.
    """
    if not isinstance(text, str):
        return ""
    
    text = text.strip().lower()

    # Handle the "The" or "A" transposition
    match = re.match(r"(.+),?\s*(a|an|the)$", text)
    if match:
        text = f"{match.group(2)} {match.group(1)}"

    # Strip leading articles so "The Minecraft Movie" == "Minecraft Movie"
    text = re.sub(r'^(the|a|an)\s+', '', text)

    # List of common prefixes/suffixes to strip for matching purposes
    # These are "soft" removals used only for comparison
    noise = []
    if custom_fixes:
        noise.extend([f.lower() for f in custom_fixes])

    for n in noise:
        text = text.replace(n, "")

    # Remove non-alphanumeric for a "fuzzy" core match (optional but recommended)
    text = re.sub(r'[^a-z0-9\s]', '', text)
    return " ".join(text.split())

def main():
    parser = argparse.ArgumentParser(description="Smart CSV/TSV Merger")
    parser.add_argument("src", help="Source file")
    parser.add_argument("dest", help="Destination file")
    parser.add_argument("-c", "--column", required=True, help="Column name to match on")
    parser.add_argument("-o", "--output", default="merged_output.csv", help="Output filename")
    parser.add_argument("-f", "--fixes", nargs='*', help="Custom prefixes/suffixes to ignore")
    parser.add_argument("--force", action="store_true", help="Force closest match if no exact match found")
    parser.add_argument("--cols", nargs='*', help="Specific columns to keep from Dest (defaults to all)")
    
    args = parser.parse_args()

    # 1. Load Files
    df_src = pd.read_csv(args.src, sep=detect_delimiter(args.src))
    df_dest = pd.read_csv(args.dest, sep=detect_delimiter(args.dest))

    # 2. Pre-process Matching Columns
    print("Normalizing match columns...")
    df_src['_match_key'] = df_src[args.column].apply(lambda x: normalize_string(x, args.fixes))
    df_dest['_match_key'] = df_dest[args.column].apply(lambda x: normalize_string(x, args.fixes))

    # 3. Handle Column Selection
    if args.cols:
        # Ensure the match key is kept for the join
        dest_cols = list(set(args.cols + [args.column, '_match_key']))
        df_dest = df_dest[dest_cols]

    # 4. Perform Matching
    mismatches = []

    print(f"Matching {len(df_src)} records...")

    # We iterate to handle the "force closest" logic and reporting
    results_list = []
    dest_keys = df_dest['_match_key'].tolist()

    for _, src_row in df_src.iterrows():
        key = src_row['_match_key']
        match_row = df_dest[df_dest['_match_key'] == key]

        if not match_row.empty:
            # Exact normalized match
            combined = {**src_row.to_dict(), **match_row.iloc[0].to_dict()}
            results_list.append(combined)
        elif args.force:
            # Look for closest string
            closest = get_close_matches(key, dest_keys, n=1, cutoff=0.7)
            if closest:
                match_row = df_dest[df_dest['_match_key'] == closest[0]]
                combined = {**src_row.to_dict(), **match_row.iloc[0].to_dict()}
                results_list.append(combined)
                mismatches.append(f"{src_row[args.column]} → {match_row.iloc[0][args.column]}")
            else:
                mismatches.append(src_row[args.column])
                results_list.append(src_row.to_dict())  # keep src row, dest cols empty
        else:
            mismatches.append(src_row[args.column])
            results_list.append(src_row.to_dict())  # keep src row, dest cols empty

    # 5. Output
    merged_df = pd.DataFrame(results_list).drop(columns=['_match_key'])
    merged_df.to_csv(args.output, index=False)

    print(f"\nMerged file saved to: {args.output}")
    if mismatches:
        print(f"Count of Mismatches: {len(mismatches)}")
        print("First 5 mismatches:", mismatches[:5])

if __name__ == "__main__":
    main()
