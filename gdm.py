#!/usr/bin/env python3.8
# -*- coding: utf-8 -*-

import json
import signal
import socket
import sys
import urllib.request
from datetime import datetime
from os import _exit as exit
from time import sleep

import pid
from loguru import logger as log
from RPLCD.i2c import CharLCD

lcd = CharLCD('PCF8574', 0x27)
lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1, cols=20, rows=4, dotsize=8, charmap='A02', auto_linebreaks=True, backlight_enabled=True)

signals = (0, 'SIGHUP', 'SIGINT', 'SIGQUIT', 4, 5, 6, 7, 8, 'SIGKILL', 10, 11, 12, 13, 14, 'SIGTERM')

def signal_handler(signal, frame):
    global main_stop_event
    log.warning(f'Termination signal [{signals[signal]}] recieved. Exiting.')
    main_stop_event = True
    writeline(2, 'Please Wait...', clear=True)
    exit(0)


signal.signal(signal.SIGTERM, signal_handler)  # Graceful Shutdown
signal.signal(signal.SIGHUP, signal_handler)  # Reload/Restart
signal.signal(signal.SIGINT, signal_handler)  # Hard Exit
signal.signal(signal.SIGQUIT, signal_handler)  # Hard Exit


def writeline(line, text, clear=False):
    if clear:
        lcd.clear()
    lcd.cursor_pos = (line - 1, 0)
    textlen = len(str(text))
    if textlen < 19:
        lcd.write_string('{: ^20}'.format(str(text)))
    elif textlen == 19:
        lcd.write_string(f'{str(text)} ')
    elif textlen == 20:
        lcd.write_string(str(text))
    else:
        log.error('LCD string length error')
    lcd.home()


def discover_gsm():
    log.info(f'Searching for Sensor...')
    writeline(2, 'Searching for Sensor', True)
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)  # UDP
    client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    client.settimeout(5)
    client.bind(("", 37030))
    found = False
    while not found:
        client.sendto(b'GSM_DISCOVER', ('255.255.255.255', 37020))
        log.debug(f'Sent GSM_DISCOVER broadcast')
        try:
            (data, addr) = client.recvfrom(1024)
        except socket.timeout:
            pass
        else:
            log.info(f"Found GSM: {data.decode()} from {addr[0]}")
            found = True
    writeline(2, 'Found Sensor')
    writeline(3, f'{addr[0]}')
    sleep(10)
    return addr[0]


def heartbeat(stime, inalarm):
    if inalarm:
        pos = 12
        char = '!'
    else:
        pos = 14
        char = ":"
    while stime != 0:
        lcd.cursor_pos = (0, pos)
        lcd.write_string(' ')
        sleep(.1)
        lcd.cursor_pos = (0, pos)
        lcd.write_string(char)
        sleep(.9)
        stime -= 1


def disptempdata(data):
    lcd.cursor_pos = (2, 0)
    lcd.write_string('Tmp:')
    lcd.cursor_pos = (2, 4)
    temp = str(data["tempc"]).rjust(6, ' ')
    lcd.write_string(temp)
    lcd.write(223)
    lcd.write_string('F')
    lcd.cursor_pos = (2, 12)
    temptrend = str(data["temptrend"]).rjust(6, ' ')
    lcd.write_string(temptrend)
    lcd.write(223)
    lcd.write_string('F')
    lcd.home()


def disphumiditydata(data):
    lcd.cursor_pos = (3, 0)
    lcd.write_string('Hum:')
    lcd.cursor_pos = (3, 4)
    temp = str(data["humidity"]).rjust(6, ' ')
    lcd.write_string(temp)
    lcd.write_string('%')
    lcd.cursor_pos = (3, 11)
    temptrend = str(data["humiditytrend"]).rjust(7, ' ')
    lcd.write_string(temptrend)
    lcd.write_string('% ')
    lcd.home()


def displaytime(data):
    # datetime_object = datetime.strptime(data['timestamp'], '%Y-%m-%d %H:%M')
    inalarm = data['hasalarms']
    if not inalarm:
        datetime_object = datetime.now()
        ts = datetime_object.strftime("%a, %b %d %I:%M %p")
        writeline(1, ts)
    else:
        writeline(1, f'ALERT!')


def displightdata(data):
    if int(data["darkness"]) < 300000:
        writeline(2, f'Lights ON ({data["lightscale"]}/100)')
    else:
        writeline(2, f'Lights OFF  ({data["lightscale"]}/100)')


def main():
    main_stop_event = False
    logfile = '/var/log/gdm.log'
    log.configure(
    handlers=[dict(sink=sys.stdout, level="INFO", backtrace=True, format='<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>'), dict(sink=logfile, level="INFO", enqueue=True, serialize=False)], levels=[dict(name="STARTUP", no=38, icon="¤", color="<yellow>")])
    pidfile = pid.PidFile('gdm')
    try:
        pidfile.create()
    except pid.PidFileAlreadyLockedError:
        log.error('GDM is already running')
        exit(1)
    except:
        log.exception('PID file error:')
        exit(1)

    log.log('STARTUP', 'GDM is starting up')
    log.info(f'Initilizing LCD display')


    log.debug(f'Clearing LCD display')
    lcd.clear()

    ipaddr = discover_gsm()

    switch = 0
    errorcount = 0
    firstrun = True
    inalarm = False

    while not main_stop_event:
        if errorcount > 5:
            ipaddr = discover_gsm()
        try:
            log.debug('Attempting to retrieve data')
            with urllib.request.urlopen(f"http://{ipaddr}/data") as url:
                data = json.loads(url.read().decode())
        except:
            errorcount += 1
            log.error('Error getting remote data')
            if firstrun:
                sleep(5)
            else:
                heartbeat(5, inalarm)
        else:
            log.debug('Data retrieved successfully')
            errorcount = 0
            firstrun = False
            inalarm = data['hasalarms']
            try:
                displaytime(data)
                displightdata(data)
                disptempdata(data)
                disphumiditydata(data)
            except:
                log.exception(f'Exception in main loop')
            heartbeat(10, inalarm)
    lcd.close()


if __name__ == '__main__':
    main()
