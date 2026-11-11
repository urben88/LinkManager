#!/bin/sh
# Instala (o actualiza) el puente de la consola como servicio de usuario.
set -eu
DIR=$(cd "$(dirname "$0")" && pwd)
install -d -m 700 "$HOME/.local/lib/consola-puente" "$HOME/.config/systemd/user"
install -m 600 "$DIR/puente.py" "$HOME/.local/lib/consola-puente/puente.py"
install -m 644 "$DIR/consola-puente.service" "$HOME/.config/systemd/user/consola-puente.service"
systemctl --user daemon-reload
systemctl --user enable consola-puente.service >/dev/null
systemctl --user restart consola-puente.service
sleep 1
systemctl --user --no-pager status consola-puente.service | head -5
echo "Socket:  $HOME/.local/share/consola-puente/consola.sock"
echo "Secreto: $HOME/.config/consola-puente/secreto"
