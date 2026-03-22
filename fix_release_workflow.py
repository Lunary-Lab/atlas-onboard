import os
path = '/home/user/code/atlas/atlas-root/atlas-onboard/.github/workflows/release.yml'
with open(path, 'r') as f:
    content = f.read()

old_build = """      - name: Build onboard payload
        working-directory: payload
        run: |
          source .venv/bin/activate
          python -m build
          mv dist/*.tar.gz dist/payload.tar.gz"""

new_build = """      - name: Build onboard payload
        working-directory: payload
        run: |
          source .venv/bin/activate
          python -m build
          # The bootstrap scripts expect a flat archive of the payload folder, not the python sdist
          tar -czf dist/payload.tar.gz ."""

if old_build in content:
    with open(path, 'w') as f:
        f.write(content.replace(old_build, new_build))
