#!/usr/bin/env python3
import pwd
from scriptlets._common.firewall_allow import *
from scriptlets._common.firewall_remove import *
from scriptlets.bz_eval_tui.prompt_yn import *
from scriptlets.bz_eval_tui.prompt_text import *
from scriptlets.bz_eval_tui.table import *
from scriptlets.bz_eval_tui.print_header import *
from scriptlets._common.get_wan_ip import *
# import:org_python/venv_path_include.py
from scriptlets.warlock.steam_app import *
from scriptlets.warlock.http_service import *
from scriptlets.warlock.ini_config import *
from scriptlets.warlock.unreal_config import *
from scriptlets.warlock.default_run import *


here = os.path.dirname(os.path.realpath(__file__))


class GameApp(SteamApp):
	"""
	Game application manager
	"""

	def __init__(self):
		super().__init__()

		self.name = 'VEIN'
		self.desc = 'VEIN Dedicated Server'
		self.steam_id = '2131400'
		self.services = ('vein-server',)

		self.configs = {
			'manager': INIConfig('manager', os.path.join(here, '.settings.ini'))
		}
		self.load()

	def get_save_directory(self) -> Union[str, None]:
		"""
		Get the save directory for the game server

		VEIN uses the default Epic save handler which stores saves in ~/.config

		:return:
		"""
		uid = os.stat(here).st_uid
		return '%s/.config/Epic/Vein/Saved/SaveGames/' % pwd.getpwuid(uid).pw_dir

	def get_save_files(self) -> Union[list, None]:
		"""
		Get a list of save files / directories for the game server

		:return:
		"""
		save_dir = self.get_save_directory()
		files = []
		for f in os.listdir(save_dir):
			src = os.path.join(save_dir, f)
			if not os.path.isdir(src):
				files.append(f)
		return files


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
		self.service = service
		self.game = game
		self.configs = {
			'game': UnrealConfig('game', os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/Game.ini')),
			'gus': UnrealConfig('gus', os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/GameUserSettings.ini')),
			'engine': UnrealConfig('engine', os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/Engine.ini'))
		}
		self.load()

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
				firewall_remove(int(previous_value), 'udp')
			firewall_allow(int(new_value), 'udp', 'Allow %s game port' % self.game.desc)
		elif option == 'SteamQueryPort':
			# Update firewall for game port change
			if previous_value:
				firewall_remove(int(previous_value), 'udp')
			firewall_allow(int(new_value), 'udp', 'Allow %s Steam query port' % self.game.desc)

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

	def get_players(self) -> Union[list, None]:
		"""
		Get the current players on the server, or None if the API is unavailable
		:return:
		"""
		ret = self._api_cmd('/players')
		if ret is None:
			return None
		else:
			return ret['players']

	def get_player_count(self) -> Union[int, None]:
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

	def get_status(self) -> Union[dict, None]:
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

	def get_weather(self) -> Union[dict, None]:
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

	def get_port(self) -> Union[int, None]:
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
		exe = os.path.join(here, 'AppFiles/Vein/Binaries/Linux/VeinServer-Linux-')
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


def menu_first_run(game: GameApp):
	"""
	Perform first-run configuration for setting up the game server initially

	:param game:
	:return:
	"""
	print_header('First Run Configuration')

	if os.geteuid() != 0:
		print('ERROR: Please run this script with sudo to perform first-run configuration.')
		sys.exit(1)

	svc = game.get_services()[0]

	if not svc.option_has_value('ServerName'):
		svc.set_option_value('ServerName', 'My VEIN Server')
	if not svc.option_has_value('GamePort'):
		svc.set_option_value('GamePort', '7777')
	if not svc.option_has_value('SteamQueryPort'):
		svc.set_option_value('SteamQueryPort', '27015')
	if not svc.option_has_value('APIPort'):
		svc.set_option_value('APIPort', '8080')

if __name__ == '__main__':
	game = GameApp()
	run_manager(game)
