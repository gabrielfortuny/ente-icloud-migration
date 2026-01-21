# Fix Ente Photos Timestamps

Fix photo timestamps from [Ente](https://ente.io/) exports so they import correctly into any photo platform.

## The Problem

When you export photos from Ente, many file creation/modification dates are set to the export time, not when the photos were originally taken.

The correct timestamps exist in Ente's companion JSON metadata files, but most photo apps don't read these.

## The Solution

This script:

1. Reads the original capture timestamps from Ente's JSON metadata
2. Copies files to an output directory (preserving album structure)
3. Uses `exiftool` to embed the correct timestamps into the files
4. Automatically fixes mismatched file extensions (e.g., a JPEG saved as `.png`)

This works with any software that reads EXIF timestamps.

## Requirements

- Python 3.10+
- [exiftool](https://exiftool.org/)

**macOS:**

```bash
brew install exiftool
```

**Linux (Debian/Ubuntu):**

```bash
sudo apt install exiftool
```

## Usage

```bash
# Preview what will happen (no changes made)
python fix_ente_timestamps.py ~/path/to/ente-export ~/path/to/output --dry-run

# Run the migration
python fix_ente_timestamps.py ~/path/to/ente-export ~/path/to/output
```

### Expected Input Structure

The script expects your Ente export to have this structure:

```
ente-exported-photos/
├── Album Name 1/
│   ├── photo1.jpg
│   ├── photo2.png
│   ├── video1.mp4
│   └── metadata/
│       ├── photo1.jpg.json
│       ├── photo2.png.json
│       └── video1.mp4.json
├── Album Name 2/
│   ├── ...
│   └── metadata/
│       └── ...
...
```

### Output

The script creates a copy of your photos with:

- Correct EXIF timestamps (`DateTimeOriginal`, `CreateDate`)
- Correct filesystem timestamps (`FileModifyDate`, `FileCreateDate` on macOS)
- Fixed file extensions where the original was incorrect
- Preserved album folder structure

```
output/
├── Album Name 1/
│   ├── photo1.jpg
│   ├── photo2.jpg  ← extension fixed from .png
│   └── video1.mp4
├── Album Name 2/
│   └── ...
...
```

## Features

- **Batch processing**: Uses optimized exiftool batch operations for speed
- **Extension detection**: Automatically detects and fixes wrong file extensions using exiftool
- **Non-destructive**: Creates copies, never modifies original files
- **Dry-run mode**: Preview all changes before committing
- **Detailed logging**: Shows progress, skipped files, and errors
- **Summary report**: Final count of processed, renamed, skipped, and errored files

## Timestamp Priority

The script reads timestamps from the JSON metadata in this order:

1. `photoTakenTime` - When the photo was actually taken
2. `creationTime` - Fallback if photoTakenTime is not available

## After Running

1. Verify a few files have correct timestamps:

   ```bash
   exiftool -time:all output/Album/photo.jpg
   ```

2. Import the `output` folder into your photo app of choice.

3. Photos should now appear with their original capture dates.

## License

MIT
