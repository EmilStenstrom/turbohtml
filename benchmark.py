#!/usr/bin/env python3
"""
Performance benchmark for TurboHTML against other HTML parsers.
Uses web100k dataset from /home/emilstenstrom/Projects/web100k/batches/
Decompresses at runtime (no disk writes) using html.dict for optimal performance.
"""

# ruff: noqa: PERF203, PLC0415, BLE001, S110
from __future__ import annotations

import argparse
import multiprocessing
import os  # MEMORY: added
import pathlib
import sys
import tarfile
import threading  # MEMORY: added
import time

try:
    import zstandard as zstd
except ImportError:
    print("ERROR: zstandard is required. Install with: pip install zstandard")
    sys.exit(1)

# MEMORY: optional dependency for RSS sampling
try:
    import psutil

    _PSUTIL_AVAILABLE = True
except Exception:
    psutil = None
    _PSUTIL_AVAILABLE = False


# MEMORY: lightweight RSS monitor using psutil
class MemoryMonitor:
    def __init__(self, pid: int | None = None, sample_interval: float = 0.01):
        """
        pid: process ID to monitor (default: current process).
        sample_interval: seconds between samples (default 10ms).
        """
        self.sample_interval = sample_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        target_pid = pid if pid is not None else os.getpid()
        self._proc = psutil.Process(target_pid) if _PSUTIL_AVAILABLE else None
        self.start_rss = None
        self.end_rss = None
        self.peak_rss = None
        self.last_rss = None
        self.samples = 0

    def _get_rss(self) -> int | None:
        if not self._proc:
            return None
        try:
            return self._proc.memory_info().rss
        except Exception:
            return None

    def start(self):
        if not _PSUTIL_AVAILABLE:
            return
        self.start_rss = self._get_rss()
        self.peak_rss = self.start_rss
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            rss = self._get_rss()
            if rss is not None:
                self.last_rss = rss
                if self.peak_rss is None or rss > self.peak_rss:
                    self.peak_rss = rss
                self.samples += 1
            self._stop.wait(self.sample_interval)

    def stop(self):
        if not _PSUTIL_AVAILABLE:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

        # Try to get current RSS, if fail (process dead), use last seen
        current = self._get_rss()
        if current and current > 0:
            self.end_rss = current
        else:
            self.end_rss = self.last_rss

    def to_dict(self) -> dict:
        if not _PSUTIL_AVAILABLE:
            return {"memory_note": "psutil not installed; memory metrics skipped"}

        def mb(x):
            return (x or 0) / (1024 * 1024)

        start_mb = mb(self.start_rss)
        end_mb = mb(self.end_rss)
        peak_mb = mb(self.peak_rss)
        delta_mb = end_mb - start_mb if (self.end_rss is not None and self.start_rss is not None) else 0.0
        return {
            "rss_start_mb": start_mb,
            "rss_end_mb": end_mb,
            "rss_delta_mb": delta_mb,
            "rss_peak_mb": peak_mb,
            "mem_samples": self.samples,
        }


def load_dict(dict_path: pathlib.Path) -> bytes:
    """Load the zstd dictionary required for decompression."""
    if not dict_path.exists():
        print(f"ERROR: Dictionary not found at {dict_path}")
        sys.exit(1)
    return dict_path.read_bytes()


def iter_html_from_batch(
    batch_path: pathlib.Path,
    dict_bytes: bytes,
    limit: int | None = None,
) -> list[tuple[str, str]]:
    """
    Stream HTML files from a compressed batch without writing to disk.
    Returns list of (filename, html_content) tuples.
    """
    if not batch_path.exists():
        print(f"ERROR: Batch file not found at {batch_path}")
        sys.exit(1)
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
                    if limit and count >= limit:
                        break
                    compressed_html = tar.extractfile(member).read()
                    html_content = html_dctx.decompress(compressed_html).decode(
                        "utf-8",
                        errors="replace",
                    )
                    results.append((member.name, html_content))
                    count += 1
    return results


def iter_html_from_downloaded(
    downloaded_dir: pathlib.Path,
    dict_bytes: bytes,
    limit: int | None = None,
) -> list[tuple[str, str]]:
    """
    Load HTML files from downloaded directory (*.html.zst files).
    Returns list of (filename, html_content) tuples.
    """
    if not downloaded_dir.exists():
        print(f"ERROR: Downloaded directory not found at {downloaded_dir}")
        sys.exit(1)
    results = []
    html_dctx = zstd.ZstdDecompressor(
        dict_data=zstd.ZstdCompressionDict(dict_bytes),
    )
    html_files = sorted(downloaded_dir.glob("*.html.zst"))
    if limit:
        html_files = html_files[:limit]
    for file_path in html_files:
        try:
            compressed = file_path.read_bytes()
            html_content = html_dctx.decompress(compressed).decode("utf-8", errors="replace")
            results.append((file_path.name, html_content))
        except Exception as e:
            print(f"Warning: Failed to decompress {file_path.name}: {e}")
            continue
    return results


def iter_html_from_all_batches(
    batches_dir: pathlib.Path,
    dict_bytes: bytes,
    limit: int | None = None,
) -> list[tuple[str, str]]:
    """
    Load HTML files from all batch files in a directory.
    Returns list of (filename, html_content) tuples.
    """
    if not batches_dir.exists():
        print(f"ERROR: Batches directory not found at {batches_dir}")
        sys.exit(1)
    batch_files = sorted(batches_dir.glob("web100k-batch-*.tar.zst"))
    if not batch_files:
        print(f"ERROR: No batch files found in {batches_dir}")
        sys.exit(1)
    all_results = []
    for batch_file in batch_files:
        print(f"  Loading {batch_file.name}...")
        batch_results = iter_html_from_batch(batch_file, dict_bytes, limit=None)
        all_results.extend(batch_results)
        if limit and len(all_results) >= limit:
            all_results = all_results[:limit]
            break
    return all_results


def benchmark_turbohtml(html_files: list, iterations: int = 1) -> dict:
    """Benchmark TurboHTML parser with Rust tokenizer."""
    try:
        from turbohtml import TurboHTML
    except ImportError:
        return {"error": "TurboHTML not importable"}
    all_times = []
    errors = 0
    error_files = []
    if html_files:
        try:
            TurboHTML(html_files[0][1])
        except Exception:
            pass
    for _ in range(iterations):
        for filename, html in html_files:
            try:
                start = time.perf_counter()
                result = TurboHTML(html)
                elapsed = time.perf_counter() - start
                all_times.append(elapsed)
                _ = result.root
            except Exception as e:
                errors += 1
                error_files.append((filename, str(e)))
    return {
        "total_time": sum(all_times),
        "mean_time": sum(all_times) / len(all_times) if all_times else 0,
        "min_time": min(all_times) if all_times else 0,
        "max_time": max(all_times) if all_times else 0,
        "errors": errors,
        "success_count": len(all_times),
        "error_files": error_files,
    }


def benchmark_html5lib(html_files: list, iterations: int = 1) -> dict:
    """Benchmark html5lib parser."""
    try:
        import html5lib
    except ImportError:
        return {"error": "html5lib not installed (pip install html5lib)"}
    all_times = []
    errors = 0
    if html_files:
        try:
            html5lib.parse(html_files[0][1])
        except Exception:
            pass
    for _ in range(iterations):
        for _, html in html_files:
            try:
                start = time.perf_counter()
                result = html5lib.parse(html)
                elapsed = time.perf_counter() - start
                all_times.append(elapsed)
                _ = result
            except Exception:
                errors += 1
    return {
        "total_time": sum(all_times),
        "mean_time": sum(all_times) / len(all_times) if all_times else 0,
        "min_time": min(all_times) if all_times else 0,
        "max_time": max(all_times) if all_times else 0,
        "errors": errors,
        "success_count": len(all_times),
    }


def benchmark_lxml(html_files: list, iterations: int = 1) -> dict:
    """Benchmark lxml parser."""
    try:
        from lxml import html as lxml_html
    except ImportError:
        return {"error": "lxml not installed (pip install lxml)"}
    times = []
    errors = 0
    if html_files:
        try:
            lxml_html.fromstring(html_files[0][1])
        except Exception:
            pass
    for _ in range(iterations):
        for _, content in html_files:
            try:
                start = time.perf_counter()
                result = lxml_html.fromstring(content)
                elapsed = time.perf_counter() - start
                times.append(elapsed)
                _ = result
            except Exception:
                errors += 1
    return {
        "total_time": sum(times),
        "mean_time": sum(times) / len(times) if times else 0,
        "min_time": min(times) if times else 0,
        "max_time": max(times) if times else 0,
        "errors": errors,
        "success_count": len(times),
    }


def benchmark_bs4(html_files: list, iterations: int = 1) -> dict:
    """Benchmark BeautifulSoup4 parser."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"error": "beautifulsoup4 not installed (pip install beautifulsoup4)"}
    times = []
    errors = 0
    if html_files:
        try:
            BeautifulSoup(html_files[0][1], "html.parser")
        except Exception:
            pass
    for _ in range(iterations):
        for _, html in html_files:
            try:
                start = time.perf_counter()
                result = BeautifulSoup(html, "html.parser")
                elapsed = time.perf_counter() - start
                times.append(elapsed)
                _ = result.name
            except Exception:
                errors += 1
    return {
        "total_time": sum(times),
        "mean_time": sum(times) / len(times) if times else 0,
        "min_time": min(times) if times else 0,
        "max_time": max(times) if times else 0,
        "errors": errors,
        "success_count": len(times),
    }


def benchmark_html_parser(html_files: list, iterations: int = 1) -> dict:
    """Benchmark stdlib html.parser."""
    try:
        from html.parser import HTMLParser
    except ImportError:
        return {"error": "html.parser not available (stdlib)"}

    class SimpleHTMLParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.data = []

        def handle_starttag(self, tag, attrs):
            self.data.append(("start", tag, attrs))

        def handle_endtag(self, tag):
            self.data.append(("end", tag))

        def handle_data(self, data):
            self.data.append(("data", data))

    times = []
    errors = 0
    if html_files:
        try:
            parser = SimpleHTMLParser()
            parser.feed(html_files[0][1])
        except Exception:
            pass
    for _ in range(iterations):
        for _, html in html_files:
            try:
                start = time.perf_counter()
                parser = SimpleHTMLParser()
                parser.feed(html)
                elapsed = time.perf_counter() - start
                times.append(elapsed)
                _ = parser.data
            except Exception:
                errors += 1
    return {
        "total_time": sum(times),
        "mean_time": sum(times) / len(times) if times else 0,
        "min_time": min(times) if times else 0,
        "max_time": max(times) if times else 0,
        "errors": errors,
        "success_count": len(times),
    }


def benchmark_selectolax(html_files: list, iterations: int = 1) -> dict:
    """Benchmark selectolax parser."""
    try:
        from selectolax.parser import HTMLParser
    except ImportError:
        return {"error": "selectolax not installed (pip install selectolax)"}
    times = []
    errors = 0
    if html_files:
        try:
            HTMLParser(html_files[0][1])
        except Exception:
            pass
    for _ in range(iterations):
        for _, html in html_files:
            try:
                start = time.perf_counter()
                result = HTMLParser(html)
                elapsed = time.perf_counter() - start
                times.append(elapsed)
                _ = result.root
            except Exception:
                errors += 1
    return {
        "total_time": sum(times),
        "mean_time": sum(times) / len(times) if times else 0,
        "min_time": min(times) if times else 0,
        "max_time": max(times) if times else 0,
        "errors": errors,
        "success_count": len(times),
    }


def _benchmark_worker(bench_fn, html_files, iterations, queue):
    """Worker function to run benchmark in a separate process."""
    try:
        res = bench_fn(html_files, iterations)
        queue.put(res)
    except Exception as e:
        queue.put({"error": str(e)})


def run_benchmark_isolated(bench_fn, html_files, iterations, args):
    """Run benchmark in a separate process to isolate memory usage."""
    if args.no_mem or not _PSUTIL_AVAILABLE:
        return bench_fn(html_files, iterations)

    # Force GC in parent to minimize COW overhead (though fork handles it)
    import gc
    gc.collect()

    queue = multiprocessing.Queue()
    p = multiprocessing.Process(
        target=_benchmark_worker,
        args=(bench_fn, html_files, iterations, queue)
    )
    p.start()

    # Monitor the child process
    mon = MemoryMonitor(pid=p.pid, sample_interval=max(0.0005, args.mem_sample_ms / 1000.0))
    mon.start()

    res = None
    try:
        res = queue.get()
    finally:
        mon.stop()
        p.join()

    if res and "error" not in res:
        res.update(mon.to_dict())
    return res


def print_results(results: dict, file_count: int, iterations: int = 1):
    """Pretty print benchmark results."""
    print("\n" + "=" * 100)
    if iterations > 1:
        print(f"BENCHMARK RESULTS ({file_count} HTML files x {iterations} iterations)")
    else:
        print(f"BENCHMARK RESULTS ({file_count} HTML files)")
    print("=" * 100)
    parsers = ["turbohtml", "turbohtml_rust", "html5lib", "lxml", "bs4", "html.parser", "selectolax"]

    # Combined header
    header = f"\n{'Parser':<15} {'Total (s)':<10} {'Mean (ms)':<10} {'Peak (MB)':<10} {'Delta (MB)':<10} {'Errors':<8}"
    print(header)
    print("-" * 100)

    turbohtml_time = results.get("turbohtml", {}).get("total_time", 0)

    for parser in parsers:
        if parser not in results:
            continue
        result = results[parser]
        if "error" in result:
            print(f"{parser:<15} {result['error']}")
            continue

        total = result["total_time"]
        mean_ms = result["mean_time"] * 1000
        errors = result["errors"]

        # Memory stats
        peak_mb = result.get("rss_peak_mb", 0)
        delta_mb = result.get("rss_delta_mb", 0)
        mem_str = f"{peak_mb:>10.1f} {delta_mb:>10.1f}" if "rss_peak_mb" in result else f"{'n/a':>10} {'n/a':>10}"

        speedup = ""
        if parser != "turbohtml" and turbohtml_time > 0 and total > 0:
            speedup_factor = total / turbohtml_time
            speedup = f" ({speedup_factor:.2f}x)"

        print(f"{parser:<15} {total:<10.3f} {mean_ms:<10.3f} {mem_str} {errors:<8}{speedup}")

    print("\n" + "=" * 100)

    # Speedup summary
    if turbohtml_time > 0:
        print("\nTurboHTML vs other parsers:")
        for parser in ["html5lib", "lxml", "bs4", "html.parser", "selectolax"]:
            if parser in results and "error" not in results[parser]:
                total = results[parser]["total_time"]
                if total > 0:
                    speedup = turbohtml_time / total
                    print(f"  {parser:<15} {speedup:>6.2f}x {'slower' if speedup < 1 else 'faster'}")
        print()
    # Error details
    for parser in parsers:
        if parser not in results:
            continue
        result = results[parser]
        error_files = result.get("error_files", [])
        if error_files:
            print(f"\nErrors for {parser}:")
            for filename, error_msg in error_files:
                print(f"  {filename}: {error_msg}")
            print()


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark HTML parsers using web100k dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--batch", type=pathlib.Path, help="Path to single batch file")
    parser.add_argument(
        "--batches-dir",
        type=pathlib.Path,
        default=pathlib.Path("/home/emilstenstrom/Projects/web100k/batches"),
        help="Path to directory containing all batch files (default: web100k/batches)",
    )
    parser.add_argument("--downloaded", type=pathlib.Path, help="Path to downloaded directory with .html.zst files")
    parser.add_argument("--all-batches", action="store_true", help="Process all batch files in batches-dir")
    parser.add_argument(
        "--dict",
        type=pathlib.Path,
        default=pathlib.Path("/home/emilstenstrom/Projects/web100k/html.dict"),
        help="Path to html.dict file",
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Limit number of files to test (default: 100, use 0 for all)",
    )
    parser.add_argument(
        "--iterations", type=int, default=5, help="Number of iterations to run for averaging (default: 5)",
    )
    parser.add_argument(
        "--parsers",
        nargs="+",
        choices=["turbohtml", "html5lib", "lxml", "bs4", "html.parser", "selectolax"],
        default=["turbohtml", "html5lib", "lxml", "bs4", "html.parser", "selectolax"],
        help="Parsers to benchmark (default: all)",
    )
    # MEMORY: options
    parser.add_argument("--no-mem", action="store_true", help="Disable memory measurement (RSS sampling)")
    parser.add_argument(
        "--mem-sample-ms", type=float, default=10.0, help="Memory sampling interval in milliseconds (default: 10ms)",
    )

    args = parser.parse_args()

    # Load dictionary
    print(f"Loading dictionary from {args.dict}...")
    dict_bytes = load_dict(args.dict)

    # Load HTML files into memory
    limit = args.limit if args.limit > 0 else None
    if args.downloaded:
        print(f"Loading HTML files from {args.downloaded}...")
        html_files = iter_html_from_downloaded(args.downloaded, dict_bytes, limit)
    elif args.all_batches:
        print(f"Loading HTML files from all batches in {args.batches_dir}...")
        html_files = iter_html_from_all_batches(args.batches_dir, dict_bytes, limit)
    elif args.batch:
        print(f"Loading HTML files from {args.batch}...")
        html_files = iter_html_from_batch(args.batch, dict_bytes, limit)
    else:
        default_batch = args.batches_dir / "web100k-batch-001.tar.zst"
        print(f"Loading HTML files from {default_batch}...")
        html_files = iter_html_from_batch(default_batch, dict_bytes, limit)
    if not html_files:
        print("ERROR: No HTML files loaded")
        sys.exit(1)
    print(f"Loaded {len(html_files)} HTML files")

    total_bytes = sum(len(html) for _, html in html_files)
    print(f"Total HTML size: {total_bytes / 1024 / 1024:.2f} MB")

    # Helper: run a benchmark with optional memory measurement
    def run_with_memory(bench_fn, *bargs, **bkwargs):
        # Use isolated process runner
        return run_benchmark_isolated(bench_fn, *bargs, args=args)

    # Run benchmarks
    results = {}
    benchmarks = {
        "turbohtml": benchmark_turbohtml,
        "html5lib": benchmark_html5lib,
        "lxml": benchmark_lxml,
        "bs4": benchmark_bs4,
        "html.parser": benchmark_html_parser,
        "selectolax": benchmark_selectolax,
    }
    if not _PSUTIL_AVAILABLE and not args.no_mem:
        print("Note: psutil not installed; memory metrics will be skipped. Install with: pip install psutil")

    for parser_name in args.parsers:
        print(f"\nBenchmarking {parser_name}...", end="", flush=True)
        res = run_with_memory(benchmarks[parser_name], html_files, args.iterations)
        results[parser_name] = res
        if "error" in res:
            print(f" SKIPPED ({res['error']})")
        else:
            print(
                f" DONE ({res['total_time']:.3f}s"
                + (f", peak RSS {res.get('rss_peak_mb', 0):.1f} MB" if "rss_peak_mb" in res else "")
                + ")",
            )

    # Print results
    print_results(results, len(html_files), args.iterations)


if __name__ == "__main__":
    main()
