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
	Configuration for the management script itself

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

	"""
	Configuration file reader for the game server
	"""
	def __init__(self):
		"""
		Initialize the configuration file reader
		:param file:
		"""
		self.configs = {
			'game': {
				'path': os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/Game.ini'),
				'parser': None,
			},
			'gus': {
				'path': os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/GameUserSettings.ini'),
				'parser': None,
			},
			'engine': {
				'path': os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/Engine.ini'),
				'parser': None,
			},
		}
		self.configured = False
		self.load()
		self.options = {
			'AISpawner': (
				'engine',
				'ConsoleVariables',
				'vein.AISpawner.Enabled',
				'True',
				'bool'
			),
			'APIPort': (
				'game',
				'/Script/Vein.VeinGameSession',
				'HTTPPort',
				'',
				'str'
			),
			'Public': (
				'game',
				'/Script/Vein.VeinGameSession',
				'bPublic',
				'True',
				'bool'
			),
			'GamePort': (
				'game',
				'URL',
				'Port',
				'7777',
				'str'
			),
			'MaxPlayers': (
				'game',
				'/Script/Engine.GameSession',
				'MaxPlayers',
				'16',
				'str'
			),
			'PVPEnabled': (
				'engine',
				'ConsoleVariables',
				'vein.PvP',
				'True',
				'bool'
			),
			'ServerDescription': (
				'game',
				'/Script/Vein.VeinGameSession',
				'ServerDescription',
				'Short description of your server and your community',
				'str'
			),
			'ServerName': (
				'game',
				'/Script/Vein.VeinGameSession',
				'ServerName',
				'My Vein Server',
				'str'
			),
			'ServerPassword': (
				'game',
				'/Script/Vein.VeinGameSession',
				'Password',
				'',
				'str'
			),
			'SteamQueryPort': (
				'game',
				'OnlineSubsystemSteam',
				'GameServerQueryPort',
				'27015',
				'str'
			),
			'VACEnabled': (
				'game',
				'OnlineSubsystemSteam',
				'bVACEnabled',
				'False',
				'bool'
			),
		}

	def load(self):
		"""
		Load the configuration file
		:return:
		"""
		for cfg in self.configs:
			self.configs[cfg]['parser'] = UnrealConfigParser()
			if os.path.exists(self.configs[cfg]['path']):
				self.configs[cfg]['parser'].read_file(self.configs[cfg]['path'])
				self.configured = True

	def save(self):
		"""
		Save the configuration files back to disk
		:return:
		"""
		for cfg in self.configs:
			if self.configs[cfg]['parser'].is_changed():
				self.configs[cfg]['parser'].write_file(self.configs[cfg]['path'])
				if IS_SUDO:
					subprocess.run(['chown', '%s:%s' % (GAME_USER, GAME_USER), self.configs[cfg]['path']])

	def _get_config_source(self, option: str) -> Union[UnrealConfigParser, None]:
		source = self.options[option][0]
		if source not in self.configs:
			print('Invalid source for option: %s' % option, file=sys.stderr)
			return None

		return self.configs[source]['parser']

	def prompt_option(self, option: str, title: str = None) -> str:

		if option not in self.options:
			print('Invalid option: %s, not present in game configuration!' % option, file=sys.stderr)
			return ''

		if title is None:
			title = option + ': '

		config = self._get_config_source(option)
		section = self.options[option][1]
		key = self.options[option][2]
		val_type = self.options[option][4]

		# Set the default to the current value if present
		default = config.get_key(section, key, self.options[option][3])

		if val_type == 'bool':
			default = 'y' if default.lower() in ['true', '1', 'yes'] else 'n'
			val = 'True' if prompt_yn(title, default) else 'False'
		else:
			val = prompt_text(title, default=default, prefill=True)

		self.set_option(option, val)
		return val

	def get_option(self, option: str) -> str:
		if option not in self.options:
			print('Invalid option: %s, not present in game configuration!' % option, file=sys.stderr)
			return ''

		config = self._get_config_source(option)
		section = self.options[option][1]
		key = self.options[option][2]
		return config.get_key(section, key, self.options[option][3])

	def set_option(self, option: str, value: str):
		if option not in self.options:
			print('Invalid option: %s, not present in game configuration!' % option, file=sys.stderr)
			return

		config = self._get_config_source(option)
		section = self.options[option][1]
		key = self.options[option][2]
		previous_value = config.get_key(section, key, '')
		config.set_key(section, key, value)

		# Special option actions
		if option == 'GamePort':
			# Update firewall for game port change
			if previous_value and previous_value != value:
				firewall_remove(int(previous_value), 'udp')
			if previous_value != value:
				firewall_allow(int(value), 'udp', 'Allow %s game port from anywhere' % GAME_DESC)
		elif option == 'SteamQueryPort':
			# Update firewall for game port change
			if previous_value and previous_value != value:
				firewall_remove(int(previous_value), 'udp')
			if previous_value != value:
				firewall_allow(int(value), 'udp', 'Allow %s Steam query port from anywhere' % GAME_DESC)

		# Save the config change
		self.save()


class GameService:
	"""
	Service definition and handler
	"""
	def __init__(self):
		"""
		Initialize and load the service definition
		:param file:
		"""
		self.config = GameConfig()
		self.service = GAME_SERVICE

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
			'http://127.0.0.1:%s%s' % (self.config.get_option('APIPort'), cmd),
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
		return self.config.get_option('APIPort') != ''

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
		return self._is_active() == 'activating'

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


def menu_first_run(game: GameService):
	"""
	Display first-run configuration for setting up the game server initially

	:param game:
	:return:
	"""
	print_header('First Run Configuration')

	if not IS_SUDO:
		print('ERROR: Please run this script with sudo to perform first-run configuration.')
		sys.exit(1)

	game.config.prompt_option('ServerName', 'Enter the server name: ')
	game.config.prompt_option('ServerDescription')
	if prompt_yn('Require a password for players to join?', 'n'):
		game.config.prompt_option('Password')
	game.config.prompt_option('GamePort')
	game.config.prompt_option('SteamQueryPort')
	if prompt_yn('Enable game API (strongly recommended)?', 'y'):
		game.config.prompt_option('APIPort', 'Enter the game API port, eg 8080: ')


def menu_main(game: GameService):
	stay = True
	wan_ip = get_wan_ip()

	while stay:
		print_header('Welcome to the %s Manager' % GAME_DESC)
		if REPO != '':
			print('Found an issue? https://github.com/%s/issues' % REPO)
		if FUNDING != '':
			print('Want to help financially support this project? %s' % FUNDING)

		keys = []
		options = []
		server_port = game.config.get_option('GamePort')
		player_pass = game.config.get_option('ServerPassword')
		api_port = game.config.get_option('APIPort')
		print('')
		table = Table()
		table.borders = False
		table.align = ['r', 'r', 'l']

		if game.is_starting():
			table.add(['Status', '', ICON_STARTING + ' Starting...'])
		elif game.is_stopping():
			table.add(['Status', '', ICON_STARTING + ' Stopping...'])
		elif game.is_running():
			table.add(['Status', 's[T]op', ICON_ENABLED + ' Running'])
			keys.append('T')
		else:
			table.add(['Status', '[S]tart', ICON_STOPPED + ' Stopped'])
			keys.append('S')

		if game.is_enabled():
			table.add(['Auto-Start', '[D]isable', ICON_ENABLED + ' Enabled'])
			keys.append('D')
		else:
			table.add(['Auto-Start', '[E]nable', ICON_DISABLED + ' Disabled'])
			keys.append('E')

		if game.is_running():
			table.add(['Memory Usage', '', game.get_memory_usage()])
			table.add(['CPU Usage', '', game.get_cpu_usage()])
			table.add(['Players', '', str(game.get_player_count())])
			table.add(['Direct Connect', '', '%s:%s' % (wan_ip, server_port) if wan_ip else 'N/A'])

		table.add(['------', '----', '---------------------'])

		table.add(['Server Name', '(opt %s)' % (len(options) + 1), game.config.get_option('ServerName')])
		options.append(('ServerName', ))

		table.add(['Port', '(opt %s)' % (len(options) + 1), server_port])
		options.append(('ServerPort', True))

		table.add(['API Access', '(opt %s)' % (len(options) + 1), ICON_ENABLED + ' ' + api_port if api_port else ICON_DISABLED + ' Disabled'])
		options.append(('APIPort', True))

		table.add(['Join Password', '(opt %s)' % (len(options) + 1), player_pass if player_pass != '' else '--No Password Required--'])
		options.append(('ServerPassword', ))

		table.add(['Max Players', '(opt %s)' % (len(options) + 1), game.config.get_option('MaxPlayers')])
		options.append(('MaxPlayers', ))

		table.add(['Query Port', '(opt %s)' % (len(options) + 1), game.config.get_option('SteamQueryPort')])
		options.append(('SteamQueryPort', True))

		table.add(['Valve Anti Cheat', '(opt %s)' % (len(options) + 1), game.config.get_option('VACEnabled')])
		options.append(('VACEnabled', ))

		table.add(['PVP Enabled', '(opt %s)' % (len(options) + 1), game.config.get_option('PVPEnabled')])
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
			game.start()

		elif opt == 't':
			game.stop()

		elif opt == 'e':
			game.enable()

		elif opt == 'd':
			game.disable()

		elif str.isnumeric(opt) and 1 <= int(opt) <= len(options):
			action = options[int(opt) - 1]
			param = action[0]
			require_sudo = len(action) == 2 and action[1]

			if require_sudo and not IS_SUDO:
				print('ERROR: This option requires sudo / root privileges.')
				continue

			game.config.prompt_option(param)
			game.config.save()


def menu_monitor(game: GameService):
	"""
	Monitor the game server status in real time

	:param game:
	:return:
	"""

	try:
		while True:
			status = game.get_status()
			weather = game.get_weather()
			players = status['onlinePlayers']

			os.system('clear')
			print_header('Game Server Monitor - Press Ctrl+C to exit')
			if not game.is_running():
				print('Game is not currently running!')
				time.sleep(20)
				continue

			if status is None:
				print('Unable to connect to game API!')
			else:
				uptime = format_seconds(status['uptime'])
				print('Players Online: %s/%s' % (str(len(status['onlinePlayers'])), str(game.config.get_option('MaxPlayers'))))
				print('Direct Connect: %s:%s' % (get_wan_ip() or 'N/A', game.config.get_option('GamePort')))
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


def menu_backup(game: GameService):
	"""
	Backup the game server files

	:param game:
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
	for cfg in game.config.configs:
		src = game.config.configs[cfg]['path']
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
	backup_name = '%s-backup-%s.tar.gz' % (game.service, timestamp)
	backup_path = os.path.join(target_dir, backup_name)
	shutil.make_archive(backup_path[:-7], 'gztar', temp_store)

	# Cleanup
	shutil.rmtree(temp_store)
	print('Backup saved to %s' % backup_path)
	sys.exit(0)


def menu_restore(game: GameService, path: str):
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

	if game.is_running():
		print('Game server is currently running, please stop it before restoring a backup!', file=sys.stderr)
		sys.exit(1)

	if game.is_starting():
		print('Game server is currently starting, please stop it before restoring a backup!', file=sys.stderr)
		sys.exit(1)

	if not os.path.exists(temp_store):
		os.makedirs(temp_store)

	# Extract the archive to the temporary location
	shutil.unpack_archive(path, temp_store)

	# Restore the various configuration files used by the game
	for cfg in game.config.configs:
		dst = game.config.configs[cfg]['path']
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
	'--restore',
	help='Restore the game server files from a backup archive',
	type=str,
	default=''
)
args = parser.parse_args()

g = GameService()

if args.pre_stop:
	g.pre_stop()
elif args.stop:
	g.stop()
elif args.start:
	g.start()
elif args.monitor:
	menu_monitor(g)
elif args.backup:
	menu_backup(g)
elif args.restore != '':
	menu_restore(g, args.restore)
else:
	# Default mode - interactive menu
	if not g.config.configured:
		menu_first_run(g)

	menu_main(g)
