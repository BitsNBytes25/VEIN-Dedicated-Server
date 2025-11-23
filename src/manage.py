#!/usr/bin/env python3
import argparse
import configparser
import json
import shutil
import time
import datetime
from urllib import request
from urllib import error as urllib_error
from scriptlets._common.firewall_allow import *
from scriptlets._common.firewall_remove import *
from scriptlets.bz_eval_tui.prompt_yn import *
from scriptlets.bz_eval_tui.prompt_text import *
from scriptlets.bz_eval_tui.table import *
from scriptlets.bz_eval_tui.print_header import *
from scriptlets._common.get_wan_ip import *
from scriptlets.com_unrealengine.config_parser import *
from scriptlets.steam.steamcmd_check_app_update import *
# import:org_python/venv_path_include.py
import yaml


here = os.path.dirname(os.path.realpath(__file__))

GAME_DESC = 'VEIN Dedicated Server'
GAME_SERVICE='vein-server'
REPO = 'BitsNBytes25/VEIN-Dedicated-Server'
FUNDING = 'https://ko-fi.com/bitsandbytes'

STEAM_ID = '2131400'
# Steam ID of the game

GAME_USER = 'steam'
STEAM_DIR = '/home/%s/.local/share/Steam' % GAME_USER

SAVE_DIR = '/home/%s/.config/Epic/Vein/Saved/SaveGames/' % GAME_USER
# VEIN uses the default Epic save handler which stores saves in ~/.config

ICON_ENABLED = '✅'
ICON_STOPPED = '🛑'
ICON_DISABLED = '❌'
ICON_WARNING = '⛔'
ICON_STARTING = '⌛'

# Require sudo / root for starting/stopping the service
IS_SUDO = os.geteuid() == 0


def format_seconds(seconds: int) -> dict:
	hours = int(seconds // 3600)
	minutes = int((seconds - (hours * 3600)) // 60)
	seconds = int(seconds % 60)

	short_minutes = ('0' + str(minutes)) if minutes < 10 else str(minutes)
	short_seconds = ('0' + str(seconds)) if seconds < 10 else str(seconds)

	if hours > 0:
		short = '%s:%s:%s' % (str(hours), short_minutes, short_seconds)
	else:
		short = '%s:%s' % (str(minutes), short_seconds)

	return {
		'h': hours,
		'm': minutes,
		's': seconds,
		'full': '%s hrs %s min %s sec' % (str(hours), str(minutes), str(seconds)),
		'short': short
	}


class ManagerConfig:
	"""
	Configuration for the management script

	Handles admin-defined settings like player messages and the like.
	"""

	_config = None

	messages = {
		'shutdown_5min': {
			'title': 'Shutdown Warning 5 Minutes',
			'default': 'Server is shutting down in 5 minutes'
		},
		'shutdown_4min': {
			'title': 'Shutdown Warning 4 Minutes',
			'default': 'Server is shutting down in 4 minutes'
		},
		'shutdown_3min': {
			'title': 'Shutdown Warning 3 Minutes',
			'default': 'Server is shutting down in 3 minutes'
		},
		'shutdown_2min': {
			'title': 'Shutdown Warning 2 Minutes',
			'default': 'Server is shutting down in 2 minutes'
		},
		'shutdown_1min': {
			'title': 'Shutdown Warning 1 Minute',
			'default': 'Server is shutting down in 1 minute'
		},
		'shutdown_30sec': {
			'title': 'Shutdown Warning 30 Seconds',
			'default': 'Server is shutting down in 30 seconds!'
		},
		'shutdown_now': {
			'title': 'Shutdown Warning NOW',
			'default': 'Server is shutting down NOW!'
		},
	}

	@classmethod
	def get_config(cls) -> configparser.ConfigParser:
		"""
		Get the raw ConfigParser for the manager settings

		:return:
		"""
		if cls._config is None:
			config_path = os.path.join(here, '.settings.ini')
			cls._config = configparser.ConfigParser()
			if os.path.exists(config_path):
				cls._config.read(config_path)

		return cls._config

	@classmethod
	def get_key(cls, section: str, key: str, default_value: str = '') -> str:
		"""
		Get a key from the manager configuration file

		:param section:
		:param key:
		:param default_value:
		:return:
		"""
		config = cls.get_config()
		if section not in config:
			return default_value
		return config[section].get(key, default_value)

	@classmethod
	def get_message(cls, message_key: str) -> str:
		"""
		Get a predefined message from the manager configuration

		:param message_key:
		:return:
		"""
		if message_key not in cls.messages:
			return message_key

		section = 'Messages'
		key = message_key
		default = cls.messages[message_key]['default']
		return cls.get_key(section, key, default)

	@classmethod
	def set_key(cls, section: str, key: str, value: str):
		"""
		Set a key in the manager and save the configuration.

		:param section:
		:param key:
		:param value:
		:return:
		"""
		config = cls.get_config()
		if section not in config:
			config[section] = {}
		config[section][key] = value
		config_path = os.path.join(here, '.settings.ini')
		with open(config_path, 'w') as cfgfile:
			config.write(cfgfile)

	@classmethod
	def set_message(cls, message_key: str, value: str):
		"""
		Set a predefined message in the manager configuration and save it.

		:param message_key:
		:param value:
		:return:
		"""
		if message_key not in cls.messages:
			return

		# Escape '%' characters that may be present
		value = value.replace('%', '%%')

		section = 'Messages'
		key = message_key
		cls.set_key(section, key, value)

class GameAPIException(Exception):
	pass


class GameConfig:
	def __init__(self, path):
		self.path = path
		self.parser = UnrealConfigParser()
		self.options = {}

	def add_option(self, name, section, key, default, type, help):
		self.options[name] = (section, key, default, type, help)

	def _convert_to_system_type(self, value: str, type: str) -> Union[str, int, bool]:
		# Auto convert
		if value == '':
			return ''
		elif type == 'int':
			return int(value)
		elif type == 'bool':
			return value.lower() in ('1', 'true', 'yes', 'on')
		else:
			return value

	def get_value(self, name: str) -> Union[str, int, bool]:
		if name not in self.options:
			print('Invalid option: %s, not present in %s configuration!' % (name, os.path.basename(self.path)), file=sys.stderr)
			return ''

		section = self.options[name][0]
		key = self.options[name][1]
		default = self.options[name][2]
		type = self.options[name][3]
		val = self.parser.get_key(section, key, default)

		return self._convert_to_system_type(val, type)

	def set_value(self, name: str, value: Union[str, int, bool]):
		if name not in self.options:
			print('Invalid option: %s, not present in %s configuration!' % (name, os.path.basename(self.path)), file=sys.stderr)
			return

		section = self.options[name][0]
		key = self.options[name][1]
		type = self.options[name][3]

		# Convert to string for storage
		if type == 'bool':
			if value == '':
				# Allow empty values to defer to default
				str_value = ''
			elif value:
				str_value = 'True'
			else:
				str_value = 'False'
		else:
			str_value = str(value)

		self.parser.set_key(section, key, str_value)

	def get_default(self, name: str) -> Union[str, int, bool]:
		if name not in self.options:
			print('Invalid option: %s, not present in %s configuration!' % (name, os.path.basename(self.path)), file=sys.stderr)
			return ''

		default = self.options[name][2]
		type = self.options[name][3]

		return self._convert_to_system_type(default, type)

	def get_type(self, name: str) -> str:
		if name not in self.options:
			print('Invalid option: %s, not present in %s configuration!' % (name, os.path.basename(self.path)), file=sys.stderr)
			return ''

		return self.options[name][3]

	def exists(self) -> bool:
		"""
		Check if the config file exists on disk
		:return:
		"""
		return os.path.exists(self.path)

	def load(self):
		"""
		Load the configuration file from disk
		:return:
		"""
		if os.path.exists(self.path):
			self.parser.read_file(self.path)

	def save(self):
		"""
		Save the configuration file back to disk
		:return:
		"""
		if self.parser.is_changed():
			self.parser.write_file(self.path)
			if IS_SUDO:
				subprocess.run(['chown', '%s:%s' % (GAME_USER, GAME_USER), self.path])


class GameApp:
	"""
	Game application manager
	"""

	def __init__(self):
		self.name = 'VEIN'
		self.desc = 'VEIN Dedicated Server'
		self.steam_id = '2131400'
		self.services = ('vein-server',)
		self._svcs = None

		self.configs = {
			'game': GameConfig(os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/Game.ini')),
			'gus': GameConfig(os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/GameUserSettings.ini')),
			'engine': GameConfig(os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/Engine.ini'))
		}

		# Load the configuration definitions from configs.yaml
		if os.path.exists(os.path.join(here, 'configs.yaml')):
			with open(os.path.join(here, 'configs.yaml'), 'r') as cfgfile:
				cfgdata = yaml.safe_load(cfgfile)
				for cfgname, cfgoptions in cfgdata.items():
					if cfgname in self.configs:
						for option in cfgoptions:
							self.configs[cfgname].add_option(
								option['name'],
								option['section'],
								option['key'],
								option['default'],
								option['type'],
								option['help']
							)

		self.configured = False
		self.load()

	def load(self):
		"""
		Load the configuration files
		:return:
		"""
		for config in self.configs.values():
			if config.exists():
				config.load()
				self.configured = True

	def save(self):
		"""
		Save the configuration files back to disk
		:return:
		"""
		for config in self.configs.values():
			config.save()

	def get_options(self) -> list:
		"""
		Get a list of available configuration options for this game
		:return:
		"""
		opts = []
		for config in self.configs.values():
			opts.extend(list(config.options.keys()))

		# Sort alphabetically
		opts.sort()

		return opts

	def get_option_value(self, option: str) -> Union[str, int, bool]:
		"""
		Get a configuration option from the game config
		:param option:
		:return:
		"""
		for config in self.configs.values():
			if option in config.options:
				return config.get_value(option)

		print('Invalid option: %s, not present in game configuration!' % option, file=sys.stderr)
		return ''

	def get_option_default(self, option: str) -> str:
		"""
		Get the default value of a configuration option
		:param option:
		:return:
		"""
		for config in self.configs.values():
			if option in config.options:
				return config.get_default(option)

		print('Invalid option: %s, not present in game configuration!' % option, file=sys.stderr)
		return ''

	def get_option_type(self, option: str) -> str:
		"""
		Get the type of a configuration option from the game config
		:param option:
		:return:
		"""
		for config in self.configs.values():
			if option in config.options:
				return config.get_type(option)

		print('Invalid option: %s, not present in game configuration!' % option, file=sys.stderr)
		return ''

	def get_option_help(self, option: str) -> str:
		"""
		Get the help text of a configuration option from the game config
		:param option:
		:return:
		"""
		for config in self.configs.values():
			if option in config.options:
				return config.options[option][4]

		print('Invalid option: %s, not present in game configuration!' % option, file=sys.stderr)
		return ''

	def set_option(self, option: str, value: str):
		"""
		Set a configuration option in the game config
		:param option:
		:param value:
		:return:
		"""
		for config in self.configs.values():
			if option in config.options:
				previous_value = config.get_value(option)
				config.set_value(option, value)
				config.save()

				# Special option actions
				if option == 'GamePort':
					# Update firewall for game port change
					if previous_value and previous_value != value:
						firewall_remove(int(previous_value), 'udp')
					if previous_value != value:
						firewall_allow(int(value), 'udp', 'Allow %s game port from anywhere' % self.desc)
				elif option == 'SteamQueryPort':
					# Update firewall for game port change
					if previous_value and previous_value != value:
						firewall_remove(int(previous_value), 'udp')
					if previous_value != value:
						firewall_allow(int(value), 'udp', 'Allow %s Steam query port from anywhere' % self.desc)

				return

		print('Invalid option: %s, not present in game configuration!' % option, file=sys.stderr)

	def check_update_available(self) -> bool:
		"""
		Check if a SteamCMD update is available for this game

		:return:
		"""
		return steamcmd_check_app_update(os.path.join(here, 'AppFiles', 'steamapps', 'appmanifest_%s.acf' % STEAM_ID))

	def get_services(self) -> dict:
		"""
		Get a dictionary of available services (instances) for this game

		:return:
		"""
		if self._svcs is None:
			self._svcs = {}
			for svc in self.services:
				self._svcs[svc] = GameService(svc, self)
		return self._svcs

	def is_active(self) -> bool:
		"""
		Check if any service instance is currently running or starting
		:return:
		"""
		for svc in self.get_services().values():
			if svc.is_running() or svc.is_starting() or svc.is_stopping():
				return True
		return False


class GameService:
	"""
	Service definition and handler
	"""
	def __init__(self, service: str, game: GameApp):
		"""
		Initialize and load the service definition
		:param file:
		"""
		self.service = service
		self.game = game

	def _api_cmd(self, cmd: str, method: str = 'GET', data: dict = None):
		method = method.upper()

		if method != 'GET':
			raise GameAPIException('Unsupported method: %s' % method)

		if not (self.is_running() or self.is_stopping):
			# If service is not running, don't even try to connect.
			raise GameAPIException('Not running')

		if not self.is_api_enabled():
			# No REST API enabled, unable to retrieve any data
			raise GameAPIException('API not enabled')

		req = request.Request(
			'http://127.0.0.1:%s%s' % (self.game.get_option_value('APIPort'), cmd),
			headers={
				'Content-Type': 'application/json; charset=utf-8',
				'Accept': 'application/json',
			},
			method=method
		)
		try:
			if method == 'POST' and data is not None:
				data = bytearray(json.dumps(data), 'utf-8')
				req.add_header('Content-Length', str(len(data)))
				with request.urlopen(req, data) as resp:
					ret = resp.read().decode('utf-8')
					if ret == '':
						return None
					else:
						return json.loads(ret)
			else:
				with request.urlopen(req) as resp:
					ret = resp.read().decode('utf-8')
					if ret == '':
						return None
					else:
						return json.loads(ret)
		except urllib_error.HTTPError:
			raise GameAPIException('Failed to connect to API')
		except urllib_error.URLError:
			raise GameAPIException('Failed to connect to API')
		except ConnectionRefusedError:
			raise GameAPIException('Connection refused')

	def is_api_enabled(self) -> bool:
		return self.game.get_option_value('APIPort') != ''

	def get_players(self) -> Union[list, None]:
		"""
		Get the current players on the server, or None if the API is unavailable
		:return:
		"""
		try:
			ret = self._api_cmd('/players')
			return ret['players']
		except GameAPIException:
			return None

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
		try:
			ret = self._api_cmd('/status')
			return ret
		except GameAPIException:
			return None

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
		try:
			ret = self._api_cmd('/weather')
			return ret
		except GameAPIException:
			return None

	def get_pid(self) -> int:
		"""
		Get the PID of the running service, or 0 if not running
		:return:
		"""
		pid = subprocess.run([
			'systemctl', 'show', '-p', 'MainPID', self.service
		], stdout=subprocess.PIPE).stdout.decode().strip()[8:]

		return int(pid)

	def get_process_status(self) -> int:
		return int(subprocess.run([
			'systemctl', 'show', '-p', 'ExecMainStatus', self.service
		], stdout=subprocess.PIPE).stdout.decode().strip()[15:])

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

	def get_memory_usage(self) -> str:
		"""
		Get the formatted memory usage of the service, or N/A if not running
		:return:
		"""

		pid = self.get_game_pid()

		if pid == 0:
			return 'N/A'

		mem = subprocess.run([
			'ps', 'h', '-p', str(pid), '-o', 'rss'
		], stdout=subprocess.PIPE).stdout.decode().strip()

		if mem.isdigit():
			mem = int(mem)
			if mem >= 1024 * 1024:
				mem_gb = mem / (1024 * 1024)
				return '%.2f GB' % mem_gb
			else:
				mem_mb = mem // 1024
				return '%.0f MB' % mem_mb
		else:
			return 'N/A'

	def get_cpu_usage(self) -> str:
		"""
		Get the formatted CPU usage of the service, or N/A if not running
		:return:
		"""

		pid = self.get_game_pid()

		if pid == 0:
			return 'N/A'

		cpu = subprocess.run([
			'ps', 'h', '-p', str(pid), '-o', '%cpu'
		], stdout=subprocess.PIPE).stdout.decode().strip()

		if cpu.replace('.', '', 1).isdigit():
			return '%.0f%%' % float(cpu)
		else:
			return 'N/A'

	def get_exec_start_status(self) -> Union[dict, None]:
		"""
		Get the ExecStart status of the service
		This includes:

		* path - string: Path of the ExecStartPre command
		* arguments - string: Arguments passed to the ExecStartPre command
		* start_time - datetime: Time the ExecStartPre command started
		* stop_time - datetime: Time the ExecStartPre command stopped
		* pid - int: PID of the ExecStartPre command
		* code - string: Exit code of the ExecStartPre command
		* status - int: Exit status of the ExecStartPre command
		* runtime - int: Runtime of the ExecStartPre command in seconds

		:return:
		"""
		return self._get_exec_status('ExecStart')

	def get_exec_start_pre_status(self) -> Union[dict, None]:
		"""
		Get the ExecStart status of the service
		This includes:

		* path - string: Path of the ExecStartPre command
		* arguments - string: Arguments passed to the ExecStartPre command
		* start_time - datetime: Time the ExecStartPre command started
		* stop_time - datetime: Time the ExecStartPre command stopped
		* pid - int: PID of the ExecStartPre command
		* code - string: Exit code of the ExecStartPre command
		* status - int: Exit status of the ExecStartPre command
		* runtime - int: Runtime of the ExecStartPre command in seconds

		:return:
		"""
		return self._get_exec_status('ExecStartPre')


	def _get_exec_status(self, lookup: str) -> Union[dict, None]:
		"""
		Get the ExecStartPre status of the service
		This includes:

		* path - string: Path of the ExecStartPre command
		* arguments - string: Arguments passed to the ExecStartPre command
		* start_time - datetime: Time the ExecStartPre command started
		* stop_time - datetime: Time the ExecStartPre command stopped
		* pid - int: PID of the ExecStartPre command
		* code - string: Exit code of the ExecStartPre command
		* status - int: Exit status of the ExecStartPre command
		* runtime - int: Runtime of the ExecStartPre command in seconds

		:return:
		"""

		# ExecStartPre={ path=/usr/games/steamcmd ; argv[]=/usr/games/steamcmd +force_install_dir /home/steam/VEIN/AppFiles +login anonymous +app_update 2131400 -beta experimental validate +quit ; ignore_errors=no ; start_time=[Sat 2025-11-15 22:53:36 EST] ; stop_time=[Sat 2025-11-15 22:53:42 EST] ; pid=1379560 ; code=exited ; status=8 }
		output = subprocess.run([
			'systemctl', 'show', '-p', lookup, self.service
		], stdout=subprocess.PIPE).stdout.decode().strip()[len(lookup)+1:]
		if output == '':
			return None

		output = output[1:-1]  # Remove surrounding {}
		parts = output.split(' ; ')
		result = {}
		for part in parts:
			if '=' not in part:
				continue
			key, val = part.split('=', 1)
			key = key.strip()
			val = val.strip()
			if key == 'path':
				result['path'] = val
			elif key == 'argv[]':
				result['arguments'] = val
			elif key == 'start_time':
				val = val[1:-1]  # Remove surrounding []
				if val == 'n/a':
					result['start_time'] = None
				else:
					result['start_time'] = datetime.datetime.strptime(val, '%a %Y-%m-%d %H:%M:%S %Z')
			elif key == 'stop_time':
				val = val[1:-1]
				if val == 'n/a':
					result['stop_time'] = None
				else:
					result['stop_time'] = datetime.datetime.strptime(val, '%a %Y-%m-%d %H:%M:%S %Z')
			elif key == 'pid':
				result['pid'] = int(val)
			elif key == 'code':
				if val == '(null)':
					result['code'] = None
				else:
					result['code'] = val
			elif key == 'status':
				if '/' in val:
					result['status'] = int(val.split('/')[0])
				else:
					result['status'] = int(val)

		if result['start_time'] and result['stop_time']:
			delta = result['stop_time'] - result['start_time']
			result['runtime'] = int(delta.total_seconds())
		else:
			result['runtime'] = 0

		return result


	def send_message(self, message: str):
		"""
		Send a message to all players via the game API
		:param message:
		:return:
		"""

		pass
		# @todo Vein just implemented this but is yet to publish documentation on how to use it.
		#try:
		#	self._api_cmd('/notification', method='POST', data={'message': message})
		#except GameAPIException as e:
		#	print('Failed to send message via API: %s' % str(e))

	def _is_enabled(self) -> str:
		"""
		Get the output of systemctl is-enabled for this service
		:return:
		"""
		return subprocess.run(
			['systemctl', 'is-enabled', self.service],
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			check=False
		).stdout.decode().strip()

	def _is_active(self) -> str:
		"""
		Returns a string based on the status of the service:

		* active - Running
		* reloading - Running but reloading configuration
		* inactive - Stopped
		* failed - Failed to start
		* activating - Starting
		* deactivating - Stopping

		:return:
		"""
		return subprocess.run(
			['systemctl', 'is-active', self.service],
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			check=False
		).stdout.decode().strip()

	def is_enabled(self) -> bool:
		"""
		Check if this service is enabled in systemd
		:return:
		"""
		return self._is_enabled() == 'enabled'

	def is_running(self) -> bool:
		"""
		Check if this service is currently running
		:return:
		"""
		return self._is_active() == 'active'

	def is_starting(self) -> bool:
		"""
		Check if this service is currently starting
		:return:
		"""
		state = self._is_active()
		if state == 'activating':
			# Systemd indicates that the service is activating
			return True

		if state == 'deactivating':
			# Systemd indicates that the service is DEACTIVATING
			return False

		if state == 'active' and self.is_api_enabled() and self.get_player_count() is None:
			# If the API is available but no player data available, it's probably starting.
			return True

		return False

	def is_stopping(self) -> bool:
		"""
		Check if this service is currently stopping
		:return:
		"""
		return self._is_active() == 'deactivating'

	def enable(self):
		"""
		Enable this service in systemd
		:return:
		"""
		if not IS_SUDO:
			print('ERROR - Unable to enable game service unless run with sudo')
			return
		subprocess.run(['systemctl', 'enable', self.service])

	def disable(self):
		"""
		Disable this service in systemd
		:return:
		"""
		if not IS_SUDO:
			print('ERROR - Unable to disable game service unless run with sudo')
			return
		subprocess.run(['systemctl', 'disable', self.service])

	def print_logs(self, lines: int = 20):
		"""
		Print the latest logs from this service
		:param lines:
		:return:
		"""
		subprocess.run(['journalctl', '-u', self.service, '-n', str(lines), '--no-pager'])

	def get_logs(self, lines: int = 20) -> str:
		"""
		Get the latest logs from this service
		:param lines:
		:return:
		"""
		return subprocess.run(
			['journalctl', '-u', self.service, '-n', str(lines), '--no-pager'],
			stdout=subprocess.PIPE
		).stdout.decode()

	def print_smart_error(self):
		"""
		Try to determine the root of an issue and print helpful logs

		This is because a multitude of issues can cause the game to fail to start,
		but the actual error is usually buried in _some_ log somewhere.
		:return:
		"""
		logs = self.get_logs(10)
		for line in logs.split('\n'):
			if 'steamcmd' in line and ("Error! App '%s' state is" % STEAM_ID) in line and 'after update job' in line:
				# Indicative of a SteamCMD error
				if os.path.exists(os.path.join(STEAM_DIR, 'logs', 'content_log.txt')):
					subprocess.run(['tail', '-n', '20', os.path.join(STEAM_DIR, 'logs', 'content_log.txt')])
					return

		# Default to printing the last 20 lines of journalctl
		self.print_logs(30)

	def post_start(self):
		"""
		Perform the necessary operations for after a game has started
		:return:
		"""
		if not self.is_running():
			print('Game is not currently running!')
			return

		pass

	def start(self):
		"""
		Start this service in systemd
		:return:
		"""
		if self.is_running():
			print('Game is currently running!')
			return

		if not IS_SUDO:
			print('ERROR - Unable to stop game service unless run with sudo')

		try:
			print('Starting game via systemd, please wait a minute...')
			start_timer = time.time()
			subprocess.run(['systemctl', 'start', self.service])

			ready = False
			counter = 0
			print('loading...')
			while counter < 240:
				counter += 1
				pid = self.get_pid()
				exec_status = self.get_process_status()

				if exec_status != 0:
					self.print_smart_error()
					print('Game failed to start, ExecMainStatus: %s' % str(exec_status))
					return

				if pid == 0:
					self.print_smart_error()
					print('Game failed to start, no PID found.')
					return

				memory = self.get_memory_usage()
				cpu = self.get_cpu_usage()
				seconds_elapsed = round(time.time() - start_timer)
				since_minutes = str(seconds_elapsed // 60)
				since_seconds = seconds_elapsed % 60
				if since_seconds < 10:
					since_seconds = '0' + str(since_seconds)
				else:
					since_seconds = str(since_seconds)

				if self.is_api_enabled():
					players = self.get_player_count()
					if players is not None:
						ready = True
						api_status = 'CONNECTED'
					else:
						api_status = 'waiting'
				else:
					api_status = 'not enabled'
					# API is not enabled, so we'll need to check the game logs for indication that it's ready
					log = self.get_logs(5)
					if (
						'Heartbeating with IP' in log or
						'SDR shared socket listening on local address' in log or
						'Pending ping measurement until network config' in log
					):
						ready = True

				print(
					'\033[1A\033[K Time: %s, PID: %s, CPU: %s, Memory: %s, API: %s' % (
						since_minutes + ':' + since_seconds,
						str(pid),
						cpu,
						memory,
						api_status
					)
				)

				if ready:
					print('Game has started successfully!')
					break
				time.sleep(.5)
		except KeyboardInterrupt:
			print('Cancelled startup wait check, (game is probably still started)')

	def pre_stop(self):
		"""
		Perform operations necessary for safely stopping a server

		Called automatically via systemd
		:return:
		"""
		if not (self.is_running() or self.is_stopping()):
			print('Game is not currently running!')
			return

		if not self.is_api_enabled():
			print('API is not enabled, unable to send shutdown warnings!')
			return

		# Disabling until VEIN publishes their documentation on notifications
		#timers = (
		#	(60, 'shutdown_5min'),
		#	(60, 'shutdown_4min'),
		#	(60, 'shutdown_3min'),
		#	(60, 'shutdown_2min'),
		#	(30, 'shutdown_1min'),
		#	(30, 'shutdown_30sec'),
		#	(0, 'shutdown_now'),
		#)
		#for wait, msg_key in timers:
		#	if self.get_player_count():
		#		message = ManagerConfig.get_message(msg_key)
		#		print('Sending message to players: %s' % message)
		#		self.send_message(message)
		#		if wait > 0:
		#			time.sleep(wait)

	def stop(self):
		"""
		Stop this service in systemd
		:return:
		"""
		if IS_SUDO:
			print('Stopping server, please wait as players will have a 5 minute warning.')
			subprocess.run(['systemctl', 'stop', self.service])
		else:
			print('ERROR - Unable to stop game service unless run with sudo')

	def restart(self):
		"""
		Restart this service in systemd
		:return:
		"""
		if not self.is_running():
			print('Game is not currently running!')
			return

		self.stop()
		self.start()


def prompt_option(game: GameApp, option: str, title: str = None):
	type = game.get_option_type(option)
	val = game.get_option_value(option)

	if title is None:
		title = '%s: ' % option

	if type == 'bool':
		default = 'y' if val else 'n'
		val = 'True' if prompt_yn(title, default) else 'False'
	else:
		val = prompt_text(title, default=val, prefill=True)

	game.set_option(option, val)


def menu_first_run(game: GameApp):
	"""
	Display first-run configuration for setting up the game server initially

	:param game:
	:return:
	"""
	print_header('First Run Configuration')

	if not IS_SUDO:
		print('ERROR: Please run this script with sudo to perform first-run configuration.')
		sys.exit(1)

	prompt_option(game, 'ServerName', 'Enter the server name: ')
	prompt_option(game, 'ServerDescription')
	if prompt_yn('Require a password for players to join?', 'n'):
		prompt_option(game, 'Password')
	prompt_option(game, 'GamePort')
	prompt_option(game, 'SteamQueryPort')
	if prompt_yn('Enable game API (strongly recommended)?', 'y'):
		prompt_option(game, 'APIPort', 'Enter the game API port, eg 8080: ')


def menu_service(service: GameService):
	stay = True
	wan_ip = get_wan_ip()

	while stay:
		print_header('Welcome to the %s Manager' % service.game.desc)
		if REPO != '':
			print('Found an issue? https://github.com/%s/issues' % REPO)
		if FUNDING != '':
			print('Want to help financially support this project? %s' % FUNDING)

		keys = []
		options = []
		server_port = service.game.get_option_value('GamePort')
		player_pass = service.game.get_option_value('ServerPassword')
		api_port = str(service.game.get_option_value('APIPort'))
		print('')
		table = Table()
		table.borders = False
		table.align = ['r', 'r', 'l']

		if service.is_starting():
			table.add(['Status', '', ICON_STARTING + ' Starting...'])
		elif service.is_stopping():
			table.add(['Status', '', ICON_STARTING + ' Stopping...'])
		elif service.is_running():
			table.add(['Status', 's[T]op', ICON_ENABLED + ' Running'])
			keys.append('T')
		else:
			table.add(['Status', '[S]tart', ICON_STOPPED + ' Stopped'])
			keys.append('S')

		if service.is_enabled():
			table.add(['Auto-Start', '[D]isable', ICON_ENABLED + ' Enabled'])
			keys.append('D')
		else:
			table.add(['Auto-Start', '[E]nable', ICON_DISABLED + ' Disabled'])
			keys.append('E')

		if service.is_running():
			table.add(['Memory Usage', '', service.get_memory_usage()])
			table.add(['CPU Usage', '', service.get_cpu_usage()])
			table.add(['Players', '', str(service.get_player_count())])
			table.add(['Direct Connect', '', '%s:%s' % (wan_ip, server_port) if wan_ip else 'N/A'])

		table.add(['------', '----', '---------------------'])

		table.add(['Server Name', '(opt %s)' % (len(options) + 1), service.game.get_option_value('ServerName')])
		options.append(('ServerName', ))

		table.add(['Port', '(opt %s)' % (len(options) + 1), server_port])
		options.append(('ServerPort', True))

		table.add(['API Access', '(opt %s)' % (len(options) + 1), ICON_ENABLED + ' ' + api_port if api_port else ICON_DISABLED + ' Disabled'])
		options.append(('APIPort', True))

		table.add(['Join Password', '(opt %s)' % (len(options) + 1), player_pass if player_pass != '' else '--No Password Required--'])
		options.append(('ServerPassword', ))

		table.add(['Max Players', '(opt %s)' % (len(options) + 1), service.game.get_option_value('MaxPlayers')])
		options.append(('MaxPlayers', ))

		table.add(['Query Port', '(opt %s)' % (len(options) + 1), service.game.get_option_value('SteamQueryPort')])
		options.append(('SteamQueryPort', True))

		table.add(['Valve Anti Cheat', '(opt %s)' % (len(options) + 1), service.game.get_option_value('VACEnabled')])
		options.append(('VACEnabled', ))

		table.add(['PVP Enabled', '(opt %s)' % (len(options) + 1), service.game.get_option_value('PVPEnabled')])
		options.append(('PVPEnabled', ))

		table.render()

		print('')
		print('Control: [%s], or [Q]uit to exit' % '/'.join(keys))
		print('Configure: [1-%s], [P]layer messages' % str(len(options)))
		opt = input(': ').lower()

		if opt == 'q':
			stay = False

		elif opt == 'p':
			menu_messages()

		elif opt == 's':
			service.start()

		elif opt == 't':
			service.stop()

		elif opt == 'e':
			service.enable()

		elif opt == 'd':
			service.disable()

		elif str.isnumeric(opt) and 1 <= int(opt) <= len(options):
			action = options[int(opt) - 1]
			param = action[0]
			require_sudo = len(action) == 2 and action[1]

			if require_sudo and not IS_SUDO:
				print('ERROR: This option requires sudo / root privileges.')
				continue

			prompt_option(service.game, param)


def menu_monitor(service: GameService):
	"""
	Monitor the game server status in real time

	:param service:
	:return:
	"""

	try:
		while True:
			status = service.get_status()
			weather = service.get_weather()
			players = status['onlinePlayers']

			os.system('clear')
			print_header('Game Server Monitor - Press Ctrl+C to exit')
			if not service.is_running():
				print('Game is not currently running!')
				time.sleep(20)
				continue

			if status is None:
				print('Unable to connect to game API!')
			else:
				uptime = format_seconds(status['uptime'])
				print('Players Online: %s/%s' % (str(len(status['onlinePlayers'])), str(service.game.get_option_value('MaxPlayers'))))
				print('Direct Connect: %s:%s' % (get_wan_ip() or 'N/A', service.game.get_option_value('GamePort')))
				print('Server Uptime:  %s' % uptime['full'])

				if weather is not None:
					print('Temperature:       %.1f °C' % weather['temperature'])
					print('Precipitation:     %d' % weather['precipitation'])
					print('Cloudiness:        %d' % weather['cloudiness'])
					print('Fog:               %d' % weather['fog'])
					print('Pressure:          %.1f hPa' % weather['pressure'])
					print('Relative Humidity: %d%%' % weather['relativeHumidity'])
					print('Wind Force:        %.1f m/s' % weather['windForce'])

				print('')
				if len(players) > 0:
					table = Table(['Player Name', 'Online For'])
					for p in players:
						table.add([players[p]['name'], format_seconds(players[p]['timeConnected'])['short']])
					table.render()
				else:
					print('No players currently online.')

			time.sleep(5)
	except KeyboardInterrupt:
		print('\nExiting monitor...')


def menu_backup(game: GameApp, max_backups: int = 0):
	"""
	Backup the game server files

	:param game:
	:param max_backups: Maximum number of backups to keep (0 = unlimited)
	:return:
	"""
	target_dir = os.path.join(here, 'backups')
	temp_store = os.path.join(here, '.save')

	if not os.path.exists(SAVE_DIR):
		print('Save directory %s does not exist, cannot continue!' % SAVE_DIR, file=sys.stderr)
		sys.exit(1)

	# Ensure target directory exists; this will store the finalized backups
	if not os.path.exists(target_dir):
		os.makedirs(target_dir)
		if IS_SUDO:
			subprocess.run(['chown', '%s:%s' % (GAME_USER, GAME_USER), target_dir])

	# Temporary directories for various file sources
	for d in ['config', 'save']:
		p = os.path.join(temp_store, d)
		if not os.path.exists(p):
			os.makedirs(p)

	# Copy the various configuration files used by the game
	for cfg in game.configs.values():
		src = cfg.path
		dst = os.path.join(temp_store, 'config', os.path.basename(src))
		if os.path.exists(src):
			shutil.copy(src, dst)

	# Copy all files from the save directory
	for f in os.listdir(SAVE_DIR):
		src = os.path.join(SAVE_DIR, f)
		dst = os.path.join(temp_store, 'save', f)
		if not os.path.isdir(src):
			shutil.copy(src, dst)

	# Ensure ownership is correct
	if IS_SUDO:
		subprocess.run(['chown', '-R', '%s:%s' % (GAME_USER, GAME_USER), temp_store])

	# Create the final archive
	timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
	backup_name = '%s-backup-%s.tar.gz' % (game.name, timestamp)
	backup_path = os.path.join(target_dir, backup_name)
	shutil.make_archive(backup_path[:-7], 'gztar', temp_store)

	# Cleanup
	shutil.rmtree(temp_store)

	# Remove old backups if necessary
	if max_backups > 0:
		backups = []
		for f in os.listdir(target_dir):
			if f.startswith('%s-backup-' % game.name) and f.endswith('.tar.gz'):
				full_path = os.path.join(target_dir, f)
				backups.append((full_path, os.path.getmtime(full_path)))
		backups.sort(key=lambda x: x[1])  # Sort by modification time
		while len(backups) > max_backups:
			old_backup = backups.pop(0)
			os.remove(old_backup[0])
			print('Removed old backup: %s' % old_backup[0])

	print('Backup saved to %s' % backup_path)
	sys.exit(0)


def menu_restore(game: GameApp, path: str):
	"""
	Restore the game server files

	:param game: Game service to restore
	:param path: Path to the backup archive
	:return:
	"""
	temp_store = os.path.join(here, '.save')

	if not os.path.exists(SAVE_DIR):
		print('Save directory %s does not exist, cannot continue!' % SAVE_DIR, file=sys.stderr)
		sys.exit(1)

	if not os.path.exists(path):
		print('Backup file %s does not exist, cannot continue!' % path, file=sys.stderr)
		sys.exit(1)

	if game.is_active():
		print('Game server is currently running, please stop it before restoring a backup!', file=sys.stderr)
		sys.exit(1)

	if not os.path.exists(temp_store):
		os.makedirs(temp_store)

	# Extract the archive to the temporary location
	shutil.unpack_archive(path, temp_store)

	# Restore the various configuration files used by the game
	for cfg in game.configs.values():
		dst = cfg.path
		src = os.path.join(temp_store, 'config', os.path.basename(dst))
		if os.path.exists(src):
			shutil.copy(src, dst)
			if IS_SUDO:
				subprocess.run(['chown', '%s:%s' % (GAME_USER, GAME_USER), dst])

	# Restore all files to the save directory
	save_src = os.path.join(temp_store, 'save')
	for f in os.listdir(save_src):
		src = os.path.join(save_src, f)
		dst = os.path.join(SAVE_DIR, f)
		if not os.path.isdir(src):
			shutil.copy(src, dst)
			if IS_SUDO:
				subprocess.run(['chown', '%s:%s' % (GAME_USER, GAME_USER), dst])

	# Cleanup
	shutil.rmtree(temp_store)
	print('Restored from %s' % path)
	sys.exit(0)


def menu_get_services(game: GameApp):
	services = game.get_services()
	stats = {}
	for svc in services:
		g = services[svc]

		if g.is_starting():
			status = 'starting'
		elif g.is_stopping():
			status = 'stopping'
		elif g.is_running():
			status = 'running'
		else:
			status = 'stopped'

		pre_exec = g.get_exec_start_pre_status()
		start_exec = g.get_exec_start_status()
		if pre_exec and pre_exec['start_time']:
			pre_exec['start_time'] = int(pre_exec['start_time'].timestamp())
		if pre_exec and pre_exec['stop_time']:
			pre_exec['stop_time'] = int(pre_exec['stop_time'].timestamp())
		if start_exec and start_exec['start_time']:
			start_exec['start_time'] = int(start_exec['start_time'].timestamp())
		if start_exec and start_exec['stop_time']:
			start_exec['stop_time'] = int(start_exec['stop_time'].timestamp())

		svc_stats = {
			'service': svc,
			'name': game.get_option_value('ServerName'),
			'ip': get_wan_ip(),
			'port': game.get_option_value('GamePort'),
			'status': status,
			'enabled': g.is_enabled(),
			'player_count': g.get_player_count(),
			'max_players': game.get_option_value('MaxPlayers'),
			'memory_usage': g.get_memory_usage(),
			'cpu_usage': g.get_cpu_usage(),
			'game_pid': g.get_game_pid(),
			'service_pid': g.get_pid(),
			'pre_exec': pre_exec,
			'start_exec': start_exec,
		}
		stats[svc] = svc_stats
	print(json.dumps(stats))


def menu_check_update(game: GameApp):
	if game.check_update_available():
		print('An update is available for %s!' % game.desc)
		sys.exit(0)
	else:
		print('%s is up to date.' % game.desc)
		sys.exit(1)

def menu_get_game_configs(game: GameApp):
	"""
	List the available configuration files for this game (JSON encoded)
	:param game:
	:return:
	"""
	opts = []
	# Get global configs
	for key in ManagerConfig.messages:
		opts.append({
			'option': key,
			'default': ManagerConfig.messages[key]['default'],
			'value': ManagerConfig.get_message(key),
			'type': 'str'
		})

	print(json.dumps(opts))
	sys.exit(0)


def menu_set_game_config(game: GameApp, option: str, value: str):
	"""
	Set a configuration option for the game
	:param game:
	:param option:
	:param value:
	:return:
	"""
	for key in ManagerConfig.messages:
		if option == key:
			ManagerConfig.set_message(option, value)
			print('Option %s set to %s' % (option, value))
			sys.exit(0)

	print('Option not valid', file=sys.stderr)
	sys.exit(1)


def menu_get_service_configs(service: GameService):
	"""
	List the available configuration files for this game (JSON encoded)
	:param game:
	:param service:
	:return:
	"""
	opts = []
	# Get per-service configs
	for opt in service.game.get_options():
		opts.append({
			'option': opt,
			'default': service.game.get_option_default(opt),
			'value': service.game.get_option_value(opt),
			'type': service.game.get_option_type(opt),
			'help': service.game.get_option_help(opt)
		})

	print(json.dumps(opts))
	sys.exit(0)


def menu_set_service_config(service: GameService, option: str, value: str):
	"""
	Set a configuration option for the game
	:param game:
	:param service:
	:param option:
	:param value:
	:return:
	"""
	if option in service.game.get_options():
		service.game.set_option(option, value)
		print('Option %s set to %s' % (option, value))
		sys.exit(0)

	print('Option not valid', file=sys.stderr)
	sys.exit(1)


def menu_messages():
	"""
	Management interface to view/edit player messages for various events
	:return:
	"""
	messages = []
	for key in ManagerConfig.messages:
		messages.append((key, ManagerConfig.messages[key]['title']))

	while True:
		print_header('Player Messages')
		print('The following messages will be sent to players when certain events occur.')
		print('')
		counter = 0
		for key, title in messages:
			counter += 1
			print('| %s | %s | %s' % (str(counter).ljust(2), title.ljust(28), ManagerConfig.get_message(key)))

		print('')
		opt = input('[1-%s] change message | [B]ack: ' % counter).lower()
		key = None
		val = ''

		if opt == 'b':
			return
		elif str.isnumeric(opt) and 1 <= int(opt) <= counter:
			key = messages[int(opt)-1][0]
			print('')
			print('Edit the message, left/right works to move cursor.  Blank to use default.')
			val = prompt_text('%s: ' % messages[int(opt)-1][1], default=ManagerConfig.get_message(key), prefill=True)
		else:
			print('Invalid option')

		if key is not None:
			ManagerConfig.set_message(key, val)


parser = argparse.ArgumentParser('manage.py')
parser.add_argument(
	'--service',
	help='Specify the service instance to manage (default: ALL)',
	type=str,
	default='ALL'
)
parser.add_argument(
	'--pre-stop',
	help='Send notifications to game players and Discord and save the world',
	action='store_true'
)
parser.add_argument(
	'--stop',
	help='Stop the game server',
	action='store_true'
)
parser.add_argument(
	'--start',
	help='Start the game server',
	action='store_true'
)
parser.add_argument(
	'--restart',
	help='Restart the game server',
	action='store_true'
)
parser.add_argument(
	'--monitor',
	help='Monitor the game server status in real time',
	action='store_true'
)
parser.add_argument(
	'--backup',
	help='Backup the game server files',
	action='store_true'
)
parser.add_argument(
	'--max-backups',
	help='Maximum number of backups to keep when creating a new backup (default: 0 = unlimited)',
	type=int,
	default=0
)
parser.add_argument(
	'--restore',
	help='Restore the game server files from a backup archive',
	type=str,
	default=''
)
parser.add_argument(
	'--check-update',
	help='Check for game updates via SteamCMD and report the status',
	action='store_true'
)
parser.add_argument(
	'--get-services',
	help='List the available service instances for this game (JSON encoded)',
	action='store_true'
)
parser.add_argument(
	'--get-configs',
	help='List the available configuration files for this game (JSON encoded)',
	action='store_true'
)
parser.add_argument(
	'--set-config',
	help='Set a configuration option for the game',
	type=str,
	nargs=2
)
parser.add_argument(
	'--is-running',
	help='Check if any game service is currently running (exit code 0 = yes, 1 = no)',
	action='store_true'
)
parser.add_argument(
	'--logs',
	help='Print the latest logs from the game service',
	action='store_true'
)
args = parser.parse_args()

game = GameApp()
services = game.get_services()

if args.service != 'ALL':
	# User opted to manage only a single game instance
	if args.service not in services:
		print('Service instance %s not found!' % args.service, file=sys.stderr)
		sys.exit(1)
	services = {args.service: services[args.service]}

if args.pre_stop:
	for svc in services:
		g = services[svc]
		g.pre_stop()
elif args.stop:
	for svc in services:
		g = services[svc]
		g.stop()
elif args.start:
	for svc in services:
		g = services[svc]
		g.start()
elif args.restart:
	for svc in services:
		g = services[svc]
		g.restart()
elif args.monitor:
	if len(services) > 1:
		print('ERROR: --monitor can only be used with a single service instance at a time.', file=sys.stderr)
		sys.exit(1)
	g = list(services.values())[0]
	menu_monitor(g)
elif args.logs:
	if len(services) > 1:
		print('ERROR: --log can only be used with a single service instance at a time.', file=sys.stderr)
		sys.exit(1)
	g = list(services.values())[0]
	g.print_logs()
elif args.backup:
	menu_backup(game, args.max_backups)
elif args.restore != '':
	menu_restore(game, args.restore)
elif args.check_update:
	menu_check_update(game)
elif args.get_services:
	menu_get_services(game)
elif args.get_configs:
	if args.service == 'ALL':
		menu_get_game_configs(game)
	else:
		g = list(services.values())[0]
		menu_get_service_configs(g)
elif args.set_config != None:
	option, value = args.set_config
	if args.service == 'ALL':
		menu_set_game_config(game, option, value)
	else:
		g = list(services.values())[0]
		menu_set_service_config(g, option, value)
else:
	# Default mode - interactive menu
	if not game.configured:
		menu_first_run(game)

	if len(services) > 1:
		print('ERROR: This game only supports one instance', file=sys.stderr)
		sys.exit(1)
	g = list(services.values())[0]
	menu_service(g)
