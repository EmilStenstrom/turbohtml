#!/usr/bin/env python3
"""Profile JustHTML on real-world HTML."""

import cProfile
import pathlib
import pstats
import tarfile

import zstandard as zstd

from justhtml import JustHTML


def load_dict(dict_path: pathlib.Path) -> bytes:
    """Load the zstd dictionary."""
    return dict_path.read_bytes()


def load_html_files(batch_path: pathlib.Path, dict_bytes: bytes, limit: int = 100):
    """Load HTML files from batch."""
    results = []
    tar_dctx = zstd.ZstdDecompressor()
    with batch_path.open("rb") as batch_file:
        with tar_dctx.stream_reader(batch_file) as reader:
            with tarfile.open(fileobj=reader, mode="r|") as tar:
                html_dctx = zstd.ZstdDecompressor(
                    dict_data=zstd.ZstdCompressionDict(dict_bytes),
                )

                count = 0
                for member in tar:
                    if not member.isfile() or not member.name.endswith(".html.zst"):
                        continue

                    if count >= limit:
                        break

                    compressed_html = tar.extractfile(member).read()
                    html_content = html_dctx.decompress(compressed_html).decode(
                        "utf-8",
                        errors="replace",
                    )
                    results.append((member.name, html_content))
                    count += 1

    return results


# Load real HTML
dict_bytes = load_dict(pathlib.Path("/home/emilstenstrom/Projects/web100k/html.dict"))
html_files = load_html_files(
    pathlib.Path("/home/emilstenstrom/Projects/web100k/batches/web100k-batch-001.tar.zst"),
    dict_bytes,
    limit=100,
)

print(f"Loaded {len(html_files)} files")

# Profile
profiler = cProfile.Profile()
profiler.enable()

for _filename, html in html_files:
    parser = JustHTML(html)
    _ = parser.root

profiler.disable()

# Print stats
stats = pstats.Stats(profiler)
stats.sort_stats("tottime")
stats.print_stats(80)
