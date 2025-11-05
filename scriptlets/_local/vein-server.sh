# scriptlet:steam/install-steamcmd.sh
# scriptlet:_common/get_firewall.sh
# scriptlet:ufw/install.sh
# scriptlet:_common/package_install.sh
# scriptlet:_common/firewall_allow.sh

##
# Install the VEIN game server using Steam
#
# Expects the following variables:
#   GAME_USER    - User account to install the game under
#   GAME_DIR     - Directory to install the game into
#   STEAM_ID     - Steam App ID of the game
#   GAME_DESC    - Description of the game (for logging purposes)
#   GAME_SERVICE - Service name to install with Systemd
#
function install_vein() {
	# Create a "steam" user account
	# This will create the account with no password, so if you need to log in with this user,
	# run `sudo passwd steam` to set a password.
	if [ -z "$(getent passwd $GAME_USER)" ]; then
		useradd -m -U $GAME_USER
	fi

	# Preliminary requirements
	# VEIN needs ALSA and PulseAudio libraries to run
	package_install curl sudo libasound2-data libpulse0 python3-venv

	if [ "$FIREWALL" == "1" ]; then
		if [ "$(get_enabled_firewall)" == "none" ]; then
			# No firewall installed, go ahead and install UFW
			install_ufw
		fi
	fi

	# Install steam binary and steamcmd
	install_steamcmd

	sudo -u $GAME_USER /usr/games/steamcmd +force_install_dir "$GAME_DIR/AppFiles" +login anonymous +app_update $STEAM_ID validate +quit
	if [ $? -ne 0 ]; then
		echo "Could not install $GAME_DESC, exiting" >&2
		exit 1
	fi

	# VEIN requires the Steam client binary to be loaded into the game server
	[ -h "$GAME_DIR/AppFiles/Vein/Binaries/Linux/steamclient.so" ] || \
		sudo -u $GAME_USER \
		ln -s /home/$GAME_USER/.steam/steam/steamcmd/linux64/steamclient.so "$GAME_DIR/AppFiles/Vein/Binaries/Linux/steamclient.so"

	# Install system service file to be loaded by systemd
    cat > /etc/systemd/system/${GAME_SERVICE}.service <<EOF
# script:systemd-template.service
EOF
    systemctl daemon-reload
    systemctl enable $GAME_SERVICE

    # Ensure game configurations exist, (for convenience)
    [ -e "$GAME_DIR/AppFiles/Vein/Saved/Config/LinuxServer" ] || \
    	sudo -u $GAME_USER mkdir -p "$GAME_DIR/AppFiles/Vein/Saved/Config/LinuxServer"
	[ -e "$GAME_DIR/AppFiles/Vein/Saved/Config/LinuxServer/Game.ini" ] || \
		sudo -u $GAME_USER touch "$GAME_DIR/AppFiles/Vein/Saved/Config/LinuxServer/Game.ini"
	[ -e "$GAME_DIR/AppFiles/Vein/Saved/Config/LinuxServer/GameUserSettings.ini" ] || \
		sudo -u $GAME_USER touch "$GAME_DIR/AppFiles/Vein/Saved/Config/LinuxServer/GameUserSettings.ini"

	# Symlink for convenience
	[ -h "$GAME_DIR/Game.ini" ] || \
		sudo -u $GAME_USER ln -s "$GAME_DIR/AppFiles/Vein/Saved/Config/LinuxServer/Game.ini" "$GAME_DIR/Game.ini"
	[ -h "$GAME_DIR/GameUserSettings.ini" ] || \
		sudo -u $GAME_USER ln -s "$GAME_DIR/AppFiles/Vein/Saved/Config/LinuxServer/GameUserSettings.ini" "$GAME_DIR/GameUserSettings.ini"
	[ -h "$GAME_DIR/SaveGames" ] || \
		sudo -u $GAME_USER ln -s "$GAME_DIR/AppFiles/Vein/Saved/SaveGames" "$GAME_DIR/SaveGames"
	[ -h "$GAME_DIR/Vein.log" ] || \
		sudo -u $GAME_USER ln -s "$GAME_DIR/AppFiles/Vein/Saved/Logs/Vein.log" "$GAME_DIR/Vein.log"
}

function install_management() {
	# Install management console and its dependencies
	local TMP=$(mktemp)
	curl -sL "https://raw.githubusercontent.com/${REPO}/refs/tags/${INSTALLER_VERSION}/dist/manage.py" -o $TMP
	if [ $? -ne 0 ]; then
		echo "Could not download management script!" >&2
		return
	fi

	mv $TMP "$GAME_DIR/manage.py"
	chown $GAME_USER:$GAME_USER "$GAME_DIR/manage.py"
	chmod +x "$GAME_DIR/manage.py"

	# If a pyenv is required:
	#sudo -u $GAME_USER python3 -m venv "$GAME_DIR/.venv"
	#sudo -u $GAME_USER "$GAME_DIR/.venv/bin/pip" install --upgrade pip
	#sudo -u $GAME_USER "$GAME_DIR/.venv/bin/pip" install ...
}