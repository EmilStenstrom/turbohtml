#!/usr/bin/env python3
"""Profile TurboHTML to find performance bottlenecks."""

import cProfile
import io
import pstats

from turbohtml import TurboHTML

# Sample HTML
html = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <div class="container">
        <p>Paragraph 1</p>
        <p>Paragraph 2</p>
        <table>
            <tr><td>Cell 1</td><td>Cell 2</td></tr>
            <tr><td>Cell 3</td><td>Cell 4</td></tr>
        </table>
    </div>
</body>
</html>
""" * 100  # Repeat for more meaningful results

# Profile
pr = cProfile.Profile()
pr.enable()

for _ in range(10):
    result = TurboHTML(html)
    _ = result.root

pr.disable()

# Print stats
s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(50)  # Top 50 functions
print(s.getvalue())
