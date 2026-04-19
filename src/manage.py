#!/usr/bin/env python3
import os

# To allow running as a standalone script without installing the package, include the venv path for imports.
# This will set the include path for this path to .venv to allow packages installed therein to be utilized.
#
# IMPORTANT - any imports that are needed for the script to run must be after this,
# otherwise the imports will fail when running as a standalone script.
# import:org_python/venv_path_include.py

import logging
import shutil

# Import the appropriate type of handler for the game installer.
# Common options are:
# from warlock_manager.apps.base_app import BaseApp
from warlock_manager.apps.steam_app import SteamApp
from warlock_manager.formatters.cli_formatter import cli_formatter

# Import the appropriate type of handler for the game services.
# Common options are:
# from warlock_manager.services.base_service import BaseService
# from warlock_manager.services.rcon_service import RCONService
# from warlock_manager.services.socket_service import SocketService
from warlock_manager.services.http_service import HTTPService

# Import the various configuration handlers used by this game.
# Common options are:
# from warlock_manager.config.cli_config import CLIConfig
from warlock_manager.config.ini_config import INIConfig
# from warlock_manager.config.json_config import JSONConfig
# from warlock_manager.config.properties_config import PropertiesConfig
from warlock_manager.config.unreal_config import UnrealConfig

# Load the application runner responsible for interfacing with CLI arguments
# and providing default functionality for running the manager.
from warlock_manager.libs.app_runner import app_runner

# If your script manages the firewall, (recommended), import the Firewall library
from warlock_manager.libs.firewall import Firewall

# Utilities provided by Warlock that are common to many applications
from warlock_manager.libs import utils

# This game supports full mod support
# from warlock_manager.mods.base_mod import BaseMod
from warlock_manager.mods.warlock_nexus_mod import WarlockNexusMod


class GameApp(SteamApp):
	"""
	Game application manager
	"""

	def __init__(self):
		super().__init__()

		self.name = 'VEIN'
		self.desc = 'VEIN Dedicated Server'
		self.steam_id = '2131400'
		self.service_handler = GameService
		self.mod_handler = WarlockNexusMod
		self.service_prefix = 'vein-'
		# VEIN currently only supports a single instance
		self.disabled_features = {'create_service', 'cmd', 'mods'}

		self.configs = {
			'manager': INIConfig('manager', os.path.join(utils.get_app_directory(), '.settings.ini'))
		}

		self.load()

	def first_run(self) -> bool:
		"""
		Perform any first-run configuration needed for this game

		:return:
		"""
		if os.geteuid() != 0:
			logging.error('Please run this script with sudo to perform first-run configuration.')
			return False

		super().first_run()

		# Install the game with Steam.
		# It's a good idea to ensure the game is installed on first run.
		self.update()

		# First run is a great time to auto-create some services for this game too
		services = self.get_services()
		if len(services) == 0:
			# No services detected, create one.
			logging.info('No services detected, creating one...')
			self.create_service('vein-server')
		else:
			# Ensure services match new format
			for service in services:
				logging.info('Ensuring %s service file is on latest format' % service.service)
				service.build_systemd_config()
				service.reload()

		return True

	def post_update(self):
		# VEIN requires the Steam client binary to be loaded into the game server
		src = os.path.join(utils.get_home_directory(), '.steam', 'steam', 'steamcmd', 'linux64', 'steamclient.so')
		dst = os.path.join(utils.get_app_directory(), 'AppFiles', 'Vein', 'Binaries', 'Linux', 'steamclient.so')
		if not os.path.exists(dst):
			logging.info('Copying Steam client library to game directory for VEIN...')
			shutil.copy2(src, dst)
			utils.ensure_file_ownership(dst)

		if os.path.exists(os.path.join(utils.get_app_directory(), 'AppFiles/Vein/Binaries/Linux/VeinServer-Linux-Test')):
			os.chmod(os.path.join(utils.get_app_directory(), 'AppFiles/Vein/Binaries/Linux/VeinServer-Linux-Test'), 0o755)
		if os.path.exists(os.path.join(utils.get_app_directory(), 'AppFiles/Vein/Binaries/Linux/VeinServer-Linux-DebugGame')):
			os.chmod(os.path.join(utils.get_app_directory(), 'AppFiles/Vein/Binaries/Linux/VeinServer-Linux-DebugGame'), 0o755)


class GameService(HTTPService):
	"""
	Service definition and handler
	"""
	def __init__(self, service: str, game: GameApp):
		"""
		Initialize and load the service definition
		:param file:
		"""
		super().__init__(service, game)
		self.configs = {
			'game': UnrealConfig('game', os.path.join(self.get_app_directory(), 'Vein/Saved/Config/LinuxServer/Game.ini')),
			'gus': UnrealConfig('gus', os.path.join(self.get_app_directory(), 'Vein/Saved/Config/LinuxServer/GameUserSettings.ini')),
			'engine': UnrealConfig('engine', os.path.join(self.get_app_directory(), 'Vein/Saved/Config/LinuxServer/Engine.ini')),
			'service': INIConfig('service', os.path.join(utils.get_app_directory(), 'Configs', 'service.%s.ini' % self.service))
		}
		self.load()

	def get_executable(self) -> str:
		if os.path.exists(os.path.join(self.get_app_directory(), 'Vein/Binaries/Linux/VeinServer-Linux-Test')):
			path = os.path.join(self.get_app_directory(), 'Vein/Binaries/Linux/VeinServer-Linux-Test') + ' Vein'
		else:
			path = os.path.join(self.get_app_directory(), 'Vein/Binaries/Linux/VeinServer-Linux-DebugGame') + ' Vein'

		# Add arguments for the service
		args = cli_formatter(self.configs['service'], 'flag', sep='=')
		if args:
			path += ' ' + args

		return path

	def option_value_updated(self, option: str, previous_value, new_value):
		"""
		Handle any special actions needed when an option value is updated
		:param option:
		:param previous_value:
		:param new_value:
		:return:
		"""
		success = None
		rebuild = False

		# Special option actions
		if option == 'GamePort' or option == 'LEGACY GamePort':
			# Update firewall for game port change
			if previous_value:
				Firewall.remove(int(previous_value), 'udp')
			Firewall.allow(int(new_value), 'udp', '%s game port' % self.game.desc)
			rebuild = True
			success = True
		elif option == 'SteamQueryPort' or option == 'LEGACY SteamQueryPort':
			# Update firewall for game port change
			if previous_value:
				Firewall.remove(int(previous_value), 'udp')
			Firewall.allow(int(new_value), 'udp', '%s Steam query port' % self.game.desc)
			rebuild = True
			success = True

		if rebuild:
			self.build_systemd_config()

		return success

	def is_api_enabled(self) -> bool:
		"""
		Check if API is enabled for this service
		:return:
		"""
		return self.get_option_value('APIPort') != ''

	def get_api_port(self) -> int:
		"""
		Get the API port from the service configuration
		:return:
		"""
		return self.get_option_value('APIPort')

	def get_players(self) -> list | None:
		"""
		Get the current players on the server, or None if the API is unavailable
		:return:
		"""
		ret = self._api_cmd('/players')
		if ret is None:
			return None
		else:
			return ret['players']

	def get_player_count(self) -> int | None:
		"""
		Get the current player count on the server, or None if the API is unavailable
		:return:
		"""
		status = self.get_status()
		if status is None:
			return None
		else:
			return len(status['onlinePlayers'])

	def get_player_max(self) -> int:
		"""
		Get the maximum player count allowed on the server
		:return:
		"""
		return self.get_option_value('MaxPlayers')

	def get_status(self) -> dict | None:
		"""
		Get the current server status from the API, or None if the API is unavailable

		Returns a dictionary with the following keys
		'uptime' - float: Uptime in seconds
		'onlinePlayers' - dict: Dictionary of online players

		Each player will be tagged with its PlayerID as the key, and a dictionary with the following keys:
		'name' - str: Player name
		'timeConnected' - float: Time connected in seconds
		'characterId' - str: Unique character ID
		'status' - str: Player status/role

		:return:
		"""
		return self._api_cmd('/status')

	def get_weather(self) -> dict | None:
		"""
		Get the current weather from the API, or None if the API is unavailable

		Returns a dictionary with the following keys
		'temperature' - float: Temperature in Celsius
		'precipitation' - int: Precipitation level
		'cloudiness' - int: Cloudiness level
		'fog' - int: Fog level
		'pressure' - float: Atmospheric pressure in hPa
		'relativeHumidity' - int: Relative humidity percentage
		'windDirection' - float: Wind direction in degrees
		'windForce' - float: Wind force in m/s

		:return:
		"""
		return self._api_cmd('/weather')

	def get_name(self) -> str:
		"""
		Get the name of this game server instance
		:return:
		"""
		return self.get_option_value('ServerName')

	def get_port(self) -> int | None:
		"""
		Get the primary port of the service, or None if not applicable
		:return:
		"""
		return self.get_option_value('GamePort')

	def get_game_pid(self) -> int:
		"""
		Get the primary game process PID of the actual game server, or 0 if not running
		:return:
		"""

		return self.get_pid()

	def send_message(self, message: str):
		"""
		Send a message to all players via the game API
		:param message:
		:return:
		"""

		pass
		# @todo Vein just implemented this but is yet to publish documentation on how to use it.
		# self._api_cmd('/notification', method='POST', data={'message': message})

	def get_port_definitions(self) -> list:
		"""
		Get a list of port definitions for this service
		:return:
		"""
		ret = [
			('APIPort', 'tcp', '%s API port' % self.game.name),
		]

		# This has been moved as of experimental / April 2026
		if self.game.get_option_value('Steam Branch') != 'experimental':
			ret.append(('LEGACY GamePort', 'udp', '%s game port' % self.game.name))
			ret.append(('LEGACY SteamQueryPort', 'udp', '%s query port' % self.game.name))
		else:
			ret.append(('GamePort', 'udp', '%s game port' % self.game.name))
			ret.append(('SteamQueryPort', 'udp', '%s query port' % self.game.name))

		return ret

	def create_service(self):
		super().create_service()

		self.set_option('ServerName', 'My VEIN Server')

	def get_save_files(self) -> list | None:
		"""
		Get the list of supplemental files or directories for this game, or None if not applicable

		This list of files **should not** be fully resolved, and will use `self.get_save_directory()` as the base path.
		For example, to return `AppFiles/SaveData` and `AppFiles/Config`:

		```python
		return ['SaveData', 'Config']
		```

		:return:
		"""
		return ['Vein/Saved/SaveGames/Server.vns']


if __name__ == '__main__':
	app = app_runner(GameApp())
	app()
