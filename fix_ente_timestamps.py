#!/usr/bin/env python3
"""
Ente Photos to iCloud Migration Tool

Fixes file timestamps from Ente Photos exports by reading the original
capture time from companion JSON metadata files and applying them using exiftool.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

# Map exiftool FileType to canonical extension
FILETYPE_TO_EXT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
    "HEIC": ".heic",
    "HEIF": ".heic",
    "MP4": ".mp4",
    "MOV": ".mov",
    "QuickTime": ".mov",
    "AVI": ".avi",
    "WEBM": ".webm",
    "MKV": ".mkv",
    "TIFF": ".tiff",
    "BMP": ".bmp",
    "CR2": ".cr2",
    "NEF": ".nef",
    "ARW": ".arw",
    "DNG": ".dng",
    "RAF": ".raf",
    "ORF": ".orf",
    "RW2": ".rw2",
}

# Extension aliases for comparison
EXT_ALIASES = {
    ".jpeg": ".jpg",
    ".jpe": ".jpg",
    ".m4v": ".mp4",
    ".heif": ".heic",
    ".tif": ".tiff",
}


def batch_detect_file_types(files: list[Path]) -> dict[str, Optional[str]]:
    """
    Detect file types for multiple files in one exiftool call.
    Returns dict mapping filename to correct extension (or None if unknown).
    """
    if not files:
        return {}

    try:
        cmd = ["exiftool", "-FileType", "-FileName", "-json"] + [str(f) for f in files]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and not result.stdout:
            print(f"  [WARN] exiftool batch detection failed: {result.stderr.strip()}")
            return {}

        data = json.loads(result.stdout)
        type_map = {}
        for item in data:
            filename = item.get("FileName", "")
            file_type = item.get("FileType", "")
            type_map[filename] = FILETYPE_TO_EXT.get(file_type)
        return type_map

    except FileNotFoundError:
        print("[ERROR] exiftool not found. Install with: brew install exiftool")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"  [WARN] Failed to parse exiftool output: {e}")
        return {}
    except Exception as e:
        print(f"  [WARN] Batch detection error: {e}")
        return {}


def get_corrected_filename(
    filepath: Path, detected_ext: Optional[str]
) -> tuple[str, bool]:
    """
    Check if file extension matches detected type, return corrected filename.
    Returns (filename, was_corrected).
    """
    if detected_ext is None:
        return filepath.name, False

    current_ext = filepath.suffix.lower()
    normalized_current = EXT_ALIASES.get(current_ext, current_ext)
    normalized_detected = EXT_ALIASES.get(detected_ext, detected_ext)

    if normalized_current == normalized_detected:
        return filepath.name, False

    # Extension mismatch - return corrected filename
    new_name = filepath.stem + detected_ext
    return new_name, True


def parse_timestamp(metadata: dict) -> Optional[datetime]:
    """
    Extract timestamp from metadata, prioritizing photoTakenTime over creationTime.
    Returns datetime object or None if no valid timestamp found.
    """
    # Try photoTakenTime first (when photo was actually taken)
    if "photoTakenTime" in metadata:
        try:
            ts = int(metadata["photoTakenTime"]["timestamp"])
            return datetime.fromtimestamp(ts)
        except (KeyError, ValueError, TypeError):
            pass

    # Fallback to creationTime
    if "creationTime" in metadata:
        try:
            ts = int(metadata["creationTime"]["timestamp"])
            return datetime.fromtimestamp(ts)
        except (KeyError, ValueError, TypeError):
            pass

    return None


def format_exif_datetime(dt: datetime) -> str:
    """Format datetime for exiftool (YYYY:MM:DD HH:MM:SS)."""
    return dt.strftime("%Y:%m:%d %H:%M:%S")


def batch_set_timestamps(
    files_and_times: list[tuple[Path, datetime]], dry_run: bool = False
) -> tuple[int, int]:
    """
    Set timestamps on multiple files in one exiftool call using argfile.
    Returns (success_count, error_count).
    """
    if not files_and_times:
        return 0, 0

    if dry_run:
        for filepath, dt in files_and_times:
            exif_dt = format_exif_datetime(dt)
            print(f"    [DRY RUN] Would set {filepath.name} -> {exif_dt}")
        return len(files_and_times), 0

    # Build argfile content
    # Use -execute between each file to process them separately
    # (otherwise options accumulate and the last timestamp applies to all files)
    argfile_lines = []
    for filepath, dt in files_and_times:
        exif_dt = format_exif_datetime(dt)
        argfile_lines.extend(
            [
                "-overwrite_original",
                f"-DateTimeOriginal={exif_dt}",
                f"-CreateDate={exif_dt}",
                f"-FileModifyDate={exif_dt}",
                f"-FileCreateDate={exif_dt}",
                str(filepath),
                "-execute",
            ]
        )

    try:
        # Write argfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as argfile:
            argfile.write("\n".join(argfile_lines))
            argfile_path = argfile.name

        # Run exiftool with argfile
        result = subprocess.run(
            ["exiftool", "-@", argfile_path],
            capture_output=True,
            text=True,
            check=False,
        )

        # Clean up argfile
        Path(argfile_path).unlink()

        # With -execute, exiftool outputs one summary per "command"
        # Count all "X image files updated" and "X image files unchanged" lines
        updated = 0
        unchanged = 0
        for line in result.stdout.split("\n"):
            line = line.strip()
            if "image files updated" in line:
                try:
                    updated += int(line.split()[0])
                except (ValueError, IndexError):
                    pass
            elif "image files unchanged" in line:
                try:
                    unchanged += int(line.split()[0])
                except (ValueError, IndexError):
                    pass

        # Files are either updated, unchanged, or errored
        total = len(files_and_times)
        accounted_for = updated + unchanged
        error_count = total - accounted_for

        # Report any errors from stderr (filter out expected FileCreateDate warnings)
        if result.stderr:
            stderr_lines = result.stderr.strip().split("\n")
            real_errors = [
                line
                for line in stderr_lines
                if line.strip() and "FileCreateDate" not in line
            ]
            if real_errors:
                print(f"\n  [WARN] exiftool reported {len(real_errors)} warning(s):")
                for err in real_errors[:5]:  # Show first 5
                    print(f"    {err}")
                if len(real_errors) > 5:
                    print(f"    ... and {len(real_errors) - 5} more")

        return updated + unchanged, error_count

    except FileNotFoundError:
        print("[ERROR] exiftool not found. Install with: brew install exiftool")
        sys.exit(1)
    except Exception as e:
        print(f"  [ERROR] Batch timestamp error: {e}")
        return 0, len(files_and_times)


def process_album(
    album_path: Path,
    output_base: Path,
    dry_run: bool = False,
) -> tuple[int, int, int, int]:
    """
    Process all media files in an album using batch operations.
    Returns (processed_count, skipped_count, error_count, renamed_count).
    """
    album_name = album_path.name
    metadata_dir = album_path / "metadata"
    output_dir = output_base / album_name

    # Collect all media files (excluding metadata dir and .DS_Store)
    media_files = []
    for item in album_path.iterdir():
        if item.name == "metadata" or item.name == ".DS_Store":
            continue
        if item.is_dir():
            continue
        media_files.append(item)

    if not media_files:
        print("  No media files found")
        return 0, 0, 0, 0

    # Step 1: Batch detect all file types
    print(f"  Detecting file types for {len(media_files)} files...")
    file_types = batch_detect_file_types(media_files)

    # Step 2: Process each file - read metadata and prepare for copy
    print("  Reading metadata...")
    files_to_process: list[tuple[Path, Path, datetime]] = []  # (src, dst, timestamp)
    skipped = 0
    errors = 0
    renamed = 0

    # Create output directory
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    for media_file in media_files:
        json_file = metadata_dir / f"{media_file.name}.json"

        # Check for metadata JSON
        if not json_file.exists():
            print(f"    [SKIP] No metadata: {media_file.name}")
            skipped += 1
            continue

        # Parse metadata
        try:
            with open(json_file, "r") as f:
                metadata = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"    [ERROR] Failed to read metadata for {media_file.name}: {e}")
            errors += 1
            continue

        # Extract timestamp
        timestamp = parse_timestamp(metadata)
        if timestamp is None:
            print(f"    [SKIP] No timestamp: {media_file.name}")
            skipped += 1
            continue

        # Get corrected filename
        detected_ext = file_types.get(media_file.name)
        corrected_name, was_corrected = get_corrected_filename(media_file, detected_ext)
        if was_corrected:
            print(f"    [FIX] {media_file.name} -> {corrected_name}")
            renamed += 1

        output_file = output_dir / corrected_name
        files_to_process.append((media_file, output_file, timestamp))

    if not files_to_process:
        return 0, skipped, errors, renamed

    # Step 3: Copy all files
    print(f"  Copying {len(files_to_process)} files...")
    files_for_timestamps: list[tuple[Path, datetime]] = []

    for src, dst, timestamp in files_to_process:
        if not dry_run:
            try:
                shutil.copy2(src, dst)
                files_for_timestamps.append((dst, timestamp))
            except IOError as e:
                print(f"    [ERROR] Failed to copy {src.name}: {e}")
                errors += 1
        else:
            print(f"    [DRY RUN] Would copy: {src.name}")
            files_for_timestamps.append((dst, timestamp))

    # Step 4: Batch set timestamps
    if files_for_timestamps:
        print(
            f"  Setting timestamps on {len(files_for_timestamps)} files...\n",
            end="",
            flush=True,
        )
        success, ts_errors = batch_set_timestamps(files_for_timestamps, dry_run)
        print(" done." if not dry_run else "")
        errors += ts_errors
        processed = success
    else:
        processed = 0

    return processed, skipped, errors, renamed


def find_albums(input_dir: Path) -> list[Path]:
    """Find all album directories (top-level subdirectories)."""
    albums = []
    for item in input_dir.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            # Check if it looks like an album (has files or metadata folder)
            has_files = any(
                f.is_file() and f.name != ".DS_Store" for f in item.iterdir()
            )
            has_metadata = (item / "metadata").is_dir()
            if has_files or has_metadata:
                albums.append(item)
    return sorted(albums)


def main():
    parser = argparse.ArgumentParser(
        description="Fix Ente Photos export timestamps for iCloud import",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python fix_ente_timestamps.py ~/Downloads/ente-export ~/Pictures/fixed-photos
  python fix_ente_timestamps.py ~/Downloads/ente-export ~/Pictures/fixed-photos --dry-run

The script expects the input directory to contain album folders, each with:
  - Media files (photos/videos) at the album root
  - A 'metadata/' subfolder with JSON files named '<filename>.json'
""",
    )
    parser.add_argument("input_dir", help="Ente export directory containing albums")
    parser.add_argument("output_dir", help="Output directory for processed files")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()

    input_path = Path(args.input_dir).expanduser().resolve()
    output_path = Path(args.output_dir).expanduser().resolve()

    if not input_path.exists():
        print(f"[ERROR] Input directory does not exist: {input_path}")
        sys.exit(1)

    if not input_path.is_dir():
        print(f"[ERROR] Input path is not a directory: {input_path}")
        sys.exit(1)

    # Find albums
    albums = find_albums(input_path)
    if not albums:
        print(f"[ERROR] No albums found in: {input_path}")
        sys.exit(1)

    print(f"Found {len(albums)} album(s) to process")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    if args.dry_run:
        print("[DRY RUN MODE - no changes will be made]")
    print()

    # Create output directory
    if not args.dry_run:
        output_path.mkdir(parents=True, exist_ok=True)

    # Process each album
    total_processed = 0
    total_skipped = 0
    total_errors = 0
    total_renamed = 0

    for album in albums:
        print(f"Album: {album.name}")
        processed, skipped, errors, renamed = process_album(
            album, output_path, args.dry_run
        )
        total_processed += processed
        total_skipped += skipped
        total_errors += errors
        total_renamed += renamed
        print()

    # Summary
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Albums processed: {len(albums)}")
    print(f"Files processed:  {total_processed}")
    print(f"Files renamed:    {total_renamed} (extension corrected)")
    print(f"Files skipped:    {total_skipped}")
    print(f"Errors:           {total_errors}")

    if args.dry_run:
        print("\n[DRY RUN] No files were actually modified.")

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
