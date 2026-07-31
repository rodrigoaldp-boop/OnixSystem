#!/usr/bin/env bash
# Wrapper seguro — so roda no AlmaLinux com /opt/onixsystem-prod.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -d /opt/onixsystem-prod/sga_financeiro ]]; then
  echo "ABORTADO: /opt/onixsystem-prod nao existe neste host."
  echo "Isso NAO e o servidor AlmaLinux. Nao copie o clone GitHub por cima do /opt."
  echo "No AlmaLinux, rode: python3 scripts/deploy_saude_cirurgico.py --restart"
  exit 1
fi
if [[ ! -f /opt/onixsystem-prod/sga_financeiro/botbot_whatsapp_config.py ]]; then
  echo "ABORTADO: BotBot nao encontrado em producao. Recusando deploy para nao operar em tree incompleto."
  exit 1
fi
python3 scripts/deploy_saude_cirurgico.py --restart "$@"
