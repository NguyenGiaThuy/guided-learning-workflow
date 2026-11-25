import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", newline="\n")

from gl import version  # noqa: E402


def main(argv):
    if argv and argv[0] == "version":
        sys.stdout.write("%s %s\n" % (version.VERSION, version.plugin_hash()))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
