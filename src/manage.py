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
import subprocess

# Import the appropriate type of handler for the game installer.
# Common options are:
# from warlock_manager.apps.base_app import BaseApp
from warlock_manager.apps.steam_app import SteamApp

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
		self.service_prefix = 'vein-'

		self.configs = {
			'manager': INIConfig('manager', os.path.join(self.get_app_directory(), '.settings.ini'))
		}
		self.load()

		self.steam_branch = self.get_option_value('Steam Branch')

	def first_run(self) -> bool:
		"""
		Perform any first-run configuration needed for this game

		:return:
		"""
		if os.geteuid() != 0:
			logging.error('Please run this script with sudo to perform first-run configuration.')
			return False

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
			logging.info('Detected %d services, skipping first-run service creation.' % len(services))

	def post_update(self):
		# VEIN requires the Steam client binary to be loaded into the game server
		src = os.path.join(self.get_home_directory(), '.steam', 'steam', 'steamcmd', 'linux64', 'steamclient.so')
		dst = os.path.join(self.get_app_directory(), 'AppFiles', 'Vein', 'Binaries', 'Linux', 'steamclient.so')
		if not os.path.exists(dst):
			logging.info('Copying Steam client library to game directory for VEIN...')
			shutil.copy2(src, dst)
			self.ensure_file_ownership(dst)

		os.chmod(os.path.join(self.get_app_directory(), 'AppFiles/Vein/Binaries/Linux/VeinServer-Linux-Test'), 0o755)


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
			'engine': UnrealConfig('engine', os.path.join(self.get_app_directory(), 'Vein/Saved/Config/LinuxServer/Engine.ini'))
		}
		self.load()

	def get_executable(self) -> str:
		return os.path.join(self.get_app_directory(), 'Vein/Binaries/Linux/VeinServer-Linux-Test') + ' Vein'

	def option_value_updated(self, option: str, previous_value, new_value):
		"""
		Handle any special actions needed when an option value is updated
		:param option:
		:param previous_value:
		:param new_value:
		:return:
		"""

		# Special option actions
		if option == 'GamePort':
			# Update firewall for game port change
			if previous_value:
				Firewall.remove(int(previous_value), 'udp')
			Firewall.allow(int(new_value), 'udp', '%s game port' % self.game.desc)
		elif option == 'SteamQueryPort':
			# Update firewall for game port change
			if previous_value:
				Firewall.remove(int(previous_value), 'udp')
			Firewall.allow(int(new_value), 'udp', '%s Steam query port' % self.game.desc)

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

		# There's no quick way to get the game process PID from systemd,
		# so use ps to find the process based on the map name
		processes = subprocess.run([
			'ps', 'axh', '-o', 'pid,cmd'
		], stdout=subprocess.PIPE).stdout.decode().strip()
		exe = os.path.join(self.get_app_directory(), 'Vein/Binaries/Linux/VeinServer-Linux-')
		for line in processes.split('\n'):
			pid, cmd = line.strip().split(' ', 1)
			if cmd.startswith(exe):
				return int(line.strip().split(' ')[0])
		return 0

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
		return [
			('APIPort', 'tcp', '%s API port' % self.game.desc),
			('GamePort', 'udp', '%s game port' % self.game.desc),
			('SteamQueryPort', 'udp', '%s Steam query port' % self.game.desc)
		]

	def create_service(self):
		super().create_service()

		self.set_option('ServerName', 'My VEIN Server')
		self.set_option('GamePort', '7777')
		self.set_option('SteamQueryPort', '27015')
		self.set_option('APIPort', '8080')


if __name__ == '__main__':
	app = app_runner(GameApp())
	app()
