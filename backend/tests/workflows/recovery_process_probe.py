"""Child process for loopback-only HTTP/crash recovery tests."""
import asyncio
import json
from pathlib import Path
import sys

from app.workflows import source_reader
from app.workflows.recovery_reads import read_source


async def main():
    root, url, phase = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

    async def fixture_url(value):
        # Only this test child can read its one parent-owned loopback fixture.
        # Production public_url and redirect validation remain unchanged.
        if value != url or not value.startswith('http://127.0.0.1:'):
            raise ValueError('Unexpected fixture URL')

    source_reader.public_url = fixture_url

    async def barrier(name):
        (root / 'phase.json').write_text(json.dumps({'phase': name}), encoding='utf-8')
        while not (root / 'release').exists():
            await asyncio.sleep(.02)

    class Reader(source_reader.SourceReader):
        async def read(self, value, kind):
            result = await super().read(value, kind)
            if phase == 'before_commit':
                await barrier(phase)
            return result

    try:
        document = await read_source(Reader(), url, 'paper', root)
        if phase == 'after_commit':
            await barrier(phase)
        print(json.dumps({'status': 'success', 'source_sha256': document.sha256}), flush=True)
    except ValueError as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
