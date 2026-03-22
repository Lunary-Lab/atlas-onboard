import os
path = '/home/user/code/atlas/atlas-root/atlas-onboard/.github/workflows/release.yml'
with open(path, 'r') as f:
    content = f.read()

content = content.replace('--config $GITHUB_WORKSPACE/.gitleaks.toml', '--config ${GITHUB_WORKSPACE:-$PWD}/.gitleaks.toml')
with open(path, 'w') as f:
    f.write(content)
