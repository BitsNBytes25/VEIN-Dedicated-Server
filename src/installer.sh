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
REPO="BitsNBytes25/VEIN-Dedicated-Server"
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

if [ -e "$GAME_DIR/AppFiles/VeinServer.sh" ]; then
	EXISTING=1
else
	EXISTING=0
fi

if [ -e "/etc/systemd/system/${GAME_SERVICE}.service" ]; then
	if egrep -q '^ExecStartPre=.*-beta ' "/etc/systemd/system/${GAME_SERVICE}.service"; then
		BETA="$(egrep '^ExecStartPre=.*-beta ' /etc/systemd/system/vein-server.service | sed 's:.*-beta \([^ ]*\) .*:\1:')"
	else
		BETA=""
	fi
else
	BETA=""
fi

############################################
## Installer
############################################

print_header "$GAME_DESC *unofficial* Installer ${INSTALLER_VERSION}"

if [ $OPT_MODE_INSTALL -eq 1 ]; then

	if [ $EXISTING -eq 0 ]; then
		FIREWALL="$(prompt_yn --default-yes "Install system firewall?")"
	else
		FIREWALL=0
	fi

	if [ -n "$BETA" ]; then
		echo "Using beta branch $BETA"
		if [ "$(prompt_yn --default-no "Switch to stable branch?")" == "1" ]; then
			BETA=""
		fi
	else
		if [ "$(prompt_yn --default-no "Install experimental branch?")" == "1" ]; then
			BETA="experimental"
		fi
	fi

	if [ -n "$BETA" ]; then
		STEAMBETABRANCH=" -beta $BETA"
	else
		STEAMBETABRANCH=""
	fi

	install_vein

	install_management

	# Print some instructions and useful tips
    print_header "$GAME_DESC Installation Complete"
    echo 'Game server will auto-update on restarts and will auto-start on server boot.'
    echo ''
    echo "Game files:     $GAME_DIR/AppFiles/"
    echo "Game settings:  $GAME_DIR/Game.ini"
    echo "GUS settings:   $GAME_DIR/GameUserSettings.ini"
    echo "Log:            $GAME_DIR/Vein.log"
    echo ''
    echo "Next steps: configure your server by running"
    echo "sudo $GAME_DIR/manage.py"
fi

