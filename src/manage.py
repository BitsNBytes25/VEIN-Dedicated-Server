#!/usr/bin/env python3

import json
from time import time, sleep
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
REPO = 'https://github.com/BitsNBytes25/VEIN-Dedicated-Server'
FUNDING = 'https://ko-fi.com/bitsandbytes'
ICON_ENABLED = '✅'
ICON_STOPPED = '🛑'
ICON_DISABLED = '❌'
ICON_WARNING = '⛔'

# Require sudo / root for starting/stopping the service
IS_SUDO = os.geteuid() == 0


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
		self._game_ini = os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/Game.ini')
		self.game_parser = None
		self._gus_ini = os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/GameUserSettings.ini')
		self.gus_parser = None
		self._engine_ini = os.path.join(here, 'AppFiles/Vein/Saved/Config/LinuxServer/Engine.ini')
		self.engine_parser = None
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
		self.game_parser = UnrealConfigParser()
		if os.path.exists(self._game_ini):
			self.game_parser.read_file(self._game_ini)
			self.configured = True

		self.gus_parser = UnrealConfigParser()
		if os.path.exists(self._gus_ini):
			self.gus_parser.read_file(self._gus_ini)

		self.engine_parser = UnrealConfigParser()
		if os.path.exists(self._engine_ini):
			self.engine_parser.read_file(self._engine_ini)

	def save(self):
		"""
		Save the configuration files back to disk
		:return:
		"""
		if self.game_parser.is_changed():
			self.game_parser.write_file(self._game_ini)
			if IS_SUDO:
				subprocess.run(['chown', 'steam:steam', self._game_ini])

		if self.gus_parser.is_changed():
			self.gus_parser.write_file(self._gus_ini)
			if IS_SUDO:
				subprocess.run(['chown', 'steam:steam', self._gus_ini])

		if self.engine_parser.is_changed():
			self.engine_parser.write_file(self._engine_ini)
			if IS_SUDO:
				subprocess.run(['chown', 'steam:steam', self._engine_ini])

	def _get_config_source(self, option: str) -> Union[UnrealConfigParser, None]:
		source = self.options[option][0]

		if source == 'game':
			return self.game_parser
		elif source == 'gus':
			return self.gus_parser
		elif source == 'engine':
			return self.engine_parser
		else:
			print('Invalid source for option: %s' % option, file=sys.stderr)
			return None

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
		:return:
		"""
		try:
			ret = self._api_cmd('/status')
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
		exe = os.path.join(here, 'AppFiles/Vein/Binaries/Linux/VeinServer-Linux-Test')
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
			start_timer = time()
			subprocess.run(['systemctl', 'start', self.service])

			ready = False
			counter = 0
			print('loading...')
			while counter < 240:
				counter += 1
				pid = self.get_pid()
				exec_status = self.get_process_status()

				if exec_status != 0:
					self.print_logs(30)
					print('Game failed to start, ExecMainStatus: %s' % str(exec_status))
					return

				memory = self.get_memory_usage()
				cpu = self.get_cpu_usage()
				seconds_elapsed = round(time() - start_timer)
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
				sleep(.5)
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

		pass

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
			print('Found an issue? %s/issues' % REPO)
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

		if game.is_running():
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
		print('Enter [1-%s], [%s], or [Q]uit to exit' % (str(len(options)), '/'.join(keys)))
		opt = input(': ').lower()

		if opt == 'q':
			stay = False

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


g = GameService()

if not g.config.configured:
	menu_first_run(g)

menu_main(g)
