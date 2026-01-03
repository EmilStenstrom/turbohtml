import sys

# Local dev helper: ensure the locally-fetched working-tree sources take precedence.
if "/justhtml_local" not in sys.path:
    sys.path.insert(0, "/justhtml_local")
