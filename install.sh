#!/usr/bin/env bash
set -euo pipefail

# Usar APT para instalar Qt5 y herramientas necesarias
# Nota: si el entorno de Render no permite apt, usá la opción Docker (B).
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  build-essential curl ca-certificates \
  qtbase5-dev qtbase5-dev-tools qtchooser qt5-qmake libgl1-mesa-dev

# Registrar qmake-qt5 como 'qmake' si existe
if [ -x /usr/bin/qmake-qt5 ]; then
  sudo update-alternatives --install /usr/bin/qmake qmake /usr/bin/qmake-qt5 50 || true
  sudo update-alternatives --set qmake /usr/bin/qmake-qt5 || true
fi

# Mostrar qmake para verificar
qmake -v || true

# (Opcional) Instalar PyQt5 en el entorno Python del build
python -m pip install --upgrade pip setuptools wheel
pip install PyQt5 || true

# Finalmente instalar tus requirements (o lo que uses en el build)
pip install -r requirements.txt