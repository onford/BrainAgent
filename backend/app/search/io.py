import json
import os
from pathlib import Path
import stat
import tempfile

from app.file_publish import replace_file


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        # Source/branch trees are deep; publication must not append another
        # entire content hash and UUID to an otherwise valid Windows path.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                dir=path.parent, prefix=".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def directory_bytes(root):
    """Sample a live tree without treating atomic publication as a failure.

    Entries may disappear after enumeration. Other I/O errors still propagate;
    inaccessible storage must not be reported as unused capacity. Do not follow
    directory links outside the owned tree. This is a resource sample, not an
    artifact integrity check.
    """
    root = Path(root)
    pending = [root]
    total = 0
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
        except FileNotFoundError:
            if directory == root:
                raise
    return total
