import os
import shutil
import zipfile
from pathlib import Path
from typing import Tuple, List, Optional
from elite_cloud.config import MAX_UPLOAD_SIZE_MB, MAX_EXTRACTED_SIZE_MB, MAX_FILES_PER_ZIP

class ZipSecurityError(Exception):
    pass

class ZipValidator:
    @staticmethod
    def validate_and_extract(
        zip_path: Path,
        destination_dir: Path,
        max_files: int = MAX_FILES_PER_ZIP,
        max_compressed_mb: int = MAX_UPLOAD_SIZE_MB,
        max_extracted_mb: int = MAX_EXTRACTED_SIZE_MB
    ) -> Tuple[int, int]:
        """
        Validates archive safety (Zip Slip, symlinks, bomb limits) and extracts to destination_dir.
        Returns (file_count, total_extracted_bytes).
        """
        if not zip_path.exists():
            raise ZipSecurityError("ZIP archive file not found.")

        # Check compressed size
        compressed_size = zip_path.stat().st_size
        if compressed_size > max_compressed_mb * 1024 * 1024:
            raise ZipSecurityError(f"ZIP archive size ({compressed_size / 1024 / 1024:.1f} MB) exceeds limit of {max_compressed_mb} MB.")

        if not zipfile.is_zipfile(zip_path):
            raise ZipSecurityError("Provided file is not a valid ZIP archive.")

        destination_dir.mkdir(parents=True, exist_ok=True)
        dest_canonical = destination_dir.resolve()

        file_count = 0
        total_extracted_bytes = 0

        with zipfile.ZipFile(zip_path, 'r') as zf:
            infolist = zf.infolist()

            if len(infolist) > max_files:
                raise ZipSecurityError(f"ZIP contains {len(infolist)} entries, exceeding maximum allowed of {max_files} files.")

            for member in infolist:
                file_count += 1
                total_extracted_bytes += member.file_size

                # Decompression bomb check
                if total_extracted_bytes > max_extracted_mb * 1024 * 1024:
                    raise ZipSecurityError(f"Extracted content exceeds safety threshold of {max_extracted_mb} MB.")

                # Zip Slip path traversal check
                target_path = (destination_dir / member.filename).resolve()
                if not str(target_path).startswith(str(dest_canonical)):
                    raise ZipSecurityError(f"Malicious archive entry detected attempting path traversal: {member.filename}")

                # Check for symlink flags in external_attr
                if (member.external_attr >> 16) & 0o120000 == 0o120000:
                    raise ZipSecurityError(f"Symlinks are disallowed for security reasons: {member.filename}")

            # Safe extraction
            zf.extractall(path=destination_dir)

        # Unnest if everything is inside a single parent folder
        ZipValidator._unnest_single_root(destination_dir)

        return file_count, total_extracted_bytes

    @staticmethod
    def _unnest_single_root(target_dir: Path):
        """If extracted directory has only 1 subfolder and no files, moves contents up one level."""
        entries = list(target_dir.iterdir())
        subdirs = [e for e in entries if e.is_dir() and not e.name.startswith(".")]
        files = [e for e in entries if e.is_file()]

        if len(subdirs) == 1 and len(files) == 0:
            single_sub = subdirs[0]
            temp_move = target_dir.parent / (target_dir.name + "_unnest_tmp")
            shutil.move(str(single_sub), str(temp_move))
            for item in temp_move.iterdir():
                shutil.move(str(item), str(target_dir))
            shutil.rmtree(temp_move, ignore_errors=True)

    @staticmethod
    def create_zip_from_dir(source_dir: Path, output_zip_path: Path) -> Path:
        """Packages a workspace folder into a clean ZIP archive (excluding junk files)."""
        ignored_names = {".git", "__pycache__", "node_modules", ".venv", "venv", ".DS_Store"}
        output_zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(source_dir):
                dirs[:] = [d for d in dirs if d not in ignored_names]
                for f in files:
                    if f in ignored_names:
                        continue
                    file_path = Path(root) / f
                    arcname = file_path.relative_to(source_dir)
                    zf.write(file_path, arcname)
        return output_zip_path
