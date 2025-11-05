#!/bin/bash
#
# Install VEIN Server
#
# https://ramjet.notion.site
#
# Please ensure to run this script as root (or at least with sudo)
#
# @LICENSE AGPLv3
# @AUTHOR  Charlie Powell <cdp1337@bitsnbytes.dev>
# @CATEGORY Game Server
# @TRMM-TIMEOUT 600
#
# Supports:
#   Debian 12, 13
#   Ubuntu 24.04
#
# Requirements:
#   None
#
# TRMM Custom Fields:
#   None
#
# Syntax:
#   OPT_MODE_INSTALL=--install - Perform an installation (default if no options given)
#
# Changelog:
#   20251103 - New installer

############################################
## Parameter Configuration
############################################

# Name of the game (used to create the directory)
INSTALLER_VERSION="v20251103"
GAME="VEIN"
GAME_DESC="VEIN Dedicated Server"
# Steam ID of the game
STEAM_ID="2131400"
GAME_USER="steam"
GAME_DIR="/home/$GAME_USER/$GAME"
GAME_SERVICE="vein-server"
# Force installation directory for game
# steam produces varying results, sometimes in ~/.local/share/Steam, other times in ~/Steam
STEAM_DIR="/home/$GAME_USER/.local/share/Steam"
#PORT_GAME=7777
#PORT_QUERY=27015

# compile:argparse
# scriptlet:_common/require_root.sh
# scriptlet:_common/get_firewall.sh
# scriptlet:bz_eval_tui/prompt_text.sh
# scriptlet:bz_eval_tui/print_header.sh
# scriptlet:_local/vein-server.sh


############################################
## Argument Parsing
############################################

# Default to install mode
OPT_MODE_INSTALL=1

############################################
## Pre-exec Checks
############################################

if systemctl -q is-active $GAME_SERVICE; then
	echo "$GAME_DESC service is currently running, please stop it before running this installer."
	echo "You can do this with: sudo systemctl stop $GAME_SERVICE"
	exit 1
fi

############################################
## Installer
############################################

print_header "$GAME_DESC *unofficial* Installer ${INSTALLER_VERSION}"

if [ $OPT_MODE_INSTALL -eq 1 ]; then

	FIREWALL="$(prompt_yn --default-yes "Install system firewall?")"
	# install_vein

	install_management

	# Print some instructions and useful tips
    print_header "$GAME_DESC Installation Complete"
    echo 'Game server will auto-update on restarts and will auto-start on server boot.'
    echo ''
    echo "Game files:     $GAME_DIR/AppFiles/"
    echo "Game settings:  $GAME_DIR/PalWorldSettings.ini"
    echo ''
    echo "Next steps: configure your server by running"
    echo "sudo $GAME_DIR/manage.py"
fi

# Install management script
#cat > $GAME_DIR/manage.py <<EOF
## script:manage.py
#EOF
#chown $GAME_USER:$GAME_USER $GAME_DIR/manage.py
#chmod +x $GAME_DIR/manage.py


# Create some helpful links for the user.
#[ -h "$GAME_DIR/PalWorldSettings.ini" ] || sudo -u steam ln -s $GAME_DIR/AppFiles/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini "$GAME_DIR/PalWorldSettings.ini"
