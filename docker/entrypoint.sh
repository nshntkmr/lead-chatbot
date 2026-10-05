#!/bin/sh
# Container start: an SSH server for Azure App Service's "SSH" console, then the app.
#
# App Service reaches a custom container's shell only through an SSH server inside it, on port 2222 with the
# fixed login root / Docker! (their documented convention). That port is not published to the internet: the
# portal connects through the platform after Azure sign-in. It exists so an operator can run, against the live
# database, the same commands as on a laptop:
#     python -m scripts.manage_users add <user>
set -e

# An SSH login does not inherit the container's environment, and the app's settings (where app.db is, the
# Claude credentials) live there. Write them where a login shell reads them, readable by root only.
umask 077
printenv | grep -v -E '^(HOME|PWD|OLDPWD|SHLVL|_|TERM|HOSTNAME)=' \
  | sed -e "s/'/'\\\\''/g" -e "s/^\([^=]*\)=\(.*\)$/export \1='\2'/" > /etc/profile.d/app-env.sh
echo 'cd /app' >> /etc/profile.d/app-env.sh
umask 022

ssh-keygen -A >/dev/null
mkdir -p /run/sshd
/usr/sbin/sshd

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
