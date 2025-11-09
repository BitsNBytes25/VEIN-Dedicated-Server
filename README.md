# VEIN Dedicated Server _unofficial_ installer for Linux

Help fund the project

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/bitsandbytes)

Wanna chat?  [hit up our Discord](https://discord.gg/jyFsweECPb) or see [what other projects I'm up to](https://bitsnbytes.dev/authors/cdp1337.html)


## What does it do?

This script will:

* Install Steam and SteamCMD
* Create a `steam` user for running the game server
* Install VEIN Dedicated Server using standard Steam procedures
* Setup a systemd service for running the game server
* Add firewall service for game server (with firewalld or UFW)
* Adds a management script for controlling your server

---

* [Quick Start](#quick-start)
* [Features](#features)
* [Requirements](#requirements)
* [Finding Your Game](#finding-your-game)
* [Directory Structure](#directory-structure)
* [Managing your Server (Easy Method)](#managing-your-server-easy-method)
* [Backups and Migrations](#backups-and-migrations)
* [Accessing Files](#accessing-files)

## Requirements

* Basic familiarity with running commands in Linux.
* Debian 12/13 or Ubuntu 22/24/25
* At least 15GB free disk space (an SSD is strongly recommended)
* 12GB RAM minimum, 16GB+ recommended.
* At least 2 CPU/vCPU cores and 2.5GHz or faster.

## Quick Start

The following command will download and run the installer script as root using defaults:

```bash
sudo su -c "bash <(curl -s https://raw.githubusercontent.com/BitsNBytes25/VEIN-Dedicated-Server/master/dist/installer.sh)" root
```

Note, if on Debian you may need to install sudo and curl first:

```bash
apt install -y sudo curl
```


## Features

Because it's managed with systemd, standardized commands are used for managing the server.
This includes an auto-restart for the game server if it crashes.

By default, VEIN Dedicated Server will **automatically start at boot**!

A management console (manage.py) is included for managing, monitoring, and administrating the game server.


### Advanced Usage

A copy of the installer will be saved in `/home/steam/VEIN/installer.sh`.
This can be useful for re-installing, repairing, or uninstalling the game server.

```bash
# Completely uninstall the game server and all player data
# This WILL wipe all save data!!!
sudo /home/steam/VEIN/installer.sh --uninstall
```

Re-running the installation script on an existing server **is safe** and will **not** overwrite
or delete your existing game data.  To install new features as they come out, simply
re-download the script installer via the steps above and re-run the installer application.


## Finding Your Game

Once installed and running, your server should appear in the server browser automatically.


## Directory Structure

```
/home/steam/VEIN
├── AppFiles/                  # Game Server Files (directly managed from Steam)
├── backups                    # Storage for backups of game data (created after first backup)
├── Game.ini                   # Game Server Configuration
├── GameUserSettings.ini       # Game Server Configuration
├── installer.sh               # Installer/Uninstaller
├── manage.py                  # Management console for game server, maps, and settings
├── SaveGames                  # Saved game data
└── Vein.log                   # Game log file
```


## Managing your Server (Easy Method)

Once installed, run `sudo /home/steam/VEIN/manage.py` to access the management console:

```
================================================================================
                  Welcome to the VEIN Dedicated Server Manager                  
================================================================================
Found an issue? https://github.com/BitsNBytes25/VEIN-Dedicated-Server/issues
Want to help financially support this project? https://ko-fi.com/bitsandbytes

            Status     s[T]op  ✅ Running              
        Auto-Start  [D]isable  ✅ Enabled              
      Memory Usage             8.97 GB                 
         CPU Usage             111%                    
           Players             0                       
    Direct Connect             45.26.230.248:7777      
            ------       ----  ---------------------   
       Server Name    (opt 1)  BitsNBytes VEIN Test    
              Port    (opt 2)  7777                    
        API Access    (opt 3)  ✅ 8080                 
     Join Password    (opt 4)  --No Password Required--
       Max Players    (opt 5)  16                      
        Query Port    (opt 6)  27015                   
  Valve Anti Cheat    (opt 7)  False                   
       PVP Enabled    (opt 8)  False                   

Control: [T/D], or [Q]uit to exit
Configure: [1-8], [P]layer messages
```

The main screen of the management UI shows some basic info and common options.

### Stopping / Starting

From the main menu overview, the options `s` and `t` respectively
will **s**tart or s**t**op the game server.

When API is enabled and available, (default), the stop logic will first check if there are
any players currently on the map.  If there are, it will send a 5-minute warning to all players
and then wait for a minute before another warning is sent if they are still logged in.

_As soon as the API for notifications is released..._

### Updating

The server will automatically run Steam update on startup.

## Backups and Migrations

To backup your server, you can run the management interface with `--backup` as an option.
to create a tarball of your game data and configuration in `/home/steam/VEIN/backups/`.

```bash
sudo /home/steam/VEIN/manage.py --backup
```

If necessary, you can view these backups with any archive manage which supports GZIP.

To migrate this game data to another server running this system, you can copy that tarball to
`/home/steam/VEIN/backups/` (or somewhere that makes sense to you),
and run:

```bash
sudo /home/steam/VEIN/manage.py --restore backups/vein-server-backup-20250505-184633.tar.gz
```

## Accessing Files

The game starts as a system user and thus `root` or an admin account must be used
to start/stop the server.  Accessing the files however should be done with the `steam` user.

[Read some tips on accessing game files via SSH](https://bitsnbytes.dev/posts/2025-05/26-howto-ssh-from-windows.html)


## Utilized libraries

* [Scripts Collection compiler by eVAL](https://github.com/eVAL-Agency/ScriptsCollection) (AGPLv3)
* [SteamCMD by Valve](https://developer.valvesoftware.com/wiki/SteamCMD)
* curl
* sudo
* systemd
* python3
* ufw
